import os

# Tests always run against the local docker FalkorDB, never the cloud demo graph.
os.environ["SINEW_LOCAL"] = "1"

import shutil

import pytest


@pytest.fixture(scope="module")
def northwind_copy(tmp_path_factory):
    """The real Northwind graph, restored from its snapshot into the test tenant 'store2'."""
    from sinew.db import client
    from sinew.engine import snapshot
    from sinew.tools import guard

    tmp = tmp_path_factory.mktemp("nw")
    real_snapshots, real_records = snapshot.SNAPSHOTS, guard.SOURCE_RECORDS
    shutil.copy(real_snapshots / "northwind.json.gz", tmp / "store2.json.gz")
    shutil.copy(real_records / "northwind_personal.json", tmp / "store2_personal.json")
    snapshot.SNAPSHOTS, guard.SOURCE_RECORDS = tmp, tmp
    snapshot.restore("store2")
    yield "store2"
    client().select_graph("store2").delete()
    snapshot.SNAPSHOTS, guard.SOURCE_RECORDS = real_snapshots, real_records
