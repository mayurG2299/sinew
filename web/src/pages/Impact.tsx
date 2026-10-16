import { useEffect, useState } from "react";
import { api, day, fmtSpan, money, pct } from "../api";
import { AgentPanel } from "../components/AgentPanel";
import { lazy, Suspense } from "react";
const PathGraph = lazy(() => import("../components/PathGraph").then((m) => ({ default: m.PathGraph })));
import { Chip, Outcome, Section, Stat } from "../components/ui";
import { TicketLink, useName } from "../staff";

const METRIC: Record<string, (v: number) => string> = {
  courier_on_time_rate: pct,
  hub_load_ratio: (v) => `${v.toFixed(2)}× capacity`,
};
const show = (metric: string, v: number | null) => (v == null ? "no data yet" : (METRIC[metric] ?? String)(v));

export function Impact({ asUser }: { asUser: string }) {
  const name = useName();
  const [v, setV] = useState<any>(null);
  const load = () => api.impact().then(setV);
  useEffect(() => { load(); }, []);
  if (!v) return <p className="p-6 text-stone-500">Walking the graph…</p>;

  const cluster = v.clusters.data?.clusters?.[0];
  const decisions = v.decisions?.data?.decisions ?? [];
  const broken = decisions.find((d: any) => d.assumptions.some((a: any) => a.status === "broken" && a.linked));
  const assumption = broken?.assumptions.find((a: any) => a.status === "broken" && a.linked);
  const linked = decisions.find((d: any) => d.decision === assumption?.linked);
  const imp = v.impact?.data;
  const warning = v.prelaunch.data?.warnings?.[0];
  const graphPaths = [
    ...(cluster ? cluster.ticket_ids.slice(0, 8).map((t: string) => [t, cluster.root_hub]) : []),
    ...(broken ? [[cluster?.root_hub, broken.decision, assumption.assumption]] : []),
    ...(linked ? [[linked.decision, assumption.assumption], [linked.decision, cluster?.root_hub]] : []),
    ...(imp ? imp.dependent_decisions.map((d: any) => [d.decision, broken.decision]) : []),
    ...(warning ? [[warning.campaign, warning.decision, warning.hub]] : []),
  ];

  return (
    <div className="h-full overflow-y-auto bg-stone-50 p-4 lg:p-6">
      <div className="w-full max-w-[1400px] space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-stone-900">Decision impact</h1>
          <p className="text-sm text-stone-600">From this week's complaints back to the company decisions behind them, and forward to what is at risk now. Computed by graph queries and algorithms; no AI involved in these numbers.</p>
        </div>

        <ol className="grid gap-4 lg:grid-cols-2">
          <Step n={1} title="Complaints cluster" outcome={v.clusters.outcome}>
            {cluster ? <>
              <p><b>{cluster.tickets}</b> {cluster.issue.replace("_", " ")} tickets in the last {v.clusters.data.days} days group together (community detection on tickets that share places).</p>
              <p className="mt-2 text-xs text-stone-500">What they share:</p>
              <ul className="text-sm">{cluster.shared.slice(0, 4).map((s: any) => (
                <li key={s.id}><span className="font-mono">{s.id}</span> <span className="text-stone-500">({s.kind.toLowerCase()})</span>: {pct(s.share)} of the tickets</li>))}</ul>
            </> : <p>{v.clusters.reason}</p>}
          </Step>

          <Step n={2} title="Root hub" outcome={v.clusters.outcome}>
            {cluster && <p><span className="font-mono text-lg font-semibold">{cluster.root_hub}</span>: {cluster.late_parcels_at_root} of the cluster's parcels were scanned late here, more than at any other hub.</p>}
          </Step>

          <Step n={3} title="The decision and its assumption" outcome={v.decisions?.outcome ?? "not_in_graph"}>
            {broken ? <>
              <p className="font-medium">{broken.title}</p>
              <p className="text-xs text-stone-500"><span className="font-mono">{broken.decision}</span> · owner {name(broken.owner)} · made {day(broken.made_at).split(",")[0]}</p>
              <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50/50 p-3">
                <p className="text-sm">Assumed: “{assumption.statement}”</p>
                <p className="mt-1 text-sm">Measured: <b>{show(assumption.metric, assumption.value)}</b> against {assumption.op} {show(assumption.metric, assumption.threshold)}, over the last 7 days <Chip tone="rose">broken</Chip></p>
              </div>
            </> : <p>{v.decisions?.reason ?? "No recorded decision affects this hub."}</p>}
          </Step>

          <Step n={4} title="Linked decision" outcome={linked ? "answered_path" : "not_in_graph"}>
            {linked ? <>
              <p className="font-medium">{linked.title}</p>
              <p className="text-xs text-stone-500"><span className="font-mono">{linked.decision}</span> · owner {name(linked.owner)} · made {day(linked.made_at).split(",")[0]}</p>
              <p className="mt-2 text-sm">Linked through the data: {assumption.basis}.</p>
              <p className="mt-1 text-xs text-stone-500">A link is an overlap in the data, not proof of cause. The owners decide.</p>
            </> : <p>No other decision overlaps this break.</p>}
          </Step>
        </ol>

        {imp && (
          <Section title="What is at risk now" hint={`forward from ${imp.decision}`}>
            <div className="flex flex-wrap gap-8">
              <Stat value={imp.parcels_in_transit} label="parcels in transit" note={`through ${imp.hubs.join(", ")}`} />
              <Stat value={imp.customers_at_risk.length} label="customers waiting" note="ranked by order value below" />
              <Stat value={imp.promises_at_risk.length} label="promises at risk" note="open, on those parcels" />
              <Stat value={`#${imp.keystone_rank}`} label="keystone rank" note={`PageRank over ${imp.decisions_ranked} decisions`} />
              <Stat value={imp.dependent_decisions.length} label="decisions built on it" />
            </div>
            <div className="mt-5 grid gap-6 lg:grid-cols-2">
              <div>
                <h3 className="text-sm font-semibold">Customers waiting, highest order value first</h3>
                <div className="overflow-x-auto"><table className="mt-1 w-full min-w-[26rem] text-sm">
                  <thead className="text-xs text-stone-500"><tr><th className="text-left">Customer</th><th>Tier</th><th className="text-right">Order value</th><th className="text-right">Open tickets</th></tr></thead>
                  <tbody>{imp.customers_at_risk.slice(0, 8).map((c: any) => (
                    <tr key={c.customer} className="border-t border-stone-100"><td className="py-1 font-mono">{c.customer}</td>
                      <td className="text-center">{c.tier}</td><td className="text-right">{money(c.order_value)}</td><td className="text-right">{c.open_tickets}</td></tr>))}</tbody>
                </table></div>
              </div>
              <div>
                <h3 className="text-sm font-semibold">Promises at risk, soonest first</h3>
                <ul className="mt-1 space-y-1 text-sm">{imp.promises_at_risk.slice(0, 8).map((p: any) => (
                  <li key={p.promise}><span className="font-mono">{p.promise}</span> · {p.kind} on {p.order} {p.ticket && <> (ticket <TicketLink id={p.ticket} />)</>} ·{" "}
                    <Chip tone={p.hours_left < 0 ? "rose" : "amber"}>{p.hours_left < 0 ? `${fmtSpan(-p.hours_left)} overdue` : `${fmtSpan(p.hours_left)} left`}</Chip></li>))}</ul>
                <h3 className="mt-4 text-sm font-semibold">Decisions built on it</h3>
                <ul className="text-sm">{imp.dependent_decisions.map((d: any) => <li key={d.decision}>{d.title} <span className="font-mono text-xs text-stone-500">{d.decision}</span></li>)}</ul>
              </div>
            </div>
          </Section>
        )}

        <Section title="Before the next launch" hint="scheduled campaigns that would use a hub with broken assumptions">
          {warning ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-4 text-sm">
              <p><b>{warning.name}</b> (<span className="font-mono">{warning.campaign}</span>) starts in <b>{warning.starts_in_days} days</b> and goes through <span className="font-mono">{warning.hub}</span>, where {warning.broken_assumptions.length} assumptions are already broken:</p>
              <ul className="mt-1 list-disc pl-5">{warning.broken_assumptions.map((a: any) => <li key={a.assumption}>{a.statement}: now {show(a.metric, a.value)}</li>)}</ul>
              {warning.reroute && <p className="mt-2">Option: route through <b className="font-mono">{warning.reroute.hub}</b> instead ({warning.reroute.path.join(" → ")}, {warning.reroute.hours} h by shortest path, capacity {warning.reroute.capacity}/day).</p>}
            </div>
          ) : <p className="text-sm text-stone-600">{v.prelaunch.reason}</p>}
        </Section>

        <Section title="Investigate with AI" hint="the agent walks the same chain and prepares actions for you">
          <AgentPanel agent="pattern" asUser={asUser} label="Investigate this week's complaints"
            task="Why are west-region complaints up this week, and what should we do?" onDone={load} />
        </Section>

        <Section title="The chain as a graph" open={false}>
          <Suspense fallback={<p className="text-sm text-stone-500">Loading graph…</p>}><PathGraph paths={graphPaths} height={360} highlight={[cluster?.root_hub, broken?.decision, linked?.decision].filter(Boolean)} /></Suspense>
        </Section>

        <Section title="Choke points" hint="hubs on the most delivery routes (betweenness centrality)" open={false}>
          <ul className="text-sm">{v.choke_points.data.map((c: any) => <li key={c.hub}><span className="font-mono">{c.hub}</span>: on {c.score} shortest routes</li>)}</ul>
        </Section>
      </div>
    </div>
  );
}

function Step({ n, title, outcome, children }: { n: number; title: string; outcome: string; children: React.ReactNode }) {
  return (
    <li className="rounded-xl border border-stone-200 bg-white p-5">
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-teal-700 text-xs font-semibold text-white">{n}</span>
        <h2 className="flex-1 text-[15px] font-semibold text-stone-800">{title}</h2>
        <Outcome outcome={outcome} />
      </div>
      <div className="text-sm text-stone-800">{children}</div>
    </li>
  );
}
