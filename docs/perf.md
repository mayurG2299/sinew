# Speed pass: what we measured and what changed

Measured with FalkorDB's own `GRAPH.PROFILE` and internal query timing (median of 30 runs, no network), on
FalkorDB 4.22.0 locally. "Rows" is the most rows any single plan step produced: the work a query does, which is
what grows with a company's data. Reproduce: `SINEW_LOCAL=1 uv run python -m sinew.perf northwind after` and
`SINEW_LOCAL=1 uv run python -m sinew.scale` (10× history, 59,587 nodes, 133,354 edges).

## Honest summary
- At demo size (6,736 nodes, 13,803 edges) **every query already runs in under 1 ms** inside FalkorDB. Page time
  is Python and round trips, not the graph.
- So the pass targeted **work per query** (rows touched), which is what decides speed as data grows, and one page
  that did hundreds of round trips.

## Changes and their effect

| Change (rule from FalkorDB's "Write effective Cypher queries" talk) | Before | After |
|---|---|---|
| **Inbox: one query along the permission path** instead of a permission check per ticket | 23.2 ms page | **4.9 ms** page |
| Inbox query at 10× history | 1,880 rows, 4.8 ms | **1,070 rows, 2.3 ms** |
| **Index what you filter on**: parcels by `last_hub` and `status` (customers waiting at a hub, 10×) | 6,000 rows (label scan) | **230 rows** |
| **Bind both ends first**, then check the path (Expand Into): permission check, largest region, 10× | 0.28 ms | **0.17 ms** |
| **Start from the small side**: on-time check starting from the 7-day window | 594 rows | 594 rows: no change. FalkorDB's planner already used the date index; the rewrite is kept only because it states the intent |

## Every main query after the pass (demo size)

| Query | ms | rows |
|---|---|---|
| permission: team covers customer's region | 0.12 | 1 |
| resolve customer from a ticket | 0.07 | 1 |
| trace: orders with items and batches | 0.23 | 6 |
| trace: parcels and courier scans | 0.18 | 13 |
| trace: tickets | 0.15 | 4 |
| related issues via the same hub/courier/batch | 0.16 | 328 |
| decisions behind a hub, with evidence | 0.20 | 2 |
| impact: customers waiting on parcels at the hub | 0.36 | 12 |
| keystone decisions (PageRank) | 0.09 | 5 |
| approver up the reporting line (SPpaths) | 0.03 | 12 |
| choke points (betweenness) | 0.26 | 8 |
| assumption check: courier on-time at a hub | 0.73 | 594 |
| inbox: newest tickets this person may see | 0.43 | 107 |
| full-text ticket search | 0.06 | 11 |

Full plans with per-step timings: `docs/perf-northwind-before.json`, `docs/perf-northwind-after.json`,
`docs/perf-sandbox-scale-before.json`, `docs/perf-sandbox-scale-after.json`.

## Things FalkorDB taught us on the way (for the README and blog)
- **`RESULTSET_SIZE` is 10,000 by default**: a query silently returns at most 10,000 rows. Our snapshot export
  and privacy scan were cut off until every large read went through paged reads (`sinew/db.py read_all`).
- **`DUMP` of a graph with a populated full-text index crashed FalkorDB 4.22.0** (SIGSEGV in
  `Index_SetLanguage`), locally and on the cloud. Snapshots are JSON instead (`sinew/engine/snapshot.py`).
- **Label propagation on a "many tickets → one hub" graph leaves every ticket alone.** Projecting
  ticket-to-ticket links first (tickets sharing two or more places) gives real clusters.
- FalkorDB 4.22 has no `EXISTS { … }` subqueries and no pattern lists inside `WHERE`; `OPTIONAL MATCH` with a
  count does the same job.
