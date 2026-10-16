"""Identity merge: one Customer per group of channel profiles that share a hashed email, phone or handle.

FalkorDB's WCC (weakly connected components) over Profile -HAS-> Identifier finds the groups. The customer
id is derived from the group's smallest profile id, so it stays stable across reloads, and when two groups
join (a new identifier links them) one id survives and the other customer node is removed.

Production note: a shared family phone would merge two people. The real product shows such merges as
"possible match" for a person to confirm; the demo data has no shared phones.
"""

from sinew.db import graph


def merge(tenant: str) -> dict:
    g = graph(tenant)
    rows = g.ro_query(
        "CALL algo.WCC({nodeLabels: ['Profile', 'Identifier'], relationshipTypes: ['HAS']}) "
        "YIELD node, componentId "
        "WITH componentId, collect(CASE WHEN node:Profile THEN node.id END) AS raw "
        "WITH [p IN raw WHERE p IS NOT NULL] AS profiles WHERE size(profiles) > 0 "
        "RETURN profiles"
    ).result_set
    groups = [sorted(r[0]) for r in rows]
    links = [{"customer": "cu-" + group[0].removeprefix("pf-"), "profile": p} for group in groups for p in group]
    # Point every profile at its customer; drop links that no longer hold.
    g.query(
        "UNWIND $links AS l "
        "MATCH (p:Profile {id: l.profile}) "
        "MERGE (c:Customer {id: l.customer}) "
        "WITH p, c OPTIONAL MATCH (p)-[old:OF]->(other:Customer) WHERE other <> c DELETE old "
        "WITH p, c MERGE (p)-[:OF]->(c)",
        {"links": links},
    )
    # Customer facts come from its profiles (no personal fields involved).
    g.query(
        "MATCH (c:Customer)<-[:OF]-(p:Profile) "
        "WITH c, min(p.since) AS since, collect(p.region) AS regions, "
        "     max(CASE p.tier WHEN 'gold' THEN 1 ELSE 0 END) AS gold, count(p) AS n "
        "SET c.since = since, c.region = regions[0], c.tier = CASE gold WHEN 1 THEN 'gold' ELSE 'standard' END, "
        "    c.profiles = n"
    )
    g.query("MATCH (c:Customer)-[r:IN]->() DELETE r")
    g.query("MATCH (c:Customer) MERGE (r:Region {id: c.region}) MERGE (c)-[:IN]->(r)")
    removed = g.query("MATCH (c:Customer) WHERE NOT (c)<-[:OF]-(:Profile) DELETE c RETURN count(c)").result_set[0][0]
    return {"customers": len(groups), "profiles": len(links), "removed": removed}
