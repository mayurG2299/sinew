"""Company documents each made-up store allows Sinew to read (a shared drive folder, in a real company).

Each passage becomes one `doc.passage` event and goes through the same pipeline as everything else: the text is
redacted, and the passage is linked in the graph to what it is about (`mentions`: hubs, couriers, decisions,
campaigns), so an answer that touches Hub W2 can show the passages about Hub W2 as its sources.
Documents name roles, not people. Facts match the simulated data (limits, dates, capacities, thresholds).
"""

from sinew.sim.northwind import DAY, NOW


def at(day: float) -> int:
    return NOW + int(day * DAY)


# doc id, title, kind, written (day), audience (None = all staff), [(heading, text, mentions)]
NORTHWIND = [
    ("doc-refund-policy", "Refund policy", "policy", -120, None, [
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
    ("doc-delivery-standard", "Delivery standard: west region", "policy", -40, None, [
        ("What we tell west customers",
         "Orders in the west region are delivered within 2 days. This standard relies on Courier Y running Hub W2 "
         "on time; it was set after the courier switch.", ["dec-2day-west", "hub-w2", "courier-y", "dec-courier-y"]),
        ("When a parcel is late",
         "If a parcel misses its 2-day date, give the customer a new date the same day. If it is more than 24 hours "
         "late, tell your team lead; if more than 10 parcels at one hub are late, the team lead opens an incident "
         "for logistics.", ["dec-2day-west"]),
    ]),
    ("doc-courier-y-agreement", "Courier Y agreement (summary)", "contract", -62, ["support_head", "logistics_manager",
                                                                                 "ceo", "analyst", "team_lead"], [
        ("Service level",
         "Courier Y runs all west deliveries through Hub W2 and commits to at least 90% of parcels on time each week. "
         "Hub W2 is rated for 14 parcels a day.", ["courier-y", "hub-w2", "dec-courier-y"]),
        ("Cost and review",
         "The rate is 12% below the previous courier. The agreement is reviewed after 60 days; if on-time delivery is "
         "below 90% for two weeks in a row, we can end it with 14 days' notice.", ["courier-y", "dec-courier-y"]),
    ]),
    ("doc-ops-notes-0818", "Operations meeting notes, 18 Aug", "meeting_notes", -60, None, [
        ("Decision: move west deliveries to Courier Y",
         "Agreed to move west deliveries to Courier Y to cut delivery cost by about 12%. Owner: the logistics "
         "manager. Assumption recorded: Courier Y delivers at least 90% on time through Hub W2.",
         ["dec-courier-y", "courier-y", "hub-w2"]),
        ("Risk raised",
         "Support asked what happens in sale weeks, because Hub W2 handles only 14 parcels a day. Answer: the backup "
         "courier covers peaks for now. Follow-up: review the backup contract in September.",
         ["hub-w2", "dec-drop-backup"]),
    ]),
    ("doc-ops-notes-0917", "Operations meeting notes, 17 Sep", "meeting_notes", -30, None, [
        ("Decision: end the backup courier contract",
         "With Courier Y on target in its first weeks, the west backup courier contract ends. Assumption recorded: "
         "Hub W2 alone can carry west volume. Peaks are to be planned with marketing before each sale.",
         ["dec-drop-backup", "hub-w2", "courier-y"]),
    ]),
    ("doc-plan-fest40", "Festive Flash Sale plan", "plan", -12, None, [
        ("The offer",
         "40% off kitchen products for west customers with the code FEST40, from 7 October. Expected lift: about 60% "
         "more west orders during the sale.", ["fest40", "dec-flash-sale"]),
        ("Delivery check",
         "Assumption: hubs can handle the sale volume within daily capacity. Delivery capacity was not reviewed with "
         "logistics before launch.", ["fest40", "dec-flash-sale", "hub-w2"]),
    ]),
    ("doc-plan-winter25", "Winter Sale plan", "plan", -2, None, [
        ("The offer",
         "25% off home products for west customers from 27 October, ten days of sale. West parcels go through "
         "Hub W2.", ["winter25", "dec-winter-sale", "hub-w2"]),
        ("Delivery check",
         "Assumption: Hub W2 can carry the Winter Sale volume. To be confirmed with logistics a week before launch.",
         ["winter25", "dec-winter-sale", "hub-w2"]),
    ]),
]

LARKSPUR = [
    ("doc-ls-refund-policy", "Refund policy", "policy", -200, None, [
        ("Who can approve a refund",
         "Care agents may refund up to $80. The care lead approves up to $400; above that, the head of operations.",
         []),
        ("Late deliveries",
         "If an order is more than a day late, apologise and offer free shipping on the next order.", []),
    ]),
    ("doc-ls-courier-q", "Courier Q agreement (summary)", "contract", -42, None, [
        ("Service level",
         "Courier Q handles all east deliveries through Hub E2 and commits to 92% on time. Hub E2 is rated for 10 "
         "parcels a day.", ["courier-q", "hub-e2", "dec-courier-q"]),
    ]),
    ("doc-ls-ops-notes", "Operations notes, 7 Sep", "meeting_notes", -40, None, [
        ("Decision: move east deliveries to Courier Q",
         "Agreed to move east deliveries to Courier Q for a lower rate. Assumption: Courier Q delivers 92% on time "
         "through Hub E2. Review after one month.", ["dec-courier-q", "courier-q", "hub-e2"]),
    ]),
]


def events(tenant: str) -> list[dict]:
    docs = {"northwind": NORTHWIND, "larkspur": LARKSPUR}.get(tenant, [])
    out = []
    for doc_id, title, kind, day, audience, passages in docs:
        for n, (heading, text, mentions) in enumerate(passages, 1):
            payload = {"doc_id": doc_id, "title": title, "kind": kind, "passage_id": f"{doc_id}-{n}",
                       "heading": heading, "order": n, "text": text, "mentions": mentions}
            if audience:
                payload["audience"] = audience
            out.append({"event_id": f"{doc_id}-{n}", "type": "doc.passage", "source": "docs",
                        "occurred_at": at(day), "payload": payload})
    return out
