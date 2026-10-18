"""The model behind the agents, behind one small interface so the provider can change in one place.

Gemini free tier (project "sinew", read in AI Studio 2026-10-16): Flash-Lite models allow 15 requests/min
and 500/day; Flash models only 20/day. So: 3.5 Flash-Lite first, 3.1 Flash-Lite if it is busy or out of
quota. If both fail, the loop falls back to a recorded replay.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from google import genai
from google.genai import types

from sinew import config

MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
# Our own ceiling per model, below each model's free 500/day, so Sinew never spends money even if billing were on.
DAILY_CAP = int(os.environ.get("GEMINI_DAILY_CAP", "450"))
USAGE = Path(os.environ.get("SINEW_USAGE_FILE", Path(__file__).resolve().parents[2] / ".sinew-usage.json"))


def _exhausted(model: str) -> bool:
    try:
        return model in json.loads(USAGE.read_text()).get("exhausted:" + time.strftime("%Y-%m-%d", time.gmtime()), [])
    except Exception:
        return False


def _mark_exhausted(model: str) -> None:
    key = "exhausted:" + time.strftime("%Y-%m-%d", time.gmtime())
    try:
        usage = json.loads(USAGE.read_text())
        usage[key] = sorted(set(usage.get(key, [])) | {model})
        USAGE.write_text(json.dumps(usage))
    except Exception:
        pass


def _count_call(model: str) -> bool:
    """Count one call to this model for today (UTC). False once today's cap for it is reached: each model's free
    tier is separate (500 a day), so each has its own cap below that."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    try:
        usage = json.loads(USAGE.read_text())
    except Exception:
        usage = {}
    key = f"{today}:{model}"
    if usage.get(key, 0) >= DAILY_CAP:
        return False
    try:
        keep = {k: v for k, v in usage.items() if today in k}  # today's entries only
        USAGE.write_text(json.dumps({**keep, key: usage.get(key, 0) + 1}))
    except OSError:
        pass  # read-only disk: the provider's own free limit still applies
    return True


@dataclass
class Turn:
    text: str = ""
    calls: list[dict] = field(default_factory=list)  # [{"name": ..., "args": {...}}]
    model: str = ""


class LLMUnavailable(Exception):
    pass


class Gemini:
    def __init__(self, models: list[str] | None = None):
        if os.environ.get("SINEW_AI") == "off":  # tests and quota-free runs: answers come from the fact sheet
            raise LLMUnavailable("the AI is switched off")
        if not config.GEMINI_API_KEY:
            raise LLMUnavailable("GEMINI_API_KEY is not set")
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.models = models or MODELS
        self.history: list[types.Content] = []

    def start(self, system: str, tools: list[dict], user_message: str):
        self.config = types.GenerateContentConfig(
            system_instruction=system, temperature=0.2,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t["description"],
                                          parameters_json_schema=t["input_schema"]) for t in tools])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self.history = [types.Content(role="user", parts=[types.Part.from_text(text=user_message)])]

    async def plan(self, system: str, user: str) -> dict:
        """One stateless call that returns JSON: the model's reading of a question (no tools, no answer)."""
        last_error = None
        for model in self.models:
            if _exhausted(model):
                continue
            if not _count_call(model):
                last_error = f"today's free limit for {model} ({DAILY_CAP} calls) is used up"
                continue
            try:
                r = await self.client.aio.models.generate_content(
                    model=model, contents=user,
                    config=types.GenerateContentConfig(system_instruction=system, temperature=0,
                                                       response_mime_type="application/json"))
                import json as _json
                return _json.loads(r.text or "{}")
            except Exception as e:  # quota, busy, or malformed JSON: next model, then the caller falls back
                last_error = e
                if "429" in str(e) and "perday" in str(e).lower().replace(" ", ""):
                    _mark_exhausted(model)
        raise LLMUnavailable(str(last_error or "no model available")[:200])

    async def next(self) -> Turn:
        last_error = None
        for model in self.models:
            if _exhausted(model):
                continue
            for attempt in range(2):
                if not _count_call(model):
                    last_error = f"today's free limit for {model} ({DAILY_CAP} calls) is used up"
                    break
                try:
                    r = await self.client.aio.models.generate_content(model=model, contents=self.history,
                                                                     config=self.config)
                    content = r.candidates[0].content
                    self.history.append(content)
                    calls = [{"name": c.name, "args": dict(c.args or {})} for c in (r.function_calls or [])]
                    text = "" if calls else (r.text or "")
                    return Turn(text=text, calls=calls, model=model)
                except Exception as e:  # 429 quota / 503 busy: short wait, then the next model
                    last_error = e
                    if "429" in str(e) and "perday" in str(e).lower().replace(" ", ""):
                        _mark_exhausted(model)  # today's free quota for this model is gone: skip it until tomorrow
                        break
                    if attempt == 0 and ("503" in str(e) or "429" in str(e)):
                        await asyncio.sleep(2)
                        continue
                    break
        raise LLMUnavailable(str(last_error or "today's free AI limit is used up")[:200])

    def add_user(self, text: str):
        """A follow-up message from Sinew itself (used once, to ask for a corrected answer)."""
        self.history.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))

    def add_results(self, results: list[tuple[str, dict]]):
        self.history.append(types.Content(role="user", parts=[
            types.Part.from_function_response(name=name, response=result) for name, result in results]))
