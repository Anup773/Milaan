import express from "express";
import { authRouter } from "./modules/auth/routes.js";
import { importsRouter } from "./modules/imports/routes.js";

export const app = express();
app.use(express.json());

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.use("/auth", authRouter);
app.use("/imports", importsRouter);