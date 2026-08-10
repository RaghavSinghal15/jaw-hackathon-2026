"""What can you check when there are no gold answers? More than you'd think.

Four checks, none of which need the answer key:

 1. TYPE CONSISTENCY -- a percent answer outside 0-100, a count that isn't a
    whole number, a day-count that's negative or absurd. Any of these is a
    guaranteed zero, so they are free points left on the table.
 2. DUPLICATE ANSWERS -- if many questions return the identical number, they
    are probably all falling through to the same fallback. The corpus-wide
    total showing up 20 times means 20 questions failed silently.
 3. SUSPICIOUS ZEROS -- a shape that returns 0 usually means an argument did
    not resolve, not that the answer is zero.
 4. SHAPE PLAUSIBILITY -- shape counts against the answer_type mix.

    python src/diagnose.py questions_v13.json
"""
import collections, csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# which shapes may legitimately answer which answer_type
TYPE_OF_SHAPE = {
    "collection_rate": "percent", "referenced_share": "percent",
    "date_span": "days",
    "absence": "count", "distinct_count": "count",
}

def load(path):
    d = json.load(open(path, encoding="utf-8"))
    return d["questions"] if isinstance(d, dict) else d

def main(qpath):
    questions = load(qpath)
    byid = {q["qid"]: q for q in questions}
    classified = json.loads((DATA / "classified.json").read_text())
    answers = {}
    with open(DATA / "submission.csv", newline="", encoding="utf-8") as f:
        for row in list(csv.reader(f))[1:]:
            if len(row) >= 2:
                try:
                    answers[row[0]] = float(row[1])
                except ValueError:
                    answers[row[0]] = None

    print(f"questions {len(questions)}   answers {len(answers)}   "
          f"classified {len(classified)}")

    # ---- 1. type violations
    bad = []
    for qid, v in answers.items():
        t = byid.get(qid, {}).get("answer_type")
        if v is None:
            bad.append((qid, t, v, "unparseable"))
        elif t == "percent" and not (0 <= v <= 100):
            bad.append((qid, t, v, "percent outside 0-100"))
        elif t == "count" and (v != int(v) or v < 0):
            bad.append((qid, t, v, "count not a non-negative integer"))
        elif t == "days" and (v < 0 or v > 20000):
            bad.append((qid, t, v, "implausible day count"))
        elif t == "money" and v < 0:
            bad.append((qid, t, v, "negative money"))
    print(f"\n1. TYPE VIOLATIONS: {len(bad)}")
    for qid, t, v, why in bad[:10]:
        print(f"   {qid}  type={t:7s} answer={v}  <- {why}")

    # ---- 2. duplicate answers
    dupes = collections.Counter(v for v in answers.values() if v is not None)
    repeated = [(v, n) for v, n in dupes.most_common() if n > 1]
    print(f"\n2. REPEATED ANSWERS: {sum(n for _, n in repeated)} answers share a value")
    for v, n in repeated[:8]:
        qids = [q for q, a in answers.items() if a == v][:4]
        shapes = {classified.get(q) for q in qids}
        print(f"   {v!s:>18}  x{n:<3} shapes={shapes}  e.g. {qids[:3]}")

    # ---- 3. zeros
    zeros = [q for q, v in answers.items() if v == 0]
    print(f"\n3. ZERO ANSWERS: {len(zeros)}")
    zshapes = collections.Counter(classified.get(q, "?") for q in zeros)
    for s, n in zshapes.most_common():
        print(f"   {s:24s} {n}")

    # ---- 4. shape vs type
    print("\n4. SHAPE / TYPE CROSS-TAB")
    grid = collections.Counter((classified.get(q["qid"], "?"), q["answer_type"])
                               for q in questions)
    shapes = sorted({s for s, _ in grid})
    for s in shapes:
        row = {t: n for (ss, t), n in grid.items() if ss == s}
        expect = TYPE_OF_SHAPE.get(s, "money")
        wrong = sum(n for t, n in row.items() if t != expect)
        flag = "  <- MIXED TYPES" if wrong else ""
        print(f"   {s:24s} {row}{flag}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "questions_v13.json")