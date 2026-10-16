"""Northwind Goods: a made-up global online store, generated as the events its systems would send.

Output (deterministic, seed 42):
  seed/events/northwind.jsonl         every event, in time order: what the SDK sends through the pipeline
  seed/source/northwind_personal.json the store's own copy of names, emails, phones and addresses.
                                      This is "their database": the graph never holds it; the mock
                                      store API serves it to allowed roles only.

The planted story (ENGINE.md §10d), with day 0 = the demo's "today":
  day -60  Ops switches the west region to Courier Y (assumes >= 90% on time at Hub W2)
  day -12  Marketing decides the Festive Flash Sale (assumes Hub W2 stays within capacity)
  day -10  the sale starts in the west with coupon FEST40; volume through W2 more than doubles
           Courier Y falls behind, late-delivery tickets pile up
  day -2   Marketing schedules the Winter Sale for the same region (the pre-launch check should flag it)
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import phonenumbers
from faker import Faker

DAY = 86_400
NOW = int(datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc).timestamp())  # the demo's "today"
ROOT = Path(__file__).resolve().parents[2] / "seed"

rng = random.Random(42)
fake = Faker(["en_US", "en_GB", "en_IN", "en_AU"])
Faker.seed(42)

events: list[dict] = []
personal: dict[str, dict] = {"Profile": {}, "User": {}, "Order": {}}
_n = 0


def at(day: float) -> int:
    return NOW + int(day * DAY)


def emit(type_: str, payload: dict, when: int, source: str = "store"):
    global _n
    _n += 1
    events.append({"event_id": f"nw-{_n:06d}", "type": type_, "source": source,
                   "occurred_at": when, "payload": payload})


# ------------------------------------------------------------------ staff and teams

TEAMS = [
    ("team-support-west", "Support West", ["west"], ["q-west"], []),
    ("team-support-north", "Support North", ["north"], ["q-north"], []),
    ("team-support-south", "Support South", ["south"], ["q-south"], []),
    ("team-contractor", "Overflow (contractor)", ["west"], ["q-overflow"], []),
    ("team-logistics", "Logistics", ["west", "north", "south"], [], []),
    ("team-marketing", "Marketing", ["west", "north", "south"], [], ["kitchen", "home"]),
    ("team-leadership", "Leadership", ["west", "north", "south"], [], []),
]
# user_id, team, role, refund limit, reports to, display name (personal: stays in the roster)
STAFF = [
    ("u-sup-head", "team-leadership", "support_head", 2000, "u-ceo", "Grace Okafor"),
    ("u-ceo", "team-leadership", "ceo", 0, None, "Daniel Reyes"),
    ("u-lead-west", "team-support-west", "team_lead", 500, "u-sup-head", "Meera Nair"),
    ("u-agent-w1", "team-support-west", "agent", 100, "u-lead-west", "Ravi Kumar"),
    ("u-agent-w2", "team-support-west", "agent", 100, "u-lead-west", "Anna Schmidt"),
    ("u-agent-n1", "team-support-north", "agent", 100, "u-sup-head", "Tom Becker"),
    ("u-agent-s1", "team-support-south", "agent", 100, "u-sup-head", "Sofia Rossi"),
    ("u-contractor-1", "team-contractor", "contractor", 0, "u-lead-west", "Karan Mehta"),
    ("u-logistics", "team-logistics", "logistics_manager", 0, "u-ceo", "Lucas Martin"),
    ("u-marketing", "team-marketing", "marketing_manager", 0, "u-ceo", "Chloe Dubois"),
    ("u-analyst", "team-marketing", "analyst", 0, "u-marketing", "Ken Watanabe"),
    ("u-agent-n2", "team-support-north", "agent", 100, "u-sup-head", "Li Wei"),
]
AGENTS = {"west": ["u-agent-w1", "u-agent-w2", "u-contractor-1"], "north": ["u-agent-n1", "u-agent-n2"], "south": ["u-agent-s1"]}
QUEUE = {"west": "q-west", "north": "q-north", "south": "q-south"}

# ------------------------------------------------------------------ catalogue and network

CATEGORIES = {"kitchen": ["Blender X", "Kettle Pro", "Air Fryer 5L", "Knife Set", "Coffee Grinder", "Toaster Duo",
                          "Rice Cooker", "Hand Mixer"],
              "home": ["Desk Lamp", "Throw Blanket", "Cushion Pair", "Wall Clock", "Storage Box", "Doormat",
                       "Bath Towels", "Plant Pot"],
              "audio": ["Earbuds Air", "Speaker Mini", "Headphones 700", "Soundbar S", "Radio Retro",
                        "Earbuds Sport", "Mic USB", "Turntable"],
              "fitness": ["Yoga Mat", "Dumbbell Pair", "Jump Rope", "Resistance Bands", "Foam Roller",
                          "Kettlebell 8kg", "Water Bottle", "Gym Bag"],
              "outdoor": ["Tent 2P", "Camping Stove", "Headlamp", "Sleeping Bag", "Trek Poles", "Cooler Box",
                          "Hammock", "Picnic Set"]}
PRICES = {"kitchen": (25, 140), "home": (12, 70), "audio": (20, 220), "fitness": (8, 90), "outdoor": (15, 260)}
SUPPLIERS = ["sup-s1", "sup-s2", "sup-s3", "sup-s4"]
COURIERS = ["courier-x", "courier-y", "courier-z"]
# hub, region, courier running it, capacity (parcels/day)
HUBS = [("hub-w1", "west", "courier-x", 12), ("hub-w2", "west", "courier-y", 14), ("hub-w4", "west", "courier-x", 10),
        ("hub-n1", "north", "courier-z", 10), ("hub-n2", "north", "courier-z", 8),
        ("hub-s1", "south", "courier-x", 10), ("hub-s2", "south", "courier-z", 8), ("hub-s3", "south", "courier-x", 6)]
ROUTES = [("hub-w1", "hub-w2", 10), ("hub-w2", "hub-w1", 10), ("hub-w1", "hub-w4", 14), ("hub-w4", "hub-w1", 14),
          ("hub-w2", "hub-w4", 6), ("hub-w4", "hub-w2", 6), ("hub-w1", "hub-n1", 30), ("hub-n1", "hub-n2", 8),
          ("hub-n2", "hub-n1", 8), ("hub-n1", "hub-s1", 36), ("hub-s1", "hub-s2", 9), ("hub-s2", "hub-s3", 7),
          ("hub-s3", "hub-s1", 12), ("hub-s1", "hub-w1", 40)]
WAREHOUSES = {"west": "wh-west", "north": "wh-north", "south": "wh-south"}
REGION_WEIGHTS = [("west", 0.45), ("north", 0.30), ("south", 0.25)]
COUNTRIES = ["US", "GB", "IN", "AU"]


def products():
    out = []
    for cat, names in CATEGORIES.items():
        for name in names:
            sku = name.lower().replace(" ", "-")
            lo, hi = PRICES[cat]
            out.append({"sku": sku, "category": cat, "title": name, "price": round(rng.uniform(lo, hi), 2)})
    return out


def phone_for(country: str) -> phonenumbers.PhoneNumber:
    for _ in range(50):
        example = phonenumbers.example_number_for_type(country, phonenumbers.PhoneNumberType.MOBILE)
        digits = str(example.national_number)
        candidate = digits[:3] + "".join(str(rng.randint(0, 9)) for _ in digits[3:])
        num = phonenumbers.parse(candidate, country)
        if phonenumbers.is_valid_number(num):
            return num
    return example


def pick_region():
    r, acc = rng.random(), 0.0
    for region, w in REGION_WEIGHTS:
        acc += w
        if r <= acc:
            return region
    return "south"


# ------------------------------------------------------------------ ticket text (templates; names inside on purpose)

TEMPLATES = {
    "late_delivery": [
        "Hi, my order {order} still hasn't arrived. Tracking says it's stuck. Can you check?",
        "This is {name}. Order {order} was due days ago and nothing. Please call me on {phone}.",
        "Where is my parcel? Order {order}. The courier keeps saying delayed.",
        "Order {order} is late again. I needed it this week. What is going on?",
    ],
    "damaged": ["The {product} from order {order} arrived broken. I want a replacement or refund.",
                "Box was crushed and the {product} doesn't work. Order {order}. Email me at {email}."],
    "refund_status": ["I returned my order {order} two weeks ago, where is my refund?",
                      "Still waiting for the refund on {order}. You said it would be done by now. - {name}"],
    "wrong_item": ["I got the wrong item in order {order}. I ordered a {product}."],
    "product_issue": ["My {product} stopped working after a few days. Order {order}.",
                      "The {product} makes a strange noise, is this normal? Order {order}."],
}


def ticket_text(kind, order_id, product, person):
    tpl = rng.choice(TEMPLATES[kind])
    return tpl.format(order=order_id, product=product, name=person["name"], phone=person["phone_display"],
                      email=person["email"])


# ------------------------------------------------------------------ build


def build():
    # Staff, teams, catalogue, network: set up at day -150.
    t0 = at(-150)
    for tid, name, regions, queues, cats in TEAMS:
        emit("team.upserted", {"team_id": tid, "name": name, "covers_regions": regions, "queues": queues,
                               "owns_categories": cats}, t0, "roster")
    for uid, team, role, limit, boss, display in STAFF:
        email = f"{display.split()[0].lower()}@northwind.example"
        personal["User"][uid] = {"display_name": display, "email": email}
        p = {"user_id": uid, "team_id": team, "role": role, "refund_limit": limit,
             "display_name": display, "email": email}
        if boss:
            p["reports_to"] = boss
        emit("staff.upserted", p, t0, "roster")
    for s in SUPPLIERS:
        emit("supplier.upserted", {"supplier_id": s}, t0, "catalogue")
    catalogue = products()
    batches = {}
    for prod in catalogue:
        emit("product.upserted", {"sku": prod["sku"], "category": prod["category"], "title": prod["title"]},
             t0, "catalogue")
        ids = []
        for k in range(rng.choice([1, 2])):
            bid = f"b-{prod['sku']}-{k + 1}"
            emit("batch.upserted", {"batch_id": bid, "sku": prod["sku"], "supplier_id": rng.choice(SUPPLIERS),
                                    "made_at": at(-200 + 40 * k)}, t0, "catalogue")
            ids.append(bid)
        batches[prod["sku"]] = ids
    # Batch B7 of Blender X from supplier S3: the bad batch the CEO case can find later.
    emit("batch.upserted", {"batch_id": "b7", "sku": "blender-x", "supplier_id": "sup-s3", "made_at": at(-90)},
         t0, "catalogue")
    batches["blender-x"].append("b7")
    for c in COURIERS:
        emit("courier.upserted", {"courier_id": c, "name": c.replace("courier-", "Courier ").title()}, t0, "ops")
    for hub, region, courier, cap in HUBS:
        # Until day -60, W2 was run by Courier X; the ops decision moves it to Courier Y.
        emit("hub.upserted", {"hub_id": hub, "region": region, "courier_id": "courier-x" if hub == "hub-w2" else courier,
                              "capacity": cap}, t0, "ops")
    for a, b, h in ROUTES:
        emit("route.upserted", {"from_hub": a, "to_hub": b, "transit_h": h, "capacity": 20}, t0, "ops")
    for region, wh in WAREHOUSES.items():
        emit("warehouse.upserted", {"warehouse_id": wh, "region": region}, t0, "ops")

    # ---- decisions
    emit("hub.upserted", {"hub_id": "hub-w2", "region": "west", "courier_id": "courier-y", "capacity": 14},
         at(-60), "ops", )
    emit("decision.recorded", {
        "decision_id": "dec-courier-y", "title": "Switch west region deliveries to Courier Y to cut cost",
        "made_at": at(-60), "owner": "u-logistics", "chose_kind": "Courier", "chose_id": "courier-y",
        "region": "west", "doc_id": "doc-ops-review-aug",
        "assumptions": [{"assumption_id": "as-courier-y-ontime",
                         "statement": "Courier Y delivers at least 90% on time through Hub W2",
                         "metric": "courier_on_time_rate", "op": ">=", "threshold": 0.9, "window_days": 7,
                         "scope_hub": "hub-w2", "scope_courier": "courier-y"}]}, at(-60), "decision-log")
    emit("decision.recorded", {
        "decision_id": "dec-2day-west", "title": "Promise 2-day delivery to west customers",
        "made_at": at(-40), "owner": "u-sup-head", "chose_kind": "Hub", "chose_id": "hub-w2", "region": "west",
        "builds_on": ["dec-courier-y"],
        "assumptions": [{"assumption_id": "as-2day-ontime", "statement": "West deliveries via W2 are 85% on time",
                         "metric": "courier_on_time_rate", "op": ">=", "threshold": 0.85, "window_days": 7,
                         "scope_hub": "hub-w2", "scope_courier": "courier-y"}]}, at(-40), "decision-log")
    emit("decision.recorded", {
        "decision_id": "dec-drop-backup", "title": "End the west backup courier contract",
        "made_at": at(-30), "owner": "u-logistics", "chose_kind": "Hub", "chose_id": "hub-w4", "region": "west",
        "builds_on": ["dec-courier-y"],
        "assumptions": [{"assumption_id": "as-w2-capacity", "statement": "Hub W2 alone can carry west volume",
                         "metric": "hub_load_ratio", "op": "<=", "threshold": 1.0, "window_days": 7,
                         "scope_hub": "hub-w2"}]}, at(-30), "decision-log")
    emit("campaign.upserted", {"campaign_id": "fest40", "name": "Festive Flash Sale", "starts": at(-10),
                               "ends": at(2), "region": "west", "category": "kitchen", "status": "running",
                               "owner": "u-marketing", "coupon_codes": ["FEST40"]}, at(-12), "marketing")
    emit("decision.recorded", {
        "decision_id": "dec-flash-sale", "title": "Run the Festive Flash Sale (40% off kitchen) in the west",
        "made_at": at(-12), "owner": "u-marketing", "chose_kind": "Campaign", "chose_id": "fest40",
        "region": "west", "doc_id": "doc-mkt-sync-oct",
        "assumptions": [{"assumption_id": "as-sale-capacity",
                         "statement": "Hubs can handle the sale volume within daily capacity",
                         "metric": "hub_load_ratio", "op": "<=", "threshold": 1.0, "window_days": 7,
                         "scope_hub": "hub-w2"}]}, at(-12), "decision-log")
    emit("campaign.upserted", {"campaign_id": "winter25", "name": "Winter Sale", "starts": at(10), "ends": at(20),
                               "region": "west", "category": "home", "status": "scheduled", "owner": "u-marketing",
                               "coupon_codes": ["WINTER25"]}, at(-2), "marketing")
    emit("decision.recorded", {
        "decision_id": "dec-winter-sale", "title": "Run the Winter Sale (25% off home) in the west",
        "made_at": at(-2), "owner": "u-marketing", "chose_kind": "Campaign", "chose_id": "winter25",
        "region": "west",
        "assumptions": [{"assumption_id": "as-winter-capacity", "statement": "Hub W2 can carry the Winter Sale volume",
                         "metric": "hub_load_ratio", "op": "<=", "threshold": 1.0, "window_days": 7,
                         "scope_hub": "hub-w2"}]}, at(-2), "decision-log")

    # ---- customers: 200 people, 320 channel profiles sharing phones/emails in different formats
    customers = []
    for i in range(200):
        country = rng.choice(COUNTRIES)
        first, last = fake.first_name(), fake.last_name()
        num = phone_for(country)
        person = {"name": f"{first} {last}", "country": country, "region": pick_region(),
                  "email": f"{first}.{last}{rng.randint(1, 99)}@example.com".lower(),
                  "phone_e164": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164),
                  "phone_display": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
                  "phone_national": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL),
                  "address": fake.address().replace("\n", ", "), "profiles": []}
        since = at(-rng.randint(65, 700))
        channels = ["web"] + rng.sample(["chat", "email", "social"], k=rng.choices([0, 1, 2], [80, 80, 40])[0])
        for ch in channels:
            pid = f"pf-{i:03d}-{ch}"
            p = {"profile_id": pid, "channel": ch, "region": person["region"], "country": country,
                 "since": since, "tier": rng.choice(["standard", "standard", "standard", "gold"])}
            if ch == "web":
                p.update({"name": person["name"], "email": person["email"], "phone": person["phone_e164"],
                          "address": person["address"]})
            elif ch == "chat":
                p.update({"phone": person["phone_national"]})  # same number, different format
            elif ch == "email":
                p.update({"email": person["email"].upper()})  # same email, different case
            else:
                p.update({"handle": f"@{first.lower()}{last[:2].lower()}{rng.randint(1, 9)}",
                          "phone": person["phone_display"]})
            personal["Profile"][pid] = {k: p.get(k) for k in ("name", "email", "phone", "address", "handle") if p.get(k)}
            emit("profile.upserted", p, since, "store" if ch == "web" else "helpdesk")
            person["profiles"].append(pid)
        if rng.random() < 0.04:  # about 3% agreed to marketing
            emit("consent.updated", {"profile_id": person["profiles"][0], "purpose": "marketing", "granted": True},
                 since + DAY, "store")
        customers.append(person)

    # ---- orders, payments, shipments, scans, tickets, refunds, returns, promises
    catalogue_by_cat = {}
    for prod in catalogue:
        catalogue_by_cat.setdefault(prod["category"], []).append(prod)
    order_days = sorted(rng.uniform(-30, -0.2) for _ in range(500))
    west_people = [c for c in customers if c["region"] == "west"]
    sale_days = sorted(rng.uniform(-10, -0.2) for _ in range(100))
    plans = [(d, rng.choice(customers), False) for d in order_days] + [(d, rng.choice(west_people), True) for d in sale_days]
    plans.sort(key=lambda x: x[0])
    # Parcels arriving at W2 per day (west orders arrive a day after they're placed). An overloaded day
    # slows every parcel that day, not just the ones after the limit.
    w2_load: dict[int, int] = {}
    for day, person, _ in plans:
        if person["region"] == "west":
            key = int(day + 1 + 10) - 10  # floor for negative days
            w2_load[key] = w2_load.get(key, 0) + 1
    stats = {"orders": 0, "tickets": 0, "late_w2": 0, "refunds": 0, "returns": 0, "promises": 0}
    for n, (day, person, sale) in enumerate(plans):
        oid = f"o-{4000 + n}"
        region = person["region"]
        cat = "kitchen" if sale else rng.choice(list(CATEGORIES))
        items = rng.sample(catalogue_by_cat[cat], k=rng.choice([1, 1, 1, 2]))
        lines, total = [], 0.0
        for k, prod in enumerate(items):
            price = round(prod["price"] * (0.6 if sale else 1.0), 2)
            batch = "b7" if prod["sku"] == "blender-x" and rng.random() < 0.5 else rng.choice(batches[prod["sku"]])
            lines.append({"line_id": f"{oid}-l{k + 1}", "sku": prod["sku"], "batch_id": batch, "qty": 1,
                          "price": price})
            total += price
        placed = at(day)
        web = person["profiles"][0]
        p = {"order_id": oid, "profile_id": web, "placed_at": placed, "status": "placed", "currency": "USD",
             "total": round(total, 2), "warehouse_id": WAREHOUSES[region], "lines": lines,
             "shipping_address": person["address"]}
        if sale:
            p["coupon_code"] = "FEST40"
        personal["Order"][oid] = {"shipping_address": person["address"]}
        emit("order.placed", p, placed, "store")
        emit("payment.captured", {"payment_id": f"pay-{oid}", "order_id": oid, "method": rng.choice(
            ["card", "card", "wallet", "cod"]), "amount": round(total, 2)}, placed + 60, "payments")
        stats["orders"] += 1

        # Route: west goes through W2 (Courier X before day -60, Courier Y after); others through their hubs.
        if region == "west":
            courier = "courier-y" if day >= -60 else "courier-x"
            path = ["hub-w1", "hub-w2"]
        elif region == "north":
            courier, path = "courier-z", ["hub-n1", rng.choice(["hub-n1", "hub-n2"])]
        else:
            courier, path = rng.choice(["courier-x", "courier-z"]), ["hub-s1", rng.choice(["hub-s2", "hub-s3"])]
        sid = f"sh-{oid}"
        promised = placed + 3 * DAY
        emit("shipment.created", {"shipment_id": sid, "order_id": oid, "courier_id": courier, "promised_at": promised},
             placed + 2 * 3600, "courier")
        arrive = placed + DAY
        late_hours = 0
        if path[-1] == "hub-w2" and courier == "courier-y":
            overloaded = w2_load.get(int(day + 1 + 10) - 10, 0) > 14
            if rng.random() < (0.32 if overloaded else 0.02):
                late_hours = rng.choice([18, 24, 30, 36, 48])
                stats["late_w2"] += 1
        elif rng.random() < 0.05:
            late_hours = rng.choice([12, 24])
        # Nothing is emitted after the demo's "now": a parcel that hasn't reached a hub yet has no scan there.
        if placed + 8 * 3600 < NOW:
            emit("scan.recorded", {"scan_id": f"{sid}-1", "shipment_id": sid, "hub_id": path[0],
                                   "status": "in_transit"}, placed + 8 * 3600, "courier")
        if arrive >= NOW:
            continue
        emit("scan.recorded", {"scan_id": f"{sid}-2", "shipment_id": sid, "hub_id": path[-1],
                               "status": "delayed" if late_hours else "in_transit", "late_hours": late_hours},
             arrive, "courier")
        delivered_at = arrive + DAY + late_hours * 3600
        delivered = delivered_at < NOW
        if delivered:
            emit("scan.recorded", {"scan_id": f"{sid}-3", "shipment_id": sid, "hub_id": path[-1],
                                   "status": "delivered"}, delivered_at, "courier")
            emit("order.updated", {"order_id": oid, "status": "delivered"}, delivered_at, "store")

        # Tickets: late parcels make people write in; some other issues at a base rate.
        kind = None
        if late_hours and rng.random() < 0.7:
            kind = "late_delivery"
        elif any(l["batch_id"] == "b7" for l in lines) and rng.random() < 0.35:
            kind = rng.choice(["product_issue", "damaged"])
        elif rng.random() < 0.26:
            kind = rng.choice(["damaged", "refund_status", "wrong_item", "product_issue"])
        if not kind:
            continue
        tid = f"t-{90000 + n}"
        t_at = min(arrive + rng.randint(4, 30) * 3600, NOW - 3600)
        if t_at < placed:
            continue
        channel_profiles = person["profiles"][1:] or person["profiles"]
        pf = rng.choice(channel_profiles)
        agent = rng.choice(AGENTS[region])
        emit("ticket.created", {"ticket_id": tid, "profile_id": pf, "channel": pf.rsplit("-", 1)[1],
                                "queue_id": "q-overflow" if agent == "u-contractor-1" else QUEUE[region],
                                "issue_type": kind, "order_id": oid, "handled_by": agent,
                                "text": ticket_text(kind, oid, items[0]["title"], person)}, t_at, "helpdesk")
        stats["tickets"] += 1

        # The agent's reply often contains a promise; the AI proposes it and the agent confirms most.
        promise_kind = {"late_delivery": "delivery", "damaged": "refund", "refund_status": "refund",
                        "wrong_item": "refund", "product_issue": "refund"}[kind]
        refund_amount = round(total, 2)
        will_refund = promise_kind == "refund" and rng.random() < 0.85
        if rng.random() < 0.55:
            prid = f"pr-{tid}"
            due = t_at + (2 if promise_kind == "delivery" else rng.choice([3, 5])) * DAY
            emit("promise.proposed", {"promise_id": prid, "ticket_id": tid, "order_id": oid, "kind": promise_kind,
                                      "due_at": due, "made_by": agent,
                                      "amount": refund_amount if promise_kind == "refund" else 0},
                 t_at + 1800, "sinew-ai")
            if rng.random() < 0.9:
                emit("promise.confirmed", {"promise_id": prid, "confirmed_by": agent}, t_at + 2000, "sinew-ai")
            stats["promises"] += 1
            if promise_kind == "refund" and rng.random() < 0.12:
                will_refund = False  # the promise that gets broken
        if will_refund:
            r_at = t_at + rng.choice([1, 2, 3, 4, 6]) * DAY
            if r_at < NOW:
                approver = agent if refund_amount <= 100 else ("u-lead-west" if refund_amount <= 500 else "u-sup-head")
                emit("refund.issued", {"refund_id": f"rf-{tid}", "order_id": oid, "amount": refund_amount,
                                       "status": "issued", "approved_by": approver}, r_at, "payments")
                stats["refunds"] += 1
                if kind in ("damaged", "product_issue", "wrong_item"):
                    emit("return.created", {"return_id": f"rt-{tid}", "line_id": lines[0]["line_id"],
                                            "reason": kind, "status": "received"}, r_at - DAY, "store")
                    stats["returns"] += 1
        if t_at + 2 * DAY < NOW and rng.random() < 0.7:
            emit("ticket.updated", {"ticket_id": tid, "status": "solved", "handled_by": agent}, t_at + 2 * DAY,
                 "helpdesk")

    events.sort(key=lambda e: e["occurred_at"])
    return stats


def main():
    stats = build()
    (ROOT / "events").mkdir(parents=True, exist_ok=True)
    (ROOT / "source").mkdir(parents=True, exist_ok=True)
    with open(ROOT / "events" / "northwind.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    with open(ROOT / "source" / "northwind_personal.json", "w") as f:
        json.dump(personal, f, indent=1)
    by_type: dict[str, int] = {}
    for e in events:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    print(json.dumps({"events": len(events), "now": NOW, **stats, "by_type": by_type}, indent=1))


if __name__ == "__main__":
    main()
