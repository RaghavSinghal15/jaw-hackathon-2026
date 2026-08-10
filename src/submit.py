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
import csv, json, sys, collections
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


def last_resort(kb, args):
    """Absolute fallback: total for whatever client was mentioned.

    If even the client did not resolve, return the corpus-wide total. It is
    almost certainly wrong, but it is a number, and a number can land in a
    scoring band while a blank cannot.
    """
    if args.get("client"):
        return sum(w["value_inr"] for w in kb.for_client(args["client"]))
    return sum(w["value_inr"] for w in kb.works)


def answer_one(kb, question, shape):
    """Returns (answer, how). Never raises."""
    try:
        args = resolve(kb, question)
        args["_q"] = question
    except Exception:
        return 0, "resolve-failed"

    fn = SHAPES.get(shape)
    if fn:
        try:
            value = fn(kb, args)
            if value is not None:
                return value, "ok"
        except Exception:
            pass                     # fall through rather than lose the question

    try:
        return last_resort(kb, args), "fallback"
    except Exception:
        return 0, "total-failure"


def main(questions_path):
    questions = load_questions(questions_path)
    kb = KB()

    shapes_file = DATA / "classified.json"
    classified = json.loads(shapes_file.read_text()) if shapes_file.exists() else {}
    if not classified:
        print("! data/classified.json missing -- run llm_classify.py first.")
        print("  falling back to any 'shape' field in the questions file.")

    rows, how_counts, shape_counts = [], collections.Counter(), collections.Counter()
    for q in questions:
        qid = q.get("qid") or q.get("id")
        shape = classified.get(qid) or q.get("shape") or DEFAULT_SHAPE
        value, how = answer_one(kb, q["question"], shape)
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
