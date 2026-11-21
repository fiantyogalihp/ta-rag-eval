"""Uji pembungkus BERTScore dan ringkasan pilot. Skor di-stub (tanpa unduh model); angka di sini bukan hasil penelitian."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
np = pytest.importorskip("numpy")
from ta_rag import bertscore as B  # noqa: E402


class StubScorer:
    hash = "stub_L9_no-idf"

    def score(self, cands, refs):
        f1 = np.array([0.8 if "16.000" in c else 0.9 for c in cands])  # mutasi (16.000) lebih rendah
        return np.array([float(len(c)) for c in cands]), np.array([float(len(r)) for r in refs]), f1


def test_score_pairs_passes_answer_as_candidate_and_evidence_as_reference():
    out = B.score_pairs([("aaa", "b")], scorer=StubScorer())
    assert out["P"] == [3.0] and out["R"] == [1.0] and out["F1"] == [0.9] and out["hash"] == "stub_L9_no-idf"


def test_auc_counts_ties_as_half_and_orders_pos_over_neg():
    assert B.auc([1, 1], [0, 0]) == 1.0 and B.auc([0], [1]) == 0.0 and B.auc([0.5], [0.5]) == 0.5
    assert B.auc([2, 0], [1]) == 0.5


def row(aid, track, label, answer, L, S, frm=None):
    return {"answer_id": aid, "track": track, "label": label, "answer": answer, "evidence": "sebesar Rp8.000,00", "L": L, "S": S,
            "mutated_from_answer_id": frm, "mutation_family": "numeric_value" if frm else None, "unsupported_numbers": ["16000"] if frm else []}


def test_pilot_analysis_pairs_each_mutation_with_its_original_and_reports_paired_deltas():
    rows = [row("A1", "R", "LAYAK", "Rp8.000,00", 0.8, 0.9), row("A2", "R", "LAYAK", "Rp8.000,00 per bulan", 0.7, 0.9),
            row("M1", "M", "TIDAK_LAYAK", "Rp16.000,00", 0.7, 0.95, "A1")]
    res = B.pilot_analysis(rows, scorer=StubScorer())
    f1 = res["summary"]["BERT_F1"]
    assert f1["n_pairs"] == 1 and f1["n_lower"] == 1 and f1["median_delta"] == pytest.approx(-0.1)
    assert res["summary"]["S"]["n_lower"] == 0  # S mutasi (0,95) lebih tinggi daripada aslinya (0,9)
    assert f1["auc_layak_vs_mutasi"] == 1.0  # kedua jawaban LAYAK (0,9) > mutasi (0,8)
    assert res["pairs"][0]["case_pair"] == ["A1", "M1"] and res["hash"] == "stub_L9_no-idf"


def test_pilot_analysis_rejects_mutation_whose_original_is_missing():
    with pytest.raises(ValueError, match="asal"):
        B.pilot_analysis([row("M1", "M", "TIDAK_LAYAK", "x", 0.1, 0.1, "A9")], scorer=StubScorer())
