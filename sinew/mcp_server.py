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

from sinew.tools import actions, docs, focus, guard, impact, pulse, trace

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
        return guard.gate(tenant, user_id, "customer_trace") or trace.customer_trace(tenant, user_id, customer).as_dict()

    @mcp.tool(annotations=READ)
    def order_detail(order: Annotated[str, Field(min_length=1, max_length=40, description="order number, e.g. #4581")]) -> dict:
        """One order and only what hangs off it: items, payment, delivery with every scan, refunds, tickets and
        commitments. Use this whenever a specific order is named."""
        return guard.gate(tenant, user_id, "order_detail") or focus.order_detail(tenant, user_id, order).as_dict()

    @mcp.tool(annotations=READ)
    def decision_detail(decision: Annotated[str, Field(min_length=2, max_length=200, description="the decision's title "
                                                       "words or id")]) -> dict:
        """One decision: what it assumed, what the data shows now, which hubs it affects, what it overlaps with
        and which decisions rely on it. Use this whenever a specific decision or plan is named."""
        return guard.gate(tenant, user_id, "decision_detail") or focus.decision_detail(tenant, user_id, decision).as_dict()

    @mcp.tool(annotations=READ)
    def hub_status(hub: Annotated[str, Field(min_length=2, max_length=40, description="e.g. Hub W2")]) -> dict:
        """One hub now: courier, capacity, parcels there and late, on-time this week, busiest day, and the
        decisions that affect it."""
        return guard.gate(tenant, user_id, "hub_status") or focus.hub_status(tenant, user_id, hub).as_dict()

    @mcp.tool(annotations=READ)
    def product_status(item: Annotated[str, Field(min_length=2, max_length=60, description="a product title or a batch, "
                                                  "e.g. Knife Set or B7")], days: Annotated[int, Field(ge=1, le=90)] = 30) -> dict:
        """A product or batch: orders containing it, complaints and returns on those orders, by issue."""
        return guard.gate(tenant, user_id, "product_status") or focus.product_status(tenant, user_id, item, days).as_dict()

    @mcp.tool(annotations=READ)
    def open_loops(customer: Id) -> dict:
        """What is still open for a customer: open tickets, open or broken promises, late parcels, unrefunded returns."""
        return guard.gate(tenant, user_id, "open_loops") or trace.open_loops(tenant, user_id, customer).as_dict()

    @mcp.tool(annotations=READ)
    def related_issues(ticket_id: Id, days: Annotated[int, Field(ge=1, le=30)] = 7) -> dict:
        """Other recent tickets through the same hub, courier, batch or campaign as this ticket."""
        return guard.gate(tenant, user_id, "related_issues") or trace.related_issues(tenant, user_id, ticket_id, days).as_dict()

    @mcp.tool(annotations=READ)
    def search_tickets(text: Annotated[str, Field(min_length=2, max_length=100)]) -> dict:
        """Full-text search of cleaned ticket summaries you are allowed to see."""
        return guard.gate(tenant, user_id, "search_tickets") or trace.search_tickets(tenant, user_id, text).as_dict()

    @mcp.tool(annotations=READ)
    def search_docs(text: Annotated[str, Field(min_length=2, max_length=200)] = "",
                    about: list[Id] | None = None) -> dict:
        """Company documents (policies, contracts, meeting notes, plans) you may read: passages matching the words,
        or about the given hubs, couriers, decisions or campaigns. Refer to a document by its title."""
        return docs.search_docs(tenant, user_id, text or None, about or []).as_dict()

    @mcp.tool(annotations=READ)
    def company_pulse(days: Annotated[int, Field(ge=1, le=30)] = 7) -> dict:
        """The state of the company this week (support, operations, marketing, finance), only the areas your
        role may read, with changes vs the week before already computed. Areas left out are listed in hidden."""
        return pulse.company_pulse(tenant, user_id, days).as_dict()

    @mcp.tool(annotations=READ)
    def cluster_incidents(days: Annotated[int, Field(ge=1, le=30)] = 7) -> dict:
        """Group recent tickets into incidents by what they share (community detection) and find each root hub."""
        return guard.gate(tenant, user_id, "cluster_incidents") or impact.cluster_incidents(tenant, days).as_dict()

    @mcp.tool(annotations=READ)
    def trace_decisions(hub_id: Id) -> dict:
        """Company decisions that affect a hub, the assumptions they rest on, the latest evidence, and links."""
        return guard.gate(tenant, user_id, "trace_decisions") or impact.trace_decisions(tenant, hub_id).as_dict()

    @mcp.tool(annotations=READ)
    def decision_impact(decision_id: Id) -> dict:
        """What rests on a decision: dependent decisions, keystone rank, parcels in transit, customers and
        promises at risk."""
        return guard.gate(tenant, user_id, "decision_impact") or impact.decision_impact(tenant, decision_id).as_dict()

    @mcp.tool(annotations=READ)
    def prelaunch_check() -> dict:
        """Scheduled campaigns that would go through a hub whose assumptions are already broken, with a reroute."""
        return guard.gate(tenant, user_id, "prelaunch_check") or impact.prelaunch_check(tenant).as_dict()

    @mcp.tool(annotations=READ)
    def reroute(from_hub: Id, avoid_hub: Id) -> dict:
        """Fastest path to another last-mile hub in the same region that avoids a hub."""
        return guard.gate(tenant, user_id, "reroute") or impact.reroute(tenant, from_hub, avoid_hub).as_dict()

    @mcp.tool(annotations=READ)
    def find_approver(amount: Annotated[float, Field(gt=0)]) -> dict:
        """Who can approve a refund of this amount: you, or the nearest manager whose limit covers it."""
        return guard.gate(tenant, user_id, "find_approver") or impact.find_approver(tenant, user_id, amount).as_dict()

    @mcp.tool(annotations=READ)
    def choke_points() -> dict:
        """Hubs that sit on the most delivery routes (betweenness centrality)."""
        return guard.gate(tenant, user_id, "choke_points") or impact.choke_points(tenant).as_dict()

    @mcp.tool(annotations=READ)
    def recall(about: Id) -> dict:
        """Earlier findings about a customer, ticket, hub, incident or decision, newest first, with dates."""
        v = guard.Viewer.load(tenant, user_id)  # findings may be about customers or operations
        if v is None or not {"support", "operations"} & set(v.areas):
            return guard.gate(tenant, user_id, "customer_trace") or {"outcome": "not_permitted"}
        return actions.recall(tenant, about).as_dict()

    if read_only:
        return mcp

    @mcp.tool(annotations=NEEDS_PERSON)
    def issue_refund(order_id: Id, amount: Annotated[float, Field(gt=0)]) -> dict:
        """Refund an order, within your limit. Over the limit it returns who must approve instead."""
        return guard.gate(tenant, user_id, "issue_refund") or actions.issue_refund(tenant, user_id, order_id, amount, run_id).as_dict()

    @mcp.tool(annotations=WRITE)
    def record_promise(ticket_id: Id, order_id: Id, kind: Literal["refund", "delivery"],
                       due_in_hours: Annotated[float, Field(gt=0, le=24 * 30)]) -> dict:
        """Propose a promise found in the agent's own reply. A person or the matching action confirms it."""
        return guard.gate(tenant, user_id, "record_promise") or actions.record_promise(tenant, user_id, ticket_id, order_id, kind, due_in_hours, run_id).as_dict()

    @mcp.tool(annotations=NEEDS_PERSON)
    def confirm_promise(promise_id: Id) -> dict:
        """Confirm a proposed promise (a person does this)."""
        return guard.gate(tenant, user_id, "confirm_promise") or actions.confirm_promise(tenant, user_id, promise_id).as_dict()

    @mcp.tool(annotations=NEEDS_PERSON)
    def file_incident(title: Annotated[str, Field(min_length=3, max_length=200)],
                      ticket_ids: Annotated[list[str], Field(min_length=1, max_length=200)], root_hub: Id) -> dict:
        """File an incident linking the clustered tickets to their root hub."""
        return guard.gate(tenant, user_id, "file_incident") or actions.file_incident(tenant, user_id, title, ticket_ids, root_hub, run_id).as_dict()

    @mcp.tool(annotations=WRITE)
    def evaluate_assumptions() -> dict:
        """Check every decision's assumptions against the latest data and record the evidence."""
        return guard.gate(tenant, user_id, "evaluate_assumptions") or actions.evaluate_assumptions(tenant).as_dict()

    @mcp.tool(annotations=NEEDS_PERSON)
    def notify_owner(decision_id: Id, message: Annotated[str, Field(min_length=3, max_length=600)]) -> dict:
        """Send the decision's owner a note with the evidence and the path."""
        return guard.gate(tenant, user_id, "notify_owner") or actions.notify_owner(tenant, user_id, decision_id, message, run_id).as_dict()

    @mcp.tool(annotations=WRITE)
    def write_finding(about: Annotated[list[str], Field(min_length=1, max_length=20)],
                      text: Annotated[str, Field(min_length=3, max_length=600)]) -> dict:
        """Remember a conclusion, tied to the things it is about, for the next session."""
        return actions.write_finding(tenant, user_id, about, text, run_id).as_dict()

    return mcp
