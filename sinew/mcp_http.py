"""Sinew's MCP server over HTTP, for connecting an outside agent (ChatGPT, Claude, an inspector) to the graph.

    SINEW_LOCAL=1 uv run python -m sinew.mcp_http            # http://127.0.0.1:8765/<secret>/<person>/mcp

Each person gets their own URL, so who the agent acts as is fixed by the URL and never chosen by the model; the guard
still checks every call against that person's role, so the CMO's URL can read the cost sheet and the brand marketer's
cannot. Only read tools are served (no refunds, promises, incidents, notifications or findings), the secret in the path
is the credential (generate it with SINEW_MCP_SECRET, or one is made at start), and the server listens on localhost:
put a tunnel in front of it to reach it from outside. The URLs are written to work-log/mcp-urls.txt (git-ignored),
never to the console, because the secret is the key.
"""

import os
import secrets
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

from sinew.mcp_server import build_server

DEMO_PEOPLE = ["u-ceo", "u-cmo", "u-marketing", "u-agent-w1"]  # Daniel, Priya, Chloe, Ravi


def make_app(tenant: str, people: list[str], secret: str) -> Starlette:
    """One read-only MCP endpoint per person at /<secret>/<person>/mcp; any other path is a 404."""
    if len(secret) < 24:
        raise ValueError("the secret in the path must be at least 24 characters")
    inner = [build_server(tenant, uid, read_only=True).streamable_http_app(
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))  # the secret path is the gate
        for uid in people]

    @asynccontextmanager
    async def lifespan(_app):
        async with AsyncExitStack() as stack:  # a mounted app's own startup is not run by its parent
            for app in inner:
                await stack.enter_async_context(app.router.lifespan_context(app))
            yield

    return Starlette(routes=[Mount(f"/{secret}/{uid}", app=app) for uid, app in zip(people, inner)], lifespan=lifespan)


def main():
    import uvicorn
    tenant = os.environ.get("SINEW_TENANT", "northwind")
    people = [p for p in os.environ.get("SINEW_MCP_PEOPLE", ",".join(DEMO_PEOPLE)).split(",") if p]
    secret = os.environ.get("SINEW_MCP_SECRET") or secrets.token_urlsafe(24)
    port = int(os.environ.get("SINEW_MCP_PORT", "8765"))
    base = os.environ.get("SINEW_MCP_PUBLIC_URL", f"http://127.0.0.1:{port}").rstrip("/")
    out = Path(__file__).resolve().parents[1] / "work-log" / "mcp-urls.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(f"{uid}  {base}/{secret}/{uid}/mcp" for uid in people) + "\n")
    out.chmod(0o600)
    print(f"Sinew MCP: {len(people)} people on 127.0.0.1:{port}, read tools only. URLs are in {out} (the secret is the key).")
    uvicorn.run(make_app(tenant, people, secret), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
