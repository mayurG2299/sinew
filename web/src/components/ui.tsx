import { useState, type ReactNode } from "react";
import type { Answer } from "../api";

export function Section({ title, hint, children, open: initial = true, right }:
  { title: string; hint?: string; children: ReactNode; open?: boolean; right?: ReactNode }) {
  const [open, setOpen] = useState(initial);
  return (
    <section className="rounded-xl border border-stone-200 bg-white">
      <header className="flex items-center gap-3 px-5 py-3">
        <button onClick={() => setOpen(!open)} className="flex flex-1 items-center gap-2 text-left" aria-expanded={open}>
          <span className="text-stone-400 text-xs w-3">{open ? "▾" : "▸"}</span>
          <h2 className="text-[15px] font-semibold text-stone-800">{title}</h2>
          {hint && <span className="text-xs text-stone-500 truncate">{hint}</span>}
        </button>
        {right}
      </header>
      {open && <div className="border-t border-stone-100 px-5 py-4">{children}</div>}
    </section>
  );
}

const OUTCOME: Record<string, [string, string]> = {
  answered_path: ["from the graph", "bg-teal-50 text-teal-800 border-teal-200"],
  answered_memory: ["from memory", "bg-sky-50 text-sky-800 border-sky-200"],
  not_in_graph: ["nothing matched", "bg-stone-100 text-stone-700 border-stone-200"],
  unknown_entity: ["not in the graph", "bg-amber-50 text-amber-800 border-amber-200"],
  not_permitted: ["not permitted", "bg-rose-50 text-rose-800 border-rose-200"],
  needs_approval: ["needs approval", "bg-amber-50 text-amber-800 border-amber-200"],
  pending_confirmation: ["waits for you", "bg-amber-50 text-amber-800 border-amber-200"],
};

export function Outcome({ outcome }: { outcome: string }) {
  const [label, cls] = OUTCOME[outcome] ?? [outcome, "bg-stone-100 text-stone-700 border-stone-200"];
  return <span className={`inline-block rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>{label}</span>;
}

export function Chip({ children, tone = "stone" }: { children: ReactNode; tone?: "stone" | "teal" | "amber" | "rose" }) {
  const cls = { stone: "bg-stone-100 text-stone-700", teal: "bg-teal-50 text-teal-800", amber: "bg-amber-50 text-amber-800", rose: "bg-rose-50 text-rose-800" }[tone];
  return <span className={`inline-block rounded-md px-1.5 py-0.5 text-xs ${cls}`}>{children}</span>;
}

export function Hidden({ items }: { items: Answer["hidden"] }) {
  if (!items?.length) return null;
  return (
    <ul className="mt-3 space-y-1 text-xs text-stone-500">
      {items.map((h, i) => (
        <li key={i}>🔒 {h.field ? `${h.field} hidden` : `${h.count ?? ""} ${h.kind ?? "items"} hidden`}: {h.reason}</li>
      ))}
    </ul>
  );
}

export function Refused({ a }: { a: Answer }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white px-5 py-6">
      <Outcome outcome={a.outcome} />
      <p className="mt-2 text-stone-700">{a.reason}</p>
    </div>
  );
}

export function Stat({ value, label, note }: { value: ReactNode; label: string; note?: string }) {
  return (
    <div className="min-w-[8rem]">
      <div className="text-2xl font-semibold text-stone-900">{value}</div>
      <div className="text-xs text-stone-600">{label}</div>
      {note && <div className="text-[11px] text-stone-400">{note}</div>}
    </div>
  );
}
