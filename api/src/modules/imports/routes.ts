import { execFile } from "node:child_process";
import { unlink } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { Router } from "express";
import multer from "multer";
import { authenticate } from "../auth/middleware.js";
import { withTenant } from "../../db/client.js";

export const importsRouter = Router();

// multer's default storage drops the original file extension -- but
// parse_file() on the Python side dispatches on .csv vs .xlsx, so the
// temp file needs to keep it.
const storage = multer.diskStorage({
  destination: "/tmp/milaan-uploads/",
  filename: (_req, file, cb) => cb(null, `${randomUUID()}${path.extname(file.originalname)}`),
});
const upload = multer({ storage });

// Where the Python engine package lives, relative to wherever this process
// runs from. Override with ENGINE_DIR in .env if your layout differs from
// api/ and engine/ sitting side by side.
const ENGINE_DIR = process.env.ENGINE_DIR ?? "../engine";
const PYTHON_BIN = process.env.PYTHON_BIN ?? "python3";

interface CliResult {
  rows: number;
  errors: number;
  warnings: number;
  total_debit: string;
  total_credit: string;
}

function runIngestionCli(filePath: string, firmId: string, companyId: string, sourceFileId: string): Promise<CliResult> {
  return new Promise((resolve, reject) => {
    execFile(
      PYTHON_BIN,
      ["-m", "engine.ingestion.cli", filePath, firmId, companyId, sourceFileId],
      { cwd: ENGINE_DIR },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(stderr.trim() || error.message));
          return;
        }
        try {
          resolve(JSON.parse(stdout));
        } catch {
          reject(new Error(`unparseable output from ingestion engine: ${stdout}`));
        }
      }
    );
  });
}

importsRouter.post("/", authenticate, upload.single("file"), async (req, res) => {
  const companyId = req.body?.companyId;
  if (typeof companyId !== "string") {
    res.status(400).json({ error: "companyId is required" });
    return;
  }
  if (!req.file) {
    res.status(400).json({ error: "no file uploaded (expected multipart field 'file')" });
    return;
  }
  const auth = req.auth!; // authenticate middleware guarantees this
  const uploadedPath = req.file.path;

  try {
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
      cliResult = await runIngestionCli(uploadedPath, auth.firmId, companyId, sourceFileId);
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
    console.error("import failed:", err);
    res.status(500).json({ error: err instanceof Error ? err.message : "import failed" });
  } finally {
    await unlink(uploadedPath).catch(() => {});
  }
});