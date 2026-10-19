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

export const tallyRouter = Router();

const UPLOAD_DIR = path.join(os.tmpdir(), "milaan-uploads");
mkdirSync(UPLOAD_DIR, { recursive: true });

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024; // a year of vouchers for a busy company is well under this
const upload = multer({
  storage: multer.diskStorage({
    destination: UPLOAD_DIR,
    filename: (_req, _file, cb) => cb(null, `${randomUUID()}.xml`),
  }),
  limits: { fileSize: MAX_UPLOAD_BYTES, files: 1 },
});

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function bad(message: string): StatusError {
  const err = new Error(message) as StatusError;
  err.status = 400;
  return err;
}

interface TallyStats {
  vouchers_seen: number;
  vouchers_imported: number;
  skipped_cancelled: number;
  skipped_optional: number;
  skipped_non_accounting: number;
  skipped_no_ledger_lines: number;
  zero_amount_lines_skipped: number;
  unbalanced_vouchers: number;
  first_date: string | null;
  last_date: string | null;
}

interface TallyImportResult {
  rows: number;
  errors: number;
  warnings: number;
  total_debit: string;
  total_credit: string;
  issues_total: number;
  issues: Array<{ row: number; field: string; severity: string; message: string }>;
  tally: TallyStats;
}

/** Is Tally reachable from the machine running the API, and what companies does it have open? Never errors just
 *  because Tally is closed: that is a normal answer, reported as reachable: false. */
tallyRouter.get("/status", authenticate, async (_req, res) => {
  try {
    const out = await runEngineCli<{ reachable: boolean; url: string | null; companies: string[]; message: string }>(
      "engine.tally.cli",
      ["status"]
    );
    res.json(out);
  } catch (err) {
    respondError(res, err, "tally status failed");
  }
});

/** Records the file, runs `run`, and marks the file PROCESSED or ERROR. The `run` callback does the Tally work. */
async function importInto(
  req: Request,
  res: Response,
  companyId: string,
  filename: string,
  run: (sourceFileId: string) => Promise<TallyImportResult>
): Promise<void> {
  const auth = req.auth!;
  await assertCompanyInFirm(auth.firmId, companyId);

  const sourceFileId = await withTenant({ firmId: auth.firmId, companyId }, async (client) => {
    const existing = await client.query(
      `SELECT id FROM data_sources WHERE company_id = $1 AND source_type = 'tally' ORDER BY created_at LIMIT 1`,
      [companyId]
    );
    let dataSourceId: string | undefined = existing.rows[0]?.id;
    if (!dataSourceId) {
      const created = await client.query(
        `INSERT INTO data_sources (company_id, name, source_type) VALUES ($1, 'Tally', 'tally') RETURNING id`,
        [companyId]
      );
      dataSourceId = created.rows[0].id as string;
    }
    const file = await client.query(
      `INSERT INTO source_files (company_id, data_source_id, filename, uploaded_by, status)
       VALUES ($1, $2, $3, $4, 'PENDING') RETURNING id`,
      [companyId, dataSourceId, filename, auth.userId]
    );
    return file.rows[0].id as string;
  });

  let result: TallyImportResult;
  try {
    result = await run(sourceFileId);
  } catch (err) {
    // A failed import saved no rows, so drop the empty file record instead of leaving a junk entry in the
    // imports list. (The audit trail still keeps the record that it was attempted.) If the delete is not
    // possible for any reason, fall back to marking it ERROR. Either way the original error is what is reported.
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
}

/** Upload a Tally XML export (Day Book > Export > XML). Works wherever the API runs; Tally need not be reachable. */
tallyRouter.post("/import-file", authenticate, (req, res, next) => {
  upload.single("file")(req, res, (err: unknown) => {
    if (err) {
      const code = (err as { code?: string }).code;
      res.status(code === "LIMIT_FILE_SIZE" ? 413 : 400).json({
        error: code === "LIMIT_FILE_SIZE" ? "that file is too large (limit 100 MB). Export a shorter date range" : "the upload failed",
      });
      return;
    }
    next();
  });
}, async (req, res) => {
  const uploadedPath = req.file?.path;
  try {
    const companyId = req.body?.companyId;
    if (typeof companyId !== "string" || !UUID.test(companyId)) throw bad("companyId is required");
    if (!req.file) throw bad("no file uploaded (expected multipart field 'file')");
    if (path.extname(req.file.originalname).toLowerCase() !== ".xml") throw bad("expected a Tally XML export (a .xml file)");
    const auth = req.auth!;
    await importInto(req, res, companyId, req.file.originalname, (sourceFileId) =>
      runEngineCli<TallyImportResult>("engine.tally.cli", ["import-file", req.file!.path, auth.firmId, companyId, sourceFileId])
    );
  } catch (err) {
    respondError(res, err, "tally file import failed");
  } finally {
    if (uploadedPath) await unlink(uploadedPath).catch(() => {});
  }
});

/** Fetch the Day Book straight from a running Tally for a date range. The Tally address is a server setting
 *  (TALLY_URL), never taken from the request. */
tallyRouter.post("/import-live", authenticate, async (req, res) => {
  try {
    const { companyId, fromDate, toDate, tallyCompany } = (req.body ?? {}) as Record<string, unknown>;
    if (typeof companyId !== "string" || !UUID.test(companyId)) throw bad("companyId is required");
    if (typeof fromDate !== "string" || !ISO_DATE.test(fromDate)) throw bad("fromDate must look like 2025-04-01");
    if (typeof toDate !== "string" || !ISO_DATE.test(toDate)) throw bad("toDate must look like 2026-03-31");
    if (toDate < fromDate) throw bad("toDate is before fromDate");
    let company = "-";
    if (tallyCompany !== undefined && tallyCompany !== null && tallyCompany !== "") {
      // eslint-disable-next-line no-control-regex
      if (typeof tallyCompany !== "string" || tallyCompany.length > 200 || /[\u0000-\u001f]/.test(tallyCompany)) throw bad("tallyCompany is not valid");
      company = tallyCompany;
    }
    const auth = req.auth!;
    const label = `Tally Day Book ${fromDate} to ${toDate}${company === "-" ? "" : ` (${company})`}`;
    await importInto(req, res, companyId, label.slice(0, 250), (sourceFileId) =>
      runEngineCli<TallyImportResult>("engine.tally.cli", ["import-live", fromDate, toDate, company, auth.firmId, companyId, sourceFileId])
    );
  } catch (err) {
    respondError(res, err, "tally live import failed");
  }
});