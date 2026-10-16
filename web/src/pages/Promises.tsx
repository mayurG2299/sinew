import { useEffect, useState } from "react";
import { api, fmtSpan } from "../api";
import { Chip, Section } from "../components/ui";
import { TicketLink, useName } from "../staff";

export function Promises({ asUser }: { asUser: string }) {
  const name = useName();
  const [v, setV] = useState<any>(null);
  const load = () => api.promises(asUser).then(setV);
  useEffect(() => { setV(null); load(); }, [asUser]);
  if (!v) return <p className="p-6 text-stone-500">Loading promises…</p>;

  const groups: [string, string, any[]][] = [
    ["Broken", "the deadline passed with no matching refund or delivery", v.promises.filter((p: any) => p.status === "broken")],
    ["Due within 24 hours", "nothing has happened yet; act now or update the customer",
      v.promises.filter((p: any) => p.status === "open" && p.hours_left >= 0 && p.hours_left < 24)],
    ["Waiting for confirmation", "the AI found these in replies; confirm or ignore",
      v.promises.filter((p: any) => p.status === "proposed")],
    ["Open, later", "", v.promises.filter((p: any) => p.status === "open" && p.hours_left >= 24)],
  ];

  async function confirm(id: string) {
    await api.confirm("confirm_promise", { promise_id: id }, asUser);
    load();
  }

  return (
    <div className="h-full overflow-y-auto bg-stone-50 p-4 lg:p-6">
      <div className="w-full max-w-[1400px] space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-stone-900">Promises</h1>
          <p className="text-sm text-stone-600">{v.scope === "mine" ? "Promises you made to customers." : "Promises your team made to customers."} A promise is kept automatically when the matching refund or delivery happens.</p>
        </div>
        {groups.map(([title, hint, rows]) => (
          <Section key={title} title={`${title} · ${rows.length}`} hint={hint} open={rows.length > 0}>
            {rows.length === 0 ? <p className="text-sm text-stone-500">None.</p> : (
              <div className="overflow-x-auto"><table className="w-full min-w-[40rem] text-sm">
                <thead className="text-left text-xs text-stone-500"><tr><th>Promise</th><th>What</th><th>Order</th><th>Ticket</th><th>Made by</th><th className="text-right">Deadline</th><th /></tr></thead>
                <tbody>{rows.map((p: any) => (
                  <tr key={p.promise} className="border-t border-stone-100">
                    <td className="py-1.5 font-mono">{p.promise}</td><td>{p.kind}</td><td className="font-mono">{p.order}</td>
                    <td>{p.ticket ? <TicketLink id={p.ticket} /> : "—"}</td><td>{name(p.owner)}</td>
                    <td className="text-right"><Chip tone={p.hours_left < 0 ? "rose" : p.hours_left < 24 ? "amber" : "stone"}>
                      {p.hours_left < 0 ? `${fmtSpan(-p.hours_left)} overdue` : `${fmtSpan(p.hours_left)} left`}</Chip></td>
                    <td className="text-right">{p.status === "proposed" && p.owner === asUser &&
                      <button onClick={() => confirm(p.promise)} className="rounded-md border border-stone-300 px-2 py-0.5 text-xs hover:bg-stone-50">Confirm</button>}</td>
                  </tr>))}</tbody>
              </table></div>
            )}
          </Section>
        ))}
      </div>
    </div>
  );
}
