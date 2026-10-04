import { execFile } from "node:child_process";
import type { StatusError } from "./http.js";

// Where the Python engine package lives, relative to wherever this process
// runs from. Override with ENGINE_DIR in .env if your layout differs from
// api/ and engine/ sitting side by side.
const ENGINE_DIR = process.env.ENGINE_DIR ?? "../engine";

// Windows rarely has a bare `python3` on PATH (it's often missing entirely,
// or a Microsoft Store stub that opens a install prompt) -- `python` is the
// normal launcher there. Still overridable via PYTHON_BIN for either OS.
const DEFAULT_PYTHON_BIN = process.platform === "win32" ? "python" : "python3";
const PYTHON_BIN = process.env.PYTHON_BIN ?? DEFAULT_PYTHON_BIN;

export function runEngineCli<T = unknown>(pythonModule: string, args: string[]): Promise<T> {
  return new Promise((resolve, reject) => {
    execFile(
      PYTHON_BIN,
      ["-m", pythonModule, ...args],
      { cwd: ENGINE_DIR },
      (error, stdout, stderr) => {
        if (error) {
          // Every engine CLI's contract is: on failure, print {"error": "...",
          // "status": 400 | 500} to stderr -- status:400 for a ValueError
          // (bad input / wrong state, the caller's fault), 500 for anything
          // else (a genuine, unexpected failure). Unwrap both here so
          // respondError reports the right HTTP code and the real message
          // reaches the client, instead of every engine error defaulting to
          // an unreadable 500.
          const trimmed = stderr.trim();
          let message = trimmed || error.message;
          let status: number | undefined;
          if (trimmed) {
            try {
              const parsed = JSON.parse(trimmed);
              if (parsed && typeof parsed.error === "string") {
                message = parsed.error;
              }
              if (parsed && typeof parsed.status === "number") {
                status = parsed.status;
              }
            } catch {
              // not JSON -- keep the raw text already assigned above
            }
          }
          const err = new Error(message) as StatusError;
          if (status !== undefined) err.status = status;
          reject(err);
          return;
        }
        try {
          resolve(JSON.parse(stdout) as T);
        } catch {
          reject(new Error(`unparseable output from ${pythonModule}: ${stdout}`));
        }
      }
    );
  });
}