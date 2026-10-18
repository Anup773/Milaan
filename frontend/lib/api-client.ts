// The one place the screens talk to the Milaan API. Calls go to this app's own /api/proxy/..., which adds the
// signed-in user's token server-side. Errors become ApiError with the API's own message, so a screen can show
// exactly why something was refused ("a note is required", "cannot approve something you made yourself", ...).

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  const clean = path.replace(/^\/+/, "");
  const params = new URLSearchParams();
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
    }
  }
  const qs = params.toString();
  return `/api/proxy/${clean}${qs ? `?${qs}` : ""}`;
}

let redirectingToLogin = false;

function handleSessionExpired(): void {
  if (typeof window === "undefined" || redirectingToLogin) return;
  redirectingToLogin = true;
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

async function errorFrom(res: Response): Promise<ApiError> {
  let message = `request failed (${res.status})`;
  try {
    const data = (await res.json()) as { error?: unknown };
    if (typeof data.error === "string" && data.error) message = data.error;
  } catch {
    /* not JSON -- keep the generic message */
  }
  return new ApiError(res.status, message);
}

export interface ApiOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
}

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal } = options;
  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), {
      method,
      headers: body !== undefined ? { "content-type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
      signal,
    });
  } catch (err) {
    if ((err as { name?: string }).name === "AbortError") throw err;
    throw new ApiError(0, "cannot reach the server - check your connection");
  }
  if (res.status === 401) handleSessionExpired();
  if (!res.ok) throw await errorFrom(res);
  return (await res.json()) as T;
}

/** Posts a file (multipart). The browser sets the multipart boundary itself, so no content-type header here. */
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path), { method: "POST", body: form, cache: "no-store" });
  } catch {
    throw new ApiError(0, "cannot reach the server - check your connection");
  }
  if (res.status === 401) handleSessionExpired();
  if (!res.ok) throw await errorFrom(res);
  return (await res.json()) as T;
}

export interface Download {
  blob: Blob;
  filename: string;
  headers: Headers;
}

/** Fetches a file (the audit CSV) and returns it for saving. */
export async function apiDownload(path: string, query?: Query): Promise<Download> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), { cache: "no-store" });
  } catch {
    throw new ApiError(0, "cannot reach the server - check your connection");
  }
  if (res.status === 401) handleSessionExpired();
  if (!res.ok) throw await errorFrom(res);
  const disposition = res.headers.get("content-disposition") ?? "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  return { blob: await res.blob(), filename: match?.[1] ?? "download", headers: res.headers };
}

/** Hands a downloaded blob to the browser as a file save. */
export function saveBlob(download: Download): void {
  const url = URL.createObjectURL(download.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = download.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function signOut(): Promise<void> {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } finally {
    window.location.assign("/login");
  }
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "something went wrong";
}
