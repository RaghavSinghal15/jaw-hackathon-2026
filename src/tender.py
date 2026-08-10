"""Tender island: bonds (60), compliance matrices (40), ISO certs (5),
dossiers (6).

These join to EACH OTHER by RFP number, and to nothing else. No completion
certificate anywhere in the corpus mentions an RFP, so this branch is
disconnected from the 155-work spine. We do not bridge it by guessing: a
match on client + category + value would look right and be unverifiable.

Same caution as contract numbers, where the naive bridge is demonstrably
wrong -- RA bill contract #70's client is Suvarna Projects Limited while the
work "... Pkg-70" belongs to Mahanadi Steel Corporation.

DATA QUALITY NOTE: 32 of 60 bonds state a guarantee of zero ("Rs. 0"), and
dossiers say earnest money of INR 0. Reported below so an aggregate over bond
values is never mistaken for a meaningful figure.
"""
import glob, json, os, re, sys
from pathlib import Path
from common import text_of, flatten, label_map, date

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CR, LAKH = 10**7, 10**5

def money(s):
    if not s:
        return None
    s = s.replace("\u20b9", " ")
    if not (m := re.search(r"([\d][\d,]*\.?\d*)\s*(Cr|Crore|Lakh|Lac)?", s, re.I)):
        return None
    v = float(m.group(1).replace(",", ""))
    u = (m.group(2) or "").lower()
    return round(v * (CR if u.startswith("cr") else LAKH if u.startswith("la") else 1))

def bonds(root):
    rows = []
    for path in sorted(glob.glob(os.path.join(root, "documents/performance_bond/*.pdf"))):
        flat = flatten(text_of(path))
        g = lambda p: (m.group(1).strip() if (m := re.search(p, flat)) else None)
        rows.append({
            "doc": os.path.basename(path)[:-4],
            "bg_no": g(r"BG No: (\S+)"),
            "bank": (text_of(path).split("\n")[0].strip()),
            "rfp": g(r"(RFP-\d+)"),
            "category": g(r"Performance Bond — (.+?) Works"),
            "amount": money(g(r"not exceeding ([^(]+)\(")),
            "issued": date(g(r"Date: (.+?) To,")),
            "valid_until": date(g(r"in force up to and including (.+?),? after which")),
        })
    return rows

def compliance(root):
    rows = []
    for path in sorted(glob.glob(os.path.join(root, "documents/compliance_matrix/*.pdf"))):
        text = text_of(path)
        flat = flatten(text)
        g = lambda p: (m.group(1).strip() if (m := re.search(p, flat)) else None)
        # the checklist restates corpus-level claims; keep them for cross-checking
        rows.append({
            "doc": os.path.basename(path)[:-4],
            "rfp": g(r"(RFP-\d+)"),
            "category": g(r"RFP-\d+ · (.+?) CM/"),
            "iso_certs": re.findall(r"Certificate (ORG-\d+)", flat),
            "requirements": len(re.findall(r"\bComplied\b", flat)),
            "claimed_personnel": int(m.group(1)) if (m := re.search(r"(\d+) personnel on rolls", flat)) else None,
            "claimed_assets": int(m.group(1)) if (m := re.search(r"(\d+) owned assets", flat)) else None,
            "min_turnover": money(g(r"Minimum average turnover requirement \(Rs\. ([\d.]+ Cr)")),
        })
    return rows

def iso_certs(root):
    rows = []
    for path in sorted(glob.glob(os.path.join(root, "documents/iso_certificate/*.pdf"))):
        text = text_of(path)
        d = label_map(text)
        flat = flatten(text)
        rows.append({
            "doc": os.path.basename(path)[:-4],
            "cert_no": (m.group(1) if (m := re.search(r"Certificate No: (\S+)", flat)) else None),
            # not all five are ISO standards -- ORG-1004 is "CPWD Class I
            # Registration" and ORG-1005 is "NABL Accreditation". Capture
            # whatever the certificate says it conforms to.
            "standard": (m.group(1).strip() if (m := re.search(
                r"requirements of\s+(.+?)\s+(?:SCOPE|Scope) OF|requirements of\s+(.+?)\s+Scope of",
                flat, re.I)) else None) or (
                m2.group(1) if (m2 := re.search(r"(ISO \d+:\d+)", flat)) else None),
            "body": text.split("\n")[0].strip(),
            "initial_certification": date(d.get("Initial Certification Date")),
            "valid_until": date(d.get("Valid Until")),
            "iaf_accredited": d.get("IAF Accreditation"),
            "audits": len(re.findall(r"(?:Initial Certification|Surveillance Audit \d|Re-certification)\s+\d{4}-", text)),
        })
    return rows

def dossiers(root):
    rows = []
    for path in sorted(glob.glob(os.path.join(root, "documents/tender_dossier/*.pdf"))):
        flat = flatten(text_of(path))
        g = lambda p: (m.group(1).strip() if (m := re.search(p, flat)) else None)
        rows.append({
            "doc": os.path.basename(path)[:-4],
            "rfp": g(r"(RFP-\d+)"),
            "category": g(r"^.*?· (.+?) Works — Tender"),
            "bid_value": money(g(r"Bid value: (.+?) Submitted")),
            "submitted": date(g(r"Submitted: (.+?) To,")),
            "authority": g(r"The Tender Inviting Authority, (.+?) Dear"),
            "earnest_money": money(g(r"Earnest money of (\S+ \S+) has been")),
            "validity_days": int(m.group(1)) if (m := re.search(r"valid for (\d+)\s*days", flat)) else None,
        })
    return rows


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "../BITS-Hackathon-Dataset"
    DATA.mkdir(exist_ok=True)

    bo, cm, iso, do = bonds(root), compliance(root), iso_certs(root), dossiers(root)

    zeros = sum(1 for b in bo if b["amount"] == 0)
    print(f"bonds              {len(bo):4d}   with RFP {sum(1 for b in bo if b['rfp'])}"
          f"   zero-valued {zeros}   unparsed amount {sum(1 for b in bo if b['amount'] is None)}")
    print(f"   ! {zeros} bonds guarantee zero rupees -- do not aggregate bond values")
    print(f"   banks: {sorted({b['bank'] for b in bo})}")

    print(f"\ncompliance matrices {len(cm):3d}   with RFP {sum(1 for c in cm if c['rfp'])}")
    uniq = lambda k: sorted({c[k] for c in cm if c[k] is not None})
    print(f"   claimed personnel {uniq('claimed_personnel')}"
          f"   claimed assets {uniq('claimed_assets')}")
    print(f"   min turnover {uniq('min_turnover')}"
          f"   matrices missing a claim {sum(1 for c in cm if c['claimed_personnel'] is None)}")

    print(f"\nISO certificates   {len(iso):4d}")
    for c in iso:
        print(f"   {c['cert_no']}  {str(c['standard'])[:26]:26s} {str(c['body'])[:16]:16s}"
              f" valid to {c['valid_until']}  audits {c['audits']}")

    print(f"\ntender dossiers    {len(do):4d}")
    for d in do:
        print(f"   {d['doc']:18s} {d['rfp']:16s} bid {(d['bid_value'] or 0)/CR:7.2f} Cr"
              f"  submitted {d['submitted']}  EMD {d['earnest_money']}")

    rfps = {b["rfp"] for b in bo} | {c["rfp"] for c in cm} | {d["rfp"] for d in do}
    print(f"\ndistinct RFPs {len(rfps - {None})}"
          f"   bond+matrix overlap {len({b['rfp'] for b in bo} & {c['rfp'] for c in cm})}")
    print("   NOTE: no completion certificate references an RFP -- this island is")
    print("   not bridged to the 155-work spine, deliberately.")

    for name, rows in [("bonds", bo), ("compliance", cm), ("iso_certs", iso),
                       ("dossiers", do)]:
        json.dump(rows, open(DATA / f"{name}.json", "w"), indent=1)
    print("\nwrote bonds.json, compliance.json, iso_certs.json, dossiers.json")
