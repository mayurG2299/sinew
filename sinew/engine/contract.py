"""The data contract: every event type, every field it may carry, and that field's class.

Classes (ENGINE.md §3):
  B   business data            -> stored as is
  P0  direct identifier        -> never stored; the graph keeps only a PersonalRef pointer to the source record
  P1  matching identifier      -> stored only as a keyed hash (HMAC, one key per company), after normalising
  P2  activity / time          -> stored as is
  P3  free text                -> redacted; the raw text is never stored

A field that is not in the contract, or a missing required field, sends the event to quarantine.
Nothing is guessed.
"""

B, P0, P1, P2, P3 = "B", "P0", "P1", "P2", "P3"

# type -> {field: (class, required)}
CONTRACT: dict[str, dict[str, tuple[str, bool]]] = {
    # --- people who work at the company (staff are people too: names stay in the roster) ---
    "staff.upserted": {
        "user_id": (B, True), "team_id": (B, True), "role": (B, True),
        "refund_limit": (B, False), "reports_to": (B, False),
        "display_name": (P0, False), "email": (P0, False),
    },
    "team.upserted": {
        "team_id": (B, True), "name": (B, True), "covers_regions": (B, False), "queues": (B, False),
        "owns_categories": (B, False),
    },
    # --- catalogue and delivery network ---
    "supplier.upserted": {"supplier_id": (B, True)},
    "product.upserted": {"sku": (B, True), "category": (B, True), "title": (B, False)},
    "batch.upserted": {"batch_id": (B, True), "sku": (B, True), "supplier_id": (B, True), "made_at": (P2, False)},
    "courier.upserted": {"courier_id": (B, True), "name": (B, False)},
    "hub.upserted": {"hub_id": (B, True), "region": (B, True), "courier_id": (B, True), "capacity": (B, False)},
    "route.upserted": {"from_hub": (B, True), "to_hub": (B, True), "transit_h": (B, True), "capacity": (B, False)},
    "warehouse.upserted": {"warehouse_id": (B, True), "region": (B, True)},
    # --- customers (one record per channel profile) ---
    "profile.upserted": {
        "profile_id": (B, True), "channel": (B, True), "region": (B, True),
        "tier": (B, False), "since": (P2, False),
        "name": (P0, False), "address": (P0, False),
        "email": (P1, False), "phone": (P1, False), "handle": (P1, False), "country": (B, False),
    },
    "consent.updated": {"profile_id": (B, True), "purpose": (B, True), "granted": (B, True)},
    # --- commerce ---
    "order.placed": {
        "order_id": (B, True), "profile_id": (B, True), "placed_at": (P2, True), "status": (B, True),
        "currency": (B, True), "total": (B, True), "warehouse_id": (B, False), "coupon_code": (B, False),
        "lines": (B, True), "shipping_address": (P0, False),
    },
    "order.updated": {"order_id": (B, True), "status": (B, True)},
    "payment.captured": {"payment_id": (B, True), "order_id": (B, True), "method": (B, True), "amount": (B, True)},
    "refund.issued": {
        "refund_id": (B, True), "order_id": (B, True), "amount": (B, True), "status": (B, True),
        "approved_by": (B, False),
    },
    "return.created": {"return_id": (B, True), "line_id": (B, True), "reason": (B, False), "status": (B, True)},
    # --- delivery ---
    "shipment.created": {
        "shipment_id": (B, True), "order_id": (B, True), "courier_id": (B, True), "promised_at": (P2, True),
    },
    "scan.recorded": {
        "scan_id": (B, True), "shipment_id": (B, True), "hub_id": (B, True), "status": (B, True),
        "late_hours": (B, False),
    },
    # --- support ---
    "ticket.created": {
        "ticket_id": (B, True), "profile_id": (B, True), "channel": (B, True), "queue_id": (B, True),
        "issue_type": (B, False), "order_id": (B, False), "handled_by": (B, False), "text": (P3, True),
    },
    "ticket.updated": {"ticket_id": (B, True), "status": (B, True), "handled_by": (B, False)},
    # --- marketing ---
    "campaign.upserted": {
        "campaign_id": (B, True), "name": (B, True), "starts": (P2, True), "ends": (P2, True),
        "region": (B, True), "category": (B, False), "status": (B, True), "owner": (B, False),
        "coupon_codes": (B, False),
    },
    # --- decisions (from the decision log form, or meeting notes confirmed by a person) ---
    "decision.recorded": {
        "decision_id": (B, True), "title": (B, True), "made_at": (P2, True), "owner": (B, True),
        "chose_kind": (B, True), "chose_id": (B, True), "region": (B, False), "builds_on": (B, False),
        "status": (B, False), "doc_id": (B, False), "assumptions": (B, True),
    },
    # --- promises (proposed by the AI from the agent's own reply, confirmed by a person or an action) ---
    "promise.proposed": {
        "promise_id": (B, True), "ticket_id": (B, True), "order_id": (B, True), "kind": (B, True),
        "due_at": (P2, True), "made_by": (B, True), "amount": (B, False),
    },
    "promise.confirmed": {"promise_id": (B, True), "confirmed_by": (B, True)},
    # --- company documents the company allows Sinew to read, one event per passage; each in one area ---
    "doc.passage": {
        "doc_id": (B, True), "title": (B, True), "kind": (B, True), "passage_id": (B, True), "heading": (B, True),
        "order": (B, True), "text": (P3, True), "area": (B, True), "mentions": (B, False),
    },
    # --- who may read which area (support, operations, marketing, finance): set by the company's admin ---
    "access.policy": {"role": (B, True), "areas": (B, True)},
    # --- finance: cost lines from the finance system, readable only through the finance area ---
    "cost.recorded": {
        "cost_id": (B, True), "kind": (B, True), "subject_id": (B, True), "amount": (B, True),
        "currency": (B, True), "per": (B, False), "period_start": (P2, True), "period_end": (P2, True),
    },
    "promise.rejected": {"promise_id": (B, True), "rejected_by": (B, True)},
}

ASSUMPTION_FIELDS = {"assumption_id", "statement", "metric", "op", "threshold", "window_days",
                     "scope_hub", "scope_courier"}
PROMISE_KINDS = {"refund", "delivery"}
AREAS = {"company", "support", "operations", "marketing", "finance"}  # what a role can be allowed to read; company = all staff
COST_KINDS = {"courier_per_parcel", "campaign_spend"}

LINE_FIELDS = {"line_id", "sku", "batch_id", "qty", "price"}
