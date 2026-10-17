import { useEffect, useState } from "react";
import { api, setTenant, type Company, type Staff } from "./api";
import { Chat, type Thread } from "./pages/Chat";
import { Privacy } from "./pages/Privacy";
import { StaffContext } from "./staff";

export const ROLE: Record<string, string> = {
  agent: "Support agent", team_lead: "Team lead", support_head: "Head of support", contractor: "Contractor",
  logistics_manager: "Logistics manager", marketing_manager: "Marketing manager", analyst: "Analyst", ceo: "CEO",
};
const initials = (name: string) => name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();

type Session = { tenant: string; user: string };
const KEY = "sinew-session";
function saved(): Session | null {
  const link = new URLSearchParams(window.location.search).get("as");  // ?as=northwind:u-agent-w1 signs in (demo links)
  if (link?.includes(":")) { const [tenant, user] = link.split(":"); return { tenant, user }; }
  try { return JSON.parse(localStorage.getItem(KEY) ?? "null"); } catch { return null; }
}
function save(s: Session | null) {
  try { s ? localStorage.setItem(KEY, JSON.stringify(s)) : localStorage.removeItem(KEY); } catch { /* private window */ }
}

export default function App() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [session, setSession] = useState<Session | null>(saved);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [view, setView] = useState<"chat" | "privacy">("chat");
  const [menu, setMenu] = useState(false);
  const [nav, setNav] = useState(false);
  const [note, setNote] = useState("");
  const [key, setKey] = useState(0);

  useEffect(() => { api.people().then(setCompanies); }, []);
  if (session) setTenant(session.tenant);

  const company = companies.find((c) => c.tenant === session?.tenant);
  const me = company?.people.find((p) => p.id === session?.user);
  if (!session || !company || !me)
    return <Login companies={companies} onSignIn={(s) => { save(s); setSession(s); setThreads([]); setCurrent(null); setView("chat"); }} />;

  function signOut() { save(null); setSession(null); setMenu(false); setThreads([]); setCurrent(null); }
  async function demo(kind: "reset" | "scan") {
    setNote(kind === "reset" ? "Restoring the demo data…" : "Sending a courier scan…");
    try {
      const r = kind === "reset" ? await api.reset() : await api.liveScan();
      setNote(kind === "reset" ? "Demo data restored." : `New courier scan received${r.signals?.length ? ": a parcel is running late" : ""}.`);
    } catch { setNote("That didn't work. Try again."); }
    setKey((k) => k + 1);
  }

  const sidebar = (
    <nav className="flex h-full flex-col bg-stone-100/70 p-3">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-teal-700 text-sm font-bold text-white">S</span>
        <span className="text-[17px] font-semibold tracking-tight text-stone-900">Sinew</span>
      </div>
      <button onClick={() => { setCurrent(null); setView("chat"); setNav(false); }}
        className="mt-4 rounded-lg border border-stone-300 bg-white px-3 py-2 text-left text-sm font-medium text-stone-800 hover:bg-stone-50">+ New chat</button>
      <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
        {threads.length > 0 && <p className="px-2 pb-1 text-xs text-stone-500">Today</p>}
        <ul className="space-y-0.5">
          {threads.map((t) => (
            <li key={t.id}>
              <button onClick={() => { setCurrent(t.id); setView("chat"); setNav(false); }}
                className={`block w-full truncate rounded-lg px-2 py-1.5 text-left text-sm ${current === t.id && view === "chat" ? "bg-white text-stone-900 shadow-sm" : "text-stone-700 hover:bg-white/70"}`}>{t.title}</button>
            </li>
          ))}
        </ul>
      </div>
      {me.role === "support_head" && (
        <button onClick={() => { setView("privacy"); setNav(false); }}
          className={`mb-2 rounded-lg px-2 py-1.5 text-left text-sm ${view === "privacy" ? "bg-white text-stone-900 shadow-sm" : "text-stone-700 hover:bg-white/70"}`}>Privacy requests</button>
      )}
      <div className="relative border-t border-stone-200 pt-2">
        {menu && (
          <div className="absolute bottom-full left-0 right-0 mb-2 rounded-xl border border-stone-200 bg-white p-1.5 shadow-lg">
            <p className="px-2 pb-1 pt-1 text-xs text-stone-500">{company.company}</p>
            <button onClick={signOut} className="block w-full rounded-lg px-2 py-1.5 text-left text-sm hover:bg-stone-50">Switch account</button>
            <div className="my-1 border-t border-stone-100" />
            <p className="px-2 pb-1 pt-1 text-xs text-stone-500">Demo</p>
            <button onClick={() => demo("scan")} className="block w-full rounded-lg px-2 py-1.5 text-left text-sm hover:bg-stone-50">Send a live courier scan</button>
            <button onClick={() => demo("reset")} className="block w-full rounded-lg px-2 py-1.5 text-left text-sm hover:bg-stone-50">Reset demo data</button>
            {note && <p className="px-2 py-1 text-xs text-stone-500">{note}</p>}
            <div className="my-1 border-t border-stone-100" />
            <button onClick={signOut} className="block w-full rounded-lg px-2 py-1.5 text-left text-sm hover:bg-stone-50">Sign out</button>
          </div>
        )}
        <button onClick={() => setMenu(!menu)} aria-expanded={menu}
          className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left hover:bg-white/70">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-100 text-xs font-semibold text-teal-900">{initials(me.name)}</span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium text-stone-900">{me.name}</span>
            <span className="block truncate text-xs text-stone-500">{ROLE[me.role] ?? me.role} · {company.company}</span>
          </span>
        </button>
      </div>
    </nav>
  );

  const byId = Object.fromEntries(company.people.map((s) => [s.id, s]));
  return (
    <StaffContext.Provider value={byId}>
      <div className="flex h-dvh bg-white text-stone-900">
        <div className="hidden w-64 shrink-0 border-r border-stone-200 md:block">{sidebar}</div>
        {nav && (
          <div className="fixed inset-0 z-30 bg-black/20 md:hidden" onClick={() => setNav(false)}>
            <div className="h-full w-72 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>{sidebar}</div>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <button onClick={() => setNav(true)} className="m-2 self-start rounded-md px-2 py-1 text-sm text-stone-700 md:hidden">☰ Sinew</button>
          <div className="min-h-0 flex-1" key={`${session.tenant}-${session.user}-${key}`}>
            {view === "privacy" ? <Privacy asUser={me.id} />
              : <Chat me={me} threads={threads} setThreads={setThreads} current={current} setCurrent={setCurrent} />}
          </div>
        </div>
      </div>
    </StaffContext.Provider>
  );
}

/** Sign in: your company's workspace, then your account. No sign-up: accounts come from the company's roster. */
function Login({ companies, onSignIn }: { companies: Company[]; onSignIn: (s: Session) => void }) {
  const [tenant, setT] = useState<string | null>(null);
  const company = companies.find((c) => c.tenant === tenant);
  return (
    <div className="flex min-h-dvh items-center justify-center bg-stone-50 p-4">
      <div className="w-full max-w-md rounded-2xl border border-stone-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-700 font-bold text-white">S</span>
          <span className="text-xl font-semibold tracking-tight">Sinew</span>
        </div>
        {!company ? <>
          <h1 className="mt-6 text-lg font-semibold">Sign in to your company</h1>
          <p className="mt-1 text-sm text-stone-600">Each company has its own private brain.</p>
          <ul className="mt-4 space-y-2">
            {companies.map((c) => (
              <li key={c.tenant}>
                <button onClick={() => setT(c.tenant)} className="flex w-full items-center justify-between rounded-xl border border-stone-200 px-4 py-3 text-left hover:border-teal-600 hover:bg-teal-50/40">
                  <span className="font-medium">{c.company}</span><span className="text-stone-400">›</span>
                </button>
              </li>
            ))}
          </ul>
        </> : <>
          <button onClick={() => setT(null)} className="mt-6 text-sm text-stone-500 hover:text-stone-800">‹ {company.company}</button>
          <h1 className="mt-1 text-lg font-semibold">Choose your account</h1>
          <ul className="mt-3 max-h-[55vh] space-y-1 overflow-y-auto">
            {company.people.map((p: Staff) => (
              <li key={p.id}>
                <button onClick={() => onSignIn({ tenant: company.tenant, user: p.id })}
                  className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left hover:bg-stone-50">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-100 text-xs font-semibold text-teal-900">{initials(p.name)}</span>
                  <span><span className="block text-sm font-medium">{p.name}</span><span className="block text-xs text-stone-500">{ROLE[p.role] ?? p.role}</span></span>
                </button>
              </li>
            ))}
          </ul>
        </>}
        <p className="mt-6 border-t border-stone-100 pt-4 text-xs text-stone-500">Demo with made-up companies: pick any account, no password. A real company signs in with its work Google or Microsoft accounts.</p>
      </div>
    </div>
  );
}
