import pytest

from sinew import schema
from sinew.db import client


@pytest.fixture
def tenant():
    name = "sandbox"  # a real tenant name; wiped before and after
    if name in client().list_graphs():
        client().select_graph(name).delete()
    yield name
    client().select_graph(name).delete()


def test_schema_is_idempotent(tenant):
    first = schema.apply(tenant)
    second = schema.apply(tenant)
    assert first["constraints_created"] == len(schema.ID_LABELS)
    assert second == {"tenant": tenant, "indexes_created": 0, "constraints_created": 0}


def test_unique_id_rejects_duplicates(tenant):
    schema.apply(tenant)
    g = client().select_graph(tenant)
    g.query("CREATE (:Order {id: 'o1'})")
    with pytest.raises(Exception):
        g.query("CREATE (:Order {id: 'o1'})")
    assert g.ro_query("MATCH (o:Order) RETURN count(o)").result_set[0][0] == 1
