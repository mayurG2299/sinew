import { useEffect, useState } from "react";

type Health = { ok: boolean; tenant: string; nodes: number; graph_host: string };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then(setHealth)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main className="min-h-screen bg-stone-50 text-stone-900 p-8">
      <h1 className="text-2xl font-semibold">Sinew · company brain</h1>
      <p className="mt-1 text-stone-600">The connective tissue of your company.</p>
      <section className="mt-6 text-sm">
        {error && <p className="text-red-700">Graph unreachable: {error}</p>}
        {!error && !health && <p>Connecting to the graph…</p>}
        {health && (
          <p>
            Graph <b>{health.tenant}</b> ({health.graph_host}): {health.nodes} nodes
          </p>
        )}
      </section>
      <footer className="mt-12 text-xs text-stone-500">
        Brewed by <a className="underline" href="https://x.com/justletmebrew">Let Me Brew</a>
      </footer>
    </main>
  );
}
