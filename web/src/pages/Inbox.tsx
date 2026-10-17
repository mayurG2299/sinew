import { useEffect, useState, lazy, Suspense } from "react";
import { ISSUE, ago, api, day, fmtSpan, money, orderNo, place } from "../api";
import { AgentPanel } from "../components/AgentPanel";
import { Chip, Clean, Hidden, Outcome, Refused, Section } from "../components/ui";
import { useName } from "../staff";
const PathGraph = lazy(() => import("../components/PathGraph").then((m) => ({ default: m.PathGraph })));

type Row = {
  ticket: string; at: number; issue: string; status: string; summary: string; customer: string; name: string | null;
  broken_promises: number; due_soon: number | null; late_parcels: number;
};

const urgency = (t: Row) => t.status === "solved" ? -1 : t.broken_promises * 3 + (t.due_soon ? 2 : 0) + (t.late_parcels ? 2 : 0);

function Flags({ t, now }: { t: Row; now: number }) {
  return <>
    {t.broken_promises > 0 && <Chip tone="rose">{t.broken_promises > 1 ? `${t.broken_promises} promises broken` : "promise broken"}</Chip>}
    {t.due_soon && <Chip tone="amber">promise due {ago(t.due_soon, now)}</Chip>}
    {t.late_parcels > 0 && <Chip tone="amber">parcel late</Chip>}
  </>;
}

export function Inbox({ asUser }: { asUser: string }) {
  const [data, setData] = useState<{ tickets: Row[]; now: number; scope: string; can_see_customers: boolean } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<"urgent" | "newest">("urgent");

  useEffect(() => {
    setData(null); setSelected(null);
    const fromLink = window.location.hash.split("/")[1];  // #inbox/t-90520 opens that ticket
    api.inbox(asUser).then((d) => {
      setData(d);
      const first = [...d.tickets].sort((a: Row, b: Row) => urgency(b) - urgency(a) || b.at - a.at)[0];
      setSelected(fromLink || (first?.ticket ?? null));
    });
  }, [asUser]);

  if (!data) return <p className="p-6 text-stone-500">Loading tickets…</p>;
  if (!data.can_see_customers)
    return <div className="p-6"><Refused a={{ outcome: "not_permitted", reason: "Your role doesn't handle individual customers, so there is no inbox. The Decision impact page shows totals and causes without anyone's personal history.", tool: "", data: {}, paths: [], hidden: [], ms: 0 }} /></div>;

  const list = data.tickets.filter((t) => !filter || t.issue === filter)
    .sort((a, b) => (sort === "urgent" ? urgency(b) - urgency(a) : 0) || b.at - a.at);
  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[22rem_1fr]">
      <aside className="max-h-[40vh] min-h-0 overflow-y-auto border-b lg:max-h-none border-stone-200 bg-white lg:border-b-0 lg:border-r">
        <div className="sticky top-0 z-10 border-b border-stone-100 bg-white px-4 py-3">
          <h1 className="text-sm font-semibold text-stone-800">Your inbox</h1>
          <p className="text-xs text-stone-500">{list.length} tickets from {data.scope}</p>
          <div className="mt-2 flex gap-2">
            <div className="flex rounded-md border border-stone-200 p-0.5 text-xs">
              {(["urgent", "newest"] as const).map((s) => (
                <button key={s} onClick={() => setSort(s)}
                  className={`rounded px-2 py-1 ${sort === s ? "bg-teal-700 text-white" : "text-stone-600 hover:bg-stone-50"}`}>
                  {s === "urgent" ? "Most urgent" : "Newest"}
                </button>
              ))}
            </div>
            <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by issue"
              className="min-w-0 flex-1 rounded-md border border-stone-200 px-2 py-1 text-xs">
              <option value="">All issues</option>
              {Object.entries(ISSUE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
        </div>
        <ul>
          {list.map((t) => (
            <li key={t.ticket}>
              <button onClick={() => setSelected(t.ticket)}
                className={`block w-full border-b border-stone-100 px-4 py-3 text-left hover:bg-stone-50 ${selected === t.ticket ? "bg-teal-50/60" : ""}`}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-sm font-semibold text-stone-900">{t.name ?? "Customer"}</span>
                  <span className="shrink-0 text-xs text-stone-500">{ago(t.at, data.now)}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <Chip>{ISSUE[t.issue] ?? t.issue}</Chip>
                  <Flags t={t} now={data.now} />
                  {t.status === "solved" && <span className="text-xs text-stone-400">solved</span>}
                </div>
                <p className="mt-1 line-clamp-2 text-sm text-stone-600"><Clean text={t.summary} /></p>
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

const sinceMonth = (at: number) => new Date(at * 1000).toLocaleString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

export function CustomerView({ ticket, asUser, embedded = false }: { ticket: string; asUser: string; embedded?: boolean }) {
  const name = useName();
  const [v, setV] = useState<any>(null);
  const load = () => api.trace(ticket, asUser).then(setV);
  useEffect(() => { setV(null); load(); }, [ticket, asUser]);
  if (!v) return <p className="text-stone-500">Loading this customer…</p>;
  const t = v.trace;
  if (t.outcome !== "answered_path") return <Refused a={t} />;
  const d = t.data, now = v.now, loops = v.open_loops?.data ?? {};
  const courier = v.freshness.find((f: any) => f.source === "courier");
  const orders = d.timeline.filter((i: any) => i.kind === "order");
  const current = d.timeline.find((i: any) => i.kind === "ticket" && i.id === ticket);

  return (
    <div className="w-full max-w-[1100px] space-y-4">
      <div className="rounded-xl border border-stone-200 bg-white p-5">
        <h1 className="text-xl font-semibold text-stone-900">{d.personal?.name ?? "Customer"}</h1>
        <p className="mt-1 text-sm text-stone-600">
          {cap(d.region)} · {d.tier} customer{d.since ? ` since ${sinceMonth(d.since)}` : ""} · {orders.length} {orders.length === 1 ? "order" : "orders"},{" "}
          {money(orders.reduce((s: number, o: any) => s + o.total, 0))} spent · contacts us by {d.channels.join(", ")}
        </p>
        {(d.personal?.email || d.personal?.phone) && (
          <p className="mt-1 text-sm text-stone-700">
            {d.personal.email && <span className="mr-4">{d.personal.email}</span>}
            {d.personal.phone && <span>{d.personal.phone}</span>}
          </p>
        )}
        <Hidden items={t.hidden} />
        {current && (
          <div className="mt-4 rounded-lg border border-stone-200 bg-stone-50 p-4">
            <p className="text-xs text-stone-500">
              This ticket · {ISSUE[current.issue] ?? current.issue} · written {ago(current.at, now)} via {current.channel}
              {current.order && <> · about order {orderNo(current.order)}</>} · {current.status}
            </p>
            <p className="mt-1 text-[15px] text-stone-900">“<Clean text={current.summary} />”</p>
          </div>
        )}
      </div>

      <Section title="What needs doing" hint="most urgent first">
        <ToDo loops={loops} now={now} ticket={ticket} />
        <div className={embedded ? "hidden" : "mt-4 border-t border-stone-100 pt-4"}>
          <AgentPanel agent="support" asUser={asUser} label="Draft a reply and next step"
            task={`Ticket ${ticket}: help me handle this customer.`} onDone={load}
            note="AI drafts the reply and suggests actions. Refunds and promises only happen after you confirm." />
        </div>
      </Section>

      {v.related?.outcome === "answered_path" && <Wider shared={v.related.data.shared} />}

      <Section title="Orders" hint="newest first; open orders are expanded">
        <div className="space-y-3">
          {[...orders].reverse().map((o: any) => (
            <OrderCard key={o.id} o={o} events={d.timeline.filter((i: any) => i.order === o.id && i.kind !== "order")} now={now} name={name} />
          ))}
          {d.timeline.some((i: any) => i.kind === "ticket" && !i.order) && (
            <OrderCard o={null} events={d.timeline.filter((i: any) => i.kind === "ticket" && !i.order)} now={now} name={name} />
          )}
        </div>
      </Section>

      <Section title="How Sinew knows this" hint="access, sources and the graph path" open={false}>
        <div className="space-y-2 text-sm text-stone-700">
          <p><Outcome outcome={t.outcome} /> You can see this customer because {d.granted_by}. The view was opened in your name and logged.</p>
          <p>Built from the company graph in {t.ms} ms, without AI.{courier && <> Courier data as of {ago(courier.last_event_at, now)}.</>}</p>
          <p>Contact details are fetched live from the store's own records, only the fields your role may see. Sinew itself stores no names, emails or phone numbers.</p>
          <p className="text-xs text-stone-500">
            Customer <span className="font-mono">{d.customer}</span> · ticket <span className="font-mono">{ticket}</span> · profiles{" "}
            <span className="font-mono">{d.profiles.join(", ")}</span>
          </p>
          <Suspense fallback={<p className="text-sm text-stone-500">Loading graph…</p>}>
            <PathGraph paths={t.paths} highlight={[d.customer, ticket]} />
          </Suspense>
        </div>
      </Section>
    </div>
  );
}

/** Open loops as a short to-do list, in plain words, most urgent first. */
function ToDo({ loops, now, ticket }: { loops: any; now: number; ticket: string }) {
  const items: { tone: "rose" | "amber" | "stone"; text: string }[] = [];
  for (const p of loops.broken_promises ?? [])
    items.push({ tone: "rose", text: `A ${p.promise} on order ${orderNo(p.order)} was promised by ${day(p.due_at)} and is ${fmtSpan((now - p.due_at) / 3600)} overdue.` });
  for (const s of loops.late_in_transit ?? [])
    items.push({ tone: "amber", text: `Order ${orderNo(s.order)} is stuck at ${place(s.hub)} (${place(s.courier)}), ${fmtSpan(s.late_hours)} late.` });
  for (const p of loops.open_promises ?? [])
    items.push({ tone: "amber", text: `A ${p.promise} on order ${orderNo(p.order)} is promised${p.status === "proposed" ? " (not yet confirmed)" : ""}, due ${ago(p.due_at, now)}.` });
  for (const r of loops.returns_not_refunded ?? [])
    items.push({ tone: "amber", text: `Return on order ${orderNo(r.order)} hasn't been refunded yet.` });
  const others = (loops.open_tickets ?? []).filter((x: any) => x.id !== ticket);
  if (others.length)
    items.push({ tone: "stone", text: `${others.length} other open ${others.length === 1 ? "ticket" : "tickets"} from this customer: ${others.map((x: any) => (ISSUE[x.issue] ?? x.issue).toLowerCase()).join(", ")}. Reply to them together.` });
  if (!items.length) return <p className="text-sm text-stone-600">Nothing else is open for this customer: just answer this ticket.</p>;
  const dot = { rose: "bg-rose-500", amber: "bg-amber-500", stone: "bg-stone-400" };
  return (
    <ul className="space-y-2">
      {items.map((x, i) => (
        <li key={i} className="flex gap-3 text-sm text-stone-800"><span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${dot[x.tone]}`} />{x.text}</li>
      ))}
    </ul>
  );
}

/** Other recent tickets through the same hub, courier, batch or campaign, said once and linked to the cause. */
function Wider({ shared }: { shared: any[] }) {
  const top = shared[0];
  const same = shared.filter((s) => s.other_tickets === top.other_tickets).map((s) => place(s.id));
  const sameIssue = Math.max(...shared.map((s) => s.same_issue));
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/60 px-5 py-4 text-sm text-amber-950">
      <p className="font-semibold">This may not be just this customer.</p>
      <p className="mt-1">
        {top.other_tickets} other tickets in the last 7 days went through the same {same.length > 1 ? "places" : "place"}: {same.join(", ")}
        {sameIssue > 0 && <>, {sameIssue} of them about the same problem</>}.{" "}
        <a href="#impact" className="font-medium text-teal-800 underline decoration-teal-300 underline-offset-2">See what's behind it →</a>
      </p>
    </div>
  );
}

const PROMISE_STATUS: Record<string, [string, "rose" | "teal" | "amber" | "stone"]> = {
  broken: ["broken", "rose"], kept: ["kept", "teal"], kept_late: ["kept late", "amber"], open: ["open", "amber"],
  proposed: ["awaiting confirmation", "stone"], rejected: ["rejected", "stone"],
};

function OrderCard({ o, events, now, name }: { o: any | null; events: any[]; now: number; name: (id?: string | null) => string }) {
  const scans = events.filter((e) => e.kind === "scan");
  const last = scans[scans.length - 1];
  const open = events.some((e) => (e.kind === "ticket" && e.status !== "solved") || (e.kind === "promise" && ["open", "broken", "proposed"].includes(e.status)))
    || (last && last.status !== "delivered" && last.late_hours > 0);
  const [show, setShow] = useState(open);
  const status = !o ? null : !last ? <Chip>not shipped yet</Chip>
    : last.status === "delivered" ? <Chip tone="teal">delivered {day(last.at).split(",")[0]}</Chip>
      : last.late_hours > 0 ? <Chip tone="rose">late · at {place(last.hub)}</Chip>
        : <Chip>on the way · at {place(last.hub)}</Chip>;
  const refund = events.find((e) => e.kind === "refund" && e.status === "issued");
  return (
    <div className="rounded-lg border border-stone-200">
      <button onClick={() => setShow(!show)} aria-expanded={show}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-left hover:bg-stone-50">
        <span className="text-xs text-stone-400">{show ? "▾" : "▸"}</span>
        {o ? <>
          <span className="font-semibold text-stone-900">Order {orderNo(o.id)}</span>
          <span className="text-sm text-stone-700">{o.lines.map((l: any) => l.title).join(", ")}</span>
          <span className="text-sm text-stone-700">{money(o.total)}</span>
          {o.coupon && <Chip tone="amber">coupon {o.coupon}</Chip>}
          {status}{refund && <Chip tone="teal">refunded {money(refund.amount)}</Chip>}
          <span className="ml-auto text-xs text-stone-500">placed {day(o.at).split(",")[0]}</span>
        </> : <span className="font-semibold text-stone-900">Messages not about an order</span>}
      </button>
      {show && (
        <ol className="space-y-1.5 border-t border-stone-100 px-4 py-3">
          {events.map((e, n) => <Event key={n} e={e} name={name} now={now} />)}
        </ol>
      )}
    </div>
  );
}

function Event({ e, name, now }: { e: any; name: (id?: string | null) => string; now: number }) {
  let body;
  switch (e.kind) {
    case "payment":
      body = <>Paid {money(e.amount)} {e.method === "cod" ? "cash on delivery" : `by ${e.method}`}</>;
      break;
    case "scan":
      body = e.status === "delivered" ? <>Delivered by {place(e.courier)}</>
        : <>Parcel scanned at {place(e.hub)} ({place(e.courier)}){e.late_hours > 0 && <> · <Chip tone="rose">{fmtSpan(e.late_hours)} late</Chip></>}</>;
      break;
    case "refund":
      body = <>Refund of {money(e.amount)} {e.status}{e.approved_by && <span className="text-stone-500"> · approved by {name(e.approved_by)}</span>}</>;
      break;
    case "return":
      body = <>Return requested: {e.reason} ({e.status})</>;
      break;
    case "ticket":
      body = <>Customer wrote via {e.channel} · {ISSUE[e.issue] ?? e.issue} · {e.status}
        {e.handled_by && <span className="text-stone-500"> · handled by {name(e.handled_by)}</span>}
        <span className="block text-stone-600">“<Clean text={e.summary} />”</span></>;
      break;
    case "promise": {
      const [label, tone] = PROMISE_STATUS[e.status] ?? [e.status, "stone"];
      body = <>{e.made_by ? name(e.made_by) : "We"} promised a {e.promise} by {day(e.due_at)} · <Chip tone={tone}>{label}</Chip>
        {e.status === "open" && <span className="text-stone-500"> · due {ago(e.due_at, now)}</span>}</>;
      break;
    }
    default:
      body = <>{e.kind}</>;
  }
  return <li className="flex gap-3 text-sm text-stone-800"><span className="w-28 shrink-0 text-xs text-stone-500">{day(e.at)}</span><span>{body}</span></li>;
}
