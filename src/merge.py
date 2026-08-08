"""Derive the works table from observations, and report disagreements.

Extractors never write field values directly -- they emit observations
(one row per fact-as-stated-by-one-document). This module reduces them.

Rule: where sources agree, that's the value and the agreement is evidence.
Where they disagree, fall back to source priority BUT report it -- with 155
works, a disagreement is a bug you can open by hand, not a tie to break.
"""
import collections, glob, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import work_key

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# higher wins a disagreement. certificates are the primary record;
# the portfolio is a summary derived from them.
PRIORITY = {"company_cert": 3, "client_cert": 2, "portfolio": 1,
            "cv": 3, "personnel_cert": 2}

def load():
    obs = []
    for f in sorted(DATA.glob("observations_*.json")):
        obs += json.load(open(f))
    return obs

def reduce(obs, kind="work"):
    """observations of one kind -> (table, disagreement list)"""
    grouped = collections.defaultdict(lambda: collections.defaultdict(list))
    for o in obs:
        if o.get("kind", "work") != kind:
            continue
        grouped[o["subject"]][o["field"]].append(o)

    works, conflicts = {}, []
    for subject, fields in grouped.items():
        row = {"key": subject}
        for field, items in fields.items():
            distinct = {}
            for i in items:
                distinct.setdefault(_canon(field, i["value"]), []).append(i)

            if len(distinct) > 1:
                conflicts.append({
                    "work": subject, "field": field,
                    "values": {str(v): [i["source"] for i in g]
                               for v, g in distinct.items()},
                })
            if field.endswith("_inr"):
                # sources agree, but at different precision: one states exact
                # rupees (19,32,99,999) and another rounds to 2dp in crore
                # (19.33 Cr). Prefer the precise one -- trailing zeros lose.
                best = min(items, key=lambda i: (_trailing_zeros(i["value"]),
                                                 -PRIORITY.get(i["extractor"], 0)))
            else:
                best = max(items, key=lambda i: PRIORITY.get(i["extractor"], 0))
            row[field] = best["value"]
            row[f"_{field}_sources"] = len(distinct) == 1 and len(items) or 1
        works[subject] = row
    return works, conflicts

def _trailing_zeros(v):
    s = str(int(v)) if isinstance(v, (int, float)) else ""
    return len(s) - len(s.rstrip("0"))

def _canon(field, v):
    """Compare like with like.

    Casing and spacing differ between families. Money is restated rounded to
    2dp in crore in some documents, so compare to the nearest 0.005 Cr rather
    than demanding exact equality -- a 1-rupee gap is not a disagreement.
    """
    if field == "work_name":
        return work_key(v)          # spacing round the dash varies by source
    if field.endswith("_inr") and isinstance(v, (int, float)):
        return round(v / 50_000)
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v).strip().lower()
    return v

def derive(works):
    """Fill fields that are absences or defaults rather than stated facts.

    Each of these is a rule, not an extraction. Keeping them here -- in one
    place, commented -- means every assumption in the KB is auditable.
    """
    notes = collections.Counter()

    # 1. a work with no reference letter is not missing data, it HAS no letter.
    #    absence questions depend on this distinction.
    for w in works.values():
        if w.get("has_reference_letter") is None:
            w["has_reference_letter"] = False
            notes["no reference letter"] += 1

    # 2. client sector is stated on some of a client's certificates and not
    #    others. propagate from a sibling certificate -- this is using a fact
    #    the corpus states elsewhere, NOT inferring from the client's name.
    sector = {}
    for w in works.values():
        if w.get("client_sector"):
            sector.setdefault(w["client"], w["client_sector"])
    for w in works.values():
        if not w.get("client_sector") and w["client"] in sector:
            w["client_sector"] = sector[w["client"]]
            notes["sector propagated from sibling"] += 1

    # 3. six works belong to clients that never state a sector on ANY of their
    #    certificates, so there is no sibling to propagate from. These are
    #    inferred from the authority's own name ("Dept, Govt of ..."), which is
    #    weaker evidence than rule 2 -- counted separately so it stays visible.
    for w in works.values():
        if not w.get("client_sector") and re.search(
                r"\bGovt of\b|\bGovernment of\b|\bDepartment\b|\bDept\b", w["client"]):
            w["client_sector"] = "government"
            notes["sector INFERRED from client name"] += 1

    # 4. role: JV Partner is recorded explicitly; anything unstated is Prime.
    #    evidence: sample questions HS-IC-0022 and HS-IC-0023 only reconcile
    #    under this rule (0023 excludes the one JV work, 0022 excludes none).
    for w in works.values():
        if not w.get("contractor_role"):
            w["contractor_role"] = "Prime"
            notes["role defaulted to Prime"] += 1

    return notes

if __name__ == "__main__":
    obs = load()
    works, conflicts = reduce(obs, "work")
    notes = derive(works)
    people, pconf = reduce(obs, "person")
    creds, cconf = reduce(obs, "credential")

    print(f"observations {len(obs)}")
    print(f"works        {len(works)}   (expected 155)")
    print(f"conflicts    {len(conflicts)}")
    for c in conflicts[:10]:
        print(f"   {c['field']:16s} {c['work'][:38]:38s} {c['values']}")

    print("\ncoverage and corroboration:")
    fields = ["work_name", "client", "client_sector", "category", "value_inr",
              "completion_date", "project_manager", "grading", "cert_ref"]
    for f in fields:
        have = [w for w in works.values() if w.get(f) is not None]
        two = [w for w in have if w.get(f"_{f}_sources", 1) >= 2]
        print(f"   {f:18s} present {len(have):4d}   confirmed by 2+ sources {len(two):4d}")

    print("\nderived (rules, not extractions):")
    for k, n in notes.most_common():
        print(f"   {k:34s} {n:4d}")
    print("   still missing sector:              ",
          sum(1 for w in works.values() if not w.get("client_sector")))
    print("   still missing grading:            ",
          sum(1 for w in works.values() if not w.get("grading")))

    total = sum(w["value_inr"] for w in works.values() if w.get("value_inr"))
    print(f"\ntotal value  INR {total/1e7:,.1f} Cr")
    print(f"clients      {len({w['client'] for w in works.values()})}")

    print(f"\npeople       {len(people)}   conflicts {len(pconf)}")
    for c in pconf[:5]:
        print(f"   {c['field']:16s} {c['work']:28s} {c['values']}")
    print(f"credentials  {len(creds)}   conflicts {len(cconf)}")
    corrob = sum(1 for p in people.values() if p.get("_qualification_sources", 1) >= 2)
    print(f"   qualification confirmed by CV + certificate: {corrob}")

    json.dump(list(works.values()), open(DATA / "works.json", "w"), indent=1)
    json.dump(list(people.values()), open(DATA / "people.json", "w"), indent=1)
    json.dump(list(creds.values()), open(DATA / "credentials.json", "w"), indent=1)
    json.dump(conflicts + pconf + cconf, open(DATA / "conflicts.json", "w"), indent=1)
    print("\nwrote works.json, people.json, credentials.json, conflicts.json")
