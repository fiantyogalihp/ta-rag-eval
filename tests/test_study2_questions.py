"""Penjaga himpunan pertanyaan Studi 2: kuota protokol, halaman unik, dan jenis yang dikenal rencana mutasi (S21)."""
import copy
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CASES, PROTOCOL = ROOT / "data/cases/questions_draft.jsonl", ROOT / "config/protocol.json"
GROUPS = {"numeric_duration": {"numeric_duration"}, "tanggal": {"numeric_date", "numeric_day"},
          "uang": {"numeric_money", "numeric_count", "numeric_range", "numeric_percent"}, "definition": {"definition"}}


def check_set(rows, protocol):
    t, issues = protocol["track_r"], []
    ans = [r for r in rows if r["kind"] == "answerable"]
    if (len(rows), len(ans)) != (t["n_questions"], t["n_answerable"]):
        issues.append(f"jumlah {len(rows)}/{len(ans)} != {t['n_questions']}/{t['n_answerable']}")
    for name, want in t["answerable_quota"].items():
        got = sum(r["question_type"] in GROUPS[next(g for g in GROUPS if name.startswith(g))] for r in ans)
        if got != want:
            issues.append(f"kuota '{name[:20]}': {got} != {want}")
    per_doc = Counter(r["source_doc_id"] for r in ans)
    lo, hi = t["per_evidence_document"]["min"], t["per_evidence_document"]["max"]
    issues += [f"{d}: {n} pertanyaan di luar {lo}-{hi}" for d, n in per_doc.items() if not lo <= n <= hi]
    issues += [f"evidence_group ganda: {g}" for g, n in Counter(r["evidence_group"] for r in rows).items() if n > 1]
    fam = protocol["track_m"]["mutation"]["families_by_question_type"]
    issues += [f"{r['case_id']}: jenis '{r['question_type']}' tidak ada di families_by_question_type" for r in ans if r["question_type"] not in fam]
    if [r["case_id"] for r in rows] != [f"T{i:02d}" for i in range(1, len(rows) + 1)]:
        issues.append("case_id bukan T01..T72 berurutan")
    return issues


@pytest.fixture(scope="module")
def study2():
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if "answerable_quota" not in protocol.get("track_r", {}) or not CASES.is_file():
        pytest.skip("protokol/pertanyaan Studi 2 tidak ada pada pohon kerja ini")
    return [json.loads(x) for x in CASES.read_text(encoding="utf-8").splitlines() if x.strip()], protocol


def test_study2_questions_follow_protocol(study2):
    assert check_set(*study2) == []


def test_check_set_detects_drift(study2):
    rows, protocol = study2
    bad = copy.deepcopy(rows)
    bad[0]["question_type"] = "numeric_duration"  # kuota definisi dan durasi bergeser
    bad[1]["evidence_group"] = bad[2]["evidence_group"]  # halaman ganda
    bad[3]["question_type"] = "numeric_tak_dikenal"  # tak ada di rencana mutasi
    issues = check_set(bad, protocol)
    assert any("kuota" in i for i in issues) and any("ganda" in i for i in issues) and any("tak_dikenal" in i for i in issues)
