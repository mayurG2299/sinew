"""Indexes and constraints for one tenant graph. Safe to run any number of times."""

from sinew.db import graph

# Every node label is looked up by `id` (events by their source event id).
ID_LABELS = [
    "User", "Team", "Role", "Region", "Queue", "Purpose",
    "Customer", "Profile", "Identifier", "PersonalRef",
    "Order", "LineItem", "Product", "Batch", "Supplier", "Warehouse", "Payment", "Refund", "Return",
    "Shipment", "Courier", "Hub", "Scan",
    "Ticket", "IssueType", "Promise", "Incident", "Doc",
    "Campaign", "Coupon",
    "Decision", "Assumption", "Evidence",
    "Finding", "AgentRun", "Access", "Tombstone",
]
# Extra lookups that queries filter on.
RANGE = [("Identifier", "hash"), ("Order", "placed_at"), ("Scan", "at"), ("Ticket", "at"), ("Shipment", "last_hub"), ("Shipment", "status"),
         ("Promise", "due_at"), ("Campaign", "starts")]
FULLTEXT = [("Ticket", "summary_clean")]


def _existing_indexes(g) -> set[tuple[str, str]]:
    rows = g.ro_query("CALL db.indexes() YIELD label, properties RETURN label, properties").result_set
    return {(label, prop) for label, props in rows for prop in props}


def apply(tenant: str) -> dict:
    g = graph(tenant)
    g.query("MERGE (:_Schema {id: 'v1'})")  # a graph exists only after its first write
    have = _existing_indexes(g)
    created = 0
    for label, prop in [(l, "id") for l in ID_LABELS] + RANGE:
        if (label, prop) not in have:
            g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
            created += 1
    for label, prop in FULLTEXT:
        try:
            g.query(f"CALL db.idx.fulltext.createNodeIndex('{label}', '{prop}')")
            created += 1
        except Exception as e:  # already exists
            if "already" not in str(e).lower():
                raise
    constraints = 0
    for label in ID_LABELS:
        try:
            g.client.connection.execute_command(
                "GRAPH.CONSTRAINT", "CREATE", tenant, "UNIQUE", "NODE", label, "PROPERTIES", "1", "id")
            constraints += 1
        except Exception as e:
            if "already" not in str(e).lower():
                raise
    return {"tenant": tenant, "indexes_created": created, "constraints_created": constraints}


if __name__ == "__main__":
    import sys
    for t in sys.argv[1:] or ["northwind"]:
        print(apply(t))
