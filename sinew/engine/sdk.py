"""The Sinew SDK: what a company (or our Northwind simulator) uses to send events.

    from sinew.engine.sdk import SinewClient
    client = SinewClient("https://…/api", tenant="northwind")
    client.send([{"event_id": "...", "type": "scan.recorded", ...}])

`SinewClient(None, tenant)` sends in-process (same pipeline, no HTTP), used for fast local seeding.
"""

import json
import time
import urllib.request

from sinew.engine import pipeline, signing

BATCH = 200


class SinewClient:
    def __init__(self, base_url: str | None, tenant: str):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.tenant = tenant

    def send(self, events: list[dict]) -> dict:
        totals = {"accepted": 0, "stale": 0, "quarantined": [], "signals": []}
        for i in range(0, len(events), BATCH):
            part = self._send_batch(events[i:i + BATCH])
            totals["accepted"] += part["accepted"]
            totals["stale"] += part["stale"]
            totals["quarantined"] += part["quarantined"]
            totals["signals"] += part["signals"]
        return totals

    def _send_batch(self, events: list[dict]) -> dict:
        if self.base_url is None:
            return pipeline.process(self.tenant, events).as_dict()
        body = json.dumps({"events": events}).encode()
        ts = int(time.time())
        req = urllib.request.Request(
            f"{self.base_url}/ingest/{self.tenant}", data=body, method="POST",
            headers={"Content-Type": "application/json", "X-Sinew-Timestamp": str(ts),
                     "X-Sinew-Signature": signing.sign(body, ts)},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
