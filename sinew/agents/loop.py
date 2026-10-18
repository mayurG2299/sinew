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

from sinew import brain
from sinew.agents import check, prompts
from sinew.agents.llm import Gemini, LLMUnavailable
from sinew.engine import snapshot
from sinew.mcp_server import build_server
from sinew.tools import actions, docs

REPLAYS = Path(__file__).resolve().parents[2] / "seed" / "replays"
MAX_STEPS = 8
RESULT_CHARS = 16000  # what the model sees of one tool result; the UI gets all of it


def for_model(result: dict) -> str:
    """A tool result as the model sees it: without the graph paths (those are for drawing), and if it is still
    too long, a timeline newest first, so a cut drops the oldest events, never the order being asked about."""
    slim = {k: v for k, v in result.items() if k != "paths"}
    text = json.dumps(slim, default=str)
    timeline = (slim.get("data") or {}).get("timeline") if isinstance(slim.get("data"), dict) else None
    if len(text) > RESULT_CHARS and timeline:
        slim = {**slim, "data": {**slim["data"], "timeline": list(reversed(timeline)), "timeline_order": "newest first"}}
        text = json.dumps(slim, default=str)
    return text[:RESULT_CHARS]


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
    repaired: str = ""  # what the first answer got wrong, when one corrected rewrite passed the check
    plan: dict = field(default_factory=dict)  # how the question was understood and broken down
    queries: list = field(default_factory=list)  # the Cypher the graph walks ran, to show with the answer
    draft: str = ""  # the answer written from the fact sheet alone (used if the model can't do better)

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


async def run_agent(tenant: str, user_id: str, agent: str, task: str, llm=None, history: list[str] | None = None) -> Run:
    start = time.perf_counter()
    snapshot.ensure_loaded(tenant)
    run = Run(run_id=f"run-{uuid.uuid4().hex[:10]}", agent=agent, task=task)
    allowed = prompts.TOOLS[agent]
    server = build_server(tenant, user_id, run_id=run.run_id)
    # The analysis layer goes first: understand and break down the question, walk the graph from what it
    # names (as this person), reconcile into a fact sheet, and write a correct draft from it. The model
    # then only rewrites the draft for the person; it may call more read tools if something is missing.
    unavailable: LLMUnavailable | None = None
    try:
        llm = llm or Gemini()
    except LLMUnavailable as e:  # no key, switched off: the word patterns read the question and the graph answers
        unavailable, llm = e, None
    plan, per_part, sheet = await brain.analyse(tenant, user_id, task, history or [], llm)
    for got in per_part:
        for result in got:
            call = result.pop("_call", {})
            if result not in run.results:
                run.results.append(result)
                run.steps.append({"tool": call.get("tool", result.get("tool")), "args": call.get("args", {}),
                                  "outcome": result.get("outcome"), "ms": call.get("ms"),
                                  "tool_ms": result.get("ms"), "by": "graph"})
    run.queries = [{"ask": r["data"].get("ask", ""), "path": r["data"]["path"], "cypher": r["data"]["cypher"],
                    "columns": r["data"]["columns"], "rows": r["data"]["rows"][:10]}
                   for r in run.results if r.get("tool") == "graph_query" and r.get("data", {}).get("cypher")]
    run.plan = {"parts": [{"ask": p["ask"], "intents": p["intents"], "named": p["named"], "status": p["status"]}
                          for p in sheet["parts"]], "window": sheet["window"]}
    run.draft = brain.write(sheet)
    for act in sheet.get("actions", []):  # actions the facts call for, offered only if this person may take them
        if not actions.precheck(tenant, user_id, act["name"], act["args"]):
            run.pending_actions.append(act)
    try:
        if llm is None:
            raise unavailable or LLMUnavailable("no model")
        async with Client(server) as mcp:
            listed = [t for t in (await mcp.list_tools()).tools if t.name in allowed]
            destructive = {t.name for t in listed if t.annotations and t.annotations.destructive_hint}
            message = (f"{task}\n\nSinew analysed this question and walked the company graph for this person "
                       f"(permissions applied). Fact sheet:\n{brain.for_model(sheet)}\n\n"
                       f"Correct draft written from the fact sheet:\n{run.draft}\n\n"
                       "Rewrite the draft as your answer for this person: keep every fact and number, add nothing that "
                       "is not in the fact sheet, follow the format rules. Do not leave out any line of the draft: you may reorder, "
                       "merge lines about the same thing and improve the wording, nothing else. Keep each number attached to the same thing it "
                       "is attached to in the draft; never join facts from different lines into one sentence. Keep any \"What to do:\" lines exactly as "
                       "written, and keep the note that an overlap is not proof of cause. Call a tool only if something "
                       "asked is missing.")
            llm.start(prompts.SYSTEM[agent], [{"name": t.name, "description": t.description or "",
                                               "input_schema": t.input_schema} for t in listed], message)
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
                    elif call["name"] in destructive and (block := actions.precheck(tenant, user_id, call["name"], call["args"])):
                        result = {**block, "reason": f"not offered: {block.get('reason')}; don't mention this action"}
                    elif call["name"] in destructive:
                        if all(p["name"] != call["name"] for p in run.pending_actions):  # one button per kind
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
                    replies.append((call["name"], {"result": for_model(result)}))
                llm.add_results(replies)
            # One repair turn: if the answer breaks a rule, say exactly which and let the model rewrite it from
            # the same tool results (no new tools). The rewrite is checked again like any answer.
            if run.answer and run.results and hasattr(llm, "add_user"):
                ok, why = check.check(run.answer, run.results, task, brain.for_model(sheet))
                if ok and _ignores_rows(run):
                    ok, why = False, "mentions nothing the graph query found (state what it returned)"
                if not ok:
                    llm.add_user(f"Your answer failed Sinew's fact check: it {why}. Rewrite the answer using only "
                                 "names and numbers that appear in the tool results, following every rule. "
                                 "Do not call any tools.")
                    try:
                        fix = await llm.next()
                        if fix.text and not fix.calls and check.check(fix.text.strip(), run.results, task, brain.for_model(sheet))[0]:
                            kept_answer, run.answer = run.answer, fix.text.strip()
                            if _ignores_rows(run):  # still ignores the finding: keep the first answer, the final check falls back
                                run.answer = kept_answer
                            else:
                                run.repaired = why
                    except LLMUnavailable:
                        pass  # keep the first answer; the check below falls back to the rows
    except LLMUnavailable as e:  # e.g. no API key: raised before the session opens
        unavailable = e
    if unavailable is not None:
        e = unavailable
        if run.draft:  # the analysis layer already wrote a correct answer from the graph
            run.answer, run.answer_source = check.paragraphs(run.draft), "graph"
            run.check_failed = f"model unavailable: {str(e)[:120]}"
            run.ms = round((time.perf_counter() - start) * 1000, 1)
            run.sources = docs.sources(tenant, user_id, run.results, task, answer=run.answer)
            return run
        replay = _load_replay(tenant, user_id, agent, task)
        if replay:
            replay.ms = round((time.perf_counter() - start) * 1000, 1)
            replay.sources = docs.sources(tenant, user_id, replay.results, task, answer=replay.answer)
            return replay
        run.answer = run.draft or (check.fallback(run.results) if run.results else
                                   f"The AI is unavailable right now ({e}). The graph tools still work.")
        run.answer_source, run.check_failed = "rows", f"model unavailable: {str(e)[:120]}"
        run.ms = round((time.perf_counter() - start) * 1000, 1)
        return run
    ok, why = check.check(run.answer, run.results, task, brain.for_model(sheet)) if run.answer else (False, "the model gave no answer")
    if ok and not run.queries:  # the rewrite must keep what the graph found: if it dropped the draft's numbers, the draft is the answer
        share, left = check.coverage(run.draft, run.answer)
        if share < 0.75:
            ok, why = False, f"the rewrite left out facts from the graph ({', '.join(left[:4])})"
    if ok and _ignores_rows(run):
        ok, why = False, "the rewrite mentions nothing the graph query found"  # the walk answered; the draft says what it found
    if not ok:
        run.check_failed, run.answer, run.answer_source = why, check.paragraphs(run.draft) or check.fallback(run.results), "rows"
    else:
        run.answer = check.plain(run.answer)
    run.ms = round((time.perf_counter() - start) * 1000, 1)
    if run.answer_source == "model":
        _save_replay(tenant, user_id, run)
    run.sources = docs.sources(tenant, user_id, run.results, task, answer=run.answer)
    return run


def _ignores_rows(run: Run) -> bool:
    """The walk found something and the answer mentions none of it."""
    return bool(run.answer and run.queries) and not any(check.uses_rows(q["rows"], run.answer) for q in run.queries)


def run_sync(tenant: str, user_id: str, agent: str, task: str) -> Run:
    return asyncio.run(run_agent(tenant, user_id, agent, task))
