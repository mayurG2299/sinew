"""Our own agent loop: the model picks MCP tools, the guard checks them, code checks the answer.

- Tools come from Sinew's MCP server, built for the signed-in person (the model can't change who it acts as).
- Tools marked destructive (refunds, confirmations, incidents, notifications) are not run: they become
  pending actions for a person to confirm in the UI.
- Every step is logged (tool, arguments, outcome, ms) for the run-trace panel.
- The final answer must pass the sentence check, or a sentence built from the rows is shown instead.
- If the model is unavailable, the last good run of the same task is replayed, clearly labelled.
"""

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mcp import Client

from sinew.agents import check, prompts
from sinew.agents.llm import Gemini, LLMUnavailable
from sinew.engine import snapshot
from sinew.mcp_server import build_server
from sinew.tools import docs

REPLAYS = Path(__file__).resolve().parents[2] / "seed" / "replays"
MAX_STEPS = 8
RESULT_CHARS = 6000  # what the model sees of one tool result; the UI gets all of it


@dataclass
class Run:
    run_id: str
    agent: str
    task: str
    answer: str = ""
    answer_source: str = "model"  # model | rows (sentence check failed) | replay
    check_failed: str = ""
    model: str = ""
    steps: list[dict] = field(default_factory=list)
    pending_actions: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    ms: float = 0.0
    model_ms: list[float] = field(default_factory=list)  # time spent waiting for the model, per turn
    sources: list[dict] = field(default_factory=list)  # document passages behind the answer, from the graph

    def as_dict(self) -> dict:
        return asdict(self)


def _key(tenant: str, user_id: str, agent: str, task: str) -> str:
    return hashlib.sha256(f"{tenant}|{user_id}|{agent}|{task.strip().lower()}".encode()).hexdigest()[:16]


def _save_replay(tenant, user_id, run: Run):
    REPLAYS.mkdir(parents=True, exist_ok=True)
    (REPLAYS / f"{_key(tenant, user_id, run.agent, run.task)}.json").write_text(json.dumps(run.as_dict(), default=str))


def _load_replay(tenant, user_id, agent, task) -> Run | None:
    p = REPLAYS / f"{_key(tenant, user_id, agent, task)}.json"
    if not p.exists():
        return None
    run = Run(**json.loads(p.read_text()))
    run.answer_source = "replay"
    return run


async def run_agent(tenant: str, user_id: str, agent: str, task: str, llm=None) -> Run:
    start = time.perf_counter()
    snapshot.ensure_loaded(tenant)
    run = Run(run_id=f"run-{uuid.uuid4().hex[:10]}", agent=agent, task=task)
    allowed = prompts.TOOLS[agent]
    server = build_server(tenant, user_id, run_id=run.run_id)
    unavailable: LLMUnavailable | None = None
    try:
        llm = llm or Gemini()
        async with Client(server) as mcp:
            listed = [t for t in (await mcp.list_tools()).tools if t.name in allowed]
            destructive = {t.name for t in listed if t.annotations and t.annotations.destructive_hint}
            llm.start(prompts.SYSTEM[agent], [{"name": t.name, "description": t.description or "",
                                               "input_schema": t.input_schema} for t in listed], task)
            for _ in range(MAX_STEPS):
                try:
                    t_model = time.perf_counter()
                    turn = await llm.next()
                    run.model_ms.append(round((time.perf_counter() - t_model) * 1000))
                except LLMUnavailable as e:  # caught here: raised inside the MCP session it would arrive wrapped
                    unavailable = e
                    break
                run.model = turn.model
                if not turn.calls:
                    run.answer = turn.text.strip()
                    break
                replies = []
                for call in turn.calls:
                    t0 = time.perf_counter()
                    if call["name"] not in allowed:
                        result = {"tool": call["name"], "outcome": "not_permitted", "reason": "tool not available"}
                    elif call["name"] in destructive:
                        run.pending_actions.append(call)
                        result = {"tool": call["name"], "outcome": "pending_confirmation",
                                  "reason": "waiting for the person to confirm; do not assume it happened"}
                    else:
                        out = await mcp.call_tool(call["name"], call["args"])
                        try:
                            result = json.loads(out.content[0].text)
                        except Exception:  # argument validation errors come back as plain text
                            result = {"tool": call["name"], "outcome": "error", "reason": out.content[0].text[:300]}
                        run.results.append(result)
                    run.steps.append({"tool": call["name"], "args": call["args"], "outcome": result.get("outcome"),
                                      "ms": round((time.perf_counter() - t0) * 1000, 1),
                                      "tool_ms": result.get("ms")})
                    replies.append((call["name"], {"result": json.dumps(result, default=str)[:RESULT_CHARS]}))
                llm.add_results(replies)
    except LLMUnavailable as e:  # e.g. no API key: raised before the session opens
        unavailable = e
    if unavailable is not None:
        e = unavailable
        replay = _load_replay(tenant, user_id, agent, task)
        if replay:
            replay.ms = round((time.perf_counter() - start) * 1000, 1)
            replay.sources = docs.sources(tenant, user_id, replay.results, task, answer=replay.answer)
            return replay
        run.answer = check.fallback(run.results) if run.results else \
            f"The AI is unavailable right now ({e}). The graph tools still work."
        run.answer_source, run.check_failed = "rows", f"model unavailable: {str(e)[:120]}"
        run.ms = round((time.perf_counter() - start) * 1000, 1)
        return run
    ok, why = check.check(run.answer, run.results, task) if run.answer else (False, "the model gave no answer")
    if not ok:
        run.check_failed, run.answer, run.answer_source = why, check.fallback(run.results), "rows"
    else:
        run.answer = check.plain(run.answer)
    run.ms = round((time.perf_counter() - start) * 1000, 1)
    if run.answer_source == "model":
        _save_replay(tenant, user_id, run)
    run.sources = docs.sources(tenant, user_id, run.results, task, answer=run.answer)
    return run


def run_sync(tenant: str, user_id: str, agent: str, task: str) -> Run:
    return asyncio.run(run_agent(tenant, user_id, agent, task))
