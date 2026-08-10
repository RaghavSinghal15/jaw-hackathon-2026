"""Transactions: general ledgers (8) + bank statements (8) + RA bills + BOQ.

THE HARD PROBLEM: these are true tables with DEBIT | CREDIT | BALANCE columns,
and an empty cell produces no text at all. So the flat text stream gives

    2019-04-01  Opening capital brought in   400,000,000  400,000,000  Dr
    2019-04-28  Monthly salaries             802,761      419,197,239  Dr

where the first row's 400,000,000 is a DEBIT and the second row's 802,761 is a
CREDIT. Identical shape, opposite meaning. No regex can recover which column a
number came from, because that information is not in the string.

THE FIX -- balance-delta inference, which is deterministic and self-checking:
the LAST number on a row is the running balance. Compare it to the previous
row's balance. The size of the change must equal one of the other numbers on
the row, and its sign tells you which column that number belongs to. If no
number on the row matches the delta, the row did not parse and we say so
rather than guessing.

That check is why this is trustworthy: every row that parses has been
confirmed arithmetically against the balance the document itself states.
"""
import glob, json, os, re, sys
from pathlib import Path

import openpyxl
from common import text_of, flatten

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

NUM = re.compile(r"-?[\d][\d,]*(?:\.\d+)?")

def nums(line):
    return [int(float(m.group(0).replace(",", ""))) for m in NUM.finditer(line)
            if re.fullmatch(r"-?[\d][\d,]*(?:\.\d+)?", m.group(0))]

DATE_TOKEN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

def parse_rows(text, date_re=r"(\d{4}-\d{2}-\d{2})"):
    """Split the flat text into transaction rows keyed on a leading date."""
    rows, current = [], None
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if m := re.match(date_re, line):
            if current:
                rows.append(current)
            current = {"date": m.group(1), "text": line}
        elif current is not None:
            # pagination tears rows in half; footers land inside them
            if re.match(r"^(DOC-|Page \d+ of|ACCOUNT |A/c:|IFSC)", line):
                continue
            current["text"] += " " + line
    if current:
        rows.append(current)
    return rows

def resolve_amounts(rows):
    """Assign each row's amount to in/out using the balance delta.

    Returns (parsed, unresolved). A row is only accepted when one of its
    numbers equals the change in balance -- otherwise it is reported, not
    guessed at.
    """
    parsed, unresolved, prev = [], [], None
    for r in rows:
        # strip date tokens first: "2019-10-20" otherwise parses as
        # [2019, -10, -20] and pollutes the delta match
        values = nums(DATE_TOKEN.sub(" ", r["text"]))
        if not values:
            continue
        balance = values[-1]
        others = values[:-1]
        narration = re.sub(r"\s+", " ", NUM.sub("", r["text"])).strip(" -|")

        if prev is None:                       # opening line: no delta to use
            parsed.append({**_base(r, narration, balance), "amount": None,
                           "direction": "opening"})
            prev = balance
            continue

        delta = balance - prev
        match = next((v for v in others if abs(v) == abs(delta)), None)
        if match is None:
            unresolved.append({**_base(r, narration, balance),
                               "candidates": others, "delta": delta})
            prev = balance
            continue

        parsed.append({**_base(r, narration, balance), "amount": abs(match),
                       "direction": "in" if delta > 0 else "out"})
        prev = balance
    return parsed, unresolved

def _base(r, narration, balance):
    out = {"date": r["date"], "narration": narration[:120], "balance": balance}
    # narrations carry the identifiers that link to RA bills and receipts
    if m := re.search(r"(AR-\d{4}-\d{5})", r["text"]):
        out["invoice_no"] = m.group(1)
    if m := re.search(r"rcpt #(\d+)", r["text"]):
        out["receipt_no"] = m.group(1)
    return out

def ledgers(root):
    all_rows, all_bad = [], []
    for path in sorted(glob.glob(os.path.join(root, "documents/general_ledger_book/*.pdf"))):
        doc = os.path.basename(path)[:-4]
        text = text_of(path)
        # ledgers restart the balance at each ACCOUNT heading, so split first
        chunks = re.split(r"\nACCOUNT ", text)
        for chunk in chunks:
            account = (m.group(1).strip() if (m := re.match(r"([^\n]+)", chunk)) else "?")
            good, bad = resolve_amounts(parse_rows(chunk))
            for g in good:
                all_rows.append({**g, "doc": doc, "account": account})
            all_bad += [{**b, "doc": doc, "account": account} for b in bad]
    return all_rows, all_bad

def bank(root):
    all_rows, all_bad = [], []
    for path in sorted(glob.glob(os.path.join(root, "documents/bank_statement/*.pdf"))):
        doc = os.path.basename(path)[:-4]
        good, bad = resolve_amounts(parse_rows(text_of(path)))
        all_rows += [{**g, "doc": doc} for g in good]
        all_bad += [{**b, "doc": doc} for b in bad]
    return all_rows, all_bad

# ---------------------------------------------------------------- RA bills

def ra_bills(root):
    rows = []
    for folder in ("ra_bill",):
        for path in sorted(glob.glob(os.path.join(root, f"documents/{folder}/*.pdf"))):
            flat = flatten(text_of(path))
            g = lambda p: (m.group(1).strip() if (m := re.search(p, flat)) else None)
            money = lambda p: (int(float(m.group(1).replace(",", "")))
                               if (m := re.search(p, flat)) else None)
            rows.append({
                "doc": os.path.basename(path)[:-4], "final": folder == "final_ra_bill",
                "contract_no": g(r"Contract #(\d+)"),
                "client": g(r"Contract #\d+ · ([^B]+?) Bill No"),
                "invoice_no": g(r"Bill No: (\S+)"),
                "work_done": money(r"Value of work done[^\d]{0,40}([\d,]+)"),
                "gst": money(r"GST @18%[^\d]{0,20}([\d,]+)"),
                "retention": money(r"Retention @[\d.]+%[^\d(]*\(?([\d,]+)"),
                "net_claimed": money(r"Net claimed[^\d]{0,40}([\d,]+)"),
                "cumulative": money(r"Cumulative up to[^\d]{0,40}([\d,]+)"),
            })
    return rows

CR = 10**7

def final_bills(root):
    """Final bills use a different template: contract abstract + as-executed
    BOQ summary, with values in crore rather than rupees."""
    rows = []
    for path in sorted(glob.glob(os.path.join(root, "documents/final_ra_bill/*.pdf"))):
        flat = flatten(text_of(path))
        cr = lambda p: (round(float(m.group(1)) * CR)
                        if (m := re.search(p, flat)) else None)
        g = lambda p: (m.group(1).strip() if (m := re.search(p, flat)) else None)
        rows.append({
            "doc": os.path.basename(path)[:-4],
            "contract_no": g(r"Contract #(\d+)"),
            "client": g(r"Contract #\d+ · (.+?) · \d+ RA bills"),
            "ra_bill_count": int(m.group(1)) if (m := re.search(r"· (\d+) RA bills", flat)) else None,
            "awarded_value": cr(r"Awarded Value INR ([\d.]+) Cr"),
            "billed_value": cr(r"Total Value of Work Billed INR ([\d.]+) Cr"),
            "period": g(r"Period ([A-Z][a-z]+ \d+, \d{4} — [A-Z][a-z]+ \d+, \d{4})"),
            "boq_total": (int(m.group(1).replace(",", ""))
                          if (m := re.search(r"Total ([\d,]{7,})", flat)) else None),
        })
    return rows

def boq(root):
    rows = []
    for path in sorted(glob.glob(os.path.join(root, "documents/workbooks/BOQ_*.xlsx"))):
        contract = re.search(r"Contract_(\d+)", path).group(1)
        ws = openpyxl.load_workbook(path, data_only=True)["BOQ"]
        it = ws.iter_rows(values_only=True)
        next(it)
        for r in it:
            if r[0] is None:
                continue
            rows.append({"contract_no": contract, "item_no": r[0],
                         "description": r[1], "unit": r[2],
                         "quantity": float(r[3]) if r[3] is not None else None,
                         "rate": float(r[4]) if r[4] is not None else None,
                         "amount": int(float(r[5])) if r[5] is not None else None})
    return rows


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "../BITS-Hackathon-Dataset"
    DATA.mkdir(exist_ok=True)

    led, led_bad = ledgers(root)
    bnk, bnk_bad = bank(root)
    bills, finals, items = ra_bills(root), final_bills(root), boq(root)

    print(f"ledger entries   {len(led):5d}   unresolved {len(led_bad)}"
          f"   ({100*len(led)/max(1,len(led)+len(led_bad)):.1f}% balance-confirmed)")
    print(f"bank entries     {len(bnk):5d}   unresolved {len(bnk_bad)}"
          f"   ({100*len(bnk)/max(1,len(bnk)+len(bnk_bad)):.1f}% balance-confirmed)")
    for b in (led_bad + bnk_bad)[:4]:
        print(f"     unresolved: {b['doc']} {b['date']} delta={b['delta']} cands={b['candidates']}")

    ins = sum(r["amount"] for r in bnk if r.get("direction") == "in" and r["amount"])
    outs = sum(r["amount"] for r in bnk if r.get("direction") == "out" and r["amount"])
    print(f"   bank money in INR {ins/1e7:,.1f} Cr   out INR {outs/1e7:,.1f} Cr")
    print(f"   entries carrying an invoice id: {sum(1 for r in led+bnk if r.get('invoice_no'))}")

    print(f"\nRA bills         {len(bills):5d}")
    for b in bills:
        # every bill states work_done, GST at 18%, retention at 5% and a net --
        # check the arithmetic closes rather than trusting the extraction
        # retention is 0.0% on some bills, so a truthiness test would read a
        # legitimate zero as "missing"
        have = all(b[k] is not None for k in ("work_done", "gst", "retention", "net_claimed"))
        ok = have and abs(b["work_done"] + b["gst"] - b["retention"] - b["net_claimed"]) <= 1
        print(f"   {b['doc']:20s} contract {b['contract_no']:>4}  arithmetic closes: {ok}")

    print(f"\nfinal bills      {len(finals):5d}")
    for b in finals:
        # the as-executed BOQ total should equal the stated billed value
        ok = (b["billed_value"] and b["boq_total"]
              and abs(b["billed_value"] - b["boq_total"]) <= 0.005 * CR)
        print(f"   {b['doc']:18s} contract {b['contract_no']:>3}  {b['ra_bill_count']:>3} bills"
              f"  awarded {(b['awarded_value'] or 0)/CR:7.2f} Cr"
              f"  billed {(b['billed_value'] or 0)/CR:7.2f} Cr   BOQ total agrees: {ok}")

    print(f"\nBOQ items        {len(items):5d}   contracts "
          f"{sorted({i['contract_no'] for i in items})}")
    bad_items = [i for i in items if i["quantity"] and i["rate"] and i["amount"]
                 and abs(i["quantity"] * i["rate"] - i["amount"]) > 20]
    print(f"   qty x rate != amount on {len(bad_items)} of {len(items)} lines")

    for name, rows in [("ledger", led), ("bank", bnk), ("ra_bills", bills),
                       ("final_bills", finals), ("boq", items)]:
        json.dump(rows, open(DATA / f"{name}.json", "w"), indent=1)
    print("\nwrote ledger.json, bank.json, ra_bills.json, boq.json")
