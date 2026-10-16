"""Sinew's MCP server: the only way agents reach the graph.

One server instance is built per signed-in person and company. Tools take no "user" argument, so the model
can't choose who it acts as; the guard checks every call against that person. Writes that move money or
change records are marked destructive, and the agent loop sends those to a person to confirm.
Export and delete-me are not exposed here at all: they are human-only actions in the UI.
"""

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from sinew.tools import actions, impact, trace

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
NEEDS_PERSON = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

Id = Annotated[str, Field(min_length=1, max_length=80)]


def build_server(tenant: str, user_id: str, run_id: str | None = None, read_only: bool = False) -> MCPServer:
    mcp = MCPServer(name="sinew", title="Sinew · company brain",
                    instructions="Answer only from tool results. Every tool returns an outcome; "
                                 "unknown_entity and not_permitted are answers, not errors to work around.")

    @mcp.tool(annotations=READ)
    def customer_trace(customer: Annotated[str, Field(description="customer, profile, order or ticket id, or the "
                                                      "customer's email/phone")]) -> dict:
        """Complete history of one customer: orders, payments, scans, refunds, returns, tickets and promises,
        filtered by what you may see. Personal details are fetched live and only for allowed roles."""
        return trace.customer_trace(tenant, user_id, customer).as_dict()

    @mcp.tool(annotations=READ)
    def open_loops(customer: Id) -> dict:
        """What is still open for a customer: open tickets, open or broken promises, late parcels, unrefunded returns."""
        return trace.open_loops(tenant, user_id, customer).as_dict()

    @mcp.tool(annotations=READ)
    def related_issues(ticket_id: Id, days: Annotated[int, Field(ge=1, le=30)] = 7) -> dict:
        """Other recent tickets through the same hub, courier, batch or campaign as this ticket."""
        return trace.related_issues(tenant, user_id, ticket_id, days).as_dict()

    @mcp.tool(annotations=READ)
    def search_tickets(text: Annotated[str, Field(min_length=2, max_length=100)]) -> dict:
        """Full-text search of cleaned ticket summaries you are allowed to see."""
        return trace.search_tickets(tenant, user_id, text).as_dict()

    @mcp.tool(annotations=READ)
    def cluster_incidents(days: Annotated[int, Field(ge=1, le=30)] = 7) -> dict:
        """Group recent tickets into incidents by what they share (community detection) and find each root hub."""
        return impact.cluster_incidents(tenant, days).as_dict()

    @mcp.tool(annotations=READ)
    def trace_decisions(hub_id: Id) -> dict:
        """Company decisions that affect a hub, the assumptions they rest on, the latest evidence, and links."""
        return impact.trace_decisions(tenant, hub_id).as_dict()

    @mcp.tool(annotations=READ)
    def decision_impact(decision_id: Id) -> dict:
        """What rests on a decision: dependent decisions, keystone rank, parcels in transit, customers and
        promises at risk."""
        return impact.decision_impact(tenant, decision_id).as_dict()

    @mcp.tool(annotations=READ)
    def prelaunch_check() -> dict:
        """Scheduled campaigns that would go through a hub whose assumptions are already broken, with a reroute."""
        return impact.prelaunch_check(tenant).as_dict()

    @mcp.tool(annotations=READ)
    def reroute(from_hub: Id, avoid_hub: Id) -> dict:
        """Fastest path to another last-mile hub in the same region that avoids a hub."""
        return impact.reroute(tenant, from_hub, avoid_hub).as_dict()

    @mcp.tool(annotations=READ)
    def find_approver(amount: Annotated[float, Field(gt=0)]) -> dict:
        """Who can approve a refund of this amount: you, or the nearest manager whose limit covers it."""
        return impact.find_approver(tenant, user_id, amount).as_dict()

    @mcp.tool(annotations=READ)
    def choke_points() -> dict:
        """Hubs that sit on the most delivery routes (betweenness centrality)."""
        return impact.choke_points(tenant).as_dict()

    @mcp.tool(annotations=READ)
    def recall(about: Id) -> dict:
        """Earlier findings about a customer, ticket, hub, incident or decision, newest first, with dates."""
        return actions.recall(tenant, about).as_dict()

    if read_only:
        return mcp

    @mcp.tool(annotations=NEEDS_PERSON)
    def issue_refund(order_id: Id, amount: Annotated[float, Field(gt=0)]) -> dict:
        """Refund an order, within your limit. Over the limit it returns who must approve instead."""
        return actions.issue_refund(tenant, user_id, order_id, amount, run_id).as_dict()

    @mcp.tool(annotations=WRITE)
    def record_promise(ticket_id: Id, order_id: Id, kind: Literal["refund", "delivery"],
                       due_in_hours: Annotated[float, Field(gt=0, le=24 * 30)]) -> dict:
        """Propose a promise found in the agent's own reply. A person or the matching action confirms it."""
        return actions.record_promise(tenant, user_id, ticket_id, order_id, kind, due_in_hours, run_id).as_dict()

    @mcp.tool(annotations=NEEDS_PERSON)
    def confirm_promise(promise_id: Id) -> dict:
        """Confirm a proposed promise (a person does this)."""
        return actions.confirm_promise(tenant, user_id, promise_id).as_dict()

    @mcp.tool(annotations=NEEDS_PERSON)
    def file_incident(title: Annotated[str, Field(min_length=3, max_length=200)],
                      ticket_ids: Annotated[list[str], Field(min_length=1, max_length=200)], root_hub: Id) -> dict:
        """File an incident linking the clustered tickets to their root hub."""
        return actions.file_incident(tenant, user_id, title, ticket_ids, root_hub, run_id).as_dict()

    @mcp.tool(annotations=WRITE)
    def evaluate_assumptions() -> dict:
        """Check every decision's assumptions against the latest data and record the evidence."""
        return actions.evaluate_assumptions(tenant).as_dict()

    @mcp.tool(annotations=NEEDS_PERSON)
    def notify_owner(decision_id: Id, message: Annotated[str, Field(min_length=3, max_length=600)]) -> dict:
        """Send the decision's owner a note with the evidence and the path."""
        return actions.notify_owner(tenant, user_id, decision_id, message, run_id).as_dict()

    @mcp.tool(annotations=WRITE)
    def write_finding(about: Annotated[list[str], Field(min_length=1, max_length=20)],
                      text: Annotated[str, Field(min_length=3, max_length=600)]) -> dict:
        """Remember a conclusion, tied to the things it is about, for the next session."""
        return actions.write_finding(tenant, user_id, about, text, run_id).as_dict()

    return mcp
