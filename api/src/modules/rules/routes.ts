import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { respondError, type StatusError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";
import { FilterError, catalogArgs, parseFilters, parseRuleSetId } from "./filters.js";

export const rulesRouter = Router();

const CLI = "engine.rules.cli";

function bad(err: FilterError): StatusError {
  const e = new Error(err.message) as StatusError;
  e.status = 400;
  return e;
}

// The catalog of accounting / auditing / tax / compliance rule sets (§12). It is the same for every firm and
// holds no client data, so any signed-in user may read it. It is a catalog only: nothing here changes the books.
rulesRouter.get("/", authenticate, async (req, res) => {
  try {
    let args: string[];
    try {
      args = catalogArgs(parseFilters(req.query as Record<string, unknown>));
    } catch (err) {
      throw err instanceof FilterError ? bad(err) : err;
    }
    res.json(await runEngineCli(CLI, args));
  } catch (err) {
    respondError(res, err, "failed to load the rules catalog");
  }
});

rulesRouter.get("/:ruleSetId", authenticate, async (req, res) => {
  try {
    let id: string;
    try {
      id = parseRuleSetId(req.params.ruleSetId);
    } catch (err) {
      throw err instanceof FilterError ? bad(err) : err;
    }
    res.json(await runEngineCli(CLI, ["get", id]));
  } catch (err) {
    respondError(res, err, "failed to load the rule set");
  }
});