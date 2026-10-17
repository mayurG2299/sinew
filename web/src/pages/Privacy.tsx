import { useState } from "react";
import { api, type Answer } from "../api";
import { Outcome, Section } from "../components/ui";

export function Privacy({ asUser }: { asUser: string }) {
  const [ref, setRef] = useState("");
  const [exported, setExported] = useState<Answer | null>(null);
  const [deleted, setDeleted] = useState<Answer | null>(null);
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);

  async function lookup() {
    setBusy(true); setDeleted(null); setSure(false);
    setExported(await api.exportCustomer(ref.trim(), asUser));
    setBusy(false);
  }
  async function remove() {
    setBusy(true);
    setDeleted(await api.deleteCustomer(ref.trim(), asUser));
    setBusy(false);
  }

  return (
    <div className="h-full overflow-y-auto bg-stone-50 p-4 lg:p-6">
      <div className="w-full max-w-[1100px] space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-stone-900">Privacy requests</h1>
          <p className="text-sm text-stone-600">Export or delete one customer (GDPR, India's DPDP Act, CCPA). Handled by the support head; the AI has no access to these actions.</p>
        </div>
        <Section title="1. Find the customer" hint="customer, ticket or order id">
          <div className="flex flex-wrap gap-2">
            <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="e.g. t-90520 or o-4520"
              className="w-72 rounded-md border border-stone-300 px-3 py-1.5 text-sm" />
            <button onClick={lookup} disabled={!ref.trim() || busy}
              className="rounded-lg bg-teal-700 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50">Show what Sinew holds</button>
          </div>
        </Section>

        {exported && (
          <Section title="2. What Sinew holds" right={<Outcome outcome={exported.outcome} />}>
            {exported.outcome !== "answered_path" ? <p className="text-sm">{exported.reason}</p> : <>
              <p className="text-sm">For <span className="font-mono">{exported.data.customer}</span>, the graph holds:</p>
              <ul className="mt-2 grid grid-cols-2 gap-x-6 text-sm sm:grid-cols-3">
                {Object.entries(exported.data.graph_holds).map(([k, n]) => <li key={k}>{String(n)} × {k}</li>)}
                <li>{exported.data.access_records} × access record</li>
              </ul>
              <p className="mt-2 text-xs text-stone-500">{exported.data.note}. Identifiers are stored only as keyed hashes.</p>
            </>}
          </Section>
        )}

        {exported?.outcome === "answered_path" && (
          <Section title="3. Delete">
            {!deleted ? <>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} />
                Remove this person's identity from Sinew. Orders, payments and tickets stay for legal retention, unlinked from them.
              </label>
              <button onClick={remove} disabled={!sure || busy}
                className="mt-3 rounded-lg bg-rose-700 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50">Delete and prove it</button>
            </> : deleted.outcome !== "answered_path" ? <p className="text-sm">{deleted.reason}</p> : (
              <div className="space-y-2 text-sm">
                <p>Removed {deleted.data.profiles_removed} profiles and their identifiers. Business records now point at <span className="font-mono">{deleted.data.tombstone}</span>.</p>
                <div className="rounded-lg border border-teal-200 bg-teal-50/50 p-3">
                  <p className="font-medium">Proof, computed by re-walking the graph:</p>
                  <ul className="mt-1 list-disc pl-5">
                    <li>{deleted.data.proof.nodes_left_with_their_ids} nodes left with this person's ids</li>
                    <li>looking them up now finds: {deleted.data.proof.resolves_now ?? "nothing"}</li>
                    <li>{deleted.data.proof.orders_still_linked_to_a_person} orders still linked to a person</li>
                  </ul>
                </div>
                <p className="text-stone-600">{deleted.data.store}.</p>
              </div>
            )}
          </Section>
        )}
      </div>
    </div>
  );
}
