export type Answer = {
  tool: string;
  outcome: "answered_path" | "answered_memory" | "not_in_graph" | "unknown_entity" | "not_permitted" | "needs_approval";
  data: any;
  paths: string[][];
  hidden: { kind?: string; field?: string; count?: number; reason: string }[];
  reason: string;
  ms: number;
};

export type Staff = { id: string; role: string; refund_limit: number; team: string; regions: string[]; name: string };

export type Run = {
  run_id: string; agent: string; task: string; answer: string;
  answer_source: "model" | "rows" | "replay"; check_failed: string; model: string;
  steps: { tool: string; args: any; outcome: string; ms: number; tool_ms?: number }[];
  pending_actions: { name: string; args: any }[]; ms: number; model_ms: number[];
};

export const TENANTS = [
  { id: "northwind", name: "Northwind Goods", note: "own database shape" },
  { id: "larkspur", name: "Larkspur Home", note: "Shopify-like + helpdesk + courier feed" },
];
let TENANT = "northwind";
export const setTenant = (t: string) => { TENANT = t; };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

const q = (o: Record<string, string>) => new URLSearchParams({ tenant: TENANT, ...o }).toString();
const post = (path: string, body: object) =>
  call<any>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tenant: TENANT, ...body }) });

export const api = {
  staff: () => call<Staff[]>(`/api/staff?${q({})}`),
  inbox: (as_user: string) => call<{ tickets: any[]; now: number; can_see_customers: boolean }>(`/api/inbox?${q({ as_user })}`),
  trace: (ref: string, as_user: string) => call<any>(`/api/trace?${q({ ref, as_user })}`),
  impact: () => call<any>(`/api/impact?${q({})}`),
  promises: (as_user: string) => call<any>(`/api/promises?${q({ as_user })}`),
  agent: (agent: string, task: string, as_user: string) => post("/api/agent", { agent, task, as_user }) as Promise<Run>,
  confirm: (name: string, args: any, as_user: string) => post("/api/confirm", { name, args, as_user }) as Promise<Answer>,
  exportCustomer: (ref: string, as_user: string) => call<Answer>(`/api/privacy/export?${q({ ref, as_user })}`),
  deleteCustomer: (ref: string, as_user: string) => post("/api/privacy/delete", { ref, as_user }) as Promise<Answer>,
  reset: () => call<any>(`/api/demo/reset?${q({})}`, { method: "POST" }),
  liveScan: () => call<any>(`/api/demo/live-scan?${q({})}`, { method: "POST" }),
};

export function ago(at: number | null | undefined, now: number): string {
  if (!at) return "—";
  const h = (now - at) / 3600;
  if (h < 0) return `in ${fmtSpan(-h)}`;
  if (h < 1) return "just now";
  return `${fmtSpan(h)} ago`;
}

export function fmtSpan(hours: number): string {
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} days`;
}

export function day(at: number): string {
  return new Date(at * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
}

export const money = (n: number | null | undefined) => (n == null ? "—" : `$${n.toFixed(2)}`);
export const pct = (n: number | null | undefined) => (n == null ? "—" : `${Math.round(n * 100)}%`);
