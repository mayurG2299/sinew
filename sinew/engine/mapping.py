"""Apply a mapping contract: a company's own exports in, ordinary Sinew events out (ENGINE.md §2b, §5e layer 2).

The contract is configuration a company's data owner confirms; this module is the same for every company.
A field spec is either a path ("default_address.country_code") or a dict:
  from       a path, or a list of paths joined with `join`
  const      a fixed value
  template   "o-{}" formats the value
  transform  iso_to_epoch | decimal | strip_hash | minutes_to_hours | lower
  add_seconds  added after the transform
  map        name of a value map: a coded value with no entry is HELD with a reason, never guessed
  each       a list inside the record, mapped with its own `fields`
Paths: "a.b.0", "$parent.x" (the record an exploded item came from), "$index", "$value".
"""

import json
from datetime import datetime
from pathlib import Path

SEED = Path(__file__).resolve().parents[2] / "seed"


class Held(Exception):
    """A record the contract can't map without guessing: kept out of the graph, reported with a reason."""


TRANSFORMS = {
    "iso_to_epoch": lambda v: int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()),
    "decimal": lambda v: round(float(v), 2),
    "strip_hash": lambda v: str(v).lstrip("#"),
    "minutes_to_hours": lambda v: int(round(float(v or 0) / 60)),
    "lower": lambda v: str(v).lower(),
}


def _get(record, path: str, ctx: dict):
    if path == "$value":
        return record
    if path == "$index":
        return ctx.get("index")
    if path.startswith("$parent."):
        record, path = ctx.get("parent"), path[len("$parent."):]
    for part in path.split(".") if path else []:
        if record is None:
            return None
        record = record[int(part)] if isinstance(record, list) else record.get(part)
    return record


def _value(spec, record, ctx: dict, maps: dict):
    if isinstance(spec, str):
        return _get(record, spec, ctx)
    if "const" in spec and "from" not in spec:
        value = spec["const"]
    elif "each" in spec:
        return [{name: _value(s, item, ctx, maps) for name, s in spec["fields"].items()}
                for item in (_get(record, spec["each"], ctx) or [])]
    elif isinstance(spec.get("from"), list):
        parts = [_get(record, p, ctx) for p in spec["from"]]
        value = spec.get("join", " ").join(str(p) for p in parts if p not in (None, ""))
    else:
        value = _get(record, spec["from"], ctx) if "from" in spec else spec.get("const")
    if value is None:
        return None
    if "map" in spec:
        table = maps[spec["map"]]
        if str(value) not in table:
            raise Held(f"value {value!r} has no entry in value map {spec['map']!r}")
        value = table[str(value)]
    if "transform" in spec:
        value = TRANSFORMS[spec["transform"]](value)
    if "add_seconds" in spec:
        value += spec["add_seconds"]
    if "template" in spec:
        value = spec["template"].format(value)
    return value


def _records(source: dict, folder: Path):
    data = json.loads((folder / source["file"]).read_text())
    rows = _get(data, source["path"], {}) if source["path"] else data
    for row in rows:
        if source.get("explode"):
            for i, item in enumerate(_get(row, source["explode"], {}) or []):
                yield item, {"parent": row, "index": i}
        else:
            yield row, {}


def apply(contract: dict, folder: Path) -> tuple[list[dict], list[dict]]:
    """Returns (events, held). Events are in time order, ready for the pipeline."""
    maps = contract.get("value_maps", {})
    events, held = [], []
    for source in contract["sources"]:
        where = source.get("where")
        for record, ctx in _records(source, folder):
            if where and _get(record, where["field"], ctx) != where["equals"]:
                continue  # e.g. test orders: not business events
            key = _value(source["key"], record, ctx, maps)
            try:
                payload = {name: _value(spec, record, ctx, maps) for name, spec in source["fields"].items()}
                occurred = _value(source["occurred_at"], record, ctx, maps)
            except Held as e:
                held.append({"source": source["name"], "key": str(key), "reason": str(e)})
                continue
            events.append({
                "event_id": f"{contract['tenant']}-{source['name']}-{key}", "type": source["event"],
                "source": source["source"], "occurred_at": occurred,
                "payload": {k: v for k, v in payload.items() if v is not None},
            })
    events.sort(key=lambda e: e["occurred_at"])
    return events, held


def build(tenant: str) -> dict:
    contract = json.loads((SEED / "contracts" / f"{tenant}.json").read_text())
    events, held = apply(contract, SEED / "source" / tenant)
    (SEED / "events").mkdir(exist_ok=True)
    with open(SEED / "events" / f"{tenant}.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    by_type: dict[str, int] = {}
    for e in events:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    return {"tenant": tenant, "contract_version": contract["version"], "events": len(events), "held": held,
            "by_type": by_type}


if __name__ == "__main__":
    import sys

    print(json.dumps(build(sys.argv[1] if len(sys.argv) > 1 else "larkspur"), indent=1))
