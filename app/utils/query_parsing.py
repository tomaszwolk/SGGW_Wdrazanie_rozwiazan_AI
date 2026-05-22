import re

DATE_PATTERN = re.compile(
    r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$|^\d{4}[./-]\d{1,2}[./-]\d{1,2}$"
)

INVOICE_ANCHOR = re.compile(
    r"(?:faktur\w*|\bfv\b|invoice)"
    r"(?:\s*(?:nr|no|numer|number))?\.?\s*[:#]?\s*"
    r"(?P<id>[\w/\-]+)",
    re.IGNORECASE,
)

IDENTIFIER_FALLBACK = re.compile(r"\b(?P<id>[A-Za-z]{0,10}\d[\w/\-]{2,39})\b")

DIGIT_FALLBACK = re.compile(r"\b(?P<id>\d{6,})\b")

MIN_CANDIDATE_LEN = 3


def _normalize_candidate(raw: str) -> str:
    return raw.strip().strip(".,;:!?\"'")


def _is_date_like(candidate: str) -> bool:
    return bool(DATE_PATTERN.match(candidate))


def _add_candidate(candidates: list[str], seen: set[str], raw: str) -> None:
    candidate = _normalize_candidate(raw)
    if len(candidate) < MIN_CANDIDATE_LEN or _is_date_like(candidate):
        return
    key = candidate.lower()
    if key in seen:
        return
    seen.add(key)
    candidates.append(candidate)


def extract_invoice_number_candidates(text: str) -> list[str]:
    """Extract invoice id fragments for SQLite LIKE search (keyword anchor + fallback)."""
    seen: set[str] = set()
    candidates: list[str] = []

    for match in INVOICE_ANCHOR.finditer(text):
        _add_candidate(candidates, seen, match.group("id"))

    if candidates:
        return candidates

    for match in IDENTIFIER_FALLBACK.finditer(text):
        _add_candidate(candidates, seen, match.group("id"))

    for match in DIGIT_FALLBACK.finditer(text):
        _add_candidate(candidates, seen, match.group("id"))

    return candidates
