"""Load the KB and resolve entities mentioned in a question.

The LLM's only job (later) is to pick a shape. Everything here is
deterministic: entities are matched against the KB's own vocabulary, so a
question can only ever refer to something that actually exists.
"""
import json, re
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

class KB:
    def __init__(self):
        self.works = json.load(open(DATA / "works.json"))
        self.people = json.load(open(DATA / "people.json"))
        self.credentials = json.load(open(DATA / "credentials.json"))
        self.clients = sorted({w["client"] for w in self.works}, key=len, reverse=True)
        self.categories = sorted({w["category"] for w in self.works if w.get("category")},
                                 key=len, reverse=True)
        self.names = sorted({p["name"] for p in self.people if p.get("name")},
                            key=len, reverse=True)
        self.grades = ["Excellent", "Very Good", "Satisfactory", "Good"]  # longest first

    # ---------------- selectors
    def for_client(self, client):
        return [w for w in self.works if w["client"] == client]

    def led_by(self, person):
        return [w for w in self.works if w.get("project_manager") == person]

    def work_named(self, name):
        from common import work_key
        k = work_key(name)
        return next((w for w in self.works if w["key"] == k), None)

    def credential_of(self, person, ctype=None):
        holder = person.strip().lower()
        found = [c for c in self.credentials if c.get("holder") == holder
                 and (ctype is None or (c.get("credential_type") or "").upper() == ctype.upper())]
        return found[0] if found else None


# ------------------------------------------------------------------ parsing

_ONES = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,
         "nine":9,"ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,
         "fifteen":15,"sixteen":16,"seventeen":17,"eighteen":18,"nineteen":19}
_TENS = {"twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,"seventy":70,
         "eighty":80,"ninety":90}

def _words_to_number(phrase):
    """'seventy-three' -> 73. Handles up to 99, which is all these need."""
    total = 0
    for part in re.split(r"[\s-]+", phrase.strip().lower()):
        if part in _TENS:
            total += _TENS[part]
        elif part in _ONES:
            total += _ONES[part]
        elif part == "hundred":
            total = (total or 1) * 100
        else:
            return None
    return total or None

_UNIT = {"cr": 10**7, "crore": 10**7, "crores": 10**7,
         "lakh": 10**5, "lakhs": 10**5, "lac": 10**5}

def find_money(text):
    """Threshold amounts, digits or words: 'INR 20 Cr', 'seventy-three crore'."""
    if m := re.search(r"(?:INR|Rs\.?|\u20b9)\s*([\d,.]+)\s*(Cr|Crore|Lakh|Lac)s?\b", text, re.I):
        return round(float(m.group(1).replace(",", "")) * _UNIT[m.group(2).lower()])
    if m := re.search(r"([\d,.]+)\s*(Cr|Crore|Lakh|Lac)s?\b", text, re.I):
        return round(float(m.group(1).replace(",", "")) * _UNIT[m.group(2).lower()])
    # spelled out: "the seventy-three crore mark". Build the alternation from
    # the number vocabulary so stray words ("the", "our") can't be swallowed.
    vocab = "|".join(sorted(list(_ONES) + list(_TENS) + ["hundred"], key=len, reverse=True))
    if m := re.search(rf"((?:{vocab})(?:[\s-](?:{vocab}))*)\s+(crore|lakh|lac)s?\b",
                      text, re.I):
        n = _words_to_number(m.group(1))
        if n:
            return round(n * _UNIT[m.group(2).lower()])
    return None

_MONTHS = ("january february march april may june july august september "
           "october november december").split()

def find_date(text):
    """ISO or 'March 10, 2021'."""
    if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", text):
        return m.group(0)
    if m := re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})", text):
        month = m.group(1).lower()
        if month in _MONTHS:
            return f"{m.group(3)}-{_MONTHS.index(month)+1:02d}-{int(m.group(2)):02d}"
    return None

def find_longest(text, candidates):
    """First candidate (longest first) that appears verbatim in the question.

    Matching against the KB's own vocabulary means we can never resolve to
    an entity that doesn't exist -- no fuzzy guessing at answer time.
    """
    low = text.lower()
    for c in candidates:
        if c.lower() in low:
            return c
    return None

def resolve(kb, question):
    """Everything a shape function might need, pulled from the question text."""
    q = question
    return {
        "client":   find_longest(q, kb.clients),
        "person":   find_longest(q, kb.names),
        # scope to the exclusion clause: client names contain category words
        # ("Irrigation & Waterways Dept" would otherwise match category
        # "Irrigation" and silently exclude the wrong works)
        "category": find_longest(_after_excluding(q), kb.categories),
        "grade":    find_longest(q, kb.grades),
        "work":     _find_work(kb, q),
        "amount":   find_money(q),
        "date":     find_date(q),
    }

def _after_excluding(text):
    m = re.search(r"\b(?:excluding|except|other than|apart from)\b(.*)", text, re.I)
    return m.group(1) if m else ""

def _find_work(kb, text):
    """Work names appear with varying dash/spacing, so compare canonical forms."""
    from common import work_key
    canon = work_key(text)
    hits = [w for w in kb.works if w["key"] in canon]
    if hits:
        return max(hits, key=lambda w: len(w["key"]))["work_name"]
    # questions paraphrase names ("WTP Augmentation project in West Bengal
    # Package 51"), so fall back to the package number, which is unique.
    if m := re.search(r"\b(?:pkg|package)[\s-]*(\d+)\b", text, re.I):
        # work_key normalises dashes to " - ", so keys end "pkg - 51"
        hits = [w for w in kb.works
                if re.search(rf"pkg\s*-\s*{m.group(1)}$", w["key"])]
        if len(hits) == 1:
            return hits[0]["work_name"]
    return None
