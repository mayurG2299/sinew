from functools import lru_cache

from falkordb import FalkorDB

from sinew import config


@lru_cache(maxsize=1)
def client() -> FalkorDB:
    return FalkorDB(
        host=config.FALKORDB_HOST,
        port=config.FALKORDB_PORT,
        username=config.FALKORDB_USERNAME,
        password=config.FALKORDB_PASSWORD,
    )


def graph(tenant: str):
    if tenant not in config.TENANTS:
        raise ValueError(f"unknown tenant: {tenant}")
    return client().select_graph(tenant)
