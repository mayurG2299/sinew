import { createContext, useContext } from "react";
import type { Staff } from "./api";

export const StaffContext = createContext<Record<string, Staff>>({});

/** A person's name from the company roster (fetched live, never stored in the graph); the id if unknown. */
export function useName() {
  const staff = useContext(StaffContext);
  return (id?: string | null) => (id ? staff[id]?.name ?? id : "—");
}

export function TicketLink({ id }: { id: string }) {
  return <a href={`#inbox/${id}`} className="font-mono text-teal-800 underline decoration-teal-200 underline-offset-2 hover:decoration-teal-700">{id}</a>;
}
