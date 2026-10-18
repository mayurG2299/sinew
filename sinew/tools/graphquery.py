"""AI-planned graph queries: the model fills a small structured spec, Sinew compiles it to Cypher.

The model never writes Cypher and never sees permissions. It describes a walk:

    {"match": [{"label": "Hub", "id": "hub-w2"},
               {"rel": "AT", "dir": "in", "label": "Scan", "where": [{"prop": "status", "op": "in", "value": ["delayed"]}]},
               {"rel": "FOR", "dir": "out", "label": "Shipment"}],
     "return": [{"agg": "count_distinct", "of": "Shipment", "as": "parcels"}],
     "group_by": [], "order_by": null, "limit": 20}

and this module checks every part against the graph's real schema before building the query:
  labels, relationship types and their direction, and properties must exist in this company's graph;
  only aggregates and non-identifying properties can be returned (never ids or text of customer records);
  the person's role must read the area of every label the walk touches (default deny);
  the query is read-only (GRAPH.RO_QUERY) and limited. The Cypher and the path are shown with the answer.
"""

import json
import re
import time

from sinew.db import graph
from sinew.tools import guard
from sinew.tools.answer import Answer, refused
from sinew.tools.trace import clock

DAY = 86_400
# The areas that may walk through a label (any one is enough); None = reference data any role with an area may count.
# Only counts and totals come back, so marketing and finance may count orders and customers (their own summaries do),
# but never read a customer record.
AREA = {
    "Order": {"support", "marketing", "finance"}, "LineItem": {"support", "marketing"}, "Payment": {"support", "finance"},
    "Refund": {"support", "finance"}, "Return": {"support"}, "Ticket": {"support"}, "Promise": {"support"},
    "Customer": {"support", "marketing"}, "Profile": {"support", "marketing"},
    "Shipment": {"operations"}, "Scan": {"operations"}, "Hub": {"operations"}, "Courier": {"operations"},
    "Decision": {"operations"}, "Assumption": {"operations"}, "Evidence": {"operations"}, "Warehouse": {"operations"},
    "Campaign": {"marketing"}, "Coupon": {"marketing"}, "CostLine": {"finance"},
    "Product": None, "Batch": None, "Supplier": None, "Region": None, "Queue": None, "User": None,
}
# Things that may be LISTED row by row (never customer records): the company's own structure and decisions.
ROW_LABELS = {"Hub", "Courier", "Decision", "Assumption", "Evidence", "Campaign", "Coupon", "Product", "Batch", "Supplier",
              "Region", "Warehouse", "Queue", "User", "CostLine"}
CUSTOMER_LINKED = {"Order", "LineItem", "Payment", "Refund", "Return", "Ticket", "Promise", "Customer", "Profile"}
NEVER_RETURNED = {"id", "summary_clean", "hash", "record", "fields", "text_clean"}  # on customer-linked labels
# Money fields: totalling them across the company is revenue, refunds paid or cost, which only the finance area reads.
# (Counting the records, or one person's own orders through their own tools, is not affected.)
MONEY = {"Order": {"total"}, "Payment": {"amount"}, "Refund": {"amount"}, "LineItem": {"price"}, "CostLine": {"amount"}}
OPS = {"=": "=", "!=": "<>", "<": "<", "<=": "<=", ">": ">", ">=": ">=", "in": "IN"}
AGGS = {"count": "count({v})", "count_distinct": "count(DISTINCT {v})", "sum": "sum({v}.{p})", "avg": "avg({v}.{p})",
        "min": "min({v}.{p})", "max": "max({v}.{p})"}
MAX_HOPS, MAX_LIMIT = 6, 50


class QueryError(ValueError):
    """The spec asks for something the graph or this person's role doesn't allow."""


_SCHEMA: dict[str, tuple[float, set, dict, dict]] = {}
NOT_CATEGORIES = {"id", "summary_clean", "text_clean", "heading", "title", "statement", "basis", "record", "name", "hash", "source",
                  "confirmed_by", "rejected_by", "approved_by", "made_by", "scope_hub", "scope_courier"}


def schema(tenant: str) -> tuple[set[tuple[str, str, str]], dict[str, set[str]]]:
    """(label, relationship, label) patterns that exist in this company's graph, and the properties each label has."""
    hit = _SCHEMA.get(tenant)
    if hit and time.time() - hit[0] < 300:
        return hit[1], hit[2]
    g = graph(tenant)
    patterns = {(a, r, b) for a, r, b in g.ro_query(
        "MATCH (a)-[r]->(b) RETURN DISTINCT labels(a)[0], type(r), labels(b)[0]").result_set
        if a in AREA and b in AREA}
    props = {}
    for label in AREA:
        props[label] = {k for k, in g.ro_query(f"MATCH (n:{label}) WITH n LIMIT 50 UNWIND keys(n) AS k RETURN DISTINCT k").result_set}
    hints = {}  # the actual values of category-like properties, so the model writes filters that match the data
    for label, ps in props.items():
        for p in sorted(ps - NOT_CATEGORIES):
            vals = [v for v, in g.ro_query(f"MATCH (n:{label}) WHERE n.{p} IS NOT NULL WITH n LIMIT 400 RETURN DISTINCT n.{p} LIMIT 12").result_set]
            if 1 <= len(vals) <= 10 and all(isinstance(v, str) and len(v) <= 28 for v in vals):
                hints[(label, p)] = sorted(vals)
    _SCHEMA[tenant] = (time.time(), patterns, props, hints)
    return patterns, props


def value_hints(tenant: str) -> dict:
    schema(tenant)
    return _SCHEMA[tenant][3]


def schema_text(tenant: str) -> str:
    """The schema as the model sees it: one line per walk it may take, and each label's usable properties."""
    patterns, props = schema(tenant)
    walks = "; ".join(f"{a} -[{r}]-> {b}" for a, r, b in sorted(patterns))
    shown = "\n".join(f"{label}: " + ", ".join(sorted(p for p in ps if p not in NEVER_RETURNED or label not in CUSTOMER_LINKED)
                                               or ["(none)"]) for label, ps in sorted(props.items()) if ps)
    values = "\n".join(f"{label}.{p} is one of: {', '.join(vs)}" for (label, p), vs in sorted(value_hints(tenant).items()))
    return (f"Walks (a relationship can be followed in either direction):\n{walks}\n\nProperties:\n{shown}\n\n"
            f"Values (use exactly these in filters):\n{values}\n"
            "Time properties (at, placed_at, starts, ends, due_at, since) are epoch seconds; late_hours and the like are numbers.")


def _value(v, now: int):
    if isinstance(v, str):
        m = re.fullmatch(r"now(?:\s*-\s*(\d+)\s*([dh]))?", v.strip().lower())
        if m:  # "now", "now-7d", "now-12h": the model never does clock arithmetic
            return now - int(m.group(1) or 0) * (DAY if m.group(2) == "d" else 3600 if m.group(2) == "h" else 0)
        return v[:80]
    if isinstance(v, bool) or isinstance(v, (int, float)):
        return v
    raise QueryError(f"a filter value must be text, a number or a list of them, not {type(v).__name__}")


def _alias(name, default: str) -> str:
    a = re.sub(r"[^A-Za-z0-9_]", "_", str(name or default))[:30] or default
    return a if re.match(r"[A-Za-z_]", a) else "_" + a


def compile_spec(tenant: str, spec: dict, now: int, customer_rows: bool = False) -> dict:
    """Spec -> {"cypher", "params", "path", "labels", "columns"} or QueryError. Nothing here touches the graph's data."""
    if not isinstance(spec, dict) or not isinstance(spec.get("match"), list) or not spec["match"]:
        raise QueryError("a query needs a 'match' walk that starts at one label")
    patterns, props = schema(tenant)
    chain = spec["match"]
    if len(chain) > MAX_HOPS:
        raise QueryError(f"a walk can have at most {MAX_HOPS} steps")
    params: dict = {}
    where: list[str] = []
    labels: list[str] = []
    pattern, path = "", ""

    def add_filters(var: str, label: str, filters):
        for f in filters or []:
            prop, op = str(f.get("prop", "")), str(f.get("op", "="))
            if prop not in props.get(label, set()) or prop in ("summary_clean", "hash", "record", "fields"):
                raise QueryError(f"{label} has no property '{prop}' that can be filtered")
            if op not in OPS:
                raise QueryError(f"filter operator must be one of {sorted(OPS)}")
            raw = f.get("value")
            val = [_value(x, now) for x in raw][:30] if op == "in" and isinstance(raw, list) else _value(raw, now)
            if op == "in" and not isinstance(val, list):
                val = [val]
            params[f"p{len(params)}"] = val
            where.append(f"{var}.{prop} {OPS[op]} $p{len(params) - 1}")

    for i, step in enumerate(chain):
        label = str(step.get("label", ""))
        if label not in AREA:
            raise QueryError(f"'{label}' is not something this graph holds that can be queried")
        var = f"v{i}"
        if i == 0:
            pattern = f"({var}:{label})"
            if step.get("id") is not None:  # ids match whatever the case: the coupon is FEST40, the campaign fest40
                params["p0"] = str(step["id"])[:80].lower()
                where.append(f"toLower({var}.id) = $p0")
            path = label + (f" {step['id']}" if step.get("id") else "")
        else:
            rel, d = str(step.get("rel", "")), step.get("dir", "out")
            prev = labels[-1]
            ok = (prev, rel, label) in patterns if d == "out" else (label, rel, prev) in patterns
            if not ok:
                raise QueryError(f"the graph has no {prev} {'-[' + rel + ']->' if d == 'out' else '<-[' + rel + ']-'} {label}")
            pattern += (f"-[:{rel}]->({var}:{label})" if d == "out" else f"<-[:{rel}]-({var}:{label})")
            path += (f" -[{rel}]-> {label}" if d == "out" else f" <-[{rel}]- {label}")
        labels.append(label)
        add_filters(var, label, step.get("where"))

    def var_of(ref) -> tuple[str, str]:
        """A step of the walk: its label (the last one, if a label repeats), "Label@1" for the first, or its position."""
        if isinstance(ref, int) and 0 <= ref < len(labels):
            return f"v{ref}", labels[ref]
        label_name, _, nth = str(ref).partition("@")
        hits = [i for i, label in enumerate(labels) if label == label_name]
        if not hits or (nth and (not nth.isdigit() or not 1 <= int(nth) <= len(hits))):
            raise QueryError(f"'{ref}' is not part of the walk")
        i = hits[int(nth) - 1] if nth else hits[-1]
        return f"v{i}", label_name

    cols, ret = [], []
    money = False
    listing = spec.get("list") or []
    for g_ in listing:  # "list": rows of the company's own structure, e.g. decisions or hubs; never customer records
        label_ = str(g_.get("of", "")).partition("@")[0]
        if label_ not in ROW_LABELS:
            raise QueryError(f"rows of {label_} can't be listed (customer records are never listed); count or total them instead")
    customer_cols: list[int] = []
    for g_ in list(spec.get("group_by") or []) + list(listing):
        v, label = var_of(g_.get("of"))
        prop = str(g_.get("prop", ""))
        if prop not in props.get(label, set()):
            raise QueryError(f"{label} has no property '{prop}'")
        if label == "Customer" and prop == "id" and customer_rows:  # a person who handles customers may list theirs
            customer_cols.append(len(ret))
            where.append(f"{v}.id IN $visible")
        elif label in CUSTOMER_LINKED and prop in NEVER_RETURNED:
            raise QueryError(f"{prop} of {label} identifies a customer record and can't be returned; only counts and totals can")
        money = money or prop in MONEY.get(label, ())
        a = _alias(g_.get("as"), prop)
        ret.append(f"{v}.{prop} AS {a}")
        cols.append(a)
    for r in spec.get("return") or []:
        agg = str(r.get("agg", ""))
        if agg not in AGGS:
            raise QueryError(f"'agg' must be one of {sorted(AGGS)}; row-level lists of customers are not returned")
        v, label = var_of(r.get("of"))
        prop = str(r.get("prop", "")) if agg not in ("count", "count_distinct") else ""
        if agg not in ("count", "count_distinct") and prop not in props.get(label, set()):
            raise QueryError(f"{agg} needs a numeric property of {label}")
        money = money or prop in MONEY.get(label, ())
        a = _alias(r.get("as"), agg)
        ret.append(AGGS[agg].format(v=v, p=prop) + f" AS {a}")
        cols.append(a)
    if not ret or not (spec.get("return") or listing):
        raise QueryError("a query must return at least one count or total, or list things")
    distinct = "DISTINCT " if not spec.get("return") else ""
    order = ""
    ob = spec.get("order_by")
    if isinstance(ob, dict) and ob.get("by") in cols:
        order = f" ORDER BY {ob['by']}" + (" DESC" if ob.get("desc", True) else "")
    limit = min(max(int(spec.get("limit") or 20), 1), MAX_LIMIT)
    cypher = (f"MATCH {pattern}" + (" WHERE " + " AND ".join(where) if where else "")
              + f" RETURN {distinct}{', '.join(ret)}{order} LIMIT {limit}")
    return {"cypher": cypher, "params": params, "path": path, "labels": labels, "columns": cols, "customer_cols": customer_cols, "money": money}


def _show(cypher: str, params: dict) -> str:
    """The Cypher with its values written in, for people to read (it is run with parameters)."""
    return re.sub(r"\$(p\d+)", lambda m: json.dumps(params[m.group(1)]), cypher)


def run_query(tenant: str, user_id: str, spec: dict, ask: str = "") -> Answer:
    start = time.perf_counter()
    v = guard.Viewer.load(tenant, user_id)
    if v is None:
        return refused("graph_query", "unknown person")
    def blocked_areas(labels) -> list[str]:
        return sorted({sorted(AREA[x])[0] for x in labels if x in AREA and AREA[x] and not (AREA[x] & set(v.areas))})
    asked = [str(st.get("label")) for st in (spec.get("match") or []) if isinstance(st, dict)] if isinstance(spec, dict) else []
    if blocked_areas(asked) or not v.areas:  # access first: someone who may not read these areas is told so, not why the walk is invalid
        return refused("graph_query", f"your role doesn't have access to {', '.join(blocked_areas(asked)) or 'company'} information")
    try:
        now = clock(tenant)
        c = compile_spec(tenant, spec, now, customer_rows=v.role in guard.SUPPORT_ROLES)
    except (QueryError, TypeError, ValueError, AttributeError) as e:
        return Answer("graph_query", "not_in_graph", reason=f"couldn't turn that into a valid walk: {e}")
    if blocked_areas(c["labels"]):
        return refused("graph_query", f"your role doesn't have access to {', '.join(blocked_areas(c['labels']))} information")
    if c["money"] and "finance" not in v.areas:
        return refused("graph_query", "your role doesn't have access to finance information")
    if c["customer_cols"]:  # only the customers this person may see, by the same paths as the inbox
        seen = guard.visible_customers(v)
        c["params"]["visible"] = seen if seen is not None else [x for x, in graph(tenant).ro_query("MATCH (c:Customer) RETURN c.id").result_set]
    rows = graph(tenant).ro_query(c["cypher"], c["params"]).result_set
    names = {}
    if c["customer_cols"]:
        names = guard.customer_names(v, sorted({r[i] for r in rows for i in c["customer_cols"]}), "graph_query")
    ms = round((time.perf_counter() - start) * 1000, 1)
    shown = _show(c["cypher"], c["params"])
    if not rows or all(all(x in (None, 0) for x in r) for r in rows):
        return Answer("graph_query", "not_in_graph", reason="the walk found nothing matching", ms=ms,
                      data={"ask": ask, "cypher": shown, "path": c["path"], "columns": c["columns"], "rows": []})
    def cell(x):  # staff and customers appear by name where the person may see names; dates as dates
        if isinstance(x, str) and re.fullmatch(r"u-[a-z0-9-]+", x):
            return guard.staff_name(tenant, x) or x
        if isinstance(x, str) and x in names:
            return names[x]
        if isinstance(x, str) and re.fullmatch(r"cu-[a-z0-9-]+", x):
            return "a customer"
        if isinstance(x, int) and not isinstance(x, bool) and 1_500_000_000 < x < 2_000_000_000:
            return time.strftime("%-d %b", time.gmtime(x))
        return round(x, 2) if isinstance(x, float) else x
    return Answer("graph_query", "answered_path", ms=ms, paths=[c["path"].split(" ")],
                  data={"ask": ask, "cypher": shown, "path": c["path"], "columns": c["columns"],
                        "rows": [[cell(x) for x in r] for r in rows]})
