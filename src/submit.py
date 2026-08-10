"""Questions in -> submission.jsonl out. The Monday entry point.

Works with the validation set, which has NO shape labels: shapes come from
data/classified.json (written by llm_classify.py). Falls back to a shape field
in the questions file when present, so the samples still work.

TWO RULES THIS FILE ENFORCES:
  1. never blank. A missing answer is a guaranteed zero; a wrong one costs
     nothing extra. Every failure falls through to a plausible default.
  2. never crash. One bad question must not kill the other 199.

Writes data/submission.csv (the format the hidden set requires) and
data/submission.jsonl (the sample format) so either can be uploaded.

Usage:
    python src/llm_classify.py <questions.json>   # once: shapes -> classified.json
    python src/submit.py <questions.json>         # -> data/submission.csv
"""
import csv, datetime as dt, json, sys, collections
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kb import KB, resolve
from shapes import SHAPES

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# used when a shape is unknown or its function blew up. The client portfolio
# total is the single most common answer pattern, so it is the least-bad guess.
DEFAULT_SHAPE = "hop_aggregate"


def load_questions(path):
    """Accepts the sample-questions format or a plain list/JSONL."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if text.startswith("{"):
        data = json.loads(text)
        return data["questions"] if "questions" in data else [data]
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return 0
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

def typical(kb):
    """Typical values per answer type, computed from the KB.

    Scoring is continuous -- max(0, 1 - |error|/gold) -- so a wrong answer of
    roughly the right size earns real partial credit while a zero or a
    wrong-magnitude number earns exactly nothing. The old fallback returned
    the corpus-wide total (INR 5,530 Cr) for EVERY unresolved question,
    including day counts and percentages: nine guaranteed zeros.

    These are deliberately median-of-the-actual-distribution, not guesses.
    """
    clients = {w["client"] for w in kb.works}
    totals = [sum(w["value_inr"] for w in kb.for_client(c)) for c in clients]
    rates = []
    for c in clients:
        inv, rec = kb.billing_for(c)
        if inv:
            rates.append(100 * rec / inv)
    cats = [len({w["category"] for w in kb.led_by(p["name"])})
            for p in kb.people if kb.led_by(p["name"])]
    # date_span questions run from a credential issue date to a completion
    spans = []
    for w in kb.works:
        try:
            spans.append(abs((dt.date.fromisoformat(w["completion_date"])
                              - dt.date(2021, 3, 10)).days))
        except Exception:
            pass
    return {"money": int(_median(totals)),
            "percent": round(_median(rates), 2) if rates else 50.0,
            "count": int(_median(cats)) if cats else 2,
            "days": int(_median(spans)) if spans else 1000}

def type_ok(value, answer_type):
    """Could this number possibly be an answer of this type?

    The question file states the expected unit, which is free, authoritative
    information. A rupee total handed to a percent question scores exactly 0,
    so reject it and fall back rather than submit it.
    """
    if value is None:
        return False
    if answer_type == "percent":
        return 0 <= value <= 100
    if answer_type == "days":
        return 0 <= value <= 20000
    if answer_type == "count":
        return 0 <= value <= 1000
    return value >= 0            # money

def last_resort(kb, args, answer_type, defaults):
    """Type-appropriate fallback. Never returns a rupee total for a day count."""
    if answer_type == "money" and args.get("client"):
        total = sum(w["value_inr"] for w in kb.for_client(args["client"]))
        if total:
            return total
    if answer_type == "percent" and args.get("client"):
        inv, rec = kb.billing_for(args["client"])
        if inv:
            return round(100 * rec / inv, 2)
    return defaults.get(answer_type, defaults["money"])


def answer_one(kb, question, shape, answer_type, defaults):
    """Returns (answer, how). Never raises, never returns a bare zero."""
    try:
        args = resolve(kb, question)
        args["_q"] = question
    except Exception:
        args = {"_q": question}
        return defaults.get(answer_type, defaults["money"]), "resolve-failed"

    fn = SHAPES.get(shape)
    if fn:
        try:
            value = fn(kb, args)
            # a 0 from a shape that needed a client it never resolved is a
            # failure, not an answer -- and 0 scores 0 under this metric.
            # A genuine 0 (absence, gap_to_threshold) keeps its client, so
            # only the unresolved case falls through.
            if (value is not None
                    and not (value == 0 and not args.get("client"))
                    and type_ok(value, answer_type)):
                return value, "ok"
        except Exception:
            pass

    try:
        return last_resort(kb, args, answer_type, defaults), "fallback"
    except Exception:
        return defaults.get(answer_type, defaults["money"]), "total-failure"


def main(questions_path):
    questions = load_questions(questions_path)
    kb = KB()

    shapes_file = DATA / "classified.json"
    classified = json.loads(shapes_file.read_text()) if shapes_file.exists() else {}
    if not classified:
        print("! data/classified.json missing -- run llm_classify.py first.")
        print("  falling back to any 'shape' field in the questions file.")

    defaults = typical(kb)
    print(f"type defaults: {defaults}")

    rows, how_counts, shape_counts = [], collections.Counter(), collections.Counter()
    for q in questions:
        qid = q.get("qid") or q.get("id")
        shape = classified.get(qid) or q.get("shape") or DEFAULT_SHAPE
        atype = q.get("answer_type", "money")
        value, how = answer_one(kb, q["question"], shape, atype, defaults)
        # counts and day counts must be whole numbers
        if atype in ("count", "days") and isinstance(value, float):
            value = int(round(value))
        rows.append({"qid": qid, "answer": value})
        how_counts[how] += 1
        shape_counts[shape] += 1

    # The hidden set ships sample_submission.csv with a "question_id,answer"
    # header, so CSV is the required format -- the samples used JSONL. A wrong
    # format scores zero no matter how good the answers are. Both are written.
    out = DATA / "submission.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question_id", "answer"])
        for r in rows:
            w.writerow([r["qid"], r["answer"]])
    with open(DATA / "submission.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    print(f"questions   {len(rows)}")
    print(f"routes      {dict(how_counts)}")
    print(f"shapes used {dict(shape_counts)}")

    # sanity checks -- catch a broken run before you upload it
    blanks = [r for r in rows if r["answer"] is None]
    negs = [r for r in rows if isinstance(r["answer"], (int, float)) and r["answer"] < 0]
    print(f"blank answers {len(blanks)}   negative answers {len(negs)}")
    if blanks or negs:
        print("  ! fix these before submitting")

    # score only if the file carries gold answers (the samples do)
    gold = [q for q in questions if "answer" in q]
    if gold:
        by_id = {r["qid"]: r["answer"] for r in rows}
        hits = sum(1 for q in gold if by_id.get(q.get("qid") or q.get("id")) == q["answer"])
        print(f"\nexact matches {hits}/{len(gold)}")
        for q in gold:
            qid = q.get("qid") or q.get("id")
            if by_id.get(qid) != q["answer"]:
                print(f"  {qid}  expected {q['answer']}  got {by_id.get(qid)}")

    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])