from fastapi import FastAPI

from sinew import config
from sinew.db import graph

app = FastAPI(title="Sinew", version="0.1.0")


@app.get("/api/health")
def health(tenant: str = "northwind"):
    rows = graph(tenant).ro_query("MATCH (n) RETURN count(n) AS nodes").result_set
    return {
        "ok": True,
        "tenant": tenant,
        "nodes": rows[0][0],
        "graph_host": "local" if config.FALKORDB_HOST == "localhost" else "cloud",
    }
