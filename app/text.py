import re
import unicodedata
from datetime import datetime

EDITION_WORDS = (
    "definitive", "deluxe", "complete", "ultimate", "game of the year", "goty", "enhanced",
    "remastered", "special", "anniversary", "collectors", "collector s", "gold", "standard",
    "digital", "director s cut", "directors cut", "nintendo switch 2", "switch 2", "switch",
    "ps4", "ps5", "edition", "hd", "the",
)
_EDITION_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in EDITION_WORDS) + r")\b")


def norm(s):
    """Lowercase, strip accents and punctuation, collapse spaces."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"'s\b", "s", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_edition(s):
    """Normalized title without edition / platform words."""
    s = _EDITION_RE.sub(" ", norm(s))
    return re.sub(r"\s+", " ", s).strip()


def parse_date(s):
    """Parse 'Oct 31, 2024', '10/21/2019' or ISO dates into YYYY-MM-DD."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    m = re.search(r"\b(19|20)\d{2}\b", s)
    if m:
        return m.group(0) + "-01-01"
    return None


def year_of(date):
    return int(date[:4]) if date and len(date) >= 4 and date[:4].isdigit() else None
