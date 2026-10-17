import { useEffect, useRef, useState } from "react";
import { api, money, orderNo, place, type Notice, type Run, type Staff } from "../api";
import { CustomerView } from "./Inbox";
import { Impact, Prelaunch } from "./Impact";
import { Promises } from "./Promises";
import { useName } from "../staff";

type Msg =
  | { from: "me"; text: string }
  | { from: "sinew"; agent: string | null; task: string | null; view: Notice["view"] | null; run?: Run; error?: string };
export type Thread = { id: string; title: string; messages: Msg[] };

const SUPPORT = new Set(["agent", "team_lead", "support_head", "contractor"]);

/** Which assistant takes a typed question: one about a customer, order or ticket goes to support (if the person
 * works in support); anything else is an investigation across the company. */
function route(text: string, role: string): "support" | "pattern" {
  return SUPPORT.has(role) && /#\d+|\b[ot]-\d+|ticket|order|refund|customer|parcel|delivery/i.test(text) ? "support" : "pattern";
}

export function Chat({ me, threads, setThreads, current, setCurrent, start, onStarted }: {
  me: Staff; threads: Thread[]; setThreads: (f: (t: Thread[]) => Thread[]) => void;
  current: string | null; setCurrent: (id: string | null) => void; start?: Notice | null; onStarted?: () => void;
}) {
  const thread = threads.find((t) => t.id === current);
  const started = useRef(false);
  useEffect(() => {  // opened from Home: ask that question straight away
    if (start && !started.current) { started.current = true; ask(start.ask, start); onStarted?.(); }
  }, [start]);

  function update(id: string, i: number, patch: Partial<Msg>) {
    setThreads((ts) => ts.map((t) => t.id !== id ? t : { ...t, messages: t.messages.map((m, j) => (j === i ? { ...m, ...patch } as Msg : m)) }));
  }

  function ask(text: string, notice?: Notice) {
    const agent = notice ? notice.agent : route(text, me.role);
    const task = notice ? notice.task : text;
    const reply: Msg = { from: "sinew", agent, task, view: notice?.view ?? null };
    let id = current;
    let index = 1;
    if (!thread) {
      id = `c${Date.now()}`;
      setThreads((ts) => [{ id: id!, title: notice?.title ?? text, messages: [{ from: "me", text }, reply] }, ...ts]);
      setCurrent(id);
    } else {
      index = thread.messages.length + 1;
      setThreads((ts) => ts.map((t) => t.id !== id ? t : { ...t, messages: [...t.messages, { from: "me", text }, reply] }));
    }
    if (agent && task)
      api.agent(agent, task, me.id).then((run) => update(id!, index, { run }))
        .catch((e) => update(id!, index, { error: String(e) }));
  }

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 py-8">
          {!thread ? (
            <div className="pt-[20vh] text-center">
              <h1 className="text-2xl font-semibold text-stone-900">What do you want to know?</h1>
              <p className="mt-2 text-sm text-stone-500">Sinew answers from your company's data, and only what your role may see.</p>
            </div>
          ) : (
            <div className="space-y-6">
              {thread.messages.map((m, i) => m.from === "me"
                ? <div key={i} className="flex justify-end"><p className="max-w-[80%] rounded-2xl bg-stone-100 px-4 py-2.5 text-[15px] text-stone-900">{m.text}</p></div>
                : <Reply key={i} m={m} me={me} />)}
            </div>
          )}
        </div>
      </div>
      <Composer onSend={(t) => ask(t)} placeholder={SUPPORT.has(me.role) ? "Ask about a customer, an order or a problem…" : "Ask why something is happening, or what's at risk…"} />
    </div>
  );
}

function Composer({ onSend, placeholder }: { onSend: (text: string) => void; placeholder: string }) {
  const [text, setText] = useState("");
  return (
    <form className="mx-auto w-full max-w-3xl px-4 pb-5" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { onSend(text.trim()); setText(""); } }}>
      <div className="flex items-center gap-2 rounded-2xl border border-stone-300 bg-white px-4 py-2 shadow-sm focus-within:border-teal-600">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} aria-label="Ask Sinew"
          className="min-w-0 flex-1 bg-transparent py-1.5 text-[15px] outline-none" />
        <button disabled={!text.trim()} className="rounded-xl bg-teal-700 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40">Ask</button>
      </div>
    </form>
  );
}

const STEP: Record<string, string> = {
  customer_trace: "Read the customer's history", open_loops: "Checked what is still open", related_issues: "Looked for others affected",
  search_tickets: "Searched tickets", find_approver: "Found who can approve", recall: "Checked earlier findings",
  cluster_incidents: "Grouped this week's complaints", trace_decisions: "Found the decisions behind it",
  decision_impact: "Measured what is at risk", prelaunch_check: "Checked upcoming launches", reroute: "Looked for another route",
  choke_points: "Found the busiest hubs", evaluate_assumptions: "Re-measured the assumptions", write_finding: "Saved a note for next time",
  issue_refund: "Prepared a refund", record_promise: "Prepared a promise", file_incident: "Prepared an incident", notify_owner: "Prepared a message",
};
const ACTION: Record<string, (a: any) => string> = {
  issue_refund: (a) => `Refund ${money(Number(a.amount))} for order ${orderNo(a.order_id)}`,
  confirm_promise: () => "Confirm the promise",
  record_promise: (a) => `Promise a ${a.kind ?? ""} for order ${orderNo(a.order_id)}`,
  file_incident: (a) => `Open an incident for ${place(a.root_hub)} (${a.ticket_ids?.length ?? 0} complaints)`,
  notify_owner: () => "Tell the decision owner",
};

function Reply({ m, me }: { m: Extract<Msg, { from: "sinew" }>; me: Staff }) {
  const [open, setOpen] = useState<"" | "picture" | "how">("");
  const [done, setDone] = useState<Record<number, any>>({});
  const [secs, setSecs] = useState(0);
  const timer = useRef<number | undefined>(undefined);
  const waiting = !!m.agent && !m.run && !m.error;
  useEffect(() => {
    if (!waiting) return;
    timer.current = window.setInterval(() => setSecs((s) => s + 1), 1000);
    return () => window.clearInterval(timer.current);
  }, [waiting]);

  // A notice with no question for the AI: the answer is the view itself.
  if (!m.agent) return <div className="rounded-xl border border-stone-200 p-4"><View v={m.view} me={me} /></div>;
  if (m.error) return <p className="text-sm text-rose-700">Sinew couldn't answer that just now. Try again.</p>;
  if (!m.run) return <p className="text-sm text-stone-500">Looking through the company's data… {secs > 3 && `${secs} s`}</p>;

  const run = m.run;
  return (
    <div>
      <p className="whitespace-pre-line text-[15px] leading-relaxed text-stone-900">{run.answer}</p>
      {run.pending_actions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {run.pending_actions.map((p, i) => done[i]
            ? <span key={i} className={`rounded-lg px-3 py-1.5 text-sm ${done[i].outcome === "answered_path" ? "bg-teal-50 text-teal-900" : "bg-amber-50 text-amber-900"}`}>
                {done[i].outcome === "answered_path" ? "Done" : done[i].outcome === "needs_approval" ? `Sent for approval${done[i].data?.approver ? "" : ""}` : `Not done: ${done[i].reason}`}</span>
            : <button key={i} onClick={() => api.confirm(p.name, p.args, me.id).then((r) => setDone((d) => ({ ...d, [i]: r })))}
                className="rounded-lg border border-teal-700 px-3 py-1.5 text-sm font-medium text-teal-800 hover:bg-teal-50">{(ACTION[p.name] ?? (() => p.name))(p.args)}</button>)}
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-4 text-sm">
        {m.view && <button onClick={() => setOpen(open === "picture" ? "" : "picture")} className="text-teal-800 hover:underline">{open === "picture" ? "Hide" : "See"} the full picture</button>}
        <button onClick={() => setOpen(open === "how" ? "" : "how")} className="text-stone-500 hover:text-stone-800">How Sinew knows</button>
      </div>
      {open === "picture" && <div className="mt-3 rounded-xl border border-stone-200 p-1"><View v={m.view} me={me} /></div>}
      {open === "how" && (
        <div className="mt-3 rounded-xl bg-stone-50 p-4 text-sm text-stone-700">
          <ol className="list-decimal space-y-0.5 pl-5">
            {run.steps.map((s, i) => <li key={i}>{STEP[s.tool] ?? s.tool}{s.tool_ms != null && <span className="text-stone-400"> · {s.tool_ms} ms</span>}</li>)}
          </ol>
          <p className="mt-2 text-xs text-stone-500">
            {run.answer_source === "model" ? "Written by AI from these results, then every name and number was checked against them."
              : run.answer_source === "replay" ? "The AI is unavailable right now, so this is its last checked answer to the same question."
              : "The AI's wording didn't pass the check, so this answer is built straight from the results."}
            {" "}{(run.ms / 1000).toFixed(1)} s.
          </p>
        </div>
      )}
    </div>
  );
}

function View({ v, me }: { v: Notice["view"] | null; me: Staff }) {
  if (!v) return null;
  if (v.kind === "customer" && v.ticket) return <CustomerView ticket={v.ticket} asUser={me.id} embedded />;
  if (v.kind === "impact") return <Impact asUser={me.id} embedded />;
  if (v.kind === "promises") return <Promises asUser={me.id} embedded />;
  if (v.kind === "prelaunch") return <PrelaunchView me={me} />;
  return null;
}

function PrelaunchView({ me }: { me: Staff }) {
  const name = useName();
  const [v, setV] = useState<any>(null);
  useEffect(() => { api.impact().then(setV); }, []);
  if (!v) return <p className="text-sm text-stone-500">Checking upcoming launches…</p>;
  const w = v.prelaunch.data?.warnings?.[0];
  if (!w) return <p className="text-sm text-stone-600">No planned launch uses a struggling hub.</p>;
  const owner = v.decisions?.data?.decisions?.find((d: any) => d.decision === w.decision)?.owner;
  return <Prelaunch w={w} asUser={me.id} owner={owner} name={name} />;
}
