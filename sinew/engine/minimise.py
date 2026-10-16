"""Minimise: normalise and keyed-hash matching identifiers, redact free text.

Raw values exist only in memory while an event is processed; they are never written anywhere.
"""

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


_analyzer = None
WITHHELD = "[text withheld: name check unavailable]"


def _names_analyzer():
    global _analyzer
    if _analyzer is None:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        nlp = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }).create_engine()
        _analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
    return _analyzer


def redact(text: str) -> str:
    """Remove names, emails, phones, cards and handles. Fails closed: no name check, no text."""
    try:
        found = _names_analyzer().analyze(text=text, language="en", entities=["PERSON"])
    except Exception:
        return WITHHELD
    # Codes like "B7" or "W2" are business ids, not people.
    spans = sorted((r for r in found if not any(ch.isdigit() for ch in text[r.start:r.end])),
                   key=lambda r: r.start, reverse=True)
    for r in spans:
        text = text[:r.start] + "[NAME]" + text[r.end:]
    for token, pattern in _PATTERNS:
        text = pattern.sub(token, text)
    return text
