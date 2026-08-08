"""Client completion certificates -- 155 docs, the independent second source.

Two families:
  table (84) "Work Completion Certificate" -- labelled particulars, 'is graded X.'
  prose (71) narrative paragraph, no labels, no grading

The client is the ISSUER here (first line), not a labelled field -- the
'Agency (Contractor)' field is always National Infrastructure Corp. Ltd.
Getting those two backwards would invert every client-portfolio question.

GRADING TRAP: table-family certs say "is graded Good." in prose and then show
a Parameter/Assessment table where every row reads "Satisfactory". Anchor on
'is graded X.' only -- the table is component-level, not the overall grade.
"""
import glob, os, re
from pathlib import Path
from common import text_of, flatten, label_map, pick, money, date, work_key, obs

FOLDER = "documents/completion_certificate"

def family(text):
    return "prose" if "Name of Work" not in text else "table"

# every certificate's second block is this strapline; the issuer name is
# everything above it -- which may be one line or two, because long authority
# names wrap. Taking only line 1 truncates "... Govt of West / Bengal".
_STRAP = re.compile(r"(Government of India|Public Sector|Private Sector|"
                    r"A Government of|Accredited|Office of the)")

def issuer(text):
    """The certifying authority: all lines above the strapline."""
    parts = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if _STRAP.search(line) or line.upper().startswith("WORK COMPLETION"):
            break
        parts.append(line)
    return " ".join(parts) if parts else None

def extract_one(path):
    text = text_of(path)
    flat = flatten(text)
    doc = os.path.basename(path)[:-4]
    fam = family(text)
    fields = {"client": issuer(text)}

    if m := re.search(r"(?:No\.|Ref:)\s*(CC/\S+)", flat):
        fields["cert_ref"] = m.group(1)

    if fam == "table":
        d = label_map(text)
        name = pick(d, "Name of Work")
        fields.update({
            "category":        pick(d, "Nature / Category"),
            "value_inr":       money(pick(d, "Contract Value (Original)")),
            "completion_date": date(pick(d, "Completion Date")),
            "project_manager": pick(d, "Contractor's Project Manager"),
        })
    else:
        # anchor on template boilerplate; the variable part is what we capture
        name = (m.group(1) if (m := re.search(r'the work of ["\u201c]([^"\u201d]+)', flat)) else None)
        if m := re.search(r'["\u201d]\s*\(([^)]+)\)\s*,\s*awarded', flat):
            fields["category"] = m.group(1).strip()
        # five date formats appear after this anchor, so capture up to the
        # next boilerplate phrase and let date() work out which one it is
        if m := re.search(r"completed in all respects on (.+?) at a gross", flat):
            fields["completion_date"] = date(m.group(1).strip())
        if m := re.search(r"gross executed value of ([^(]+)\(", flat):
            fields["value_inr"] = money(m.group(1))
        if m := re.search(r"supervised on the contractor's side by ([^.]+)\.", flat):
            fields["project_manager"] = m.group(1).strip()

    # grading: table family only, and ONLY this phrasing (see docstring)
    if m := re.search(r"is graded ([A-Za-z ]+?)\.", flat):
        fields["grading"] = m.group(1).strip()

    key = work_key(name)
    if not key:
        return [], {"doc": doc, "family": fam, "problem": "no work name"}

    out = [obs(key, "work_name", name, doc, "client_cert")]
    out += [obs(key, f, v, doc, "client_cert") for f, v in fields.items() if v is not None]

    # in-document check: prose states the value twice, in different units
    inline = None
    if m := re.search(r"\(Rupees ([\d.,]+ (?:Crore|Lakh))", flat):
        inline = money(m.group(1))
    check = None
    if inline is not None and fields.get("value_inr") is not None:
        # the parenthetical is a 2dp restatement in crore, so it rounds --
        # allow tolerance rather than demanding exact equality
        check = abs(inline - fields["value_inr"]) <= 0.005 * 10**7

    return out, {"doc": doc, "family": fam, "work": key, "unit_check": check,
                 "missing": [f for f in ("client", "value_inr", "completion_date",
                                         "project_manager", "category")
                             if fields.get(f) is None]}

def run(root):
    observations, report = [], []
    for path in sorted(glob.glob(os.path.join(root, FOLDER, "*.pdf"))):
        o, r = extract_one(path)
        observations += o
        report.append(r)
    return observations, report

if __name__ == "__main__":
    import sys, json, collections
    ROOT = Path(__file__).resolve().parents[1]
    (ROOT / "data").mkdir(exist_ok=True)
    root = sys.argv[1] if len(sys.argv) > 1 else "../BITS-Hackathon-Dataset"

    observations, report = run(root)
    print(f"documents    {len(report)}   families {dict(collections.Counter(r['family'] for r in report))}")
    print(f"observations {len(observations)}")
    print(f"works seen   {len({o['subject'] for o in observations})}")

    broken = [r for r in report if r.get("problem") or r.get("missing")]
    print(f"incomplete   {len(broken)}")
    for r in broken[:5]:
        print("   ", r)

    checks = collections.Counter(r.get("unit_check") for r in report)
    print(f"in-document unit check: pass {checks[True]}, FAIL {checks[False]}, n/a {checks[None]}")

    print("\nfield coverage (of 155):")
    for f, n in collections.Counter(o["field"] for o in observations).most_common():
        print(f"   {f:22s} {n:4d}")

    out = ROOT / "data" / "observations_client_cert.json"
    json.dump(observations, open(out, "w"), indent=1)
    print(f"\nwrote {out.relative_to(ROOT)}")
