"""Larkspur Home: a second made-up store whose systems send data in their own shapes, not Sinew's.

Output (deterministic, seed 7), as each source system would export it:
  seed/source/larkspur/store.json      Shopify-like: customers and orders (prices as "25.99" strings, ISO dates,
                                       order names "#1001", test orders mixed in, accepts_marketing flags)
  seed/source/larkspur/tracking.json   courier feed: numeric status codes 1/2/3, delays in minutes
  seed/source/larkspur/helpdesk.json   Zendesk-like tickets: requester email, order as "#1001" in a custom field
  seed/source/larkspur/ops.json        staff, teams, hubs, couriers, catalogue, decisions
  seed/source/larkspur_personal.json   the store's own copy of names, emails, phones, addresses (for live fetch)

None of this is Sinew's event format. seed/contracts/larkspur.json maps it, and sinew/sim/map_larkspur.py
applies that contract to produce ordinary Sinew events.

Story: day -40 Larkspur moved its east region to Courier Q (assumes >= 92% on time at Hub E2). In the last week
Courier Q has fallen behind at E2; delay complaints cluster there. No campaign is involved.
"""

import json
import random
from datetime import datetime, timedelta, timezone

import phonenumbers
from faker import Faker

from sinew.sim.northwind import NOW, ROOT

rng = random.Random(7)
fake = Faker(["en_US", "en_GB"])
Faker.seed(7)
OUT = ROOT / "source" / "larkspur"
DAY = 86_400


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def at(day: float) -> int:
    return NOW + int(day * DAY)


CATALOGUE = [("lamp-arc", "Arc Floor Lamp", "lighting", 89.0), ("lamp-desk", "Desk Lamp Mini", "lighting", 34.5),
             ("rug-wool", "Wool Rug 160", "textiles", 129.0), ("throw-linen", "Linen Throw", "textiles", 45.0),
             ("vase-stone", "Stone Vase", "decor", 28.0), ("mirror-round", "Round Mirror", "decor", 75.0),
             ("chair-oak", "Oak Side Chair", "furniture", 159.0), ("shelf-wall", "Wall Shelf", "furniture", 52.0)]


def build():
    ops = {
        "teams": [
            {"team_id": "team-care-east", "name": "Care East", "covers_regions": ["east"], "queues": ["q-east"]},
            {"team_id": "team-care-central", "name": "Care Central", "covers_regions": ["central"], "queues": ["q-central"]},
            {"team_id": "team-ops", "name": "Operations", "covers_regions": ["east", "central"], "queues": []},
        ],
        "staff": [
            {"user_id": "u-care-lead", "team_id": "team-care-east", "role": "team_lead", "refund_limit": 400,
             "reports_to": "u-ops-head", "display_name": "Imogen Hale"},
            {"user_id": "u-care-e1", "team_id": "team-care-east", "role": "agent", "refund_limit": 80,
             "reports_to": "u-care-lead", "display_name": "Felix Moreau"},
            {"user_id": "u-care-c1", "team_id": "team-care-central", "role": "agent", "refund_limit": 80,
             "reports_to": "u-ops-head", "display_name": "Asha Rao"},
            {"user_id": "u-ops-head", "team_id": "team-ops", "role": "support_head", "refund_limit": 1500,
             "display_name": "Mateo Silva"},
            {"user_id": "u-ops-logistics", "team_id": "team-ops", "role": "logistics_manager", "refund_limit": 0,
             "reports_to": "u-ops-head", "display_name": "Hannah Berg"},
        ],
        "couriers": ["courier-p", "courier-q"],
        "hubs": [{"hub_id": "hub-e1", "region": "east", "courier_id": "courier-p", "capacity": 12},
                 {"hub_id": "hub-e2", "region": "east", "courier_id": "courier-q", "capacity": 10},
                 {"hub_id": "hub-c1", "region": "central", "courier_id": "courier-p", "capacity": 12}],
        "routes": [["hub-e1", "hub-e2", 8], ["hub-e2", "hub-e1", 8], ["hub-e1", "hub-c1", 20], ["hub-c1", "hub-e1", 20]],
        "catalogue": [{"sku": s, "title": t, "category": c} for s, t, c, _ in CATALOGUE],
        "decisions": [{
            "decision_id": "dec-courier-q", "title": "Move east deliveries to Courier Q", "made_at": iso(at(-40)),
            "owner": "u-ops-logistics", "chose_kind": "Courier", "chose_id": "courier-q", "region": "east",
            "assumptions": [{"assumption_id": "as-courier-q-ontime", "statement": "Courier Q delivers 92% on time through Hub E2",
                             "metric": "courier_on_time_rate", "op": ">=", "threshold": 0.92, "window_days": 7,
                             "scope_hub": "hub-e2", "scope_courier": "courier-q"}]}],
    }
    customers, orders, tracking, tickets, personal = [], [], [], [], {"Profile": {}, "User": {}, "Order": {}}
    for s in ops["staff"]:
        personal["User"][s["user_id"]] = {"display_name": s["display_name"]}
    for i in range(80):
        country = rng.choice(["US", "GB"])
        first, last = fake.first_name(), fake.last_name()
        example = phonenumbers.example_number_for_type(country, phonenumbers.PhoneNumberType.MOBILE)
        while True:
            digits = str(example.national_number)
            num = phonenumbers.parse(digits[:3] + "".join(str(rng.randint(0, 9)) for _ in digits[3:]), country)
            if phonenumbers.is_valid_number(num):
                break
        c = {"id": 7000 + i, "email": f"{first}.{last}{rng.randint(1, 99)}@example.org".lower(),
             "phone": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
             "first_name": first, "last_name": last, "created_at": iso(at(-rng.randint(45, 500))),
             "accepts_marketing": rng.random() < 0.05,
             "default_address": {"address1": fake.street_address(), "city": fake.city(), "country_code": country},
             "tags": "east" if rng.random() < 0.6 else "central"}
        customers.append(c)
        personal["Profile"][f"pf-ls-{c['id']}"] = {"name": f"{first} {last}", "email": c["email"], "phone": c["phone"],
                                                   "address": f"{c['default_address']['address1']}, {c['default_address']['city']}"}
    for n in range(260):
        c = rng.choice(customers)
        day = rng.uniform(-30, -0.3)
        created = at(day)
        items = rng.sample(CATALOGUE, k=rng.choice([1, 1, 2]))
        total = sum(p for *_, p in items)
        order = {"id": 900000 + n, "name": f"#{1001 + n}", "created_at": iso(created), "test": n % 37 == 5,
                 "financial_status": "paid", "fulfillment_status": None, "currency": "USD",
                 "total_price": f"{total:.2f}", "customer": {"id": c["id"]},
                 "line_items": [{"id": 50000 + n * 10 + k, "sku": s, "title": t, "price": f"{p:.2f}", "quantity": 1}
                                for k, (s, t, _, p) in enumerate(items)],
                 "shipping_address": c["default_address"]}
        orders.append(order)
        personal["Order"][f"o-{1001 + n}"] = {"shipping_address": c["default_address"]["address1"]}
        if order["test"]:
            continue
        region = c["tags"]
        hub = "hub-e2" if region == "east" else "hub-c1"
        courier = "courier-q" if region == "east" else "courier-p"
        # Courier Q falls behind at E2 in the last week.
        late_p = (0.42 if day > -7 else 0.03) if hub == "hub-e2" else 0.03
        delay_min = rng.choice([900, 1440, 2160]) if rng.random() < late_p else 0
        arrive = created + DAY
        tracking.append({"tracking_number": f"LS{1001 + n}", "order_name": order["name"], "carrier": courier,
                         "checkpoints": [cp for cp in (
                             {"time": iso(created + 6 * 3600), "location": "hub-e1" if region == "east" else "hub-c1",
                              "status_code": 1, "delay_min": 0},
                             {"time": iso(arrive), "location": hub, "status_code": 2 if delay_min else 1,
                              "delay_min": delay_min},
                             {"time": iso(arrive + DAY + delay_min * 60), "location": hub, "status_code": 3,
                              "delay_min": 0},
                         ) if datetime.fromisoformat(cp["time"].replace("Z", "+00:00")).timestamp() < NOW]})
        delivered_at = arrive + DAY + delay_min * 60
        complain_at = arrive + DAY + rng.randint(2, max(3, delay_min // 60 - 2)) * 3600  # expected day passed, still not here
        if delay_min and rng.random() < 0.9 and complain_at < min(NOW, delivered_at):
            tickets.append({"id": 30000 + n, "created_at": iso(complain_at),
                            "via": {"channel": rng.choice(["email", "web", "chat"])},
                            "requester": {"id": 40000 + c["id"], "email": c["email"].upper()}, "group": region,
                            "subject": "Where is my order?",
                            "description": rng.choice([f"My order {order['name']} is late. Please help.",
                                                       f"Hi, it's {c['first_name']} {c['last_name']}. {order['name']} hasn't arrived.",
                                                       f"Tracking for {order['name']} says delayed again."]),
                            "status": "open", "custom_fields": {"order_number": order["name"], "reason": "delay"}})
        elif rng.random() < 0.08 and delivered_at + 2 * 3600 < NOW:
            tickets.append({"id": 30000 + n, "created_at": iso(min(delivered_at + rng.randint(2, 30) * 3600, NOW - 600)),
                            "via": {"channel": "email"}, "requester": {"id": 40000 + c["id"], "email": c["email"]},
                            "group": region,
                            "subject": "Damaged item", "description": f"The {items[0][1]} in {order['name']} arrived damaged.",
                            "status": rng.choice(["open", "solved"]),
                            "custom_fields": {"order_number": order["name"], "reason": "damaged"}})
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("store", {"customers": customers, "orders": orders}), ("tracking", tracking),
                       ("helpdesk", tickets), ("ops", ops)):
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=1))
    (ROOT / "source" / "larkspur_personal.json").write_text(json.dumps(personal, indent=1))
    return {"customers": len(customers), "orders": len(orders), "test_orders": sum(o["test"] for o in orders),
            "tracking": len(tracking), "tickets": len(tickets)}


if __name__ == "__main__":
    print(build())
