import type { People } from "@/lib/types";
import { shortId } from "@/lib/format";

/** A person's e-mail from an id -> person map (or the short id when unknown, or a dash). */
export function who(id: string | null | undefined, people?: People | null): string {
  if (!id) return "-";
  return people?.[id]?.email ?? shortId(id);
}

export function Who({ id, people }: { id: string | null | undefined; people?: People | null }) {
  return <span>{who(id, people)}</span>;
}