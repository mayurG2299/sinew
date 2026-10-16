"""Every tool returns the same shape (the answer contract, RESOURCES.md R1).

outcome:
  answered_path    the graph held the relationships; `paths` shows the hops
  answered_memory  returned from an earlier Finding (with its date)
  not_in_graph     the entity exists but nothing matches the question (not the same as "nothing wrong")
  unknown_entity   the id isn't in the graph, so no query ran
  not_permitted    the guard refused; `reason` says why
"""

from dataclasses import asdict, dataclass, field


@dataclass
class Answer:
    tool: str
    outcome: str
    data: dict | list = field(default_factory=dict)
    paths: list[list[str]] = field(default_factory=list)
    hidden: list[dict] = field(default_factory=list)
    reason: str = ""
    ms: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def unknown(tool: str, what: str) -> Answer:
    return Answer(tool, "unknown_entity", reason=f"{what} is not in the graph; no query was run")


def refused(tool: str, reason: str) -> Answer:
    return Answer(tool, "not_permitted", reason=reason)
