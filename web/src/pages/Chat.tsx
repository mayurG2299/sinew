import { useEffect, useRef, useState } from "react";
import { AssistantRuntimeProvider, useExternalStoreRuntime, type AppendMessage, type ThreadMessageLike } from "@assistant-ui/react";
import { Thread as ThreadView } from "@/components/assistant-ui/thread";
import { api, money, orderNo, place, type Notice, type Run, type Staff } from "../api";
import { CustomerView } from "./Inbox";
import { Impact, Prelaunch } from "./Impact";
import { Promises } from "./Promises";
import { useName } from "../staff";

type Msg = { id: string; role: "user" | "assistant"; text?: string; run?: Run; view?: Notice["view"] | null;
  pending?: boolean; error?: boolean };
export type Thread = { id: string; title: string; messages: Msg[] };

/** A typed question about a named order or ticket goes to the support assistant (for support staff);
 * every other question goes to the general assistant, which picks the skills that fit. */
const SUPPORT = new Set(["agent", "team_lead", "support_head", "contractor"]);
const route = (text: string, role: string) => (SUPPORT.has(role) && /#\d+|\b[ot]-\d+/i.test(text) ? "support" : "ask");

export function Chat({ me, threads, setThreads, current, setCurrent, start, onStarted }: {
  me: Staff; threads: Thread[]; setThreads: (f: (t: Thread[]) => Thread[]) => void;
  current: string | null; setCurrent: (id: string | null) => void; start?: Notice | null; onStarted?: () => void;
}) {
  const thread = threads.find((t) => t.id === current);
  const idRef = useRef<string | null>(current);
  const started = useRef(false);

  function put(id: string, msg: Msg, title: string) {
    setThreads((ts) => ts.some((t) => t.id === id)
      ? ts.map((t) => (t.id === id ? { ...t, messages: [...t.messages.filter((m) => m.id !== msg.id), msg] } : t))
      : [{ id, title, messages: [msg] }, ...ts]);
  }

  function ask(text: string, notice?: Notice) {
    const id = idRef.current ?? `c${Date.now()}`;
    idRef.current = id;
    const title = notice?.ask ?? text;
    put(id, { id: `u${Date.now()}`, role: "user", text }, title);
    setCurrent(id);
    const replyId = `a${Date.now()}`;
    const agent = notice ? notice.agent : route(text, me.role);
    const task = notice ? notice.task : text;
    if (!agent || !task) {  // a notice that is answered by its view alone
      put(id, { id: replyId, role: "assistant", view: notice?.view }, title);
      return;
    }
    put(id, { id: replyId, role: "assistant", pending: true, view: notice?.view }, title);
    api.agent(agent, task, me.id)
      .then((run) => put(id, { id: replyId, role: "assistant", run, view: notice?.view }, title))
      .catch(() => put(id, { id: replyId, role: "assistant", error: true }, title));
  }

  useEffect(() => {  // opened from Home: ask that question straight away
    if (start && !started.current) { started.current = true; ask(start.ask, start); onStarted?.(); }
  }, [start]);

  const messages = thread?.messages ?? [];
  const runtime = useExternalStoreRuntime<Msg>({
    messages,
    isRunning: messages.some((m) => m.pending),
    convertMessage: (m): ThreadMessageLike => m.role === "user"
      ? { id: m.id, role: "user", content: [{ type: "text", text: m.text ?? "" }] }
      : m.pending ? { id: m.id, role: "assistant", content: [], status: { type: "running" } }
      : { id: m.id, role: "assistant", content: [
          ...(m.run ? [{ type: "text" as const, text: m.run.answer }] : []),
          ...(m.error ? [{ type: "text" as const, text: "Sinew couldn't answer that just now. Please try again." }] : []),
          { type: "data-sinew" as const, data: { run: m.run ?? null, view: m.view ?? null } },
        ] },
    onNew: async (message: AppendMessage) => {
      const part = message.content.find((p) => p.type === "text");
      if (part && part.type === "text" && part.text.trim()) ask(part.text.trim());
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadView
        placeholder={SUPPORT.has(me.role) ? "Ask about a customer, an order, a policy…" : "Ask why something is happening, or about a policy…"}
        welcome={<>
          <p className="text-2xl font-medium tracking-tight">What do you want to know?</p>
          <p className="text-muted-foreground mt-1 text-sm">Sinew answers from your company's data and documents, only what your role may see.</p>
        </>}
        renderData={(name, data) => (name === "sinew" ? <Extras run={data.run} view={data.view} me={me} /> : null)}
      />
    </AssistantRuntimeProvider>
  );
}

const STEP: Record<string, string> = {
  customer_trace: "Read the customer's history", open_loops: "Checked what is still open", related_issues: "Looked for others affected",
  search_tickets: "Searched tickets", search_docs: "Searched company documents", find_approver: "Found who can approve",
  recall: "Checked earlier findings", cluster_incidents: "Grouped this week's complaints", trace_decisions: "Found the decisions behind it",
  decision_impact: "Measured what is at risk", prelaunch_check: "Checked upcoming launches", reroute: "Looked for another route",
  choke_points: "Found the busiest hubs", evaluate_assumptions: "Re-measured the assumptions", write_finding: "Saved a note for next time",
  order_detail: "Walked from the order", decision_detail: "Walked from the decision", hub_status: "Walked from the hub",
  product_status: "Walked from the product or batch", company_pulse: "Summarised the areas you can see",
  issue_refund: "Prepared a refund", record_promise: "Prepared a follow-up", file_incident: "Prepared an incident", notify_owner: "Prepared a message",
};
const ACTION: Record<string, (a: any) => string> = {
  issue_refund: (a) => `Refund ${money(Number(a.amount))} for order ${orderNo(a.order_id)}`,
  confirm_promise: () => "Confirm",
  record_promise: (a) => `Commit to the ${a.kind ?? "follow-up"} for order ${orderNo(a.order_id)}`,
  file_incident: (a) => `Open an incident for ${place(a.root_hub)} (${a.ticket_ids?.length ?? 0} complaints)`,
  notify_owner: () => "Tell the decision owner",
};
const INTENT: Record<string, string> = { why: "why it is happening", what_to_do: "what to do", pulse: "how the company is doing",
  cost: "a cost question", policy: "a policy or decision", count: "a number", status: "the latest on it", unknown: "a question" };
const KIND: Record<string, string> = { policy: "Policy", contract: "Contract", meeting_notes: "Meeting notes", plan: "Plan", guide: "Guide" };

/** Under each answer: the actions (wait for a click), the documents it came from, and the rest behind a click. */
function Extras({ run, view, me }: { run: Run | null; view: Notice["view"] | null; me: Staff }) {
  const [open, setOpen] = useState<"" | "picture" | "how">("");
  const [source, setSource] = useState<number | null>(null);
  const [done, setDone] = useState<Record<number, any>>({});
  if (!run) return view ? <div className="mt-2 rounded-xl border p-2"><View v={view} me={me} /></div> : null;
  const sources = run.sources ?? [];
  return (
    <div className="mt-3 space-y-3 text-sm">
      {run.pending_actions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {run.pending_actions.map((p, i) => done[i]
            ? <span key={i} className={`rounded-lg px-3 py-1.5 ${done[i].outcome === "answered_path" ? "bg-teal-50 text-teal-900" : "bg-amber-50 text-amber-900"}`}>
                {done[i].outcome === "answered_path" ? "Done" : done[i].outcome === "needs_approval" ? "Sent for approval" : `Not done: ${done[i].reason}`}</span>
            : <button key={i} onClick={() => api.confirm(p.name, p.args, me.id).then((r) => setDone((d) => ({ ...d, [i]: r })))}
                className="rounded-lg border border-teal-700 px-3 py-1.5 font-medium text-teal-800 hover:bg-teal-50">{(ACTION[p.name] ?? (() => p.name))(p.args)}</button>)}
        </div>
      )}
      {sources.length > 0 && (
        <div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-muted-foreground">Sources</span>
            {sources.map((s: any, i: number) => (
              <button key={s.passage} onClick={() => setSource(source === i ? null : i)}
                className={`rounded-full border px-2.5 py-0.5 text-xs ${source === i ? "border-teal-700 bg-teal-50 text-teal-900" : "hover:bg-stone-50"}`}>
                {s.title} · {s.heading}</button>))}
          </div>
          {source !== null && sources[source] && (
            <blockquote className="mt-2 border-l-2 border-teal-600 pl-3 text-stone-700">
              <p className="text-xs text-stone-500">{KIND[sources[source].kind] ?? "Document"} · {sources[source].title} · {sources[source].heading}</p>
              <p className="mt-1">{sources[source].text}</p>
            </blockquote>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-4">
        {view?.kind && <button onClick={() => setOpen(open === "picture" ? "" : "picture")} className="text-teal-800 hover:underline">{open === "picture" ? "Hide" : "See"} the full picture</button>}
        <button onClick={() => setOpen(open === "how" ? "" : "how")} className="text-muted-foreground hover:text-foreground">How Sinew knows</button>
      </div>
      {open === "picture" && <div className="rounded-xl border p-2"><View v={view} me={me} /></div>}
      {open === "how" && (
        <div className="rounded-xl bg-stone-50 p-4 text-stone-700">
          {run.plan?.parts?.length ? (
            <div className="mb-3">
              <p className="font-medium text-stone-800">How Sinew read your question ({run.plan.window})</p>
              <ul className="mt-1 space-y-0.5">
                {run.plan.parts.map((p, i) => (
                  <li key={i}>“{p.ask}” — {INTENT[p.intents[0]] ?? p.intents[0]}{p.named.length > 0 && <>, about {p.named.join(", ")}</>}
                    <span className="text-stone-500"> · {p.status === "answered" ? "found" : p.status === "no_access" ? "outside your access" : "no information"}</span></li>
                ))}
              </ul>
              <p className="mt-2 font-medium text-stone-800">What it looked up</p>
            </div>
          ) : null}
          <ol className="list-decimal space-y-0.5 pl-5">
            {run.steps.map((s, i) => <li key={i}>{STEP[s.tool] ?? s.tool}{s.tool_ms != null && <span className="text-stone-400"> · {s.tool_ms} ms</span>}</li>)}
          </ol>
          <p className="mt-2 text-xs text-stone-500">
            {run.answer_source === "model" ? "Written by AI from these results, then every name and number was checked against them."
              : run.answer_source === "replay" ? "The AI is unavailable right now, so this is its last checked answer to the same question."
              : "The AI's wording didn't pass the check, so this answer is built straight from the results."}
            {run.repaired && ` The first draft ${run.repaired}, so Sinew asked for a corrected answer and checked it again.`}
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
  useEffect(() => { api.impact(me.id).then(setV).catch(() => setV({ refused: true })); }, []);
  if (!v) return <p className="text-sm text-stone-500">Checking upcoming launches…</p>;
  if (v.refused) return <p className="text-sm text-stone-600">Your role doesn't have access to operations information.</p>;
  const w = v.prelaunch.data?.warnings?.[0];
  if (!w) return <p className="text-sm text-stone-600">No planned launch uses a struggling hub.</p>;
  const owner = v.decisions?.data?.decisions?.find((d: any) => d.decision === w.decision)?.owner;
  return <Prelaunch w={w} asUser={me.id} owner={owner} name={name} />;
}
