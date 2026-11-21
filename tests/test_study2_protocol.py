"""Penjaga Studi 2: operasionalisasi H1-H3 di `config/protocol.json` harus dapat dieksekusi persis oleh kode pelaporan, tanpa tafsir kedua.
Dilewati bila protokol tidak memuatnya (cabang main = Studi 1). Data sintetis; angka di sini bukan hasil penelitian."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
pytest.importorskip("numpy")
import test_pipeline as TP  # noqa: E402  (baris skor sintetis tiga lari: multi_run_test_rows, CFGS)
from ta_rag import agent  # noqa: E402
from ta_rag import pipeline as P  # noqa: E402

OUTCOMES = {"ACCEPT", "REVIEW", "REJECT"}
SHEET_GUARDS = {"S19_label": ["label_sheets_complete"], "S22_mutants": ["mutants_sheet_complete"], "S26_relabel": ["relabel_sheet_complete"]}


@pytest.fixture
def protocol():
    p = json.loads((REPO / "config" / "protocol.json").read_text(encoding="utf-8"))
    if "operationalization" not in p.get("significance_claims", {}):
        pytest.skip("protokol tanpa operasionalisasi H1-H3 (Studi 1 / main)")
    return p


def check_operationalization(p: dict) -> list[str]:
    op, probs = p["significance_claims"]["operationalization"], []
    grid = set(p["selection"]["grid_configs"])
    available = {"A", "B", "C", "D", "D*"} | ({"E"} & grid) | ({"F"} & grid)  # select_all selalu memilih A-D dan D*; E dan F hanya bila grid memuatnya
    families = {f for fs in p["track_m"]["mutation"]["families_by_question_type"].values() for f in fs}
    for h in ("H1", "H2", "H3"):
        s = op.get(h)
        if s is None:
            probs.append(f"{h}: tidak ada")
            continue
        probs += [f"{h}: konfigurasi {s[k]!r} tidak dihasilkan seleksi" for k in ("higher", "lower") if s[k] not in available]
        if s["outcome"] not in OUTCOMES:
            probs.append(f"{h}: outcome {s['outcome']!r} bukan rute")
        if s["families"] is not None and (not s["families"] or not set(s["families"]) <= families):
            probs.append(f"{h}: family {s['families']!r} tidak ada di rencana mutasi")
    level = 1 - op["alpha_family"] / op["n_hypotheses"]
    rule = p["significance_claims"]["decision_rule"]
    if op["n_hypotheses"] != 3 or round(100 * level, 1) != 98.3 or "98,3%" not in rule:
        probs.append("level CI != 98,3% (Bonferroni, tiga hipotesis) seperti decision_rule")
    if round(100 * op["min_diff"]) != 10 or "10 poin" not in rule:
        probs.append("min_diff != 10 poin persentase seperti decision_rule")
    return probs


def test_operationalization_is_consistent_with_selection_mutation_plan_and_decision_rule(protocol):
    assert check_operationalization(protocol) == []


def test_check_operationalization_detects_each_kind_of_drift(protocol):
    def broken(edit):
        q = copy.deepcopy(protocol)
        edit(q)
        return check_operationalization(q)

    ops = lambda q: q["significance_claims"]["operationalization"]
    assert broken(lambda q: ops(q)["H2"].update(higher="G"))
    assert broken(lambda q: ops(q)["H3"].update(outcome="TERIMA"))
    assert broken(lambda q: ops(q)["H2"].update(families=["units"]))
    assert broken(lambda q: ops(q)["H1"].update(families=[]))
    assert broken(lambda q: ops(q).update(min_diff=0.2))
    assert broken(lambda q: ops(q).update(n_hypotheses=2))
    assert broken(lambda q: q["selection"].update(grid_configs=["C", "D"]))  # E dan F tidak dihasilkan seleksi
    assert broken(lambda q: ops(q).pop("H3"))


def test_report_code_executes_the_real_protocol_operationalization(protocol):
    cl = P.clustered_analysis(TP.multi_run_test_rows(), TP.CFGS, protocol)
    h = cl["hypotheses"]
    assert list(h) == ["H1", "H2", "H3"] and [h[k]["verdict"] for k in h] == ["TERDUKUNG"] * 3
    assert h["H1"]["level"] == pytest.approx(0.98333, abs=1e-4) and h["H1"]["min_diff"] == 0.1


def test_real_workflow_human_sheet_steps_carry_exactly_their_importer_guards(protocol):  # `protocol`: hanya agar dilewati pada Studi 1 / main
    wf = agent.load_workflow(REPO / "config" / "workflow.json")  # load_workflow memanggil validate_workflow: tiap nama penjaga harus ada di REGISTRY
    assert {s["id"]: s.get("guards_post") for s in wf["stages"] if s["id"] in SHEET_GUARDS} == SHEET_GUARDS
