import json

from fastapi import FastAPI, HTTPException, Request

from sinew import config
from sinew.db import graph
from sinew.engine import pipeline, signing, snapshot

app = FastAPI(title="Sinew", version="0.1.0")


@app.get("/api/health")
def health(tenant: str = "northwind"):
    if tenant not in config.TENANTS:
        raise HTTPException(404, "unknown tenant")
    refill = snapshot.ensure_loaded(tenant)  # free instance can restart or come back older: refill if so
    g = graph(tenant)
    exists = tenant in g.client.list_graphs()  # a graph only exists after its first write
    nodes = g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0] if exists else 0
    return {
        "ok": True,
        "tenant": tenant,
        "nodes": nodes,
        "refill": refill,
        "version": snapshot.graph_version(tenant) if exists else None,
        "graph_host": "local" if config.FALKORDB_HOST == "localhost" else "cloud",
    }


@app.post("/api/ingest/{tenant}")
async def ingest(tenant: str, request: Request):
    if tenant not in config.TENANTS:
        raise HTTPException(404, "unknown tenant")
    body = await request.body()
    if not signing.verify(body, request.headers.get("X-Sinew-Timestamp"),
                          request.headers.get("X-Sinew-Signature")):
        raise HTTPException(401, "bad or expired signature")
    try:
        result = pipeline.process(tenant, json.loads(body)["events"])
    except (ValueError, KeyError, TypeError) as e:  # bad JSON or an event that doesn't fit the envelope
        raise HTTPException(400, f"malformed request: {e}")
    return result.as_dict()
