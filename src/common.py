"""Shared helpers: PDF text, normalisation, and the observation record."""
import re
import fitz  # pymupdf

# ---------------------------------------------------------------- pdf text

def text_of(path):
    """Full text of a PDF, pages joined by newline."""
    return "\n".join(page.get_text() for page in fitz.open(path))

def flatten(text):
    """Collapse all whitespace to single spaces.

    Prose documents wrap at different widths, so a line break can land in the
    middle of a phrase you're matching on. Always flatten before matching prose.
    """
    return re.sub(r"\s+", " ", text)

def label_map(text):
    """These PDFs emit 'Label' then 'Value' on consecutive lines. First win.

    Only valid for label/value documents -- NOT for true tables, where column
    identity is lost in the text stream and you need word coordinates instead.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    out = {}
    for i, line in enumerate(lines[:-1]):
        out.setdefault(line, lines[i + 1])
    return out

def pick(d, *labels):
    """First matching label wins. Families name the same field differently."""
    for label in labels:
        if label in d:
            return d[label]
    return None

# ---------------------------------------------------------------- normalise

_UNITS = {"cr": 10**7, "crore": 10**7, "crores": 10**7,
          "lakh": 10**5, "lakhs": 10**5, "lac": 10**5, "lacs": 10**5,
          "mn": 10**6, "million": 10**6, "thousand": 10**3}

def money(s):
    """Any money string -> integer rupees. 'INR 33.38 Cr' -> 333800000.

    Convert at the boundary. Nothing downstream should ever see a unit word.
    """
    if not s:
        return None
    s = s.replace("\u20b9", " ")
    m = re.search(r"([\d][\d,]*\.?\d*)\s*([A-Za-z.]*)", s)
    if not m:
        return None
    amount = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower().strip(".")
    return round(amount * _UNITS.get(unit, 1))

_MONTHS = {m: i for i, m in enumerate(
    ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1)}

def date(s):
    """Any date string -> 'YYYY-MM-DD'. Returns None if unrecognised.

    dd/mm/yyyy is assumed (Indian convention). That assumption is verifiable:
    the company certificate states defect liability as completion + 365 days,
    so a misread date fails that check.
    """
    if not s:
        return None
    s = s.strip()
    if m := re.match(r"(\d{4})-(\d{2})-(\d{2})", s):
        return m.group(0)
    if m := re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s):
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if m := re.match(r"(\d{1,2}) ([A-Za-z]{3})[a-z]* (\d{4})", s):
        return f"{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    if m := re.match(r"([A-Za-z]{3})[a-z]* (\d{1,2}), (\d{4})", s):
        return f"{m.group(3)}-{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    return None

def work_key(name):
    """Canonical form of a work name, for joining across documents.

    Dashes vary (em/en/hyphen) and whitespace varies, so normalise both.
    """
    if not name:
        return None
    s = name.replace("\u2014", "-").replace("\u2013", "-")
    s = re.sub(r"\s+", " ", s)
    # spacing AROUND the dash varies too ("A - B" vs "A-B" vs "A- B"),
    # depending on how the source document wrapped the line
    s = re.sub(r"\s*-\s*", " - ", s)
    return s.strip().lower()

# ---------------------------------------------------------------- observation

def obs(subject, field, value, source, extractor, kind="work"):
    """One fact, as stated by one document.

    Tables are DERIVED from these, so disagreement between sources is
    queryable rather than silently resolved. `kind` says which table the
    subject belongs to -- work, person, or credential.
    """
    return {"subject": subject, "field": field, "value": value,
            "source": source, "extractor": extractor, "kind": kind}
