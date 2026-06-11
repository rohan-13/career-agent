"""Targeting filters: single source of truth for new-grad/entry-level matching.

Title-level seniority words exclude; years-of-experience requirements exclude
anywhere (title or description). Include + role signals are checked on the
title (plus description for include signals).
"""
import re

INCLUDE_PATTERNS = [
    r"new[\s-]*grad",
    r"university\s+grad",
    # Grad year is hardcoded; bump to 2028 listings when the 2027 cycle ends.
    r"class\s+of\s+2027",
    r"\b2027\b",
    r"entry[\s-]*level",
    r"early\s+career",
    r"\bjunior\b",
    r"engineer\s+i\b",
    r"\bswe\s+i\b",
    r"0\s*[-–]\s*2\s+years",
    r"recent\s+grad",
]

TITLE_EXCLUDE_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\bstaff\b",
    r"\bprincipal\b",
    r"\blead\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bintern(ship)?s?\b",
]

TEXT_EXCLUDE_PATTERNS = [
    r"\b([3-9]|\d{2,})\s*\+?\s*years",
]

ROLE_PATTERNS = [
    r"software\s+engineer",
    r"data\s+scien",
    r"data\s+engineer",
    r"machine\s+learning",
    r"\bml\s+engineer",
    r"\bai\s+engineer",
    r"analytics\s+engineer",
    r"\bswe\b",
    r"software\s+develop",
    r"\bdeveloper\b",
    r"\b(back[\s-]?end|front[\s-]?end|full[\s-]?stack|platform|systems?|infrastructure|site\s+reliability|cloud|security|devops|embedded)[\s-]+engineer",
    r"data\s+analyst",
    r"\bmle\b",
    r"\bsde\b",
]


def _any(patterns, text):
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def is_target(title, description=""):
    text = f"{title} {description}"
    if _any(TITLE_EXCLUDE_PATTERNS, title) or _any(TEXT_EXCLUDE_PATTERNS, text):
        return False
    return _any(ROLE_PATTERNS, title) and _any(INCLUDE_PATTERNS, text)


def match_strength(title):
    """Ranking refinement (0-3) for titles that already passed is_target().

    Title-only by design: it does not re-check role/exclude/description, so a
    non-zero score does NOT mean the job is a target. Filter first, then rank.
    """
    if _any([r"new[\s-]*grad", r"class\s+of\s+2027", r"\b2027\b", r"university\s+grad"], title):
        return 3
    if _any([r"entry[\s-]*level", r"early\s+career", r"recent\s+grad"], title):
        return 2
    if _any([r"\bjunior\b", r"engineer\s+i\b", r"\bswe\s+i\b", r"0\s*[-–]\s*2\s+years"], title):
        return 1
    return 0
