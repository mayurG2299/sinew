import { useEffect, useState } from "react";
import { api, setTenant, TENANTS, type Staff } from "./api";
import { Impact } from "./pages/Impact";
import { Inbox } from "./pages/Inbox";
import { Privacy } from "./pages/Privacy";
import { Promises } from "./pages/Promises";
import { StaffContext } from "./staff";

const PAGES = [
  { id: "inbox", label: "Inbox", note: "customer trace" },
  { id: "impact", label: "Decision impact", note: "complaints → decisions" },
  { id: "promises", label: "Promises", note: "kept, due, broken" },
  { id: "privacy", label: "Privacy", note: "export, delete-me" },
] as const;
type Page = (typeof PAGES)[number]["id"];

const ROLE: Record<string, string> = {
  agent: "Support agent", team_lead: "Team lead", support_head: "Support head", contractor: "Contractor",
  logistics_manager: "Logistics", marketing_manager: "Marketing", analyst: "Analyst", ceo: "CEO",
};

function fromHash(): Page {
  const h = window.location.hash.replace("#", "").split("/")[0];
  return (PAGES.find((p) => p.id === h)?.id ?? "inbox") as Page;
}

export default function App() {
  const [tenant, setTenantState] = useState(() => {
    const q = new URLSearchParams(window.location.search).get("company");  // ?company=larkspur opens that company
    return TENANTS.some((t) => t.id === q) ? q! : "northwind";
  });
  const [staff, setStaff] = useState<Staff[]>([]);
  const [asUser, setAsUser] = useState("u-agent-w1");
  const [page, setPage] = useState<Page>(fromHash());
  const [hash, setHash] = useState(window.location.hash);
  const [menuOpen, setMenuOpen] = useState(false);
  const [note, setNote] = useState("");
  const [key, setKey] = useState(0);

  useEffect(() => {
    setTenant(tenant);
    api.staff().then((list) => {
      setStaff(list);
      // keep the person if they belong to this company, else start as its first support agent
      if (!list.some((s) => s.id === asUser)) setAsUser((list.find((s) => s.role === "agent") ?? list[0]).id);
      setKey((k) => k + 1);
    });
  }, [tenant]);
  useEffect(() => {
    const on = () => { setPage(fromHash()); setHash(window.location.hash); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const me = staff.find((s) => s.id === asUser);

  async function demo(kind: "reset" | "scan") {
    setNote(kind === "reset" ? "Restoring the demo graph…" : "Sending a courier scan through the SDK…");
    const r = kind === "reset" ? await api.reset() : await api.liveScan();
    setNote(kind === "reset" ? `Demo data restored (${r.version}).` : `New scan received: ${r.accepted} event, signals: ${r.signals.map((s: any) => s.signal).join(", ") || "none"}.`);
    setKey((k) => k + 1);
  }

  const sidebar = (
    <nav className="flex h-full flex-col gap-5 overflow-y-auto bg-white p-4">
      <div>
        <p className="text-lg font-semibold tracking-tight text-stone-900">Sinew</p>
        <p className="text-xs text-stone-500">company brain · made-up demo data</p>
      </div>
      <div>
        <label className="text-xs font-medium text-stone-500">Company</label>
        <select value={tenant} onChange={(e) => setTenantState(e.target.value)}
          className="mt-1 w-full rounded-md border border-stone-300 px-2 py-1.5 text-sm">
          {TENANTS.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <p className="mt-1 text-[11px] leading-snug text-stone-500">Its own graph; data arrives as {TENANTS.find((t) => t.id === tenant)?.note}. Same engine, same tools.</p>
      </div>
      <div>
        <label className="text-xs font-medium text-stone-500">Signed in as</label>
        <select value={asUser} onChange={(e) => { setAsUser(e.target.value); setKey((k) => k + 1); }}
          className="mt-1 w-full rounded-md border border-stone-300 px-2 py-1.5 text-sm">
          {staff.map((s) => <option key={s.id} value={s.id}>{s.name} · {ROLE[s.role] ?? s.role}</option>)}
        </select>
        {me && <p className="mt-1 text-[11px] leading-snug text-stone-500">{me.team} · regions {me.regions.join(", ") || "none"}
          {me.refund_limit > 0 && ` · refunds up to $${me.refund_limit}`}. Switch person to see the same data filtered differently.</p>}
      </div>
      <ul className="space-y-1">
        {PAGES.map((p) => (
          <li key={p.id}>
            <a href={`#${p.id}`} onClick={() => setMenuOpen(false)}
              className={`block rounded-lg px-3 py-2 ${page === p.id ? "bg-teal-50 text-teal-900" : "text-stone-700 hover:bg-stone-50"}`}>
              <span className="block text-sm font-medium">{p.label}</span>
              <span className={`block text-[11px] ${page === p.id ? "text-teal-800" : "text-stone-500"}`}>{p.note}</span>
            </a>
          </li>
        ))}
      </ul>
      <div className="mt-auto space-y-2 border-t border-stone-100 pt-4">
        <p className="text-xs font-medium text-stone-500">Demo controls</p>
        <button onClick={() => demo("scan")} className="block w-full rounded-md border border-stone-300 px-2 py-1.5 text-left text-xs hover:bg-stone-50">Send a live courier scan</button>
        <button onClick={() => demo("reset")} className="block w-full rounded-md border border-stone-300 px-2 py-1.5 text-left text-xs hover:bg-stone-50">Reset demo data</button>
        {note && <p className="text-[11px] text-stone-500">{note}</p>}
        <p className="pt-2 text-[11px] text-stone-400">Brewed by <a className="underline" href="https://x.com/justletmebrew">Let Me Brew</a></p>
      </div>
    </nav>
  );

  const byId = Object.fromEntries(staff.map((s) => [s.id, s]));
  return (
    <StaffContext.Provider value={byId}>
    <div className="flex h-dvh bg-stone-50 text-stone-900">
      <div className="hidden w-64 shrink-0 border-r border-stone-200 lg:block">{sidebar}</div>
      {menuOpen && (
        <div className="fixed inset-0 z-30 lg:hidden" onClick={() => setMenuOpen(false)}>
          <div className="h-full w-72 border-r border-stone-200 shadow-xl" onClick={(e) => e.stopPropagation()}>{sidebar}</div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <button onClick={() => setMenuOpen(true)} className="m-2 self-start rounded-md border border-stone-300 bg-white px-3 py-1 text-sm lg:hidden">
          ☰ {PAGES.find((p) => p.id === page)?.label} · {me?.name}
        </button>
        <div className="min-h-0 flex-1" key={`${tenant}-${hash.startsWith("#inbox/") ? hash : page}-${asUser}-${key}`}>
          {page === "inbox" && <Inbox asUser={asUser} />}
          {page === "impact" && <Impact asUser={asUser} />}
          {page === "promises" && <Promises asUser={asUser} />}
          {page === "privacy" && <Privacy asUser={asUser} />}
        </div>
      </div>
    </div>
    </StaffContext.Provider>
  );
}
