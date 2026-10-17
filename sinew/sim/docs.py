"""Company setup each made-up store gives Sinew: who may read which area, and the documents it allows Sinew to read.

Access policy: one `access.policy` event per role (support, operations, marketing, finance). A role with no
policy reads nothing. The company's admin sets this in Sinew; it is data, not code.

Documents: each passage becomes one `doc.passage` event in one area and goes through the same pipeline as
everything else: the text is redacted, and the passage is linked in the graph to what it is about (`mentions`).
Documents name roles, not people. Facts match the simulated data (limits, dates, capacities, thresholds, costs).
"""

from sinew.sim.northwind import DAY, NOW


def at(day: float) -> int:
    return NOW + int(day * DAY)


POLICY = {
    "northwind": {
        "agent": ["support", "operations"], "contractor": ["support"],
        "team_lead": ["support", "operations"], "support_head": ["support", "operations"],
        "logistics_manager": ["operations", "support"],
        "marketing_manager": ["marketing", "operations"], "cmo": ["marketing", "operations", "finance"],
        "analyst": ["support", "operations", "marketing"], "ceo": ["support", "operations", "marketing", "finance"],
    },
    "larkspur": {
        "agent": ["support", "operations"], "team_lead": ["support", "operations"],
        "logistics_manager": ["operations", "support"],
        "support_head": ["support", "operations", "marketing", "finance"],  # Larkspur's head of operations
    },
}

# doc id, title, kind, area, written (day), [(heading, text, mentions)]
NORTHWIND = [
    ("doc-refund-policy", "Refund policy", "policy", "support", -120, [
        ("Who can approve a refund",
         "Support agents may refund up to $100. Team leads approve up to $500. Anything above $500 goes to the head "
         "of support. If a refund is over your limit, Sinew sends it to the right person for approval.", []),
        ("How fast refunds must go out",
         "Once we tell a customer a refund is on its way, it must be issued within 3 working days. If we miss that "
         "date, apologise first, issue the refund the same day and add a 10% voucher for the next order.", []),
        ("Returns",
         "Damaged or wrong items can be returned within 30 days. The refund is issued once the return is received "
         "at the warehouse, or straight away for items under $40.", []),
    ]),
    ("doc-delivery-standard", "Delivery standard: west region", "policy", "support", -40, [
        ("What we tell west customers",
         "Orders in the west region are delivered within 2 days. This standard relies on Courier Y running Hub W2 "
         "on time; it was set after the courier switch.", ["dec-2day-west", "hub-w2", "courier-y", "dec-courier-y"]),
        ("When a parcel is late",
         "If a parcel misses its 2-day date, give the customer a new date the same day. If it is more than 24 hours "
         "late, tell your team lead; if more than 10 parcels at one hub are late, the team lead opens an incident "
         "for logistics.", ["dec-2day-west"]),
    ]),
    ("doc-courier-y-agreement", "Courier Y agreement (service terms)", "contract", "operations", -62, [
        ("Service level",
         "Courier Y runs all west deliveries through Hub W2 and commits to at least 90% of parcels on time each week. "
         "Hub W2 is rated for 14 parcels a day.", ["courier-y", "hub-w2", "dec-courier-y"]),
        ("Review and exit",
         "The agreement is reviewed after 60 days. If on-time delivery is below 90% for two weeks in a row, we can "
         "end it with 14 days' notice.", ["courier-y", "dec-courier-y"]),
    ]),
    ("doc-ops-notes-0818", "Operations meeting notes, 18 Aug", "meeting_notes", "operations", -60, [
        ("Decision: move west deliveries to Courier Y",
         "Agreed to move west deliveries to Courier Y to lower delivery cost (figures in the finance cost sheet). "
         "Owner: the logistics manager. Assumption recorded: Courier Y delivers at least 90% on time through Hub W2.",
         ["dec-courier-y", "courier-y", "hub-w2"]),
        ("Risk raised",
         "Support asked what happens in sale weeks, because Hub W2 handles only 14 parcels a day. Answer: the backup "
         "courier covers peaks for now. Follow-up: review the backup contract in September.",
         ["hub-w2", "dec-drop-backup"]),
    ]),
    ("doc-ops-notes-0917", "Operations meeting notes, 17 Sep", "meeting_notes", "operations", -30, [
        ("Decision: end the backup courier contract",
         "With Courier Y on target in its first weeks, the west backup courier contract ends. Assumption recorded: "
         "Hub W2 alone can carry west volume. Peaks are to be planned with marketing before each sale.",
         ["dec-drop-backup", "hub-w2", "courier-y"]),
    ]),
    ("doc-plan-fest40", "Festive Flash Sale plan", "plan", "marketing", -12, [
        ("The offer",
         "40% off kitchen products for west customers with the code FEST40, from 7 October to 19 October. Expected "
         "lift: about 60% more west orders during the sale.", ["fest40", "dec-flash-sale"]),
        ("Delivery check",
         "Assumption: hubs can handle the sale volume within daily capacity. Delivery capacity was not reviewed with "
         "logistics before launch.", ["fest40", "dec-flash-sale", "hub-w2"]),
    ]),
    ("doc-plan-winter25", "Winter Sale plan", "plan", "marketing", -2, [
        ("The offer",
         "25% off home products for west customers from 27 October, ten days of sale with the code WINTER25. West "
         "parcels go through Hub W2.", ["winter25", "dec-winter-sale", "hub-w2"]),
        ("Delivery check",
         "Assumption: Hub W2 can carry the Winter Sale volume. To be confirmed with logistics a week before launch.",
         ["winter25", "dec-winter-sale", "hub-w2"]),
    ]),
    ("doc-cost-sheet-q4", "Cost sheet, October", "finance", "finance", -5, [
        ("Delivery cost per parcel",
         "Courier X costs $4.80 per parcel, Courier Y $4.20 and Courier Z $5.10. Moving west deliveries to Courier Y "
         "saves about 12% per parcel.", ["courier-x", "courier-y", "courier-z", "dec-courier-y"]),
        ("Campaign spend",
         "The Festive Flash Sale (FEST40) has $3,500 of ad spend. The Winter Sale (WINTER25) has a $4,000 budget.",
         ["fest40", "winter25", "dec-flash-sale", "dec-winter-sale"]),
    ]),
]

LARKSPUR = [
    ("doc-ls-refund-policy", "Refund policy", "policy", "support", -200, [
        ("Who can approve a refund",
         "Care agents may refund up to $80. The care lead approves up to $400; above that, the head of operations.",
         []),
        ("Late deliveries",
         "If an order is more than a day late, apologise and offer free shipping on the next order.", []),
    ]),
    ("doc-ls-courier-q", "Courier Q agreement (service terms)", "contract", "operations", -42, [
        ("Service level",
         "Courier Q handles all east deliveries through Hub E2 and commits to 92% on time. Hub E2 is rated for 10 "
         "parcels a day.", ["courier-q", "hub-e2", "dec-courier-q"]),
    ]),
    ("doc-ls-ops-notes", "Operations notes, 7 Sep", "meeting_notes", "operations", -40, [
        ("Decision: move east deliveries to Courier Q",
         "Agreed to move east deliveries to Courier Q for a lower rate. Assumption: Courier Q delivers 92% on time "
         "through Hub E2. Review after one month.", ["dec-courier-q", "courier-q", "hub-e2"]),
    ]),
]


def events(tenant: str) -> list[dict]:
    out = [{"event_id": f"policy-{role}", "type": "access.policy", "source": "admin", "occurred_at": at(-150),
            "payload": {"role": role, "areas": areas}} for role, areas in POLICY.get(tenant, {}).items()]
    for doc_id, title, kind, area, day, passages in {"northwind": NORTHWIND, "larkspur": LARKSPUR}.get(tenant, []):
        for n, (heading, text, mentions) in enumerate(passages, 1):
            out.append({"event_id": f"{doc_id}-{n}", "type": "doc.passage", "source": "docs", "occurred_at": at(day),
                        "payload": {"doc_id": doc_id, "title": title, "kind": kind, "passage_id": f"{doc_id}-{n}",
                                    "heading": heading, "order": n, "text": text, "area": area,
                                    "mentions": mentions}})
    return out
