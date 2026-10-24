// The sidebar, grouped the way an accountant works: look -> bring data in -> check -> change -> approve -> prove.
export interface NavItem {
  href: string;
  label: string;
  icon: string; // key into the icon table in Sidebar.tsx
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    title: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: "grid" },
      { href: "/statements", label: "Statements", icon: "book" },
      { href: "/assistant", label: "Ask Milaan", icon: "chat" },
    ],
  },
  {
    title: "Bring data in",
    items: [
      { href: "/companies", label: "Companies", icon: "building" },
      { href: "/imports", label: "Imports", icon: "upload" },
      { href: "/tally", label: "Tally", icon: "book" },
      { href: "/sheets", label: "Google Sheets", icon: "grid" },
      { href: "/bank", label: "Bank statements", icon: "scale" },
      { href: "/registers", label: "GST & payroll", icon: "book" },
      { href: "/mappings", label: "Mappings", icon: "link" },
      { href: "/versions", label: "Versions", icon: "compare" },
    ],
  },
  {
    title: "Check",
    items: [
      { href: "/schedules", label: "Schedules", icon: "calendar" },
      { href: "/reconciliation", label: "Reconciliation", icon: "scale" },
      { href: "/exceptions", label: "Exceptions", icon: "flag" },
      { href: "/rules", label: "Rules", icon: "shield" },
    ],
  },
  {
    title: "Change",
    items: [
      { href: "/adjustments", label: "Adjustments", icon: "edit" },
      { href: "/simulator", label: "Simulator", icon: "bolt" },
      { href: "/impact", label: "Impact", icon: "wave" },
    ],
  },
  {
    title: "Sign off",
    items: [
      { href: "/approvals", label: "Approvals", icon: "check" },
      { href: "/audit", label: "Audit trail", icon: "shield" },
    ],
  },
];
