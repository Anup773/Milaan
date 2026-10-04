import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

export const mappingsRouter = Router();

interface NewAccountInput {
  code: string;
  name: string;
  accountType: string;
  parentAccountId?: string | null;
}

mappingsRouter.get("/:companyId/unmapped", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;

  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.mapping.cli", ["unmapped", auth.firmId, companyId]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to list unmapped accounts");
  }
});

mappingsRouter.post(
  "/:companyId/confirm",
  authenticate,
  requireRole("accountant", "senior_accountant", "ca", "admin"),
  async (req, res) => {
    const { companyId } = req.params;
    const auth = req.auth!;
    const { accountRef, accountId, newAccount } = req.body ?? {} as {
      accountRef?: string;
      accountId?: string;
      newAccount?: NewAccountInput;
    };

    if (typeof accountRef !== "string" || !accountRef.trim()) {
      res.status(400).json({ error: "accountRef is required" });
      return;
    }
    if ((accountId == null) === (newAccount == null)) {
      res.status(400).json({ error: "pass exactly one of accountId or newAccount" });
      return;
    }

    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      const payload = JSON.stringify({ accountRef, accountId, newAccount, confirmedBy: auth.userId });
      const result = await runEngineCli("engine.mapping.cli", ["confirm", auth.firmId, companyId, payload]);
      res.json(result);
    } catch (err) {
      respondError(res, err, "failed to confirm mapping");
    }
  }
);

mappingsRouter.post(
  "/:companyId/source-files/:sourceFileId/materialize",
  authenticate,
  requireRole("accountant", "senior_accountant", "ca", "admin"),
  async (req, res) => {
    const { companyId, sourceFileId } = req.params;
    const auth = req.auth!;

    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      const result = await runEngineCli("engine.mapping.cli", [
        "materialize",
        auth.firmId,
        companyId,
        sourceFileId,
        auth.userId,
      ]);
      res.json(result);
    } catch (err) {
      respondError(res, err, "failed to materialize source file");
    }
  }
);
