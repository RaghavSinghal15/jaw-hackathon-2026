"""People: CVs (39) and personnel certificates (48).

CV TRAP: section 4 "Project Experience & Certifications" is deliberately
hollow -- it points at other documents instead of listing projects. NO CV in
the corpus names a single project (checked: 0 of 39 mention 'Pkg-'). The
person -> work link lives in the completion certificates' Project Lead field,
not here. The corpus README's description of CVs is misleading on this.

Full name is the join key: all 39 are distinct, so the 20 personnel
certificates that omit Employee ID can still be attributed safely.

Only fields that VARY are worth extracting. Designation (all "Project
Manager"), software skills, institution and affiliations are identical across
all 39 -- cardinality 1, so nothing can be asked about them.
"""
import glob, os, re
from pathlib import Path
from common import text_of, flatten, label_map, pick, date, obs

CV_FOLDER = "documents/cv"
PC_FOLDER = "documents/personnel_certificate"

def person_key(name):
    return re.sub(r"\s+", " ", (name or "")).strip().lower()

def years(s):
    """'6 years' -> 6"""
    if not s:
        return None
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else None

# ---------------------------------------------------------------- CVs

def cv_one(path):
    text = text_of(path)
    doc = os.path.basename(path)[:-4]
    d = label_map(text)
    key = person_key(d.get("Name"))
    if not key:
        return [], {"doc": doc, "problem": "no name"}

    fields = {
        "name":              d.get("Name"),
        "employee_id":       d.get("Employee ID"),
        "business_unit":     d.get("Business Unit"),
        "wage_group":        d.get("Wage Group"),
        "qualification":     d.get("Highest Qualification") or d.get("Qualification"),
        "experience_years":  years(d.get("Total Experience")),
        "date_of_joining":   date(d.get("Date of Joining")),
    }
    out = [obs(key, f, v, doc, "cv", kind="person") for f, v in fields.items() if v is not None]
    return out, {"doc": doc, "person": key,
                 "missing": [f for f, v in fields.items() if v is None]}

# ---------------------------------------------------------------- certificates

def pc_one(path):
    text = text_of(path)
    flat = flatten(text)
    doc = os.path.basename(path)[:-4]
    d = label_map(text)

    # two families: full (labelled, has Employee ID) and minimal (name + dates)
    name = pick(d, "This is to certify that", "This credential is conferred upon")
    key = person_key(name)
    if not key:
        return [], {"doc": doc, "problem": "no name"}

    cred_id = pick(d, "Credential ID") or (
        m.group(1) if (m := re.search(r"Certificate No\.\s*\n?(\S+)", text)) else None)
    cred_type = pick(d, "Credential Type") or (
        m.group(1).strip() if (m := re.search(r"conferred upon .*? the (.+?) credential", flat)) else None)

    out = []
    if cred_id:
        cfields = {
            "holder":            key,
            "credential_type":   cred_type,
            "issuing_authority": pick(d, "Issuing Authority"),
            "issued":            date(pick(d, "Date of Issue", "Issued")),
            "valid_through":     date(pick(d, "Valid Through")),
        }
        out += [obs(cred_id, f, v, doc, "personnel_cert", kind="credential")
                for f, v in cfields.items() if v is not None]

    # the full family restates CV fields -- free corroboration
    pfields = {"name": name,
               "qualification": pick(d, "Highest Qualification"),
               "experience_years": years(pick(d, "Years of Experience"))}
    if m := re.search(r"Employee ID: (EMP-\d+)", flat):
        pfields["employee_id"] = m.group(1)
    out += [obs(key, f, v, doc, "personnel_cert", kind="person")
            for f, v in pfields.items() if v is not None]

    return out, {"doc": doc, "person": key, "credential": cred_id,
                 "family": "full" if pick(d, "Credential ID") else "minimal"}

# ---------------------------------------------------------------- run

def run(root):
    observations, report = [], []
    for path in sorted(glob.glob(os.path.join(root, CV_FOLDER, "*.pdf"))):
        o, r = cv_one(path); observations += o; report.append(("cv", r))
    for path in sorted(glob.glob(os.path.join(root, PC_FOLDER, "*.pdf"))):
        o, r = pc_one(path); observations += o; report.append(("pcert", r))
    return observations, report

if __name__ == "__main__":
    import sys, json, collections
    ROOT = Path(__file__).resolve().parents[1]
    (ROOT / "data").mkdir(exist_ok=True)
    root = sys.argv[1] if len(sys.argv) > 1 else "../BITS-Hackathon-Dataset"

    observations, report = run(root)
    cvs = [r for k, r in report if k == "cv"]
    pcs = [r for k, r in report if k == "pcert"]
    print(f"CVs                  {len(cvs)}   incomplete {len([r for r in cvs if r.get('missing') or r.get('problem')])}")
    print(f"personnel certs      {len(pcs)}   families {dict(collections.Counter(r.get('family') for r in pcs))}")
    print(f"distinct people      {len({o['subject'] for o in observations if o['kind']=='person'})}")
    print(f"distinct credentials {len({o['subject'] for o in observations if o['kind']=='credential'})}")
    print(f"observations         {len(observations)}")

    out = ROOT / "data" / "observations_people.json"
    json.dump(observations, open(out, "w"), indent=1)
    print(f"wrote {out.relative_to(ROOT)}")
