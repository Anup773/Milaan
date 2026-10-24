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

export const registersRouter = Router();

const UPLOAD_DIR = path.join(os.tmpdir(), "milaan-uploads");
mkdirSync(UPLOAD_DIR, { recursive: true });

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const MAX_NAME_LENGTH = 150;
const MAX_ROLES = 20;
// .xls is accepted here only so the engine can explain how to convert it, instead of a bare "wrong file type".
const ALLOWED_EXTENSIONS = new Set([".csv", ".xlsx", ".xlsm", ".xls"]);
const TEMPLATES: Record<string, string> = { sales: "Sales register", purchase: "Purchase register", payroll: "Payroll register" };

const upload = multer({
  storage: multer.diskStorage({
    destination: UPLOAD_DIR,
    filename: (_req, file, cb) => cb(null, `${randomUUID()}${path.extname(file.originalname).toLowerCase()}`),
  }),
  limits: { fileSize: MAX_UPLOAD_BYTES, files: 1 },
});

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ROLE_KEY = /^[a-z_]{1,30}$/;

function bad(message: string): StatusError {
  const err = new Error(message) as StatusError;
  err.status = 400;
  return err;
}

interface RegisterResult {
  rows: number;
  errors: number;
  warnings: number;
  total_debit: string;
  total_credit: string;
  issues_total: number;
  issues: Array<{ row: number; field: string; severity: string; message: string }>;
  register: Record<string, unknown>;
  preview: boolean;
}

/** The register types, the columns each one looks for, and the default account names. */
registersRouter.get("/templates", authenticate, async (_req, res) => {
  try {
    res.json(await runEngineCli("engine.registers.cli", ["templates"]));
  } catch (err) {
    respondError(res, err, "could not load the register types");
  }
});

/** Reads and checks everything a person sent. Throws a 400 for anything they can fix. */
function readRequest(req: Request): { companyId: string; template: string; accountsJson: string; voucherDate: string; party: string; filePath: string; fileName: string } {
  const body = (req.body ?? {}) as Record<string, unknown>;
  const companyId = body.companyId;
  if (typeof companyId !== "string" || !UUID.test(companyId)) throw bad("companyId is required");
  const template = body.template;
  if (typeof template !== "string" || !Object.prototype.hasOwnProperty.call(TEMPLATES, template)) throw bad("choose a register type: sales, purchase or payroll");

  const accounts: Record<string, string> = {};
  if (body.accounts !== undefined && body.accounts !== null && body.accounts !== "") {
    let parsed: unknown;
    try {
      parsed = typeof body.accounts === "string" ? JSON.parse(body.accounts) : body.accounts;
    } catch {
      throw bad("the account names were not understood");
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw bad("the account names were not understood");
    const entries = Object.entries(parsed as Record<string, unknown>);
    if (entries.length > MAX_ROLES) throw bad("too many account names");
    for (const [key, value] of entries) {
      if (!ROLE_KEY.test(key) || typeof value !== "string") throw bad("the account names were not understood");
      const name = value.trim();
      if (name === "") continue; // left empty: the default name is used
      if (name.length > MAX_NAME_LENGTH) throw bad(`an account name is too long (limit ${MAX_NAME_LENGTH} characters)`);
      // eslint-disable-next-line no-control-regex
      if (/[\u0000-\u001f]/.test(name)) throw bad("an account name has characters that are not allowed");
      accounts[key] = name;
    }
  }

  let voucherDate = "-";
  if (body.voucherDate !== undefined && body.voucherDate !== null && body.voucherDate !== "") {
    if (typeof body.voucherDate !== "string" || !ISO_DATE.test(body.voucherDate)) throw bad("the voucher date must look like 2026-03-31");
    voucherDate = body.voucherDate;
  }
  const party = body.partyAccounts === true || body.partyAccounts === "true" || body.partyAccounts === "1" ? "1" : "0";

  if (!req.file) throw bad("no file uploaded (expected multipart field 'file')");
  if (!ALLOWED_EXTENSIONS.has(path.extname(req.file.originalname).toLowerCase())) throw bad("expected a register as a .csv or .xlsx file");
  return { companyId, template, accountsJson: JSON.stringify(accounts), voucherDate, party, filePath: req.file.path, fileName: req.file.originalname };
}

function takeUpload(req: Request, res: Response, next: () => void): void {
  upload.single("file")(req, res, (err: unknown) => {
    if (err) {
      const code = (err as { code?: string }).code;
      res.status(code === "LIMIT_FILE_SIZE" ? 413 : 400).json({
        error: code === "LIMIT_FILE_SIZE" ? "that file is too large (limit 25 MB). Split it by date range" : "the upload failed",
      });
      return;
    }
    next();
  });
}

/** Reads the register and reports what would be imported, including every check and any rows already imported
 *  earlier. Saves nothing. */
registersRouter.post("/preview", authenticate, takeUpload, async (req, res) => {
  const uploadedPath = req.file?.path;
  try {
    const r = readRequest(req);
    const auth = req.auth!;
    await assertCompanyInFirm(auth.firmId, r.companyId);
    res.json(await runEngineCli<RegisterResult>("engine.registers.cli", ["preview", r.template, r.filePath, r.accountsJson, r.voucherDate, r.party, auth.firmId, r.companyId]));
  } catch (err) {
    respondError(res, err, "register check failed");
  } finally {
    if (uploadedPath) await unlink(uploadedPath).catch(() => {});
  }
});

/** Reads the register and saves one balanced voucher per row, ready for the normal mapping and posting steps. */
registersRouter.post("/import", authenticate, takeUpload, async (req, res) => {
  const uploadedPath = req.file?.path;
  try {
    const r = readRequest(req);
    const auth = req.auth!;
    await assertCompanyInFirm(auth.firmId, r.companyId);
    const companyId = r.companyId;

    const label = `${TEMPLATES[r.template]}: ${r.fileName}`.slice(0, 250);
    const sourceType = `${r.template}-register`;
    const sourceFileId = await withTenant({ firmId: auth.firmId, companyId }, async (client) => {
      const existing = await client.query(
        `SELECT id FROM data_sources WHERE company_id = $1 AND source_type = $2 ORDER BY created_at LIMIT 1`,
        [companyId, sourceType]
      );
      let dataSourceId: string | undefined = existing.rows[0]?.id;
      if (!dataSourceId) {
        const created = await client.query(
          `INSERT INTO data_sources (company_id, name, source_type) VALUES ($1, $2, $3) RETURNING id`,
          [companyId, `${TEMPLATES[r.template]}s`, sourceType]
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

    let result: RegisterResult;
    try {
      result = await runEngineCli<RegisterResult>("engine.registers.cli", ["import", r.template, r.filePath, r.accountsJson, r.voucherDate, r.party, auth.firmId, companyId, sourceFileId]);
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
    respondError(res, err, "register import failed");
  } finally {
    if (uploadedPath) await unlink(uploadedPath).catch(() => {});
  }
});