"""Past performance portfolio -- one 64-page document indexing all 155 works.

This is a TRUE TABLE, so flat text is useless: 'INR', '200.00', 'Cr' come out
on separate lines and long work names wrap mid-phrase. Column identity lives
in the x-coordinate, not in the text stream, so we read word positions.

Its value is corroboration. It carries no project manager, grading, sector or
certificate ref -- so it can't replace the certificates, but it independently
restates work / client / category / value / completion for every work.
"""
import collections, glob, os, re
from pathlib import Path
import fitz
from common import money, date, work_key, obs

FOLDER = "documents/past_performance_portfolio"

# column left/right bounds in PDF points, read off the header row
COLS = [(60, 100, "idx"), (100, 215, "work"), (215, 335, "client"),
        (335, 405, "category"), (405, 455, "value"), (455, 540, "completed")]

def rows_from(path):
    """Group words into records: bucket by x for the column, by y for the line.

    A record starts wherever the index column holds a bare number; continuation
    lines (wrapped names) attach to the record above.
    """
    records, current, last_y = [], None, None
    for page in fitz.open(path):
        last_y = None
        lanes = collections.defaultdict(lambda: collections.defaultdict(list))
        for x0, y0, x1, y1, word, *_ in page.get_text("words"):
            col = next((c for a, b, c in COLS if a <= x0 < b), None)
            if col:
                lanes[round(y0)][col].append((x0, word))
        for y in sorted(lanes):
            cells = lanes[y]
            idx = " ".join(w for _, w in sorted(cells.get("idx", [])))
            if re.fullmatch(r"\d+", idx):
                if current:
                    records.append(current)
                current = collections.defaultdict(list)
                current["idx"] = idx
                last_y = y
            elif last_y is None or y - last_y > 20:
                # not a wrapped continuation line -- the index table has ended
                # and this is other page content. close the record and ignore.
                if current:
                    records.append(current)
                current = None
            if current is not None:
                last_y = y
                for c in ("work", "client", "category", "value", "completed"):
                    current[c] += [w for _, w in sorted(cells.get(c, []))]
    if current:
        records.append(current)
    return records

def extract_one(path):
    doc = os.path.basename(path)[:-4]
    out, bad = [], 0
    for r in rows_from(path):
        join = lambda k: " ".join(r[k]).replace(" —", "—").strip()
        name = join("work")
        key = work_key(name)
        if not key:
            bad += 1
            continue
        fields = {"work_name": name,
                  "client": join("client"),
                  "category": join("category"),
                  "value_inr": money(join("value")),
                  "completion_date": date(join("completed"))}
        out += [obs(key, f, v, doc, "portfolio") for f, v in fields.items() if v is not None]
    return out, bad

if __name__ == "__main__":
    import sys, json
    ROOT = Path(__file__).resolve().parents[1]
    (ROOT / "data").mkdir(exist_ok=True)
    root = sys.argv[1] if len(sys.argv) > 1 else "../BITS-Hackathon-Dataset"

    observations, dropped = [], 0
    for path in sorted(glob.glob(os.path.join(root, FOLDER, "*.pdf"))):
        o, b = extract_one(path)
        observations += o
        dropped += b

    print(f"works indexed {len({o['subject'] for o in observations})}   (expected 155)")
    print(f"rows dropped  {dropped}")
    print(f"observations  {len(observations)}")

    out = ROOT / "data" / "observations_portfolio.json"
    json.dump(observations, open(out, "w"), indent=1)
    print(f"wrote {out.relative_to(ROOT)}")
