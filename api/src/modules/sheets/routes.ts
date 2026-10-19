import { Router, type Request, type Response } from "express";
import { authenticate } from "../auth/middleware.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError, type StatusError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";
import { withTenant } from "../../db/client.js";

export const sheetsRouter = Router();

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_LINK_LENGTH = 500;

function bad(message: string): StatusError {
  const err = new Error(message) as StatusError;
  err.status = 400;
  return err;
}

interface SheetsStatus {
  mode: "service_account" | "public_link" | "service_account_error";
  service_account_email: string | null;
  message: string;
}

interface SheetCheck {
  mode: "service_account" | "public_link";
  title: string | null;
  tabs: Array<{ title: string; gid: number }>;
  suggested_tab: string | null;
  rows_seen?: number;
  gid?: number;
}

interface SheetsImportResult {
  rows: number;
  errors: number;
  warnings: number;
  total_debit: string;
  total_credit: string;
  issues_total: number;
  issues: Array<{ row: number; field: string; severity: string; message: string }>;
  sheet: { mode: string; title: string | null; tab: string | null; label: string };
}

/** The link is only ever handed to the engine as a command-line argument (never run by a shell) and the engine
 *  validates it and builds its own Google addresses, so nothing a person pastes is requested as-is. */
function readLink(value: unknown): string {
  if (typeof value !== "string" || value.trim() === "") throw bad("paste the Google Sheets link");
  const link = value.trim();
  if (link.length > MAX_LINK_LENGTH) throw bad("that link is too long");
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f]/.test(link)) throw bad("that link has characters that are not allowed");
  return link;
}

/** How sheets will be read: with the server's service account (and the email to share sheets with), or only via
 *  "anyone with the link". Never errors just because nothing is set up. */
sheetsRouter.get("/status", authenticate, async (_req, res) => {
  try {
    res.json(await runEngineCli<SheetsStatus>("engine.sheets.cli", ["status"]));
  } catch (err) {
    respondError(res, err, "sheets status failed");
  }
});

/** Can this sheet be reached? Returns its title and tabs (tabs only with a service account). Saves nothing. */
sheetsRouter.post("/check", authenticate, async (req, res) => {
  try {
    const link = readLink((req.body ?? {}).url);
    res.json(await runEngineCli<SheetCheck>("engine.sheets.cli", ["check", link]));
  } catch (err) {
    respondError(res, err, "sheet check failed");
  }
});

async function importInto(req: Request, res: Response, companyId: string, run: (sourceFileId: string) => Promise<SheetsImportResult>): Promise<void> {
  const auth = req.auth!;
  await assertCompanyInFirm(auth.firmId, companyId);

  const sourceFileId = await withTenant({ firmId: auth.firmId, companyId }, async (client) => {
    const existing = await client.query(
      `SELECT id FROM data_sources WHERE company_id = $1 AND source_type = 'google-sheets' ORDER BY created_at LIMIT 1`,
      [companyId]
    );
    let dataSourceId: string | undefined = existing.rows[0]?.id;
    if (!dataSourceId) {
      const created = await client.query(
        `INSERT INTO data_sources (company_id, name, source_type) VALUES ($1, 'Google Sheets', 'google-sheets') RETURNING id`,
        [companyId]
      );
      dataSourceId = created.rows[0].id as string;
    }
    const file = await client.query(
      `INSERT INTO source_files (company_id, data_source_id, filename, uploaded_by, status)
       VALUES ($1, $2, 'Google Sheet (importing)', $3, 'PENDING') RETURNING id`,
      [companyId, dataSourceId, auth.userId]
    );
    return file.rows[0].id as string;
  });

  let result: SheetsImportResult;
  try {
    result = await run(sourceFileId);
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
  // The real label (sheet title and tab) comes from the engine, never from the browser.
  await withTenant({ firmId: auth.firmId, companyId }, (client) =>
    client.query(`UPDATE source_files SET status = 'PROCESSED', filename = $2 WHERE id = $1`, [sourceFileId, result.sheet.label.slice(0, 250)])
  );
  res.json({ sourceFileId, ...result });
}

/** Read one tab of a Google Sheet and import it like an Excel/CSV file. */
sheetsRouter.post("/import", authenticate, async (req, res) => {
  try {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const companyId = body.companyId;
    if (typeof companyId !== "string" || !UUID.test(companyId)) throw bad("companyId is required");
    const link = readLink(body.url);
    let tab = "-";
    if (body.tab !== undefined && body.tab !== null && body.tab !== "") {
      // eslint-disable-next-line no-control-regex
      if (typeof body.tab !== "string" || body.tab.length > 200 || /[\u0000-\u001f]/.test(body.tab)) throw bad("the tab name is not valid");
      tab = body.tab;
    }
    const auth = req.auth!;
    await importInto(req, res, companyId, (sourceFileId) =>
      runEngineCli<SheetsImportResult>("engine.sheets.cli", ["import", link, tab, auth.firmId, companyId, sourceFileId])
    );
  } catch (err) {
    respondError(res, err, "sheet import failed");
  }
});