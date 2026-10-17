"""Every action a person can take in the portal, through the same API the buttons call (no AI calls)."""

import pytest
from fastapi.testclient import TestClient

from sinew import config
from sinew.main import app

T = "sandbox"


@pytest.fixture(scope="module")
def api(northwind_copy, monkeypatch_module):
    monkeypatch_module.setattr(config, "TENANTS", (*config.TENANTS,))
    return TestClient(app)


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def get(api, path, **params):
    r = api.get(path, params={"tenant": T, **params})
    assert r.status_code == 200, r.text
    return r.json()


def post(api, path, body=None, **params):
    r = api.post(path, params={"tenant": T, **params}, json={"tenant": T, **(body or {})})
    assert r.status_code == 200, r.text
    return r.json()


def test_switching_person_changes_what_the_inbox_shows(api):
    west = get(api, "/api/inbox", as_user="u-agent-w1")["tickets"]
    north = get(api, "/api/inbox", as_user="u-agent-n1")["tickets"]
    assert west and north and {t["region"] for t in west} == {"west"} and {t["region"] for t in north} == {"north"}
    assert get(api, "/api/inbox", as_user="u-marketing")["tickets"] == []
    contractor = get(api, "/api/inbox", as_user="u-contractor-1")["tickets"]
    assert contractor and {t["queue"] for t in contractor} == {"q-overflow"}


def test_contractor_trace_hides_other_queues_tickets(api):
    ticket = get(api, "/api/inbox", as_user="u-contractor-1")["tickets"][0]["ticket"]
    t = get(api, "/api/trace", ref=ticket, as_user="u-contractor-1")["trace"]
    shown = [i for i in t["data"]["timeline"] if i["kind"] == "ticket"]
    lead = get(api, "/api/trace", ref=ticket, as_user="u-lead-west")["trace"]
    all_tickets = [i for i in lead["data"]["timeline"] if i["kind"] == "ticket"]
    hidden = sum(h.get("count", 0) for h in t["hidden"] if h.get("kind") == "ticket")
    assert len(shown) + hidden == len(all_tickets)


def test_opening_a_ticket_builds_the_trace_with_freshness(api):
    v = get(api, "/api/trace", ref="t-90520", as_user="u-agent-w1")
    assert v["trace"]["outcome"] == "answered_path" and v["open_loops"] and v["related"]["outcome"] == "answered_path"
    assert all(f["last_event_at"] <= v["now"] for f in v["freshness"])  # nothing from the future


def test_opening_someone_elses_ticket_explains_why_not(api):
    v = get(api, "/api/trace", ref="t-90520", as_user="u-agent-n1")
    assert v["trace"]["outcome"] == "not_permitted" and "region" in v["trace"]["reason"]


def test_decision_impact_page(api):
    v = get(api, "/api/impact")
    assert v["clusters"]["data"]["clusters"][0]["root_hub"] == "hub-w2"
    assert v["impact"]["data"]["decision"] == "dec-courier-y"
    assert v["prelaunch"]["data"]["warnings"][0]["campaign"] == "winter25"
    assert all(p["ticket"] for p in v["impact"]["data"]["promises_at_risk"])  # every row links to its ticket


def test_confirming_prepared_actions(api):
    small = post(api, "/api/confirm", {"name": "issue_refund", "args": {"order_id": "o-4500", "amount": 5},
                                       "as_user": "u-agent-w1"})
    assert small["outcome"] == "answered_path"
    big = post(api, "/api/confirm", {"name": "issue_refund", "args": {"order_id": "o-4500", "amount": 150},
                                     "as_user": "u-agent-w1"})
    assert big["outcome"] in ("needs_approval", "not_permitted")
    inc = post(api, "/api/confirm", {"name": "file_incident", "args": {"title": "W2", "ticket_ids": ["t-90520"],
                                     "root_hub": "hub-w2"}, "as_user": "u-agent-w1"})
    assert inc["outcome"] == "not_permitted"  # agents can't file incidents, even when the AI prepared one
    r = api.post("/api/confirm", json={"tenant": T, "name": "delete_customer", "args": {}, "as_user": "u-sup-head"})
    assert r.status_code == 400  # privacy actions can't be confirmed through the AI path


def test_promises_board_scope(api):
    mine = get(api, "/api/promises", as_user="u-agent-w1")
    team = get(api, "/api/promises", as_user="u-lead-west")
    assert mine["scope"] == "mine" and {p["owner"] for p in mine["promises"]} <= {"u-agent-w1"}
    assert team["scope"] == "team" and len(team["promises"]) >= len(mine["promises"])


def test_privacy_export_and_delete(api):
    assert get(api, "/api/privacy/export", ref="t-95397", as_user="u-agent-w1")["outcome"] == "not_permitted"
    exported = get(api, "/api/privacy/export", ref="t-95397", as_user="u-sup-head")
    assert exported["outcome"] == "answered_path" and exported["data"]["graph_holds"]
    deleted = post(api, "/api/privacy/delete", {"ref": "t-95397", "as_user": "u-sup-head"})
    assert deleted["data"]["proof"]["nodes_left_with_their_ids"] == 0


def test_live_scan_and_reset(api, tmp_path):
    before = get(api, "/api/trace", ref="t-90520", as_user="u-agent-w1")
    r = post(api, "/api/demo/live-scan", None, shipment="sh-o-4520")
    assert r["accepted"] == 1 and {"signal": "late_scan", "shipment": "sh-o-4520", "hub": "hub-w2"} in r["signals"]
    assert api.post("/api/demo/live-scan", params={"tenant": T, "shipment": "sh-nope"}).status_code == 404
    after = get(api, "/api/trace", ref="t-90520", as_user="u-agent-w1")
    assert after["now"] > before["now"]
    assert sum(1 for i in after["trace"]["data"]["timeline"] if i["kind"] == "scan") == \
        sum(1 for i in before["trace"]["data"]["timeline"] if i["kind"] == "scan") + 1
    assert post(api, "/api/demo/reset", None)["restored"] == T
    assert get(api, "/api/trace", ref="t-90520", as_user="u-agent-w1")["now"] == before["now"]
