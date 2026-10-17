"""Minimise: normalise and keyed-hash matching identifiers, redact free text.

Raw values exist only in memory while an event is processed; they are never written anywhere.
"""

import calendar
import hashlib
import hmac
import re

import phonenumbers

from sinew import config


def tenant_key(tenant: str) -> bytes:
    key = config.env(f"HASH_KEY_{tenant.upper()}")
    if not key:
        raise RuntimeError(f"no hashing key for tenant {tenant}")
    return bytes.fromhex(key)


def normalise(kind: str, value: str, country: str | None = None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if kind == "email":
        return value.lower()
    if kind == "handle":
        return value.lower().lstrip("@")
    if kind == "phone":
        try:
            num = phonenumbers.parse(value, (country or "").upper() or None)
        except phonenumbers.NumberParseException:
            return None
        if not phonenumbers.is_valid_number(num):
            return None
        return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    return value


def keyed_hash(tenant: str, kind: str, normalised: str) -> str:
    digest = hmac.new(tenant_key(tenant), f"{kind}:{normalised}".encode(), hashlib.sha256).hexdigest()
    return f"{kind}:{digest[:32]}"


# Structured identifiers: regex. Names: Presidio's PERSON recogniser (spaCy small model).
_PATTERNS = [
    ("[EMAIL]", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("[CARD]", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("[PHONE]", re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d")),
    ("[HANDLE]", re.compile(r"(?<!\w)@\w{2,}")),
]


# Second layer for names the model misses: a capitalised name after a common self-introduction or sign-off.
_NAME = r"[A-Z][a-z'’-]+(?:\s+[A-Z][a-z'’-]+){0,2}"
_NAME_CUES = re.compile(
    rf"(?:\b(?:I'm|I am|This is|this is|My name is|my name is|Regards,?|Thanks,?|Thank you,?|Cheers,?)\s+|^\s*-\s*|\s-\s+)({_NAME})",
    re.MULTILINE,
)

_analyzer = None
WITHHELD = "[text withheld: name check unavailable]"


def _names_analyzer():
    global _analyzer
    if _analyzer is None:
        import logging

        for name in ("presidio-analyzer", "presidio_analyzer", "presidio-anonymizer"):
            logging.getLogger(name).setLevel(logging.ERROR)
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        nlp = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }).create_engine()
        _analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
    return _analyzer


_OWN_WORDS = {"sinew"}  # our own name appears in company documents; it is not a person
_CALENDAR = {w.lower() for w in (*calendar.month_name, *calendar.month_abbr, *calendar.day_name, *calendar.day_abbr) if w}


def redact(text: str, allow: frozenset[str] = frozenset()) -> str:
    """Remove names, emails, phones, cards and handles. Fails closed: no name check, no text.

    `allow` holds the company's own business words (product titles); the name model sometimes takes
    "Hand Mixer" for a person, which would blank the meaning of the ticket.
    """
    try:
        found = _names_analyzer().analyze(text=text, language="en", entities=["PERSON"])
    except Exception:
        return WITHHELD
    # Codes like "B7" or "W2" are business ids, not people; nor are month and day names ("due on 15 Oct").
    def business(span: str) -> bool:
        s = span.lower().strip(" .,!?;:'\"")
        return any(ch.isdigit() for ch in s) or s in _CALENDAR or s in _OWN_WORDS or any(s in a for a in allow)

    spans = sorted((r for r in found if not business(text[r.start:r.end])), key=lambda r: r.start, reverse=True)
    for r in spans:
        text = text[:r.start] + "[NAME]" + text[r.end:]
    text = _NAME_CUES.sub(lambda m: m.group(0)[: m.start(1) - m.start(0)] + "[NAME]", text)
    for token, pattern in _PATTERNS:
        text = pattern.sub(token, text)
    return text
