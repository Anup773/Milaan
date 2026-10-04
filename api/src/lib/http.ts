import type { Response } from "express";

/** Any error may carry a `status`; those from access.ts and elsewhere do. */
export interface StatusError extends Error {
  status?: number;
}

export function respondError(res: Response, err: unknown, fallbackMessage: string): void {
  const status = (err as StatusError)?.status ?? 500;
  const message = err instanceof Error ? err.message : fallbackMessage;
  if (status >= 500) {
    console.error(fallbackMessage + ":", err);
  }
  res.status(status).json({ error: message });
}