"""Flag questions where the classifier's shape conflicts with a strong signal.

Type-consistency already proves the classifier never crosses money/percent/
days/count. What it cannot show is a swap WITHIN a type -- hop_aggregate where
avg_work_size was meant, for instance. At 333 questions a classifier that is
98.5% accurate leaves ~5 wrong, which is the size of the remaining loss.

These rules are deliberately HIGH-PRECISION and low-recall: each fires only on
vocabulary that admits one reading. A disagreement is not proof the classifier
is wrong -- it is a question worth reading by hand.

    python src/crosscheck.py questions_v14.json
"""
import json, re, sys, collections
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kb import KB, resolve

ROOT = Path(__file__).resolve().parents[1]

# (shape, pattern, description) -- only unambiguous vocabulary
SIGNALS = [
    ("mean_minus_median",  r"\bmedian\b", "says median"),
    ("date_span",          r"how many days|number of days|days (?:to|until|elapsed)", "asks for days"),
    ("absence",            r"\b(?:lack|no|without|missing)\b[^.]{0,40}reference letter", "absence of a letter"),
    ("collection_rate",    r"\bcollect(?:ed|ion)\b", "collection"),
    ("outstanding_balance", r"still (?:owed|due|pending)|unpaid|outstanding|remaining balance", "balance owed"),
    ("awarded_vs_invoiced", r"award(?:ed)?[^.]{0,60}(?:invoic|bill|claim|sanction)", "awarded vs billed"),
    ("rank_value",         r"(?:largest|biggest|highest)[^.]{0,70}(?:second|next|runner)", "top vs second"),
    ("gap_to_threshold",   r"how much (?:more|additional|further)|to (?:reach|clear|hit) the", "shortfall to a target"),
    ("distinct_count",     r"(?:distinct|different|separate)[^.]{0,20}(?:work )?categor", "distinct categories"),
    ("referenced_share",   r"out of (?:100|a hundred)", "percentage out of 100"),
]

def signals_for(text):
    t = text.lower()
    return [(s, why) for s, pat, why in SIGNALS if re.search(pat, t)]

def main(qpath):
    questions = json.load(open(qpath, encoding="utf-8"))
    questions = questions["questions"] if isinstance(questions, dict) else questions
    classified = json.loads((ROOT / "data" / "classified.json").read_text())
    kb = KB()

    conflicts = []
    for q in questions:
        got = classified.get(q["qid"])
        sig = signals_for(q["question"])
        if not sig:
            continue
        if got not in [s for s, _ in sig]:
            conflicts.append((q, got, sig))

    print(f"questions {len(questions)}   with a strong signal "
          f"{sum(1 for q in questions if signals_for(q['question']))}")
    print(f"CONFLICTS: {len(conflicts)}\n")
    for q, got, sig in conflicts:
        a = resolve(kb, q["question"])
        print(f"  {q['qid']}  classified={got}")
        print(f"     signal suggests: {', '.join(f'{s} ({w})' for s, w in sig)}")
        print(f"     client={a['client']}  cats={a['categories']}  years={a['years']}")
        print(f"     {' '.join(q['question'].split())[:150]}\n")

    # also: shapes that need two categories or two years but only found one
    print("SHAPES MISSING A SECOND ARGUMENT:")
    for q in questions:
        got = classified.get(q["qid"])
        a = resolve(kb, q["question"])
        if got == "category_pair_difference" and len(a["categories"]) < 2:
            print(f"  {q['qid']} category_pair but cats={a['categories']}")
        if got == "year_pair" and len(a["years"]) < 2:
            print(f"  {q['qid']} year_pair but years={a['years']}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "questions_v14.json")