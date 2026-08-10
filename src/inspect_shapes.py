"""Eyeball what the classifier actually assigned. Not a test -- a sanity check.

    python src\inspect_shapes.py questions_v13.json [shape_name]
"""
import json, sys, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
qs = json.load(open(sys.argv[1], encoding="utf-8"))
qs = qs["questions"] if isinstance(qs, dict) else qs
cls = json.load(open(ROOT / "data" / "classified.json"))
want = sys.argv[2] if len(sys.argv) > 2 else None

by = collections.defaultdict(list)
for q in qs:
    by[cls.get(q["qid"], "?")].append(q)

for shape in sorted(by, key=lambda s: -len(by[s])):
    if want and shape != want:
        continue
    print(f"\n===== {shape}  ({len(by[shape])})")
    for q in by[shape][: (12 if want else 3)]:
        print(f"  {q['qid']}  {' '.join(q['question'].split())[:150]}")