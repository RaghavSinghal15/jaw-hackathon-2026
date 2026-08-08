"""Reference letters -- 132 docs, and the ONLY source of Contractor's Role.

Two families:
  table (44) "Reference Letter" -- labelled Project Details incl. role
  prose (88) "Letter of Recommendation" -- work name in curly quotes, no role

Two jobs here:
  1. record which works have a letter -- absence questions need the works with
     NO letter, which you can only answer if you know the complete works set
  2. pull Contractor's Role (Prime / JV Partner) for the role_split questions

Roles are table-family only, so ~88 works have no stated role. That is a
coverage gap, not a default of Prime -- do not fill it in.
"""
import glob, os, re
from pathlib import Path
from common import text_of, flatten, label_map, pick, money, date, work_key, obs

FOLDER = "documents/reference_letter"

def family(text):
    return "table" if "Project Name" in text else "prose"

def extract_one(path):
    text = text_of(path)
    flat = flatten(text)
    doc = os.path.basename(path)[:-4]
    fam = family(text)
    fields = {}

    if fam == "table":
        d = label_map(text)
        name = pick(d, "Project Name")
        fields.update({
            "category":         pick(d, "Nature of Work"),
            "value_inr":        money(pick(d, "Contract Value")),
            "completion_date":  date(pick(d, "Date of Completion")),
            "contractor_role":  pick(d, "Contractor's Role"),
        })
    else:
        # prose: work name in curly quotes, value in brackets right after
        name = (m.group(1) if (m := re.search(r"[\u201c\"]([^\u201d\"]+)[\u201d\"]", flat)) else None)
        if m := re.search(r"[\u201d\"]\s*\(([^)]+)\)", flat):
            fields["value_inr"] = money(m.group(1))
        if m := re.search(r"completed on (.+?)\.", flat):
            fields["completion_date"] = date(m.group(1).strip())

    key = work_key(name)
    if not key:
        return [], {"doc": doc, "family": fam, "problem": "no work name"}

    out = [obs(key, "has_reference_letter", True, doc, "reference_letter"),
           obs(key, "reference_letter_doc", doc, doc, "reference_letter")]
    out += [obs(key, f, v, doc, "reference_letter") for f, v in fields.items() if v is not None]
    return out, {"doc": doc, "family": fam, "work": key,
                 "role": fields.get("contractor_role")}

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
    print(f"letters      {len(report)}   families {dict(collections.Counter(r['family'] for r in report))}")
    print(f"works with a letter {len({o['subject'] for o in observations})}")
    print(f"unparsed     {len([r for r in report if r.get('problem')])}")
    print(f"roles        {dict(collections.Counter(r['role'] for r in report))}")

    out = ROOT / "data" / "observations_reference_letter.json"
    json.dump(observations, open(out, "w"), indent=1)
    print(f"wrote {out.relative_to(ROOT)}")
