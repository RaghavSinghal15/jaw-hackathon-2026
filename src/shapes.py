"""One function per reasoning shape.

Every shape starts by establishing a COMPLETE set -- all works for a client,
all works led by a person. That is precisely what retrieval cannot give you,
and it is why absence and aggregate questions are trivial here.

No LLM, no arithmetic in a prompt. Each answer is a traversal over verified
facts, so it is reproducible and explainable.
"""
import datetime as dt

def _days(a, b):
    f = "%Y-%m-%d"
    return abs((dt.datetime.strptime(b, f) - dt.datetime.strptime(a, f)).days)


def absence(kb, a):
    """Works for this client with NO reference letter on file."""
    return sum(1 for w in kb.for_client(a["client"]) if not w.get("has_reference_letter"))

def referenced_share(kb, a):
    """Percentage of the client's works that carry a reference letter."""
    works = kb.for_client(a["client"])
    n = sum(1 for w in works if w.get("has_reference_letter"))
    return round(100 * n / len(works), 2)

def hop_aggregate(kb, a):
    """Person -> named work -> its client -> EVERY work for that client.

    The person and the named work are the hop chain that identifies the
    client; they are not filters. Evidence: HS-IC-0007 and 0008 both sum the
    client's entire portfolio, including works led by other managers.
    """
    client = a["client"] or kb.work_named(a["work"])["client"]
    return sum(w["value_inr"] for w in kb.for_client(client))

def avg_work_size(kb, a):
    """Mean value across ALL of the commissioning client's completed works."""
    client = a["client"] or kb.work_named(a["work"])["client"]
    works = kb.for_client(client)
    return int(sum(w["value_inr"] for w in works) / len(works))

def exclusion_aggregate(kb, a):
    """Client total, excluding one category."""
    ex = (a.get("category") or "").lower()
    return sum(w["value_inr"] for w in kb.for_client(a["client"])
               if ex not in (w.get("category") or "").lower())

def threshold_aggregate(kb, a):
    """Client total, counting only works at or above a stated amount."""
    bar = a["amount"]
    return sum(w["value_inr"] for w in kb.for_client(a["client"]) if w["value_inr"] >= bar)

def gap_to_threshold(kb, a):
    """How much more is needed to reach a credential target."""
    have = sum(w["value_inr"] for w in kb.for_client(a["client"]))
    return max(0, a["amount"] - have)

def rank_value(kb, a):
    """Gap between the client's largest and second-largest work."""
    vals = sorted((w["value_inr"] for w in kb.for_client(a["client"])), reverse=True)
    return vals[0] - vals[1]

def role_split(kb, a):
    """Client total for works where we were Prime (JV Partner is recorded
    explicitly; anything unstated is Prime -- see merge.derive rule 4)."""
    want = "JV Partner" if "jv" in a["_q"].lower() else "Prime"
    return sum(w["value_inr"] for w in kb.for_client(a["client"])
               if w.get("contractor_role") == want)

def doc_filtered_aggregate(kb, a):
    """Client total, restricted to works carrying a stated grading."""
    g = (a.get("grade") or "").lower()
    return sum(w["value_inr"] for w in kb.for_client(a["client"])
               if (w.get("grading") or "").lower() == g)

def distinct_count(kb, a):
    """How many distinct categories this person has led to completion."""
    return len({w["category"] for w in kb.led_by(a["person"])})

def temporal_chain(kb, a):
    """Value of the person's works completed AFTER their credential date."""
    cut = a["date"] or kb.credential_of(a["person"], "PMP")["issued"]
    return sum(w["value_inr"] for w in kb.led_by(a["person"])
               if w["completion_date"] > cut)

def date_span(kb, a):
    """Days from a credential issue date to a named work's completion."""
    work = kb.work_named(a["work"])
    start = a["date"] or kb.credential_of(a["person"], "PMP")["issued"]
    return _days(start, work["completion_date"])


# ---------------------------------------------------------------- billing
# These read the AR ledger (receivables.json), not the completion
# certificates. A client can have works but no billing rows -- 4 of 28 do --
# so each one degrades to something sensible rather than raising.

def collection_rate(kb, a):
    """Percentage of everything billed to a client that has been collected."""
    invoiced, received = kb.billing_for(a["client"])
    if not invoiced:
        return 0.0
    return round(100 * received / invoiced, 2)

def awarded_vs_invoiced(kb, a):
    """Gap between the value of work awarded and the amount invoiced.

    The only shape spanning both islands: awarded value comes from the
    completion certificates, invoiced from the AR ledger.
    """
    awarded = sum(w["value_inr"] for w in kb.for_client(a["client"]))
    invoiced, _ = kb.billing_for(a["client"])
    return abs(awarded - invoiced)

# ---------------------------------------------------------------- shape stats

def mean_minus_median(kb, a):
    """Rupee difference between the mean and the median contract value.

    They diverge when a portfolio holds one outsized project, which is
    presumably the point of asking.
    """
    vals = sorted(w["value_inr"] for w in kb.for_client(a["client"]))
    if not vals:
        return 0
    n = len(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    return int(round(sum(vals) / n - median))

def year_pair(kb, a):
    """Absolute difference in value completed between two named years.

    Phrased as "difference", "swing", "move" or "gap" -- all absolute.
    """
    years = a.get("years") or []
    if len(years) < 2:
        return 0
    first = sum(w["value_inr"] for w in kb.completed_in(a["client"], years[0]))
    second = sum(w["value_inr"] for w in kb.completed_in(a["client"], years[1]))
    return abs(first - second)


SHAPES = {f.__name__: f for f in [
    absence, referenced_share, hop_aggregate, avg_work_size, exclusion_aggregate,
    threshold_aggregate, gap_to_threshold, rank_value, role_split,
    doc_filtered_aggregate, distinct_count, temporal_chain, date_span,
    collection_rate, awarded_vs_invoiced, mean_minus_median, year_pair]}


def answer(kb, question_text, shape, resolver):
    args = resolver(kb, question_text)
    args["_q"] = question_text
    return SHAPES[shape](kb, args)


if __name__ == "__main__":
    import json, sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from kb import KB, resolve

    ROOT = Path(__file__).resolve().parents[1]
    corpus = sys.argv[1] if len(sys.argv) > 1 else "../BITS-Hackathon-Dataset"
    questions = json.load(open(Path(corpus) / "sample_questions.json"))["questions"]

    kb = KB()
    rows, wrong = [], []
    for q in questions:
        try:
            got = answer(kb, q["question"], q["shape"], resolve)
        except Exception as e:
            got = None
            wrong.append((q, f"ERROR {type(e).__name__}: {e}"))
            rows.append({"qid": q["qid"], "answer": 0})
            continue
        rows.append({"qid": q["qid"], "answer": got})
        if got != q["answer"]:
            wrong.append((q, got))

    print(f"exact matches {len(questions) - len(wrong)} / {len(questions)}")
    for q, got in wrong:
        print(f"\n  {q['qid']} [{q['shape']}]  expected {q['answer']}  got {got}")
        print(f"     {q['question'][:110]}")

    out = ROOT / "data" / "submission_samples.jsonl"
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"\nwrote {out.relative_to(ROOT)}")
