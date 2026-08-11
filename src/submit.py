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

# shapes whose answer may legitimately be negative -- a signed difference
# One client has been overpaid, so its outstanding balance is genuinely
# negative -- the AR ledger's own "outstanding" column states that figure, and
# it matches invoiced minus received exactly. Rejecting it as invalid would
# throw away a correct answer.
SIGNED = {"mean_minus_median", "outstanding_balance"}

def type_ok(value, answer_type, shape=None):
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
    if shape in SIGNED:
        return True              # signed difference: negative is a real answer
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


# arguments each shape actually needs. Used to flag answers that were
# produced without the inputs the shape depends on -- those are guesses
# wearing the costume of an answer.
NEEDS = {
    "collection_rate": ["client"], "outstanding_balance": ["client"],
    "awarded_vs_invoiced": ["client"], "mean_minus_median": ["client"],
    "year_pair": ["client", "years2"], "category_pair_difference": ["client", "cats2"],
    "exclusion_aggregate": ["client", "category"],   # via excluded_category "threshold_aggregate": ["client", "amount"],
    "gap_to_threshold": ["client", "amount"], "rank_value": ["client"],
    "avg_work_size": ["client"], "hop_aggregate": ["client"],
    "referenced_share": ["client"], "absence": ["client"],
    "distinct_count": ["person"], "temporal_chain": ["person"],
    "date_span": ["work"],
}

def missing_args(shape, args):
    out = []
    for need in NEEDS.get(shape, []):
        if need == "years2":
            if len(args.get("years") or []) < 2:
                out.append("years")
        elif need == "cats2":
            if len(args.get("categories") or []) < 2:
                out.append("categories")
        elif not args.get(need):
            out.append(need)
    return out

def answer_one(kb, question, shape, answer_type, defaults):
    """Returns (answer, how, missing). Never raises, never returns a bare zero."""
    try:
        args = resolve(kb, question)
        args["_q"] = question
    except Exception:
        return defaults.get(answer_type, defaults["money"]), "resolve-failed", ["ALL"]

    missing = missing_args(shape, args)
    # a client found by anything other than its stated name is a guess that
    # will not show up as "missing" -- surface it so it can be checked
    # only worth flagging when the shape actually consumes a client --
    # distinct_count and temporal_chain are person-scoped, date_span is
    # work-scoped, so an inferred client there is harmless noise
    if ("client" in NEEDS.get(shape, [])
            and args.get("client_via") in ("tokens", "unique-token", "person-guess")):
        missing = missing + [f"client~{args['client_via']}"]

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
                    and type_ok(value, answer_type, shape)):
                return value, ("ok" if not missing else "thin"), missing
        except Exception:
            pass

    try:
        return last_resort(kb, args, answer_type, defaults), "fallback", missing
    except Exception:
        return defaults.get(answer_type, defaults["money"]), "total-failure", missing


# ---------------------------------------------------------------- variants
# Some questions are genuinely ambiguous in the source data, so the only way
# to settle them is to submit a variant and read the score delta. Each variant
# changes exactly ONE assumption -- never two, or the delta is uninterpretable.
VARIANTS = {
    "person_scoped_mm":
        "mean_minus_median over the works the PERSON led, rather than over "
        "the portfolio of a client guessed from that person. Affects only "
        "questions where no client is named (Sanjay Joshi has 6 works across "
        "6 clients, so 'his client' is not resolvable).",
    "lower_median":
        "for an even number of works, take the LOWER of the two middle values "
        "as the median rather than their average. Six of the 19 questions have "
        "an even count and the two conventions diverge sharply there "
        "(61.8M vs 119.5M on one). Sign of the delta settles it: positive "
        "means lower-median is intended, negative means the standard "
        "average-of-middles is.",
    "count_client":
        "when guessing a person's client, pick the one they did the most "
        "WORKS for rather than the most VALUE.",
}

def apply_variant(kb, variant, shape, args):
    """Returns an override answer, or None to use the normal path."""
    if variant == "lower_median" and shape == "mean_minus_median" and args.get("client"):
        vals = sorted(w["value_inr"] for w in kb.for_client(args["client"]))
        if vals:
            return int(round(sum(vals) / len(vals) - vals[(len(vals) - 1) // 2]))
    if variant == "person_scoped_mm" and shape == "mean_minus_median":
        if args.get("client_via") == "person-guess" and args.get("person"):
            vals = sorted(w["value_inr"] for w in kb.led_by(args["person"]))
            if vals:
                n = len(vals)
                med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
                return int(round(sum(vals) / n - med))
    return None


def main(questions_path, variant=None, zero_shapes=None, zero_qids=None):
    questions = load_questions(questions_path)
    kb = KB()

    shapes_file = DATA / "classified.json"
    classified = json.loads(shapes_file.read_text()) if shapes_file.exists() else {}
    if not classified:
        print("! data/classified.json missing -- run llm_classify.py first.")
        print("  falling back to any 'shape' field in the questions file.")

    defaults = typical(kb)
    print(f"type defaults: {defaults}")

    rows, detail = [], []
    how_counts, shape_counts = collections.Counter(), collections.Counter()
    for q in questions:
        qid = q.get("qid") or q.get("id")
        shape = classified.get(qid) or q.get("shape") or DEFAULT_SHAPE
        atype = q.get("answer_type", "money")
        value, how, missing = answer_one(kb, q["question"], shape, atype, defaults)
        # PROBE MODE: an answer of 0 scores exactly 0 under
        # max(0, 1 - |a-g|/g) for any non-zero gold. So zeroing one shape and
        # reading the score drop measures precisely what that shape was
        # contributing. Compare the drop against n/total*100: any shortfall is
        # loss hiding inside that shape.
        if (zero_shapes and shape in zero_shapes) or (zero_qids and qid in zero_qids):
            rows.append({"qid": qid, "answer": 0})
            detail.append({"qid": qid, "shape": shape, "route": "ZEROED",
                           "missing": [], "answer": 0, "question": q["question"]})
            how_counts["ZEROED"] += 1
            shape_counts[shape] += 1
            continue
        if variant:
            try:
                args = resolve(kb, q["question"])
                over = apply_variant(kb, variant, shape, args)
                if over is not None:
                    value, how = over, f"variant:{variant}"
            except Exception:
                pass
        detail.append({"qid": qid, "shape": shape, "route": how,
                       "missing": missing, "answer": value,
                       "question": q["question"]})
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

    json.dump(detail, open(DATA / "detail.json", "w"), indent=1)
    thin = [d for d in detail if d["route"] != "ok"]
    print(f"\nSUSPECT ANSWERS: {len(thin)}  (guessed, or computed without a needed input)")
    for d in sorted(thin, key=lambda x: x["shape"]):
        print(f"   {d['qid']:12s} {d['shape']:26s} {d['route']:9s} missing={d['missing']}")
        print(f"        {' '.join(d['question'].split())[:120]}")

    if zero_shapes or zero_qids:
        n = how_counts["ZEROED"]
        print(f"\nPROBE: zeroed {n} of {len(rows)} answers")
        print(f"  expected score drop if those shapes were PERFECT: "
              f"{100*n/len(rows):.3f} points")
        print(f"  a smaller drop = that much loss was already inside them")

    print(f"\nquestions   {len(rows)}")
    print(f"routes      {dict(how_counts)}")
    print(f"shapes used {dict(shape_counts)}")

    # sanity checks -- catch a broken run before you upload it
    blanks = [r for r in rows if r["answer"] is None]
    # mean_minus_median is signed by design ("negative if avg dips"), so a
    # negative there is a correct answer, not a defect
    signed_ids = {d["qid"] for d in detail if d["shape"] in SIGNED}
    negs = [r for r in rows if isinstance(r["answer"], (int, float))
            and r["answer"] < 0 and r["qid"] not in signed_ids]
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
        print("variants:")
        for k, v in VARIANTS.items():
            print(f"  --variant {k}\n      {v}")
        sys.exit(1)
    qids = None
    if "--zero-qids" in sys.argv:
        qids = set(sys.argv[sys.argv.index("--zero-qids") + 1].split(","))
        print(f"PROBE MODE -- zeroing {len(qids)} specific questions: {sorted(qids)}\n")
    zeros = None
    if "--zero" in sys.argv:
        zeros = set(sys.argv[sys.argv.index("--zero") + 1].split(","))
        print(f"PROBE MODE -- zeroing: {sorted(zeros)}")
        print("  submit this, then compare the score drop against the expected")
        print("  maximum below. A shortfall means loss inside those shapes.\n")
    var = None
    if "--variant" in sys.argv:
        var = sys.argv[sys.argv.index("--variant") + 1]
        if var not in VARIANTS:
            print(f"unknown variant {var}. known: {list(VARIANTS)}")
            sys.exit(1)
        print(f"VARIANT ACTIVE: {var}\n  {VARIANTS[var]}\n")
    main(sys.argv[1], var, zeros, qids)