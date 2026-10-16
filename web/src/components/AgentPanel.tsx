import { useState } from "react";
import { api, type Run } from "../api";
import { Outcome } from "./ui";

const SOURCE: Record<string, string> = {
  model: "Written by AI, checked against the graph",
  rows: "Built from the graph results (the AI's wording didn't pass the check)",
  replay: "Replay of an earlier run (the AI is unavailable right now)",
};

const ACTION_LABEL: Record<string, (a: any) => string> = {
  issue_refund: (a) => `Refund ${a.order_id}: $${a.amount}`,
  confirm_promise: (a) => `Confirm promise ${a.promise_id}`,
  file_incident: (a) => `File incident "${a.title}" (${a.ticket_ids?.length} tickets, root ${a.root_hub})`,
  notify_owner: (a) => `Notify the owner of ${a.decision_id}: “${a.message}”`,
};

export function AgentPanel({ agent, task, asUser, label, onDone }:
  { agent: "support" | "pattern"; task: string; asUser: string; label: string; onDone?: () => void }) {
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<Record<number, any>>({});

  async function go() {
    setBusy(true); setError(""); setRun(null); setDone({});
    try { setRun(await api.agent(agent, task, asUser)); } catch (e) { setError(String(e)); }
    setBusy(false);
  }

  async function confirm(i: number, name: string, args: any) {
    const r = await api.confirm(name, args, asUser);
    setDone((d) => ({ ...d, [i]: r }));
    onDone?.();
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={go} disabled={busy}
          className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-60">
          {busy ? "Working…" : label}
        </button>
        <span className="text-xs text-stone-500">
          {busy ? "The AI picks graph tools step by step; the free model can take 20–60 s." :
            "The AI chooses which graph tools to call. Every fact it states is checked against what the tools returned."}
        </span>
      </div>
      {error && <p className="mt-3 text-sm text-rose-700">{error}</p>}
      {run && (
        <div className="mt-4 space-y-4">
          <div className="rounded-lg bg-stone-50 p-4">
            <p className="whitespace-pre-line text-[15px] leading-relaxed text-stone-800">{run.answer}</p>
            <p className="mt-2 text-xs text-stone-500">{SOURCE[run.answer_source]}
              {run.check_failed && ` — ${run.check_failed}`} · {(run.ms / 1000).toFixed(1)} s
              {run.model && ` · ${run.model}`}</p>
          </div>
          {run.pending_actions.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-stone-800">Waiting for you</h3>
              <p className="text-xs text-stone-500">The AI prepared these. Nothing happens until you confirm; limits are checked again when you do.</p>
              <ul className="mt-2 space-y-2">
                {run.pending_actions.map((p, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-200 bg-amber-50/50 px-3 py-2">
                    <span className="flex-1 text-sm text-stone-800">{(ACTION_LABEL[p.name] ?? ((a) => `${p.name} ${JSON.stringify(a)}`))(p.args)}</span>
                    {done[i] ? (
                      <span className="flex items-center gap-2 text-sm"><Outcome outcome={done[i].outcome} />
                        <span className="text-stone-600">{done[i].reason || "done"}</span></span>
                    ) : (
                      <button onClick={() => confirm(i, p.name, p.args)}
                        className="rounded-md border border-stone-300 bg-white px-3 py-1 text-sm hover:bg-stone-50">Confirm</button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <details className="text-sm">
            <summary className="cursor-pointer text-stone-600">Run trace: {run.steps.length} tool calls
              {run.model_ms.length > 0 && `, AI thinking ${(run.model_ms.reduce((a, b) => a + b, 0) / 1000).toFixed(1)} s`}</summary>
            <div className="overflow-x-auto"><table className="mt-2 w-full min-w-[30rem] text-left text-xs">
              <thead className="text-stone-500"><tr><th className="py-1">Tool</th><th>Arguments</th><th>Result</th><th className="text-right">Graph time</th></tr></thead>
              <tbody>
                {run.steps.map((s, i) => (
                  <tr key={i} className="border-t border-stone-100 align-top">
                    <td className="py-1.5 font-mono">{s.tool}</td>
                    <td className="max-w-[28rem] truncate font-mono text-stone-600">{JSON.stringify(s.args)}</td>
                    <td><Outcome outcome={s.outcome} /></td>
                    <td className="text-right">{s.tool_ms != null ? `${s.tool_ms} ms` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          </details>
        </div>
      )}
    </div>
  );
}
