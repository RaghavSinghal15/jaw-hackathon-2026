"""LLM shape classification: batched, cached, and safe to fail.

WHY THIS IS THE PRIMARY PATH, not a fallback:
hand-written rules scored 25/25 on the sample questions and 2/15 on held-out
paraphrases of the SAME shapes. The samples were what the rules were written
against; the hidden set is deliberately reworded. Rules cannot generalise.

WHAT THE MODEL CAN AND CANNOT DO:
it picks one NAME from a fixed list. It never sees a document, never reads a
value, never does arithmetic. Anything outside the list is rejected here. So
a bad classification gives a visibly wrong KIND of answer, never a plausible
wrong number.

Classification is persisted to data/classified.json and read from there by the
answer stage. Run it once; a rate limit at midnight cannot then block you.
"""
import json, os, re, time, urllib.request
from pathlib import Path

# load .env manually (python does not read it automatically)
_env = Path(__file__).resolve().parents[1] / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if "=" in _line and not _line.strip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

DATA = Path(__file__).resolve().parents[1] / "data"
CACHE = DATA / "classify_cache.json"
BATCH = 20                      # questions per request; 30 RPM free tier
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
       "{model}:generateContent?key={key}")

from classify import RULES  # reuse the shape vocabulary

SHAPE_HELP = {
    "absence":                "count of a client's works with NO reference letter on file",
    "referenced_share":       "percentage of a client's works that DO have a reference letter",
    "hop_aggregate":          "total value of every work for a client. A person or project may be named as the route to that client but does NOT filter the works",
    "avg_work_size":          "mean value across all of a client's works",
    "exclusion_aggregate":    "total value for a client, excluding one named category of work",
    "threshold_aggregate":    "total value for a client, counting only works at or above a stated amount",
    "rank_value":             "difference between a client's largest and second-largest work",
    "doc_filtered_aggregate": "total value for a client restricted to works carrying a stated grading (Excellent/Very Good/Good/Satisfactory)",
    "distinct_count":         "how many distinct categories of work a named person has led",
    "temporal_chain":         "total value of a person's works completed AFTER their credential date",
    "date_span":              "number of days between a credential issue date and a named work's completion",
    "gap_to_threshold":       "how much MORE value is needed to reach a target. "
                              "Requires an explicit target amount stated in the question. "
                              "If no target amount is given, this is NOT the shape.",
    "role_split":             "total value for a client restricted to Prime (or JV Partner) "
                              "works. Any question saying 'as Prime' or 'as JV Partner' is "
                              "this shape.",
    "collection_rate":        "percentage out of 100 of the amount BILLED to a client "
                              "that has actually been collected/received. A billing "
                              "question, not a project-value question.",
    "awarded_vs_invoiced":    "gap between the total value of work AWARDED to a client "
                              "and the amount INVOICED/billed to them.",
    "mean_minus_median":      "rupee difference between the mean and the median contract "
                              "value across a client's works. Signed, not absolute.",
    "year_pair":              "difference in value of work completed between two named "
                              "calendar years for one client. Phrased as difference, "
                              "swing, move or gap.",
}

PROMPT = """Each line below is a question about a construction company's project records.
Classify each into exactly one reasoning shape.

Shapes:
{shapes}

Questions:
{questions}

Reply with JSON only, no prose and no markdown fences:
{{"1": "shape_name", "2": "shape_name", ...}}
Use the question numbers exactly as given. Every question must get a shape."""


def _load_cache():
    return json.load(open(CACHE)) if CACHE.exists() else {}

def _save_cache(c):
    DATA.mkdir(exist_ok=True)
    json.dump(c, open(CACHE, "w"), indent=1)


def _call(prompt, retries=4):
    """One API call, with backoff. Returns text or None -- never raises."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0}}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                URL.format(model=MODEL, key=key), data=body,
                headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            # 429s are expected on the free tier; back off and retry
            wait = 2 ** attempt * 3
            print(f"   api attempt {attempt+1} failed ({type(e).__name__}), waiting {wait}s")
            time.sleep(wait)
    return None


def classify_batch(questions):
    """questions: list of strings -> list of shape names (None where unresolved)."""
    numbered = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
    text = _call(PROMPT.format(
        shapes="\n".join(f"- {k}: {v}" for k, v in SHAPE_HELP.items()),
        questions=numbered))
    if not text:
        return [None] * len(questions)
    try:
        cleaned = re.sub(r"```(json)?", "", text).strip()
        parsed = json.loads(cleaned)
    except Exception:
        return [None] * len(questions)
    # reject anything not in the allowed vocabulary
    return [parsed.get(str(i + 1)) if parsed.get(str(i + 1)) in SHAPE_HELP else None
            for i in range(len(questions))]

# Unambiguous domain vocabulary. These override the model because they have
# exactly one meaning in this corpus -- unlike the phrasing-specific rules in
# classify.py, which scored 2/15 on held-out paraphrases.
# Keep this list SHORT and only add terms that cannot mean anything else.
OVERRIDES = [
    ("role_split", r"\b(as (?:the )?prime|prime contractor|jv partner|joint venture partner)\b"),
]

def classify_all(questions, use_cache=True):
    """questions: list of {qid, question}. Returns {qid: (shape, route)}."""
    cache = _load_cache() if use_cache else {}
    out, todo = {}, []

    for q in questions:
        forced = next((s for s, p in OVERRIDES if re.search(p, q["question"], re.I)), None)
        if forced:
            out[q["qid"]] = (forced, "override")
        elif use_cache and q["question"] in cache:
            out[q["qid"]] = (cache[q["question"]], "cache")
        else:
            todo.append(q)

    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        print(f"   classifying {i+1}-{i+len(chunk)} of {len(todo)}")
        for q, shape in zip(chunk, classify_batch([c["question"] for c in chunk])):
            if shape:
                cache[q["question"]] = shape
                out[q["qid"]] = (shape, "llm")
            else:
                out[q["qid"]] = ("hop_aggregate", "fallback")   # never blank
        _save_cache(cache)          # save after every batch, not at the end

    return out


if __name__ == "__main__":
    import sys, collections
    arg = Path(sys.argv[1] if len(sys.argv) > 1 else "../BITS-Hackathon-Dataset")
    # accept either a corpus directory or a questions file directly --
    # the samples live inside the corpus, the hidden set is a standalone file
    path = arg / "sample_questions.json" if arg.is_dir() else arg
    data = json.load(open(path, encoding="utf-8"))
    questions = data["questions"] if isinstance(data, dict) and "questions" in data else data

    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set -- nothing to do.")
        sys.exit(1)

    result = classify_all(questions)
    routes = collections.Counter(r for _, r in result.values())
    print(f"\nclassified {len(result)}   routes {dict(routes)}")
    print("shapes used:", dict(collections.Counter(s for s, _ in result.values())))

    # the samples carry a gold shape; the hidden set does not
    gold = [q for q in questions if "shape" in q]
    if gold:
        hits = sum(1 for q in gold if result[q["qid"]][0] == q["shape"])
        print(f"shapes correct {hits}/{len(gold)}")
        for q in gold:
            got, route = result[q["qid"]]
            if got != q["shape"]:
                print(f"  {q['qid']}  want {q['shape']:24s} got {got} ({route})")

    json.dump({k: v[0] for k, v in result.items()}, open(DATA / "classified.json", "w"), indent=1)
    print("wrote data/classified.json")