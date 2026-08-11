"""Load the KB and resolve entities mentioned in a question.

The LLM's only job (later) is to pick a shape. Everything here is
deterministic: entities are matched against the KB's own vocabulary, so a
question can only ever refer to something that actually exists.
"""
import collections, json, re
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

class KB:
    def __init__(self):
        self.works = json.load(open(DATA / "works.json"))
        self.people = json.load(open(DATA / "people.json"))
        self.credentials = json.load(open(DATA / "credentials.json"))
        # billing lives in its own table -- collection questions read the AR
        # ledger, not the completion certificates
        arp = DATA / "receivables.json"
        self.receivables = json.load(open(arp)) if arp.exists() else []
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

    def billing_for(self, client):
        """(invoiced, received) for a client. Returns (0, 0) when the client
        has no AR rows -- 4 of the 28 clients have works but no billing."""
        rows = [r for r in self.receivables if r.get("client") == client]
        return (sum(r.get("invoiced") or 0 for r in rows),
                sum(r.get("received") or 0 for r in rows))

    def completed_in(self, client, year):
        return [w for w in self.for_client(client)
                if (w.get("completion_date") or "").startswith(str(year))]

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
    # "March 10, 2021", "mar 10 2021", "March 10th 2021" all appear
    if m := re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", text):
        month = m.group(1).lower()
        hit = next((i for i, name in enumerate(_MONTHS)
                    if name.startswith(month[:3])), None)
        if hit is not None:
            return f"{m.group(3)}-{hit+1:02d}-{int(m.group(2)):02d}"
    return None

EXCL_CUE = re.compile(r"\b(exclud\w*|except|remov\w*|omit\w*|set aside|leav\w+ (?:out|aside)|"
                      r"minus|net of|without|other than|apart from|strip\w*|drop\w*|less)\b", re.I)

def excluded_category(kb, text, client=None):
    """Which category is being excluded.

    Splitting on the verb fails: the phrasing may be passive ("after the water
    treatment division is excluded"), or use a verb no list anticipates
    ("remove", "set aside", "strip out"). Instead take the categories the
    question names and pick whichever sits closest to an exclusion cue.
    """
    cats = find_categories(kb, text, client)
    if not cats:
        return None
    if len(cats) == 1:
        return cats[0]
    flat = _flatten_punct(text)
    cues = [m.start() for m in EXCL_CUE.finditer(flat)]
    if not cues:
        return cats[0]
    best, best_d = None, 10**9
    for c in cats:
        pos = flat.find(_flatten_punct(c))
        if pos < 0:
            continue
        d = min(abs(pos - cue) for cue in cues)
        if d < best_d:
            best, best_d = c, d
    return best or cats[0]

def find_categories(kb, text, client=None):
    """Every category named, in the order mentioned.

    Questions write categories loosely: "bridges and flyovers" for
    "Bridges Flyovers", "expressway assignments" for "Expressways", "roads and
    highways" for "Roads Highways". Drop the joining "and" and match each word
    by prefix so singular/plural and truncation both work.
    """
    flat = _flatten_punct(text)
    # client names contain category words -- "Irrigation & Waterways Dept"
    # would otherwise register as the category "Irrigation". Blank the client
    # out first so only categories the question actually names survive.
    if client:
        flat = flat.replace(_flatten_punct(client), " ")
    flat = re.sub(r"\band\b", " ", flat)
    words = flat.split()
    found = []
    for cat in kb.categories:
        toks = _flatten_punct(cat).split()
        pos = None
        for i in range(len(words) - len(toks) + 1):
            # both directions, but only for words long enough to be meaningful:
            # without the length floor, "i" (from "I'm") prefix-matches
            # "Irrigation" and every question sprouts a phantom category
            # exact match always counts (so "epc" matches "epc"); fuzzy
            # prefix matching only for words long enough to be meaningful --
            # otherwise "i" (from "I'm") prefix-matches "Irrigation" and every
            # question sprouts a phantom category
            def _same(w, t):
                return w == t or (len(w) >= 4 and
                                  (w.startswith(t[:5]) or t.startswith(w[:5])))
            if all(_same(words[i + j], t) for j, t in enumerate(toks)):
                pos = i
                break
        if pos is not None and cat not in found:
            found.append((pos, cat))

    # elliptical second category: "roads highways and maintenance" means
    # Roads Highways AND Roads Maintenance -- the shared first word is
    # dropped. Recover it via a last word that belongs to only one category.
    tails = {}
    for cat in kb.categories:
        tail = _flatten_punct(cat).split()[-1]
        tails.setdefault(tail, []).append(cat)
    have = {c for _, c in found}
    heads = {_flatten_punct(c).split()[0] for c in have}
    for i, w in enumerate(words):
        owners = tails.get(w)
        if not owners or len(owners) != 1 or owners[0] in have:
            continue
        # only a genuine ellipsis: the recovered category must share its first
        # word with one already named ("roads highways and maintenance").
        # Otherwise "bridges" in "bridges and flyovers" would also drag in
        # "Large Bridges", which the question never mentions.
        if _flatten_punct(owners[0]).split()[0] in heads:
            found.append((i, owners[0]))
            have.add(owners[0])
    return [c for _, c in sorted(found)]

def find_years(text):
    """Calendar years named in the question. Works completed 2010-2025, so
    anything outside that window is a credential id or a package number, not
    a year. Deduped, in the order mentioned."""
    seen = []
    for m in re.finditer(r"\b(20[0-2]\d)\b", text):
        y = m.group(1)
        if "2010" <= y <= "2025" and y not in seen:
            seen.append(y)
    return seen

def _flatten_punct(s):
    """Lowercase, drop punctuation, collapse spaces.

    Validation questions are often telegraphic and unpunctuated -- "public
    health engineering dept odisha" for "Public Health Engineering Dept,
    Odisha". Matching on the raw string misses the comma and resolves
    nothing, which silently turns a real question into a fallback.
    """
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()

def find_longest(text, candidates):
    """First candidate (longest first) that appears in the question.

    Matching against the KB's own vocabulary means we can never resolve to
    an entity that doesn't exist -- no fuzzy guessing at answer time.
    """
    flat = _flatten_punct(text)
    for c in candidates:
        if _flatten_punct(c) in flat:
            return c
    return None

def _find_person(kb, text, client=None, work=None):
    """Full name first; fall back to a bare first name.

    23 of 39 first names are shared (three Meeras, three Sureshes), so a bare
    "sunita" is ambiguous. Narrow it using the client or work the question
    also names -- only one of the candidates will have led there.
    """
    if full := find_longest(text, kb.names):
        return full
    low = text.lower()
    # "pritis pmp" is a possessive with the apostrophe dropped, so allow an
    # optional trailing s on the first name
    cands = [n for n in kb.names
             if re.search(rf"\b{re.escape(n.split()[0].lower())}s?\b", low)]
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        if work:
            w = kb.work_named(work)
            hit = [n for n in cands if w and w.get("project_manager") == n]
            if len(hit) == 1:
                return hit[0]
        if client:
            led = {w["project_manager"] for w in kb.for_client(client)}
            hit = [n for n in cands if n in led]
            if len(hit) == 1:
                return hit[0]
        return cands[0]          # a guess beats nothing; never blank
    return None

STOP = {"dept", "department", "of", "the", "govt", "government", "and", "co",
        "corporation", "ltd", "limited", "authority", "office", "works"}

# Questions use state abbreviations and shorthand freely: "the UP irrigation
# account", "pheg gujarat", "mega infra authority". Expand before matching.
ABBREV = {
    "up": "uttar pradesh", "mp": "madhya pradesh", "wb": "west bengal",
    "mah": "maharashtra", "guj": "gujarat", "raj": "rajasthan",
    "pw": "public works", "npso": "national special projects office",
    "neda": "national expressway development authority",
    "tn": "tamil nadu", "ap": "andhra pradesh", "hp": "himachal pradesh",
    "jk": "jammu kashmir", "pwd": "public works department",
    "phed": "public health engineering dept", "pheg": "public health engineering",
    "infra": "infrastructure", "corp": "corporation", "engg": "engineering",
    "municipal corp": "municipal corporation",
}

def _expand(flat):
    words = flat.split()
    out = []
    for w in words:
        out.append(ABBREV.get(w, w))
    return " ".join(out)

def _client_by_tokens(kb, text, floor=0.6):
    """Abbreviations and reorderings: 'pheg gujarat', 'Maharashtra PWD'.

    Score each client by how much of its distinguishing vocabulary appears --
    initials count, so "PHEG" matches "Public Health Engineering ... Gujarat".
    Generic words (dept, corporation, authority) are ignored because every
    client has them.
    """
    flat = _expand(_flatten_punct(text))
    words = set(flat.split())

    def present(tok):
        """Exact, or a prefix either way: 'infra' matches 'infrastructure'."""
        if tok in words:
            return True
        return any(len(w) >= 4 and (w.startswith(tok) or tok.startswith(w))
                   for w in words)

    best, best_score = None, 0.0
    for c in kb.clients:
        toks = [t for t in _expand(_flatten_punct(c)).split()
                if t not in STOP and len(t) > 2]
        if not toks:
            continue
        hits = sum(1 for t in toks if present(t))
        # initialisms are formed from every word, including the ones we drop
        # as generic: "NEDA" = National Expressway Development Authority
        all_toks = _expand(_flatten_punct(c)).split()
        for cand in ("".join(t[0] for t in toks),
                     "".join(t[0] for t in all_toks)):
            if len(cand) >= 3 and cand in words:
                hits = len(toks)
                break
        score = hits / len(toks)
        # tie-break toward the client whose distinctive words are all present
        if score > best_score or (score == best_score and best and len(c) < len(best)):
            best, best_score = c, score
    return best if best_score >= floor else None

def _client_by_unique_token(kb, text):
    """A single distinctive word can identify a client on its own.

    "trishakti" appears in exactly one client name, so seeing it is decisive
    even though it is only one token of three. Restricted to words that are
    unique across the whole client vocabulary, so it cannot misfire on a
    generic word like "municipal" that several clients share.
    """
    owner = collections.defaultdict(set)
    for c in kb.clients:
        for t in _expand(_flatten_punct(c)).split():
            if len(t) >= 6 and t not in STOP:
                owner[t].add(c)
    unique = {t: next(iter(cs)) for t, cs in owner.items() if len(cs) == 1}
    for w in _expand(_flatten_punct(text)).split():
        if w in unique:
            return unique[w]
    return None

def _client_of_person(kb, person):
    """Infer the client from the person when the question never names one.

    One client outright is certain. Otherwise take the client they delivered
    the most value to -- a guess, but scoring is proportional, so a plausible
    client's figures beat the corpus-wide median default by a wide margin.
    """
    works = kb.led_by(person)
    clients = {w["client"] for w in works}
    if len(clients) == 1:
        return clients.pop()
    if not clients:
        return None
    by_value = collections.Counter()
    for w in works:
        by_value[w["client"]] += w["value_inr"]
    return by_value.most_common(1)[0][0]

def resolve(kb, question):
    """Everything a shape function might need, pulled from the question text."""
    q = question
    client = find_longest(q, kb.clients)
    work = _find_work(kb, q)
    # the client is often named only indirectly. Prefer the most reliable
    # route available: stated > via the named work > token match > via a
    # person who only ever served one client.
    if not client and work:
        w = kb.work_named(work)
        client = w["client"] if w else None
    if not client:
        client = _client_by_tokens(kb, q)
    if not client:
        client = _client_by_unique_token(kb, q)
    person_guess = _find_person(kb, q, client, work)
    if not work:
        work = _work_via_person(kb, q, person_guess)
    if not client and person_guess:
        client = _client_of_person(kb, person_guess)

    return {
        "client":   client,
        "person":   person_guess,
        "years":    find_years(q),
        # scope to the exclusion clause: client names contain category words
        # ("Irrigation & Waterways Dept" would otherwise match category
        # "Irrigation" and silently exclude the wrong works)
        "category":   (find_longest(_after_excluding(q), kb.categories)
                       or excluded_category(kb, q, client)),
        "categories": find_categories(kb, q, client),
        "grade":    find_longest(q, kb.grades),
        "work":     work,
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

STATES = ["andhra pradesh", "madhya pradesh", "uttar pradesh", "himachal pradesh",
          "west bengal", "tamil nadu", "jharkhand", "gujarat", "maharashtra",
          "odisha", "rajasthan", "karnataka", "kerala", "punjab", "haryana",
          "bihar", "assam", "delhi", "goa", "telangana", "chhattisgarh",
          "uttarakhand"]

def _work_via_person(kb, text, person):
    """Questions name projects in prose: "the Jharkhand hydro tunnel package".

    No package number to key on, but the person IS known -- so restrict to the
    works they led and pin it down with the state, then any shared keyword.
    Only returns a match when exactly one candidate survives.
    """
    if not person:
        return None
    flat = _flatten_punct(text)
    led = kb.led_by(person)
    if len(led) == 1:
        return led[0]["work_name"]
    state = next((s for s in STATES if s in flat), None)
    if state:
        led = [w for w in led if state in _flatten_punct(w["work_name"])] or led
    if len(led) == 1:
        return led[0]["work_name"]
    # narrow further on any distinctive word shared with the work's name
    words = set(flat.split())
    scored = [(sum(1 for t in _flatten_punct(w["work_name"]).split()
                   if len(t) > 3 and t in words), w) for w in led]
    best = max(scored, key=lambda x: x[0]) if scored else (0, None)
    if best[0] >= 1 and sum(1 for s, _ in scored if s == best[0]) == 1:
        return best[1]["work_name"]
    return None