import { useContext, useState } from "react";
import { api, type Answer } from "../api";
import { Section } from "../components/ui";
import { StaffContext } from "../staff";

const HOLDS: Record<string, [string, string]> = {
  Profile: ["profile", "profiles (one per channel they used)"], Identifier: ["contact fingerprint", "contact fingerprints"],
  PersonalRef: ["pointer to the store's record", "pointers to the store's records"], Consent: ["consent choice", "consent choices"],
  Order: ["order", "orders"], LineItem: ["order line", "order lines"], Payment: ["payment", "payments"],
  Shipment: ["parcel", "parcels"], Scan: ["courier scan", "courier scans"], Refund: ["refund", "refunds"],
  Return: ["return", "returns"], Promise: ["commitment", "commitments"], Ticket: ["support ticket", "support tickets"],
};

export function Privacy({ asUser }: { asUser: string }) {
  const staff = useContext(StaffContext);
  const [ref, setRef] = useState("");
  const [exported, setExported] = useState<Answer | null>(null);
  const [deleted, setDeleted] = useState<Answer | null>(null);
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const isHead = staff[asUser]?.role === "support_head";

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
      <div className="w-full max-w-[1000px] space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-stone-900">Privacy requests</h1>
          <p className="text-sm text-stone-600">When a customer asks "what do you hold about me?" or "delete me" (GDPR, India's DPDP Act, CCPA). Only the head of support can do this, and the AI can't.</p>
        </div>
        {!isHead && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
            You're signed in as someone who isn't the head of support, so Sinew will refuse these requests. Switch "Signed in as" to the head of support to try them.
          </p>
        )}

        <Section title="1. Find the customer" hint="the way they'd identify themselves">
          <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); lookup(); }}>
            <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Their email, phone or an order number like #4397"
              className="w-full max-w-md rounded-md border border-stone-300 px-3 py-1.5 text-sm" />
            <button disabled={!ref.trim() || busy}
              className="rounded-lg bg-teal-700 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50">See what Sinew holds</button>
          </form>
          <p className="mt-2 text-xs text-stone-500">An email or phone typed here is turned into a fingerprint to find them; it isn't saved.</p>
        </Section>

        {exported && (
          <Section title="2. What Sinew holds about them">
            {exported.outcome !== "answered_path" ? <p className="text-sm text-stone-700">{exported.outcome === "unknown_entity" ? "No customer matches that." : exported.reason}</p> : <>
              <ul className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                {Object.entries(exported.data.graph_holds).map(([k, n]) => (
                  <li key={k}><b>{String(n)}</b> {(HOLDS[k] ?? [k, k])[Number(n) === 1 ? 0 : 1]}</li>))}
              </ul>
              <p className="mt-3 text-sm text-stone-700">
                <b>Not held by Sinew:</b> their name, email, phone or address. Those stay in the store's own system. Sinew keeps only scrambled fingerprints that can match them but can't be read back.
              </p>
              <p className="mt-1 text-sm text-stone-700">Staff have opened their record <b>{exported.data.access_records}</b> times. Every view is logged with who and why.</p>
            </>}
          </Section>
        )}

        {exported?.outcome === "answered_path" && (
          <Section title="3. Delete them">
            {!deleted ? <>
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={sure} onChange={(e) => setSure(e.target.checked)} />
                <span>Remove this person from Sinew. Their orders, payments and tickets are kept for accounting and the law, but will no longer point to them.</span>
              </label>
              <button onClick={remove} disabled={!sure || busy}
                className="mt-3 rounded-lg bg-rose-700 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50">Delete and prove it</button>
            </> : deleted.outcome !== "answered_path" ? <p className="text-sm">{deleted.reason}</p> : (
              <div className="space-y-3 text-sm">
                <p>Done. Their {deleted.data.profiles_removed} {deleted.data.profiles_removed === 1 ? "profile" : "profiles"} and contact fingerprints are gone. Their business records are kept but now belong to nobody.</p>
                <div className="rounded-lg border border-teal-200 bg-teal-50/50 p-4 text-teal-950">
                  <p className="font-medium">Proof: Sinew searched the whole graph again afterwards</p>
                  <ul className="mt-1 list-disc pl-5">
                    <li>Records still carrying their ids: <b>{deleted.data.proof.nodes_left_with_their_ids}</b></li>
                    <li>Searching for them now finds: <b>{deleted.data.proof.resolves_now ?? "nobody"}</b></li>
                    <li>Orders still linked to a person: <b>{deleted.data.proof.orders_still_linked_to_a_person}</b></li>
                  </ul>
                </div>
                <p className="text-stone-600">{deleted.data.store.replace(/^./, (c: string) => c.toUpperCase())}.</p>
                <p className="text-xs text-stone-500">Use "Reset demo data" in the sidebar to bring this customer back for the next demo.</p>
              </div>
            )}
          </Section>
        )}
      </div>
    </div>
  );
}
