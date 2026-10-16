"""The model behind the agents, behind one small interface so the provider can change in one place.

Gemini free tier (project "sinew", read in AI Studio 2026-10-16): Flash-Lite models allow 15 requests/min
and 500/day; Flash models only 20/day. So: 3.5 Flash-Lite first, 3.1 Flash-Lite if it is busy or out of
quota. If both fail, the loop falls back to a recorded replay.
"""

import asyncio
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from sinew import config

MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


@dataclass
class Turn:
    text: str = ""
    calls: list[dict] = field(default_factory=list)  # [{"name": ..., "args": {...}}]
    model: str = ""


class LLMUnavailable(Exception):
    pass


class Gemini:
    def __init__(self, models: list[str] | None = None):
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

    async def next(self) -> Turn:
        last_error = None
        for model in self.models:
            for attempt in range(2):
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
                    if attempt == 0 and ("503" in str(e) or "429" in str(e)):
                        await asyncio.sleep(2)
                        continue
                    break
        raise LLMUnavailable(str(last_error)[:200])

    def add_results(self, results: list[tuple[str, dict]]):
        self.history.append(types.Content(role="user", parts=[
            types.Part.from_function_response(name=name, response=result) for name, result in results]))
