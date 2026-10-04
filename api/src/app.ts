import express from "express";
import { authRouter } from "./modules/auth/routes.js";
import { importsRouter } from "./modules/imports/routes.js";
import { mappingsRouter } from "./modules/mappings/routes.js";
import { accountsRouter } from "./modules/accounts/routes.js";
import { periodsRouter } from "./modules/periods/routes.js";
import { statementsRouter } from "./modules/statements/routes.js";
import { schedulesRouter } from "./modules/schedules/routes.js";
import { adjustmentsRouter } from "./modules/adjustments/routes.js";

export const app = express();
app.use(express.json());

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.use("/auth", authRouter);
app.use("/imports", importsRouter);
app.use("/mappings", mappingsRouter);
app.use("/companies", accountsRouter);
app.use("/companies", periodsRouter);
app.use("/companies", statementsRouter);
app.use("/companies", schedulesRouter);
app.use("/companies", adjustmentsRouter);
