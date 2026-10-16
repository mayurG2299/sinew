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


PAGE = 5000  # below FalkorDB's RESULTSET_SIZE (10,000 by default): a bigger result is silently cut off


def read_all(g, match: str, returns: str, params: dict | None = None, alias: str = "n") -> list:
    """Every row of `MATCH {match} RETURN {returns}`, read in pages ordered by the internal id of `alias`.

    Never rely on one query to return more than RESULTSET_SIZE rows.
    """
    rows, last = [], -1
    while True:
        page = g.ro_query(
            f"MATCH {match} WHERE id({alias}) > $__last RETURN id({alias}) AS __id, {returns} "
            f"ORDER BY __id LIMIT {PAGE}", {**(params or {}), "__last": last}).result_set
        rows.extend(r[1:] for r in page)
        if len(page) < PAGE:
            return rows
        last = page[-1][0]
