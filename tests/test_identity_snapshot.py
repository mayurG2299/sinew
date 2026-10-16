import pytest

from sinew import schema
from sinew.db import client
from sinew.engine import pipeline, snapshot

T = "store2"


@pytest.fixture(autouse=True)
def fresh_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "SNAPSHOTS", tmp_path)
    if T in client().list_graphs():
        client().select_graph(T).delete()
    schema.apply(T)
    yield
    if T in client().list_graphs():
        client().select_graph(T).delete()


def profile(pid, **ids):
    return {"event_id": f"e-{pid}-{len(ids)}", "type": "profile.upserted", "source": "store", "occurred_at": 1,
            "payload": {"profile_id": pid, "channel": pid.split("-")[-1], "region": "west", "country": "GB", **ids}}


def customers():
    return dict(client().select_graph(T).ro_query(
        "MATCH (p:Profile)-[:OF]->(c:Customer) RETURN p.id, c.id ORDER BY p.id").result_set)


def test_profiles_sharing_an_identifier_become_one_customer():
    pipeline.process(T, [profile("pf-1-web", email="Sam@Example.com", phone="+44 7911 123456"),
                         profile("pf-1-chat", phone="07911 123456"),
                         profile("pf-2-web", email="other@example.com")])
    assert customers() == {"pf-1-chat": "cu-1-chat", "pf-1-web": "cu-1-chat", "pf-2-web": "cu-2-web"}


def test_a_new_link_joins_two_customers_and_removes_the_extra():
    pipeline.process(T, [profile("pf-1-web", email="sam@example.com"), profile("pf-2-chat", phone="07911 123456")])
    assert len(set(customers().values())) == 2
    # Later the web profile adds the same phone: one person after all.
    pipeline.process(T, [profile("pf-1-web", email="sam@example.com", phone="+447911123456")])
    assert set(customers().values()) == {"cu-1-web"}
    assert client().select_graph(T).ro_query("MATCH (c:Customer) RETURN count(c)").result_set == [[1]]


def test_snapshot_refills_a_wiped_graph():
    pipeline.process(T, [profile("pf-1-web", email="sam@example.com"), profile("pf-1-chat", email="SAM@example.com")])
    snapshot.save(T)  # adds the version stamp node, so count after saving
    before = client().select_graph(T).ro_query("MATCH (n) RETURN count(n)").result_set
    client().select_graph(T).delete()
    assert snapshot.ensure_loaded(T) == "restored"
    assert client().select_graph(T).ro_query("MATCH (n) RETURN count(n)").result_set == before
    assert snapshot.ensure_loaded(T) == "present"


def test_an_older_copy_is_replaced_by_the_snapshot():
    pipeline.process(T, [profile("pf-1-web", email="sam@example.com")])
    snapshot.save(T)
    g = client().select_graph(T)
    fingerprint = lambda: (g.ro_query("MATCH (n) UNWIND keys(n) AS k RETURN count(*)").result_set,
                           g.ro_query("MATCH ()-[r]->() UNWIND keys(r) AS k RETURN count(*)").result_set)
    before = fingerprint()
    # Simulate the instance coming back with an older copy: different stamp, a node missing.
    g.query("MATCH (m:Meta {id: 'snapshot'}) SET m.version = 'older'")
    g.query("MATCH (c:Customer) DETACH DELETE c")
    assert snapshot.ensure_loaded(T) == "restored"
    assert fingerprint() == before


def test_snapshot_keeps_more_rows_than_one_query_can_return():
    from sinew import db
    g = client().select_graph(T)
    g.query("UNWIND range(1, 12000) AS i CREATE (:Doc {id: 'd' + toString(i)})")  # more than RESULTSET_SIZE
    g.query("MATCH (d:Doc) WHERE d.id IN ['d1', 'd2'] WITH collect(d) AS ds "
            "UNWIND range(1, 11000) AS i WITH ds[0] AS a, ds[1] AS b, i CREATE (a)-[:CITES {n: i}]->(b)")
    snapshot.save(T)
    snapshot.restore(T)
    assert g.ro_query("MATCH (d:Doc) RETURN count(d)").result_set == [[12000]]
    assert g.ro_query("MATCH ()-[r:CITES]->() RETURN count(r)").result_set == [[11000]]
