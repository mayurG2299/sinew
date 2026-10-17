import os

# Tests always run against the local docker FalkorDB, never the cloud demo graph, and in a scratch tenant
# called "sandbox", never a real company's graph.
os.environ["SINEW_LOCAL"] = "1"
os.environ.setdefault("HASH_KEY_SANDBOX", "5a" * 32)

from sinew import config  # noqa: E402

config.TENANTS = (*config.TENANTS, "sandbox")

import shutil

import pytest


@pytest.fixture(scope="module")
def northwind_copy(tmp_path_factory):
    """The real Northwind graph, restored from its snapshot into the test tenant 'sandbox'."""
    from sinew.db import client
    from sinew.engine import snapshot
    from sinew.tools import guard

    tmp = tmp_path_factory.mktemp("nw")
    real_snapshots, real_records = snapshot.SNAPSHOTS, guard.SOURCE_RECORDS
    shutil.copy(real_snapshots / "northwind.json.gz", tmp / "sandbox.json.gz")
    shutil.copy(real_records / "northwind_personal.json", tmp / "sandbox_personal.json")
    snapshot.SNAPSHOTS, guard.SOURCE_RECORDS = tmp, tmp
    snapshot.restore("sandbox")
    yield "sandbox"
    client().select_graph("sandbox").delete()
    snapshot.SNAPSHOTS, guard.SOURCE_RECORDS = real_snapshots, real_records
