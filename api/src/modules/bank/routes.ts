import { unlink } from "node:fs/promises";
import { mkdirSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { randomUUID } from "node:crypto";
import { Router, type Request, type Response } from "express";
import multer from "multer";
import { authenticate } from "../auth/middleware.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError, type StatusError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";
import { withTenant } from "../../db/client.js";

export const bankRouter = Router();

const UPLOAD_DIR = path.join(os.tmpdir(), "milaan-uploads");
mkdirSync(UPLOAD_DIR, { recursive: true });

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024; // years of statement lines are still far below this
const MAX_NAME_LENGTH = 150;
// .xls is accepted here only so the engine can explain how to convert it, instead of a bare "wrong file type".
const ALLOWED_EXTENSIONS = new Set([".csv", ".xlsx", ".xlsm", ".xls"]);

const upload = multer({
  storage: multer.diskStorage({
    destination: UPLOAD_DIR,
    filename: (_req, file, cb) => cb(null, `${randomUUID()}${path.extname(file.originalname).toLowerCase()}`),
  }),
  limits: { fileSize: MAX_UPLOAD_BYTES, files: 1 },
});

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function bad(message: string): StatusError {
  const err = new Error(message) as StatusError;
  err.status = 400;
  return err;
}

interface BankStats {
  transactions: number;
  deposits: number;
  withdrawals: number;
  total_deposits: string;
  total_withdrawals: string;
  net_movement: string;
  opening_balance: string | null;
  closing_balance: string | null;
  first_date: string | null;
  last_date: string | null;
  balance_check: "passed" | "failed" | "not_checked";
  balance_mismatches: number;
  order: "oldest_first" | "newest_first";
  skipped_rows: number;
  unreadable_rows: number;
  duplicates: number;
}

interface BankImportResult {
  rows: number;
  errors: number;
  warnings: number;
  total_debit: string;
  total_credit: string;
  issues_total: number;
  issues: Array<{ row: number; field: string; severity: string; message: string }>;
  bank: BankStats;
  preview: boolean;
}

function readName(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim() === "") throw bad(`${label} is required`);
  const name = value.trim();
  if (name.length > MAX_NAME_LENGTH) throw bad(`${label} is too long (limit ${MAX_NAME_LENGTH} characters)`);
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f]/.test(name)) throw bad(`${label} has characters that are not allowed`);
  return name;
}

/** Reads and checks everything a person sent. Throws a 400 for anything they can fix. */
function readRequest(req: Request): { companyId: string; bank: string; suspense: string; filePath: string; fileName: string } {
  const body = (req.body ?? {}) as Record<string, unknown>;
  const companyId = body.companyId;
  if (typeof companyId !== "string" || !UUID.test(companyId)) throw bad("companyId is required");
  const bank = readName(body.bankAccount, "the bank account name");
  const suspense = readName(body.suspenseAccount, "the suspense account name");
  if (bank.toLowerCase() === suspense.toLowerCase()) throw bad("the bank account and the suspense account must be different accounts");
  if (!req.file) throw bad("no file uploaded (expected multipart field 'file')");
  if (!ALLOWED_EXTENSIONS.has(path.extname(req.file.originalname).toLowerCase())) throw bad("expected a bank statement as a .csv or .xlsx file");
  return { companyId, bank, suspense, filePath: req.file.path, fileName: req.file.originalname };
}

function takeUpload(req: Request, res: Response, next: () => void): void {
  upload.single("file")(req, res, (err: unknown) => {
    if (err) {
      const code = (err as { code?: string }).code;
      res.status(code === "LIMIT_FILE_SIZE" ? 413 : 400).json({
        error: code === "LIMIT_FILE_SIZE" ? "that file is too large (limit 25 MB). Download a shorter date range from the bank" : "the upload failed",
      });
      return;
    }
    next();
  });
}

/** Reads the statement and reports what would be imported, including the running-balance check and any transactions
 *  already imported earlier. Saves nothing. */
bankRouter.post("/preview", authenticate, takeUpload, async (req, res) => {
  const uploadedPath = req.file?.path;
  try {
    const { companyId, bank, suspense, filePath } = readRequest(req);
    const auth = req.auth!;
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli<BankImportResult>("engine.bank.cli", ["preview", filePath, bank, suspense, auth.firmId, companyId]));
  } catch (err) {
    respondError(res, err, "bank statement check failed");
  } finally {
    if (uploadedPath) await unlink(uploadedPath).catch(() => {});
  }
});

/** Reads the statement and saves it as two balanced lines per transaction (bank account and suspense account),
 *  ready for the normal mapping and posting steps. */
bankRouter.post("/import", authenticate, takeUpload, async (req, res) => {
  const uploadedPath = req.file?.path;
  try {
    const { companyId, bank, suspense, filePath, fileName } = readRequest(req);
    const auth = req.auth!;
    await assertCompanyInFirm(auth.firmId, companyId);

    const label = `Bank: ${bank} (${fileName})`.slice(0, 250);
    const sourceFileId = await withTenant({ firmId: auth.firmId, companyId }, async (client) => {
      const existing = await client.query(
        `SELECT id FROM data_sources WHERE company_id = $1 AND source_type = 'bank-statement' ORDER BY created_at LIMIT 1`,
        [companyId]
      );
      let dataSourceId: string | undefined = existing.rows[0]?.id;
      if (!dataSourceId) {
        const created = await client.query(
          `INSERT INTO data_sources (company_id, name, source_type) VALUES ($1, 'Bank statements', 'bank-statement') RETURNING id`,
          [companyId]
        );
        dataSourceId = created.rows[0].id as string;
      }
      const file = await client.query(
        `INSERT INTO source_files (company_id, data_source_id, filename, uploaded_by, status)
         VALUES ($1, $2, $3, $4, 'PENDING') RETURNING id`,
        [companyId, dataSourceId, label, auth.userId]
      );
      return file.rows[0].id as string;
    });

    let result: BankImportResult;
    try {
      result = await runEngineCli<BankImportResult>("engine.bank.cli", ["import", filePath, bank, suspense, auth.firmId, companyId, sourceFileId]);
    } catch (err) {
      // A failed import saved no rows, so drop the empty file record rather than leave junk in the imports list.
      try {
        await withTenant({ firmId: auth.firmId, companyId }, async (client) => {
          const gone = await client.query(
            `DELETE FROM source_files
             WHERE id = $1 AND NOT EXISTS (SELECT 1 FROM source_rows WHERE source_file_id = $1)`,
            [sourceFileId]
          );
          if (gone.rowCount === 0) await client.query(`UPDATE source_files SET status = 'ERROR' WHERE id = $1`, [sourceFileId]);
        });
      } catch {
        /* keep the original error */
      }
      throw err;
    }
    await withTenant({ firmId: auth.firmId, companyId }, (client) =>
      client.query(`UPDATE source_files SET status = 'PROCESSED' WHERE id = $1`, [sourceFileId])
    );
    res.json({ sourceFileId, ...result });
  } catch (err) {
    respondError(res, err, "bank statement import failed");
  } finally {
    if (uploadedPath) await unlink(uploadedPath).catch(() => {});
  }
});