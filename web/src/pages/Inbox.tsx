import { useEffect, useState } from "react";
import { ago, api, day, money } from "../api";
import { AgentPanel } from "../components/AgentPanel";
import { lazy, Suspense } from "react";
const PathGraph = lazy(() => import("../components/PathGraph").then((m) => ({ default: m.PathGraph })));
import { Chip, Hidden, Outcome, Refused, Section, Stat } from "../components/ui";
import { useName } from "../staff";

const ISSUE: Record<string, string> = {
  late_delivery: "Late delivery", damaged: "Damaged", refund_status: "Refund status", wrong_item: "Wrong item",
  product_issue: "Product issue", other: "Other",
};

export function Inbox({ asUser }: { asUser: string }) {
  const [data, setData] = useState<{ tickets: any[]; now: number; can_see_customers: boolean } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    setData(null); setSelected(null);
    const fromLink = window.location.hash.split("/")[1];  // #inbox/t-90500 opens that ticket
    api.inbox(asUser).then((d) => { setData(d); setSelected(fromLink || (d.tickets[0]?.ticket ?? null)); });
  }, [asUser]);

  if (!data) return <p className="p-6 text-stone-500">Loading tickets…</p>;
  if (!data.can_see_customers)
    return <div className="p-6"><Refused a={{ outcome: "not_permitted", reason: "Your role has no support purpose for individual customers. The Decision impact view shows totals and causes without personal histories.", tool: "", data: {}, paths: [], hidden: [], ms: 0 }} /></div>;

  const list = data.tickets.filter((t) => !filter || t.issue === filter);
  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[22rem_1fr]">
      <aside className="max-h-[40vh] min-h-0 overflow-y-auto border-b lg:max-h-none border-stone-200 bg-white lg:border-b-0 lg:border-r">
        <div className="sticky top-0 z-10 border-b border-stone-100 bg-white px-4 py-3">
          <h1 className="text-sm font-semibold text-stone-800">Inbox · {list.length} tickets you may see</h1>
          <select value={filter} onChange={(e) => setFilter(e.target.value)}
            className="mt-2 w-full rounded-md border border-stone-200 px-2 py-1 text-sm">
            <option value="">All issues</option>
            {Object.entries(ISSUE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <ul>
          {list.map((t) => (
            <li key={t.ticket}>
              <button onClick={() => setSelected(t.ticket)}
                className={`block w-full border-b border-stone-100 px-4 py-3 text-left hover:bg-stone-50 ${selected === t.ticket ? "bg-teal-50/60" : ""}`}>
                <div className="flex items-center justify-between gap-2 text-xs text-stone-500">
                  <span className="font-mono">{t.ticket}</span><span>{ago(t.at, data.now)}</span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <Chip tone={t.issue === "late_delivery" ? "amber" : "stone"}>{ISSUE[t.issue] ?? t.issue}</Chip>
                  {t.status !== "solved" && <Chip tone="teal">open</Chip>}
                </div>
                <p className="mt-1 line-clamp-2 text-sm text-stone-700">{t.summary}</p>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <main className="min-h-0 overflow-y-auto bg-stone-50 p-4 lg:p-6">
        {selected ? <CustomerView ticket={selected} asUser={asUser} /> : <p className="text-stone-500">No tickets.</p>}
      </main>
    </div>
  );
}

function CustomerView({ ticket, asUser }: { ticket: string; asUser: string }) {
  const [v, setV] = useState<any>(null);
  const load = () => api.trace(ticket, asUser).then(setV);
  useEffect(() => { setV(null); load(); }, [ticket, asUser]);
  if (!v) return <p className="text-stone-500">Building the trace…</p>;
  const t = v.trace;
  if (t.outcome !== "answered_path") return <Refused a={t} />;
  const d = t.data, now = v.now, loops = v.open_loops?.data ?? {};
  const courier = v.freshness.find((f: any) => f.source === "courier");
  const orders = d.timeline.filter((i: any) => i.kind === "order");
  const loopCount = ["open_tickets", "open_promises", "broken_promises", "late_in_transit", "returns_not_refunded"]
    .reduce((n, k) => n + (loops[k]?.length ?? 0), 0);

  return (
    <div className="w-full max-w-[1400px] space-y-4">
      <div className="rounded-xl border border-stone-200 bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs text-stone-500">Ticket <span className="font-mono">{ticket}</span> · customer</p>
            <h1 className="text-xl font-semibold text-stone-900">{d.personal?.name ?? d.customer}</h1>
            <p className="mt-1 text-sm text-stone-600">
              <span className="font-mono">{d.customer}</span> · {d.region} · {d.tier} · customer since {day(d.since).split(",")[0]} ·{" "}
              {d.channels.length > 1 ? `one person across ${d.channels.length} channels:` : "one channel:"} {d.channels.map((c: string) => <Chip key={c}>{c}</Chip>)}
            </p>
            {Object.keys(d.personal ?? {}).length > 0 && (
              <p className="mt-2 text-sm text-stone-700">
                {d.personal.email && <span className="mr-4">✉ {d.personal.email}</span>}
                {d.personal.phone && <span>☎ {d.personal.phone}</span>}
                <span className="block text-[11px] text-stone-400">Contact details are fetched live from the store for your role; Sinew doesn't store them.</span>
              </p>
            )}
          </div>
          <div className="text-right text-xs text-stone-500">
            <Outcome outcome={t.outcome} />
            <p className="mt-1">You may see this because {d.granted_by}.</p>
            <p>Trace built from the graph in {t.ms} ms, without AI.</p>
            {courier && <p>Courier data as of {ago(courier.last_event_at, now)}.</p>}
          </div>
        </div>
        <Hidden items={t.hidden} />
        <div className="mt-4 flex flex-wrap gap-8 border-t border-stone-100 pt-4">
          <Stat value={orders.length} label="orders" note={money(orders.reduce((s: number, o: any) => s + o.total, 0)) + " in total"} />
          <Stat value={d.timeline.filter((i: any) => i.kind === "ticket").length} label="tickets" note="all channels" />
          <Stat value={d.timeline.filter((i: any) => i.kind === "refund").length} label="refunds" />
          <Stat value={loopCount} label="open loops" note="see below" />
        </div>
      </div>

      <Section title="Next step" hint="AI drafts; you confirm anything that moves money">
        <AgentPanel agent="support" asUser={asUser} label="Draft the next step"
          task={`Ticket ${ticket}: help me handle this customer.`} onDone={load} />
      </Section>

      <Section title="Open loops" hint={`${loopCount} things still open for this customer`}>
        <OpenLoops loops={loops} now={now} />
      </Section>

      {v.related?.outcome === "answered_path" && (
        <Section title="Others affected" hint="tickets in the last 7 days that went through the same places">
          <ul className="space-y-1 text-sm">
            {v.related.data.shared.map((s: any) => (
              <li key={s.id}><b>{s.other_tickets}</b> other tickets went through <span className="font-mono">{s.id}</span>
                <span className="text-stone-500"> ({s.through.toLowerCase()}; {s.same_issue} with the same issue)</span></li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Timeline" hint={`${d.timeline.length} events, oldest first`}>
        <ol className="space-y-1.5">
          {d.timeline.map((i: any, n: number) => <TimelineItem key={n} i={i} />)}
        </ol>
      </Section>

      <Section title="Graph path" hint="how the trace is connected" open={false}>
        <Suspense fallback={<p className="text-sm text-stone-500">Loading graph…</p>}><PathGraph paths={t.paths} highlight={[d.customer, ticket]} /></Suspense>
      </Section>
    </div>
  );
}

function OpenLoops({ loops, now }: { loops: any; now: number }) {
  const rows: [string, any[], (x: any) => string][] = [
    ["Broken promises", loops.broken_promises ?? [], (p) => `${p.promise} on ${p.order}: was due ${ago(p.due_at, now)}`],
    ["Open promises", loops.open_promises ?? [], (p) => `${p.promise} on ${p.order} (${p.status}): due ${ago(p.due_at, now).replace(" ago", " overdue")}`],
    ["Late parcels in transit", loops.late_in_transit ?? [], (s) => `${s.id} at ${s.hub}, ${s.late_hours} h late`],
    ["Open tickets", loops.open_tickets ?? [], (t) => `${t.id}: ${t.issue}`],
    ["Returns not refunded", loops.returns_not_refunded ?? [], (r) => `${r.id} on ${r.order}`],
  ];
  const any = rows.some(([, xs]) => xs.length);
  if (!any) return <p className="text-sm text-stone-600">Nothing open: no open tickets, promises, late parcels or unrefunded returns.</p>;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {rows.filter(([, xs]) => xs.length).map(([title, xs, f]) => (
        <div key={title}>
          <h3 className="text-sm font-semibold text-stone-800">{title} · {xs.length}</h3>
          <ul className="mt-1 space-y-0.5 text-sm text-stone-700">{xs.map((x, i) => <li key={i}>{f(x)}</li>)}</ul>
        </div>
      ))}
    </div>
  );
}

function TimelineItem({ i }: { i: any }) {
  const name = useName();
  const when = <span className="w-28 shrink-0 text-xs text-stone-500">{day(i.at)}</span>;
  let body;
  switch (i.kind) {
    case "order":
      body = <>Order <b className="font-mono">{i.id}</b> placed · {money(i.total)}{i.coupon && <> · coupon <Chip tone="amber">{i.coupon}</Chip></>} · {i.lines.map((l: any) => l.batch ? `${l.title} (batch ${l.batch})` : l.title).join(", ")}</>;
      break;
    case "payment":
      body = <>Paid {money(i.amount)} by {i.method} for {i.order}</>;
      break;
    case "scan":
      body = <>Parcel for {i.order} {i.status === "delivered" ? "delivered" : `at ${i.hub}`} via {i.courier}
        {i.late_hours > 0 && <> · <Chip tone="rose">{i.late_hours} h late</Chip></>}</>;
      break;
    case "refund":
      body = <>Refund {money(i.amount)} {i.status} for {i.order}{i.approved_by && ` · approved by ${name(i.approved_by)}`}</>;
      break;
    case "return":
      body = <>Return for {i.order}: {i.reason} ({i.status})</>;
      break;
    case "ticket":
      body = <>Ticket <b className="font-mono">{i.id}</b> via {i.channel} · {i.issue} · {i.status}{i.handled_by && <span className="text-stone-500"> · {name(i.handled_by)}</span>}<span className="block text-stone-600">“{i.summary}”</span></>;
      break;
    case "promise":
      body = <>Promise <b className="font-mono">{i.id}</b>: {i.promise} on {i.order} by {day(i.due_at)} ·{" "}
        <Chip tone={i.status === "broken" ? "rose" : i.status.startsWith("kept") ? "teal" : "amber"}>{i.status.replace("_", " ")}</Chip>
        {i.kept_by && ` by ${i.kept_by}`}{i.made_by && <span className="text-stone-500"> · made by {name(i.made_by)}</span>}</>;
      break;
    default:
      body = JSON.stringify(i);
  }
  return <li className="flex gap-3 text-sm text-stone-800">{when}<span>{body}</span></li>;
}
