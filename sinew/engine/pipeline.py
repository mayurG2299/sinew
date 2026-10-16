"""The entry pipeline: every event, from the SDK or a webhook, goes through these stages in order.

receive -> validate -> classify -> minimise -> upsert -> derive -> signal  (ENGINE.md §4)

Authentication happens before this (signed requests, see signing.py). Personal values exist only in
memory inside `_minimise`; what reaches the writers is already pseudonymous.
"""

import time
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from sinew.db import graph
from sinew.engine import derive, identity
from sinew.engine import assumptions
from sinew.engine.contract import ASSUMPTION_FIELDS, CONTRACT, LINE_FIELDS, P0, P1, P3, PROMISE_KINDS
from sinew.engine.writers import CHOOSABLE
from sinew.engine.minimise import keyed_hash, normalise, redact
from sinew.engine.writers import WRITERS, Ctx


class Event(BaseModel):
    event_id: str = Field(min_length=1)
    type: str
    source: str = Field(min_length=1)  # e.g. "store", "helpdesk", "courier"
    occurred_at: int  # when it happened (epoch seconds)
    source_updated_at: int | None = None  # version of the record at the source; defaults to occurred_at
    payload: dict


@dataclass
class Result:
    accepted: int = 0
    stale: int = 0
    quarantined: list[dict] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"accepted": self.accepted, "stale": self.stale,
                "quarantined": self.quarantined, "signals": self.signals}


class Rejected(Exception):
    pass


def _validate(ev: Event) -> dict:
    spec = CONTRACT.get(ev.type)
    if spec is None:
        raise Rejected(f"unknown event type {ev.type}")
    unknown = set(ev.payload) - set(spec)
    if unknown:
        raise Rejected(f"fields not in the contract: {sorted(unknown)}")  # drift: hold, never guess
    missing = [f for f, (_, required) in spec.items() if required and ev.payload.get(f) in (None, "")]
    if missing:
        raise Rejected(f"missing required fields: {missing}")
    for line in ev.payload.get("lines", []) or []:
        if set(line) - LINE_FIELDS or not {"line_id", "sku", "qty", "price"} <= set(line):
            raise Rejected("order line does not match the contract")
    if ev.type == "decision.recorded":
        if ev.payload["chose_kind"] not in CHOOSABLE:
            raise Rejected(f"chose_kind must be one of {sorted(CHOOSABLE)}")
        if not ev.payload["assumptions"]:
            raise Rejected("a decision needs at least one assumption")
        for a in ev.payload["assumptions"]:
            if set(a) - ASSUMPTION_FIELDS or not {"assumption_id", "statement"} <= set(a):
                raise Rejected("assumption does not match the contract")
            why = assumptions.check_shape(a)
            if why:  # decision 4: an assumption must be machine-checkable before it can be saved
                raise Rejected(f"assumption {a['assumption_id']} is not checkable: {why}")
    if ev.type == "promise.proposed" and ev.payload["kind"] not in PROMISE_KINDS:
        raise Rejected(f"promise kind must be one of {sorted(PROMISE_KINDS)}")
    return spec


def _minimise(tenant: str, ev: Event, spec: dict, allow: frozenset[str] = frozenset()) -> tuple[dict, list, list]:
    clean, identifiers, personal = {}, [], []
    country = ev.payload.get("country")
    for name, value in ev.payload.items():
        cls = spec[name][0]
        if cls == P0:
            if value:
                personal.append(name)  # dropped; only a pointer to the source record is kept
        elif cls == P1:
            normalised = normalise(name, str(value), country) if value else None
            if normalised:
                identifiers.append((name, keyed_hash(tenant, name, normalised)))
        elif cls == P3:
            clean[name] = redact(str(value), allow)[:500]
        else:
            clean[name] = value
    return clean, identifiers, personal


def _quarantine(g, ev: Event, reason: str, now: int):
    # Only the event id, type and reason: the payload may hold personal data and is not stored.
    g.query(
        "MERGE (q:Quarantine {id: $id}) SET q.type = $type, q.source = $source, q.reason = $reason, q.at = $now",
        {"id": ev.event_id, "type": ev.type, "source": ev.source, "reason": reason, "now": now},
    )


def process(tenant: str, events: list[Event | dict]) -> Result:
    g = graph(tenant)
    result = Result()
    now = int(time.time())
    newest: dict[str, int] = {}
    allow: frozenset[str] | None = None  # product titles, read once per batch, only if a text field arrives
    for raw in events:
        ev = raw if isinstance(raw, Event) else Event.model_validate(raw)
        try:
            spec = _validate(ev)
        except Rejected as e:
            _quarantine(g, ev, str(e), now)
            result.quarantined.append({"event_id": ev.event_id, "reason": str(e)})
            continue
        if allow is None and any(c == P3 for c, _ in spec.values()):
            allow = frozenset(r[0].lower() for r in g.ro_query(
                "MATCH (p:Product) WHERE p.title IS NOT NULL RETURN p.title").result_set)
        clean, identifiers, personal = _minimise(tenant, ev, spec, allow or frozenset())
        c = Ctx(g=g, tenant=tenant, event_id=ev.event_id, source=ev.source, occurred_at=ev.occurred_at,
                sua=ev.source_updated_at or ev.occurred_at, now=now,
                identifiers=identifiers, personal_fields=personal)
        WRITERS[ev.type](c, clean)
        result.accepted += 1
        if c.stale:
            result.stale += 1  # older than what we hold: its properties were ignored, its links kept
        result.signals.extend(derive.run(c, ev.type, clean))
        newest[ev.source] = max(newest.get(ev.source, 0), ev.occurred_at)
    # A new or changed profile can join or split customers: rerun the merge once per batch.
    if any((e if isinstance(e, Event) else Event.model_validate(e)).type == "profile.upserted" for e in events) \
            and result.accepted:
        identity.merge(tenant)
    # Freshness watermark per source: what the UI's "data as of" badge reads.
    for source, at in newest.items():
        g.query(
            "MERGE (s:Source {id: $s}) SET s.last_event_at = CASE WHEN coalesce(s.last_event_at, 0) > $at "
            "THEN s.last_event_at ELSE $at END, s.last_received_at = $now",
            {"s": source, "at": at, "now": now},
        )
    return result
