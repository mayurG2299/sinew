import { useEffect, useState } from "react";
import { api, ago, type Notice, type Staff } from "../api";

type Item = { id: string; label: string; since: number | null; note: string | null; ask: string;
  agent: Notice["agent"]; task: string | null; view: Notice["view"] | null };
type HomeData = { now: number; open_label: string; counts: { open: number; attention: number; at_risk: number };
  attention: Item[]; at_risk: Item[]; insights: { id: string; text: string; ask: string; agent: Notice["agent"]; task: string | null; view: Notice["view"] }[] };

const greeting = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; };
const SHOWN = 4;

/** Same frame for everyone; the lines in it come from the person's job and what they may see. */
export function Home({ me, open, onAsk }: { me: Staff; open: (n: Notice) => void; onAsk: () => void }) {
  const [d, setD] = useState<HomeData | null>(null);
  const [list, setList] = useState<"attention" | "at_risk">("attention");
  const [all, setAll] = useState(false);
  const [hidden, setHidden] = useState<string[]>([]);
  useEffect(() => { api.home(me.id).then(setD); }, [me.id]);

  const go = (i: { id: string; ask: string; agent: Notice["agent"]; task: string | null; view: Notice["view"] | null }) =>
    open({ id: i.id, tone: "warn", title: i.ask, detail: "", ask: i.ask, agent: i.agent, task: i.task, view: i.view ?? { kind: "" } });

  if (!d) return <p className="p-8 text-stone-500">Getting your day ready…</p>;
  const items = d[list];
  const insights = d.insights.filter((i) => !hidden.includes(i.id));
  const Count = ({ n, label, k }: { n: number; label: string; k?: "attention" | "at_risk" }) => (
    <button disabled={!k} onClick={() => k && (setList(k), setAll(false))}
      className={`rounded-xl px-4 py-3 text-left ${k && list === k ? "bg-stone-100" : k ? "hover:bg-stone-50" : "cursor-default"}`}>
      <span className="block text-3xl font-semibold text-stone-900">{n}</span>
      <span className="block text-sm text-stone-600">{label}</span>
    </button>
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-8">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-2xl font-semibold text-stone-900">{greeting()}, {me.name.split(" ")[0]}</h1>
          <button onClick={onAsk} className="rounded-xl border border-stone-300 px-3 py-1.5 text-sm text-stone-700 hover:bg-stone-50">
            Ask Sinew <span className="ml-1 text-xs text-stone-400">⌘K</span></button>
        </div>

        <div className="mt-6 grid grid-cols-3 gap-2">
          <Count n={d.counts.open} label={d.open_label} />
          <Count n={d.counts.attention} label="need your attention" k="attention" />
          <Count n={d.counts.at_risk} label="at risk" k="at_risk" />
        </div>

        <h2 className="mt-8 text-sm font-medium text-stone-500">{list === "attention" ? "Needs your attention" : "At risk"}</h2>
        {items.length === 0 ? <p className="mt-2 text-sm text-stone-600">Nothing here right now.</p> : (
          <ul className="mt-2 divide-y divide-stone-100 rounded-xl border border-stone-200">
            {(all ? items : items.slice(0, SHOWN)).map((i) => (
              <li key={i.id}>
                <button onClick={() => go(i)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-stone-50">
                  <span className="min-w-0 flex-1 truncate text-[15px] text-stone-900">{i.label}</span>
                  <span className="shrink-0 text-sm text-stone-500">{i.since ? ago(i.since, d.now).replace(" ago", "") : i.note}</span>
                  <span className="text-stone-400">›</span>
                </button>
              </li>
            ))}
            {!all && items.length > SHOWN && (
              <li><button onClick={() => setAll(true)} className="w-full px-4 py-2.5 text-left text-sm text-teal-800 hover:bg-stone-50">+ {items.length - SHOWN} more</button></li>
            )}
          </ul>
        )}

        {insights.length > 0 && <>
          <h2 className="mt-8 text-sm font-medium text-stone-500">Insights</h2>
          <ul className="mt-2 space-y-2">
            {insights.map((i) => (
              <li key={i.id} className="flex items-start gap-3 rounded-xl border border-stone-200 px-4 py-3">
                <p className="flex-1 text-[15px] text-stone-800">{i.text}</p>
                <button onClick={() => go(i)} className="shrink-0 text-sm font-medium text-teal-800 hover:underline">Ask Sinew ›</button>
                <button onClick={() => setHidden((h) => [...h, i.id])} aria-label="Dismiss" className="shrink-0 text-stone-400 hover:text-stone-700">✕</button>
              </li>
            ))}
          </ul>
        </>}
      </div>
    </div>
  );
}
