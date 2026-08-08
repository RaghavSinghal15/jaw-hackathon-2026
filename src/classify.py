"""Question -> reasoning shape.

The ONLY language-understanding step in the pipeline. It picks a function
name; it never sees a document, never reads a value, never does arithmetic.
Worst case it picks the wrong function, which is visibly wrong and easy to
debug -- it cannot produce a plausible-but-subtly-wrong number.

Rules are tried IN ORDER, so put the specific ones first. Several shapes
share vocabulary ("combined value" appears in hop_aggregate, temporal_chain
and role_split), and the distinguishing phrase is usually the qualifier, not
the verb.
"""
import re

# (shape, pattern) -- first match wins
RULES = [
    # --- distinctive qualifiers, checked before the generic aggregates
    ("exclusion_aggregate",    r"\b(excluding|except for|other than|apart from)\b"),
    ("role_split",             r"\bas (?:the )?(prime|jv|joint venture)\b"),
    ("temporal_chain",         r"\b(after (?:that|the|her|his|its)|wrapped up after|completed after|since (?:that|her|his))"),
    ("threshold_aggregate",    r"\b(crossing|above|over|exceeding|hitting|at or above|greater than)\b.{0,40}\b(mark|line|crore|lakh|threshold|\d)"),
    ("gap_to_threshold",       r"\b(how much (?:more|additional)|must we secure|to reach|shortfall|remaining to|short of)\b"),

    # --- shapes with a signature question form
    ("rank_value",             r"\b(largest|biggest|highest).{0,60}\b(second|next)\b"),
    ("referenced_share",       r"\b(out of one hundred|percentage|percent|share of|what proportion|divided by the total)\b"),
    ("absence",               r"\b(no|lack|without|missing|not have|absent)\b.{0,40}\breference letter\b"),
    # allow a few filler words: "how many distinct WORK classifications"
    ("distinct_count",         r"\bhow many\s+(?:\w+\s+){0,3}(categor\w+|classification\w*|types|kinds|sectors)\b"),
    ("date_span",              r"\b(how many days|number of days|days (?:passed|elapsed|between)|interval from|time between|duration between)\b"),
    ("avg_work_size",          r"\b(average|mean|typical)\b.{0,30}\b(size|value|work|project|contract)\b"),
    ("doc_filtered_aggregate", r"\b(graded|marked|rated|assessed as)\b|\b(excellent|very good|satisfactory)\b"),

    # --- generic client aggregate, last because its vocabulary is common
    ("hop_aggregate",          r"\b(combined value|total value|aggregate value|sum of|total amount|overall value)\b"),
]

COMPILED = [(shape, re.compile(pat, re.I)) for shape, pat in RULES]

def classify(question):
    """Return a shape name, or None if no rule fires."""
    for shape, rx in COMPILED:
        if rx.search(question):
            return shape
    return None


if __name__ == "__main__":
    import json, sys, collections
    from pathlib import Path
    corpus = sys.argv[1] if len(sys.argv) > 1 else "../BITS-Hackathon-Dataset"
    questions = json.load(open(Path(corpus) / "sample_questions.json"))["questions"]

    hit = miss = unclassified = 0
    confusion = collections.Counter()
    for q in questions:
        got = classify(q["question"])
        if got is None:
            unclassified += 1
            print(f"  NO RULE   {q['qid']}  (true {q['shape']})")
            print(f"            {q['question'][:100]}")
        elif got == q["shape"]:
            hit += 1
        else:
            miss += 1
            confusion[(q["shape"], got)] += 1
            print(f"  WRONG     {q['qid']}  true {q['shape']:24s} got {got}")
            print(f"            {q['question'][:100]}")

    n = len(questions)
    print(f"\ncorrect {hit}/{n}   wrong {miss}   no rule fired {unclassified}")
    for (true, got), c in confusion.most_common():
        print(f"   {true} mistaken for {got}  x{c}")
