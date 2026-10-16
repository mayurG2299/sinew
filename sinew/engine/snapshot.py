"""Snapshot refill: export a tenant graph to JSON, rebuild it with bulk UNWIND writes in seconds.

Why: the free cloud instance can restart or be wiped, and replaying every event takes minutes, too long
for one Vercel function (300 s). The snapshot is made by the loader after a full replay and a passing
privacy scan, so it is the same graph the pipeline produced.

Why not Redis DUMP/RESTORE: on FalkorDB 4.22.0, DUMP of a graph whose full-text index holds data crashes
the server (signal 11 in Index_SetLanguage), reproduced locally and on the cloud on 2026-10-16. JSON is
also independent of the FalkorDB version, so a cloud upgrade can't break the refill.

Every node has exactly one label and an `id`, which makes the export lossless.
"""

import gzip
import json
import time
from collections import defaultdict
from pathlib import Path

from sinew import schema
from sinew.db import client, graph

SNAPSHOTS = Path(__file__).resolve().parents[2] / "seed" / "snapshot"
CHUNK = 2000


def path(tenant: str) -> Path:
    return SNAPSHOTS / f"{tenant}.json.gz"


def export(tenant: str) -> dict:
    g = graph(tenant)
    nodes = g.ro_query("MATCH (n) RETURN labels(n)[0], properties(n)").result_set
    edges = g.ro_query(
        "MATCH (a)-[r]->(b) RETURN labels(a)[0], a.id, type(r), properties(r), labels(b)[0], b.id").result_set
    return {"version": 1, "nodes": [[label, props] for label, props in nodes],
            "edges": [list(e) for e in edges]}


def save(tenant: str) -> int:
    """Stamp a version into the graph, then export it. The stamp travels with the snapshot."""
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    version = f"{tenant}-{int(time.time())}"
    graph(tenant).query("MERGE (m:Meta {id: 'snapshot'}) SET m.version = $v", {"v": version})
    data = gzip.compress(json.dumps(export(tenant), separators=(",", ":")).encode())
    path(tenant).write_bytes(data)
    path(tenant).with_suffix(".version").write_text(version)
    return len(data)


def graph_version(tenant: str) -> str | None:
    rows = graph(tenant).ro_query("MATCH (m:Meta {id: 'snapshot'}) RETURN m.version").result_set
    return rows[0][0] if rows else None


def restore(tenant: str) -> bool:
    """Rebuild the tenant graph from its snapshot (replaces whatever is there). False if no snapshot."""
    if not path(tenant).exists():
        return False
    snap = json.loads(gzip.decompress(path(tenant).read_bytes()))
    if tenant in client().list_graphs():
        graph(tenant).delete()
    schema.apply(tenant)  # indexes first, so the edge MATCHes below are index lookups
    g = graph(tenant)
    g.query("MATCH (s:_Schema) DELETE s")  # recreated from the snapshot itself
    by_label = defaultdict(list)
    for label, props in snap["nodes"]:
        by_label[label].append(props)
    for label, rows in by_label.items():
        for i in range(0, len(rows), CHUNK):
            g.query(f"UNWIND $rows AS p CREATE (n:{label}) SET n = p", {"rows": rows[i:i + CHUNK]})
    by_shape = defaultdict(list)
    for la, a, rel, props, lb, b in snap["edges"]:
        by_shape[(la, rel, lb)].append({"a": a, "b": b, "p": props})
    for (la, rel, lb), rows in by_shape.items():
        for i in range(0, len(rows), CHUNK):
            g.query(f"UNWIND $rows AS r MATCH (a:{la} {{id: r.a}}), (b:{lb} {{id: r.b}}) "
                    f"CREATE (a)-[e:{rel}]->(b) SET e = r.p", {"rows": rows[i:i + CHUNK]})
    return True


def ensure_loaded(tenant: str) -> str:
    """Called before serving a tenant. Refill from the snapshot if the graph is gone, or if it is a different
    version: the free cloud instance can restart and come back with an older copy (seen 2026-10-16)."""
    expected = path(tenant).with_suffix(".version")
    if tenant in client().list_graphs():
        if not expected.exists() or graph_version(tenant) == expected.read_text():
            return "present"
    return "restored" if restore(tenant) else "missing"
