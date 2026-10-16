from fastapi import FastAPI

from sinew import config
from sinew.db import graph

app = FastAPI(title="Sinew", version="0.1.0")


@app.get("/api/health")
def health(tenant: str = "northwind"):
    g = graph(tenant)
    exists = tenant in g.client.list_graphs()  # a graph only exists after its first write
    nodes = g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0] if exists else 0
    return {
        "ok": True,
        "tenant": tenant,
        "nodes": nodes,
        "graph_host": "local" if config.FALKORDB_HOST == "localhost" else "cloud",
    }
