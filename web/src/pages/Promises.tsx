import { useEffect, useState } from "react";
import { api, day, fmtSpan, money, orderNo } from "../api";
import { Chip, Section } from "../components/ui";
import { TicketLink, useName } from "../staff";

/** One promise as a sentence: what, to whom, by when, who made it, and the next step. */
function Row({ p, asUser, onConfirm }: { p: any; asUser: string; onConfirm: (id: string) => void }) {
  const name = useName();
  const what = p.kind === "refund" ? `Refund${p.amount ? ` of ${money(p.amount)}` : ""}` : "Delivery";
  const when = p.hours_left < 0 ? <Chip tone="rose">{fmtSpan(-p.hours_left)} overdue</Chip>
    : <Chip tone={p.hours_left < 24 ? "amber" : "stone"}>due in {fmtSpan(p.hours_left)}</Chip>;
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-stone-100 py-2.5 text-sm first:border-t-0">
      <span className="min-w-0 flex-1">
        <b>{what}</b> to {p.name ?? "the customer"} for order {orderNo(p.order)}, by {day(p.due_at)}
        <span className="text-stone-500"> · promised by {p.owner === asUser ? "you" : name(p.owner)}</span>
      </span>
      {when}
      {p.ticket && <TicketLink id={p.ticket} />}
      {p.status === "proposed" && p.owner === asUser &&
        <button onClick={() => onConfirm(p.promise)}
          className="rounded-md bg-teal-700 px-3 py-1 text-xs font-medium text-white hover:bg-teal-800">Yes, I promised this</button>}
    </li>
  );
}

export function Promises({ asUser }: { asUser: string }) {
  const [v, setV] = useState<any>(null);
  const load = () => api.promises(asUser).then(setV);
  useEffect(() => { setV(null); load(); }, [asUser]);
  if (!v) return <p className="p-6 text-stone-500">Loading promises…</p>;

  const all = v.promises;
  const groups: [string, string, any[]][] = [
    ["Broken", "the date passed and the refund or delivery didn't happen. Apologise and fix it first.",
      all.filter((p: any) => p.status === "broken")],
    ["Due in the next 24 hours", "nothing has happened yet. Act now, or tell the customer the new date.",
      all.filter((p: any) => p.status === "open" && p.hours_left >= 0 && p.hours_left < 24)],
    ["Did you promise this?", "the AI spotted these in replies. Confirm the ones you really promised so they're tracked.",
      all.filter((p: any) => p.status === "proposed")],
    ["Later", "on track so far.", all.filter((p: any) => p.status === "open" && p.hours_left >= 24)],
  ];
  const [broken, soon, proposed] = groups.map((g) => g[2].length);

  async function confirm(id: string) {
    await api.confirm("confirm_promise", { promise_id: id }, asUser);
    load();
  }

  return (
    <div className="h-full overflow-y-auto bg-stone-50 p-4 lg:p-6">
      <div className="w-full max-w-[1100px] space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-stone-900">Promises</h1>
          <p className="text-sm text-stone-600">
            {v.scope === "mine" ? "What you promised customers." : "What your team promised customers."} A promise is marked kept by itself when the refund or delivery actually happens.
          </p>
        </div>
        <div className="rounded-xl border border-stone-200 bg-white p-5">
          <p className="text-[15px] text-stone-900">
            {broken + soon + proposed === 0 ? "Nothing needs you right now: every promise is on track."
              : <>{broken > 0 && <><b className="text-rose-800">{broken} broken</b>{soon + proposed > 0 ? ", " : "."} </>}
                {soon > 0 && <><b>{soon} due in the next 24 hours</b>{proposed > 0 ? ", " : "."} </>}
                {proposed > 0 && <><b>{proposed} waiting for you to confirm</b>.</>}</>}
          </p>
        </div>
        {groups.map(([title, hint, rows]) => (
          <Section key={title} title={`${title} · ${rows.length}`} hint={hint} open={rows.length > 0 && title !== "Later"}>
            {rows.length === 0 ? <p className="text-sm text-stone-500">None.</p>
              : <ul>{rows.map((p: any) => <Row key={p.promise} p={p} asUser={asUser} onConfirm={confirm} />)}</ul>}
          </Section>
        ))}
      </div>
    </div>
  );
}
