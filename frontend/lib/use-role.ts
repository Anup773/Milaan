"use client";

import { useWorkspace } from "./workspace";
import type { Role } from "./roles";

/** The signed-in user's role (undefined until the workspace has loaded). Only for showing or hiding buttons: the API enforces it. */
export function useAuthRole(): Role | undefined {
  return useWorkspace().me?.role;
}