import { unlink } from "node:fs/promises";
import { mkdirSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { randomUUID } from "node:crypto";
import { Router } from "express";
import multer from "multer";
import { authenticate } from "../auth/middleware.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";
import { withTenant } from "../../db/client.js";

export const importsRouter = Router();

const UPLOAD_DIR = path.join(os.tmpdir(), "milaan-uploads");
mkdirSync(UPLOAD_DIR, { recursive: true });

const storage = multer.diskStorage({
  destination: UPLOAD_DIR,
  filename: (_req, file, cb) => cb(null, `${randomUUID()}${path.extname(file.originalname)}`),
});
const upload = multer({ storage });

interface CliResult {
  rows: number;
  errors: number;
  warnings: number;
  total_debit: string;
  total_credit: string;
  issues_total: number;
  issues: Array<{ row: number; field: string; severity: string; message: string }>;
}

importsRouter.post("/", authenticate, upload.single("file"), async (req, res) => {
  const companyId = req.body?.companyId;
  const auth = req.auth!;

  if (typeof companyId !== "string") {
    res.status(400).json({ error: "companyId is required" });
    if (req.file) await unlink(req.file.path).catch(() => {});
    return;
  }
  if (!req.file) {
    res.status(400).json({ error: "no file uploaded (expected multipart field 'file')" });
    return;
  }
  const uploadedPath = req.file.path;

  try {
    await assertCompanyInFirm(auth.firmId, companyId);

    const sourceFileId = await withTenant({ firmId: auth.firmId, companyId }, async (client) => {
      const dataSource = await client.query(
        `INSERT INTO data_sources (company_id, name, source_type)
         VALUES ($1, 'Manual upload', 'csv-or-excel')
         ON CONFLICT DO NOTHING
         RETURNING id`,
        [companyId]
      );
      let dataSourceId = dataSource.rows[0]?.id;
      if (!dataSourceId) {
        const existing = await client.query(
          `SELECT id FROM data_sources WHERE company_id = $1 AND name = 'Manual upload' LIMIT 1`,
          [companyId]
        );
        dataSourceId = existing.rows[0].id;
      }

      const sourceFile = await client.query(
        `INSERT INTO source_files (company_id, data_source_id, filename, uploaded_by, status)
         VALUES ($1, $2, $3, $4, 'PENDING') RETURNING id`,
        [companyId, dataSourceId, req.file!.originalname, auth.userId]
      );
      return sourceFile.rows[0].id as string;
    });

    let cliResult: CliResult;
    try {
      cliResult = await runEngineCli<CliResult>("engine.ingestion.cli", [uploadedPath, auth.firmId, companyId, sourceFileId]);
    } catch (err) {
      await withTenant({ firmId: auth.firmId, companyId }, (client) =>
        client.query(`UPDATE source_files SET status = 'ERROR' WHERE id = $1`, [sourceFileId])
      );
      throw err;
    }

    await withTenant({ firmId: auth.firmId, companyId }, (client) =>
      client.query(`UPDATE source_files SET status = 'PROCESSED' WHERE id = $1`, [sourceFileId])
    );

    res.json({ sourceFileId, ...cliResult });
  } catch (err) {
    respondError(res, err, "import failed");
  } finally {
    await unlink(uploadedPath).catch(() => {});
  }
});
