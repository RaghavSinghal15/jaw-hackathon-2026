"""Company completion certificates -- 155 docs, the works spine.

Two families:
  long  (80) "PROJECT COMPLETION CERTIFICATE" -- sections, prose grading
  short (75) "RECORD OF WORK COMPLETED"       -- one label block, client cert ref

Same fields, different labels, so every lookup passes both names.
"""
import glob, os, re
from pathlib import Path
from common import text_of, flatten, label_map, pick, money, date, work_key, obs

FOLDER = "documents/company_completion_certificate"

def family(text):
    return "long" if "PROJECT COMPLETION CERTIFICATE" in text.upper() else "short"

def split_client(raw):
    """'Mega Infrastructure Authority (Government)' -> (name, 'government')"""
    if not raw:
        return None, None
    m = re.search(r"^(.*?)\s*\((government|psu|private)\)\s*$", raw.strip(), re.I)
    if m:
        return m.group(1).strip(), m.group(2).lower()
    return raw.strip(), None

def extract_one(path):
    text = text_of(path)
    doc = os.path.basename(path)[:-4]
    fam = family(text)
    d = label_map(text)
    flat = flatten(text)

    name = pick(d, "Work", "Project Name")
    key = work_key(name)
    if not key:
        return [], {"doc": doc, "family": fam, "problem": "no work name"}

    client, sector = split_client(pick(d, "Client"))
    out = [obs(key, "work_name", name, doc, "company_cert")]

    fields = {
        "client":           client,
        "client_sector":    sector,
        "category":         pick(d, "Category", "Work Category"),
        "value_inr":        money(pick(d, "Executed Value", "Contract Value")),
        "completion_date":  date(pick(d, "Completion", "Completion Date")),
        "project_manager":  pick(d, "Project Lead", "Project Manager"),
        "client_cert_ref":  pick(d, "Client Certificate Ref"),
    }

    # grading is prose, long family only
    if m := re.search(r"assessed the completed work as ([A-Za-z ]+?)\.", flat):
        fields["grading"] = m.group(1).strip()

    # defect liability: stated end date, used below as a date-parse check
    if m := re.search(r"until (\d{4}-\d{2}-\d{2})", flat):
        fields["defect_liability_end"] = m.group(1)

    for f, v in fields.items():
        if v is not None:
            out.append(obs(key, f, v, doc, "company_cert"))

    return out, {"doc": doc, "family": fam,
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
    ROOT = Path(__file__).resolve().parents[1]      # repo root, wherever we run from
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

    have = collections.Counter(o["field"] for o in observations)
    print("\nfield coverage (of 155):")
    for f, n in have.most_common():
        print(f"   {f:22s} {n:4d}")

    out = ROOT / "data" / "observations_company_cert.json"
    json.dump(observations, open(out, "w"), indent=1)
    print(f"\nwrote {out.relative_to(ROOT)}")
