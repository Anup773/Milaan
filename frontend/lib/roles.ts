// Who may do what. These lists mirror the role lists in the API routes (api/src/modules/*/routes.ts). They only
// decide which buttons the screen SHOWS; the API checks the role again on every request and is the real gate.

export type Role = "accountant" | "senior_accountant" | "ca" | "reviewer" | "admin";

export const ROLE_LABEL: Record<Role, string> = {
  accountant: "Accountant",
  senior_accountant: "Senior accountant",
  ca: "Chartered accountant",
  reviewer: "Reviewer",
  admin: "Admin",
};

const any = (...roles: Role[]) => roles;

export const CAN = {
  createCompany: any("senior_accountant", "ca", "admin"),
  createAccount: any("senior_accountant", "ca", "admin"),
  createPeriod: any("senior_accountant", "ca", "admin"),
  createFixedAsset: any("senior_accountant", "ca", "admin"),
  postDepreciation: any("senior_accountant", "ca", "admin"),
  confirmMapping: any("accountant", "senior_accountant", "ca", "admin"),
  proposeAdjustment: any("accountant", "senior_accountant", "ca", "admin"),
  decideAdjustment: any("senior_accountant", "ca", "reviewer", "admin"),
  // scenarios
  makeScenario: any("accountant", "senior_accountant", "ca", "admin"),
  reviewScenario: any("reviewer", "ca", "admin"),
  linkOrPostScenario: any("senior_accountant", "ca", "reviewer", "admin"),
  finalizeScenario: any("ca", "admin"),
  requestReopen: any("senior_accountant", "ca", "admin"),
  decideReopen: any("ca", "admin"),
  // exceptions
  reviewException: any("senior_accountant", "ca", "reviewer", "admin"),
  proposeReversal: any("accountant", "senior_accountant", "ca", "admin"),
  // audit
  readAudit: any("senior_accountant", "ca", "reviewer", "admin"),
  exportAudit: any("ca", "reviewer", "admin"),
  verifyAudit: any("ca", "reviewer", "admin"),
} as const;

export function can(role: Role | undefined | null, allowed: readonly Role[]): boolean {
  return !!role && allowed.includes(role);
}
