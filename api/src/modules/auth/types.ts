// Role list matches ARCHITECTURE.md §9 exactly.
export type Role = "accountant" | "senior_accountant" | "ca" | "reviewer" | "admin";

export interface AuthContext {
  userId: string;
  firmId: string;
  companyId: string | null; // null until a specific company is selected/scoped
  role: Role;
}

declare global {
  namespace Express {
    interface Request {
      auth?: AuthContext;
    }
  }
}
