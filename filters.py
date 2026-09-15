"""Targeting filters: single source of truth for new-grad/entry-level matching.

Title-level seniority words exclude; years-of-experience requirements exclude
anywhere (title or description). Include + role signals are checked on the
title (plus description for include signals). Location must show a US
presence or be remote (see `is_us_or_remote`) -- added 2026-09-14 after
Canada-only and UK-only postings (e.g. Atlassian/Capital One in Canada,
Norton Rose Fulbright/American Express in the UK) kept showing up in the
Docket for a US-based candidate who can't take them.
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


# US state 2-letter codes, matched as ", XX" (comma-space-code) to avoid
# false positives on unrelated 2-letter substrings elsewhere in a location
# string.
_US_STATE_RE = re.compile(
    r",\s*(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|"
    r"MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|"
    r"VT|VA|WA|WV|WI|WY|DC)\b"
)
_US_SIGNAL_RE = re.compile(r"\b(usa|u\.s\.a\.?|united states|u\.s\.)\b", re.IGNORECASE)
_BARE_REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
# Separator is OPTIONAL: Greenhouse renders this as "Remote Canada" (bare
# space, no punctuation) while Workday/GitHub trackers use "Remote - Canada".
# Found live 2026-09-14 -- the dash-required version let "Remote Canada"
# through as if it were unqualified bare-remote.
_REMOTE_QUALIFIER_RE = re.compile(r"remote\s*[-–(,]?\s*([a-z][a-z .]*)", re.IGNORECASE)

# Countries/regions that show up often enough in these trackers to be worth
# naming explicitly (Workday "locationsText" and GitHub tracker location
# columns both commonly read "Remote - {Country}" or "{City}, {Country}").
# Not exhaustive by design -- an unrecognized location with no US signal and
# no "remote" falls through to the permissive default below rather than
# being excluded, since ambiguous strings like "SF"/"NYC"/"LA" (no state,
# no country) are common and are almost always US postings in this pipeline.
_NON_US_COUNTRY_RE = re.compile(
    r"\b(canada|united\s+kingdom|\buk\b|india|germany|mexico|brazil|ukraine|"
    r"bulgaria|ireland|poland|singapore|australia|france|netherlands|spain|"
    r"israel|philippines|china|japan|italy|sweden|switzerland|portugal|"
    r"romania|czech(?:ia)?|hungary|austria|belgium|denmark|norway|finland|"
    r"greece|argentina|colombia|chile|peru|indonesia|vietnam|thailand|"
    r"malaysia|new\s+zealand|south\s+africa|egypt|turkey|russia)\b",
    re.IGNORECASE,
)
_CANADA_PROVINCE_RE = re.compile(r",\s*(?:AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\b")


def is_us_or_remote(location):
    """True if `location` shows a US presence, is remote, or gives no
    location signal at all (missing data isn't treated as disqualifying --
    only an EXPLICIT non-US-only location is excluded). False only when the
    location is recognizably non-US (a Canadian province, a named non-US
    country) with no accompanying US or bare-remote signal."""
    loc = (location or "").strip()
    if not loc:
        return True

    if _US_STATE_RE.search(loc) or _US_SIGNAL_RE.search(loc):
        return True

    # "Remote - Canada" / "Remote - Ukraine" names an explicit non-US country
    # even though the string also contains "remote" -- bare "Remote" (no
    # qualifier) is exactly what the user wants kept.
    m = _REMOTE_QUALIFIER_RE.search(loc)
    if m:
        return not _NON_US_COUNTRY_RE.search(m.group(1))

    if _BARE_REMOTE_RE.search(loc):
        return True

    if _CANADA_PROVINCE_RE.search(loc) or _NON_US_COUNTRY_RE.search(loc):
        return False

    return True


def is_target(title, description="", location=""):
    text = f"{title} {description}"
    if _any(TITLE_EXCLUDE_PATTERNS, title) or _any(TEXT_EXCLUDE_PATTERNS, text):
        return False
    if not is_us_or_remote(location):
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
