import { useEffect, useState, lazy, Suspense } from "react";
import { ISSUE, api, day, fmtSpan, money, orderNo, pct, place, plain, type Answer } from "../api";
import { AgentPanel } from "../components/AgentPanel";
import { Chip, Outcome, Section } from "../components/ui";
import { TicketLink, useName } from "../staff";
const PathGraph = lazy(() => import("../components/PathGraph").then((m) => ({ default: m.PathGraph })));

const METRIC: Record<string, (v: number) => string> = {
  courier_on_time_rate: pct,
  hub_load_ratio: (v) => `${v.toFixed(2)}× its daily capacity`,
};
const show = (metric: string, v: number | null) => (v == null ? "no data yet" : (METRIC[metric] ?? String)(v));
const OP: Record<string, string> = { ">=": "at least", "<=": "at most", ">": "over", "<": "under" };
const date = (at: number) => day(at).split(",")[0];

export function Impact({ asUser, embedded = false }: { asUser: string; embedded?: boolean }) {
  const name = useName();
  const [v, setV] = useState<any>(null);
  const load = () => api.impact(asUser).then(setV).catch(() => setV({ refused: true }));
  useEffect(() => { load(); }, []);
  if (!v) return <p className="p-6 text-stone-500">Working out what's behind this week's complaints…</p>;
  if (v.refused) return <p className="p-4 text-sm text-stone-600">Your role doesn't have access to operations information.</p>;

  const cluster = v.clusters.data?.clusters?.[0];
  const decisions = v.decisions?.data?.decisions ?? [];
  const hasBroken = (d: any) => d.assumptions.some((a: any) => a.status === "broken");
  const broken = decisions.find((d: any) => d.assumptions.some((a: any) => a.status === "broken" && a.linked))
    ?? decisions.find(hasBroken);
  const assumption = broken?.assumptions.find((a: any) => a.status === "broken" && a.linked)
    ?? broken?.assumptions.find((a: any) => a.status === "broken");
  const linked = decisions.find((d: any) => d.decision === assumption?.linked);
  const imp = v.impact?.data;
  const warning = v.prelaunch.data?.warnings?.[0];
  const waiting = imp?.customers_at_risk ?? [];
  const pastPromise = waiting.filter((c: any) => c.past_promise).length;
  const issue = cluster ? (ISSUE[cluster.issue] ?? cluster.issue).toLowerCase() : "";
  const root = cluster ? place(cluster.root_hub) : "";
  const graphPaths = [
    ...(cluster ? cluster.ticket_ids.slice(0, 8).map((t: string) => [t, cluster.root_hub]) : []),
    ...(broken ? [[cluster?.root_hub, broken.decision, assumption.assumption]] : []),
    ...(linked && assumption ? [[linked.decision, assumption.assumption], [linked.decision, cluster?.root_hub]] : []),
    ...(imp ? imp.dependent_decisions.map((d: any) => [d.decision, broken.decision]) : []),
    ...(warning ? [[warning.campaign, warning.decision, warning.hub]] : []),
  ];

  if (!cluster)
    return (
      <div className="h-full overflow-y-auto bg-stone-50 p-4 lg:p-6">
        <h1 className="text-xl font-semibold text-stone-900">Decision impact</h1>
        <p className="mt-2 rounded-xl border border-stone-200 bg-white p-5 text-stone-700">
          No unusual group of complaints this week, so there is nothing to trace back. ({v.clusters.reason})</p>
      </div>
    );

  return (
    <div className={embedded ? "" : "h-full overflow-y-auto bg-stone-50 p-4 lg:p-6"}>
      <div className="w-full max-w-[1200px] space-y-4">
        <div className={embedded ? "hidden" : ""}>
          <h1 className="text-xl font-semibold text-stone-900">Decision impact</h1>
          <p className="text-sm text-stone-600">Why complaints went up this week, which company decision is behind it, and what to do before it gets worse.</p>
        </div>

        {/* The answer first: one paragraph, the numbers that matter, and the actions. */}
        <div className={embedded ? "hidden" : "rounded-xl border border-rose-200 bg-white p-5"}>
          <h2 className="text-lg font-semibold text-stone-900">
            {cluster.tickets} {issue} complaints this week all went through {root}
            {broken && <>, where a decision's assumption no longer holds</>}
          </h2>
          {broken && (
            <p className="mt-2 text-[15px] leading-relaxed text-stone-800">
              “{broken.title}” ({name(broken.owner)}, {date(broken.made_at)}) assumed “{assumption.statement}”.
              {" "}This week it is <b>{show(assumption.metric, assumption.value)}</b>.
              {linked && <> At the same time, “{linked.title}” ({name(linked.owner)}) was running: {plain(assumption.basis.split("; ")[1] ?? assumption.basis)}.</>}
            </p>
          )}
          <div className="mt-4 grid gap-4 border-t border-stone-100 pt-4 sm:grid-cols-3">
            <Fact value={waiting.length} label={`customers still waiting on parcels at ${root}`} note={`${money(waiting.reduce((s: number, c: any) => s + c.order_value, 0))} of orders`} />
            {waiting.some((c: any) => c.promised_by != null)  // some companies' data has no promised delivery date
              ? <Fact value={pastPromise} label="of them are already past their delivery promise" note={`${waiting.filter((c: any) => c.open_tickets > 0).length} have written in so far`} />
              : <Fact value={waiting.filter((c: any) => c.late_hours > 0).length} label="of them are already running late" note={`${waiting.filter((c: any) => c.open_tickets > 0).length} have written in so far`} />}
            {warning
              ? <Fact value={`${warning.starts_in_days} days`} label={`until the ${warning.name}, which uses the same hub`} note="see Before the next launch" />
              : <Fact value={imp?.dependent_decisions.length ?? 0} label="other decisions depend on this one" />}
          </div>
          {broken && (
            <div className="mt-4 flex flex-wrap gap-2 border-t border-stone-100 pt-4">
              <Act asUser={asUser} label={`Tell ${name(broken.owner)} (decision owner)`} name="notify_owner"
                args={{ decision_id: broken.decision, message: `Your decision "${broken.title}" assumed: ${assumption.statement}. This week it is ${show(assumption.metric, assumption.value)}. ${cluster.tickets} ${issue} complaints went through ${root}; ${waiting.length} customers are still waiting there.` }} />
              {linked && <Act asUser={asUser} label={`Tell ${name(linked.owner)} too (overlapping decision)`} name="notify_owner"
                args={{ decision_id: linked.decision, message: `While "${linked.title}" ran, ${plain(assumption.basis.split("; ")[1] ?? "")}. ${root} is behind: ${assumption.statement} is now ${show(assumption.metric, assumption.value)}.` }} />}
              <Act asUser={asUser} label={`Open an incident for ${root}`} name="file_incident"
                args={{ title: `${issue} at ${root}`, ticket_ids: cluster.ticket_ids, root_hub: cluster.root_hub }} />
            </div>
          )}
        </div>

        <Section title="How we got here" hint="four steps, from complaints back to decisions">
          <ol className="grid gap-4 lg:grid-cols-2">
            <Step n={1} title="What customers are complaining about">
              <p><b>{cluster.tickets}</b> {issue} complaints in the last {v.clusters.data.days} days have the same places in common:</p>
              <ul className="mt-1">{cluster.shared.slice(0, 4).map((s: any) => (
                <li key={s.id}>{s.kind === "Campaign" ? `used the ${s.id.toUpperCase()} coupon` : `went through ${place(s.id)}`}: <b>{pct(s.share)}</b> of them</li>))}</ul>
            </Step>
            <Step n={2} title="Where it goes wrong">
              <p><b>{root}</b>. {cluster.late_parcels_at_root} of these parcels were scanned late here, more than at any other hub.</p>
            </Step>
            <Step n={3} title="The decision behind it" tone={broken ? "rose" : undefined}>
              {broken ? <>
                <p className="font-medium">{broken.title}</p>
                <p className="text-xs text-stone-500">{name(broken.owner)} · {date(broken.made_at)}</p>
                <p className="mt-2">It assumed: “{assumption.statement}”.</p>
                <p>This week: <b>{show(assumption.metric, assumption.value)}</b>, needed {OP[assumption.op] ?? assumption.op} {show(assumption.metric, assumption.threshold)}. <Chip tone="rose">no longer true</Chip></p>
              </> : <p>No recorded decision affects {root}.</p>}
            </Step>
            <Step n={4} title="What else was happening">
              {linked ? <>
                <p className="font-medium">{linked.title}</p>
                <p className="text-xs text-stone-500">{name(linked.owner)} · {date(linked.made_at)}</p>
                <p className="mt-2">{plain(assumption.basis).replace(/^./, (c: string) => c.toUpperCase())}.</p>
                <p className="mt-1 text-xs text-stone-500">This shows the two overlapped, not that one caused the other. The owners decide.</p>
              </> : <p>No other decision overlapped with this one in the data.</p>}
            </Step>
          </ol>
        </Section>

        {imp && (
          <Section title="Who is affected right now" hint={`parcels still on their way through ${imp.hubs.map(place).join(", ")}`}>
            <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
              <div>
                <h3 className="text-sm font-semibold">Customers waiting, biggest orders first</h3>
                <p className="text-xs text-stone-500">Names aren't shown here: this page is for causes and totals. Support staff see each person in their inbox.</p>
                <div className="overflow-x-auto"><table className="mt-2 w-full min-w-[30rem] text-sm">
                  <thead className="text-xs text-stone-500"><tr>
                    <th className="text-left font-normal">Customer</th><th className="text-left font-normal">Orders</th>
                    <th className="text-right font-normal">Value</th><th className="text-left font-normal pl-4">Delivery</th>
                    <th className="text-right font-normal">Written in</th></tr></thead>
                  <tbody>{waiting.slice(0, 10).map((c: any) => (
                    <tr key={c.customer} className="border-t border-stone-100">
                      <td className="py-1.5">{c.tier === "gold" ? <Chip tone="amber">gold</Chip> : "standard"}</td>
                      <td>{c.orders.map(orderNo).join(", ")}</td>
                      <td className="text-right">{money(c.order_value)}</td>
                      <td className="pl-4">{c.past_promise ? <Chip tone="rose">past promise</Chip> : c.late_hours > 0 ? <Chip tone="amber">{fmtSpan(c.late_hours)} late</Chip> : "on time so far"}</td>
                      <td className="text-right">{c.open_tickets ? `${c.open_tickets} open` : "—"}</td>
                    </tr>))}</tbody>
                </table></div>
                {waiting.length > 10 && <p className="mt-1 text-xs text-stone-500">and {waiting.length - 10} more.</p>}
              </div>
              <div className="space-y-5">
                <div>
                  <h3 className="text-sm font-semibold">Promises we made that are at risk</h3>
                  {imp.promises_at_risk.length === 0 && <p className="mt-1 text-sm text-stone-600">None: no open promise rides on these parcels.</p>}
                  <ul className="mt-1 space-y-1 text-sm">{imp.promises_at_risk.slice(0, 8).map((p: any) => (
                    <li key={p.promise}>{p.kind === "delivery" ? "Delivery" : "Refund"} of order {orderNo(p.order)} ·{" "}
                      <Chip tone={p.hours_left < 0 ? "rose" : "amber"}>{p.hours_left < 0 ? `${fmtSpan(-p.hours_left)} overdue` : `due in ${fmtSpan(p.hours_left)}`}</Chip>
                      {p.ticket && <> · <TicketLink id={p.ticket} /></>}</li>))}</ul>
                </div>
                <div>
                  <h3 className="text-sm font-semibold">Other decisions that rely on this one</h3>
                  {imp.dependent_decisions.length === 0 && <p className="mt-1 text-sm text-stone-600">None.</p>}
                  <ul className="mt-1 list-disc pl-5 text-sm">{imp.dependent_decisions.map((d: any) => <li key={d.decision}>{d.title}</li>)}</ul>
                  {imp.dependent_decisions.length > 0 && <p className="mt-1 text-xs text-stone-500">If the courier choice is changed, these need a second look too.</p>}
                </div>
              </div>
            </div>
          </Section>
        )}

        <Section title="Before the next launch" hint="planned campaigns that would use a hub that's already struggling">
          {warning ? <Prelaunch w={warning} asUser={asUser} owner={decisions.find((d: any) => d.decision === warning.decision)?.owner} name={name} />
            : <p className="text-sm text-stone-600">Nothing planned uses a struggling hub. ({v.prelaunch.reason})</p>}
        </Section>

        {!embedded && <Section title="Ask the AI to investigate" hint="it walks the same chain and drafts the actions for you">
          <AgentPanel agent="pattern" asUser={asUser} label="Investigate this week's complaints"
            task="Why are complaints up this week, and what should we do?" onDone={load}
            note="Every fact the AI states is checked against the company's data. Nothing is sent until you confirm." />
        </Section>}

        <Section title="How Sinew knows this" hint="methods, timings and the graph" open={false}>
          <div className="space-y-2 text-sm text-stone-700">
            <p><Outcome outcome={v.clusters.outcome} /> Every number on this page comes from graph queries and graph algorithms, not from AI.</p>
            <ul className="list-disc space-y-1 pl-5">
              <li><b>Complaint group:</b> community detection (label propagation) on tickets linked through the hubs, couriers, batches and campaigns they share. {v.clusters.ms} ms.</li>
              <li><b>Decision behind it:</b> decisions that affect {root}, with each assumption measured daily against scans. {v.decisions?.ms} ms.</li>
              {imp && <li><b>How central the decision is:</b> PageRank over decisions that build on each other: {imp.keystone_rank ? `#${imp.keystone_rank} of ${imp.decisions_ranked}` : "no decision builds on another yet"}. {v.impact.ms} ms.</li>}
              {warning?.reroute && <li><b>Other route:</b> shortest path that avoids {place(warning.hub)}. {v.prelaunch.ms} ms.</li>}
              <li><b>Busiest hubs on the network</b> (betweenness centrality): {v.choke_points.data.map((c: any) => `${place(c.hub)} (${c.score})`).join(", ")}.</li>
            </ul>
            <p className="text-xs text-stone-500">Ids: decision <span className="font-mono">{broken?.decision}</span>{linked && <>, linked <span className="font-mono">{linked.decision}</span></>}, assumption <span className="font-mono">{assumption?.assumption}</span>, hub <span className="font-mono">{cluster.root_hub}</span>.</p>
            <Suspense fallback={<p className="text-sm text-stone-500">Loading graph…</p>}>
              <PathGraph paths={graphPaths} height={360} highlight={[cluster.root_hub, broken?.decision, linked?.decision].filter(Boolean)} />
            </Suspense>
          </div>
        </Section>
      </div>
    </div>
  );
}

function Fact({ value, label, note }: { value: React.ReactNode; label: string; note?: string }) {
  return (
    <div>
      <div className="text-2xl font-semibold text-stone-900">{value}</div>
      <div className="text-sm text-stone-700">{label}</div>
      {note && <div className="text-xs text-stone-500">{note}</div>}
    </div>
  );
}

/** One click runs the action as the signed-in person, through the same permission checks as the AI. */
function Act({ label, name, args, asUser }: { label: string; name: string; args: any; asUser: string }) {
  const [r, setR] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const run = () => { setBusy(true); api.confirm(name, args, asUser).then(setR).finally(() => setBusy(false)); };
  if (r) return (
    <span className={`rounded-md border px-3 py-1.5 text-sm ${r.outcome === "answered_path" ? "border-teal-200 bg-teal-50 text-teal-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
      {r.outcome === "answered_path" ? (name === "file_incident" ? "Incident opened" : "Sent") : `Not done: ${r.reason}`}
    </span>
  );
  return (
    <button onClick={run} disabled={busy}
      className="rounded-md border border-teal-700 px-3 py-1.5 text-sm font-medium text-teal-800 hover:bg-teal-50 disabled:opacity-50">
      {busy ? "…" : label}
    </button>
  );
}

function Step({ n, title, tone, children }: { n: number; title: string; tone?: "rose"; children: React.ReactNode }) {
  return (
    <li className={`rounded-lg border p-4 ${tone === "rose" ? "border-rose-200 bg-rose-50/40" : "border-stone-200"}`}>
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-teal-700 text-xs font-semibold text-white">{n}</span>
        <h3 className="text-[15px] font-semibold text-stone-800">{title}</h3>
      </div>
      <div className="text-sm text-stone-800">{children}</div>
    </li>
  );
}

/** The warning, with assumptions that measure the same thing said once. */
export function Prelaunch({ w, asUser, owner, name }: { w: any; asUser: string; owner?: string; name: (id?: string | null) => string }) {
  const groups: Record<string, { value: number; statements: string[] }> = {};
  for (const a of w.broken_assumptions) (groups[a.metric] ??= { value: a.value, statements: [] }).statements.push(a.statement);
  const hub = place(w.hub);
  const line = (metric: string, value: number) => metric === "hub_load_ratio"
    ? `${hub} is already carrying ${show(metric, value)}.` : `On-time delivery through ${hub} is ${show(metric, value)}.`;
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-4 text-sm text-amber-950">
      <p className="text-[15px]"><b>{w.name}</b> starts in <b>{w.starts_in_days} days</b> and its parcels go through {hub}, which is already struggling:</p>
      <ul className="mt-2 space-y-2">
        {Object.entries(groups).map(([metric, g]) => (
          <li key={metric}>
            <p className="font-medium">{line(metric, g.value)}</p>
            <p className="text-xs">{g.statements.length === 1 ? "A plan assumed" : `${g.statements.length} plans assumed`} otherwise: {g.statements.map((s) => `“${s}”`).join(", ")}</p>
          </li>
        ))}
      </ul>
      {w.reroute && <p className="mt-3">Option: send these parcels through <b>{place(w.reroute.hub)}</b> instead ({w.reroute.path.map(place).join(" → ")}, about {w.reroute.hours} h, room for {w.reroute.capacity} parcels a day).</p>}
      {owner && (
        <div className="mt-3">
          <Act asUser={asUser} label={`Warn ${name(owner)} before the launch`} name="notify_owner"
            args={{ decision_id: w.decision, message: `${w.name} starts in ${w.starts_in_days} days through ${hub}, which is already struggling: ${Object.entries(groups).map(([m, g]) => line(m, g.value)).join(" ")}${w.reroute ? ` Option: route through ${place(w.reroute.hub)}.` : ""}` }} />
        </div>
      )}
    </div>
  );
}
