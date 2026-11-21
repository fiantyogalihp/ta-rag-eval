"""Uji perekat alur dengan data sintetis (bukan hasil penelitian)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ta_rag import corpus, pipeline as P  # noqa: E402
from ta_rag.protocol import load_protocol  # noqa: E402

pytest.importorskip("numpy")
FIXTURE = REPO / "tests" / "fixtures" / "reducto_perpres_59_2024_r1_ui_export.json"
PROTO = load_protocol(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "studi1" / "protocol.json")


def test_build_chunks_from_raw_dir_and_scope_guard(tmp_path):
    cfg = corpus.load_config()
    only = {"documents": [d for d in cfg["documents"] if d["doc_id"].startswith("perpres_59_2024")]}
    shutil.copy(FIXTURE, tmp_path / "perpres_59_2024_perubahan_ketiga_jaminan_kesehatan__reducto-r-1.json")
    ch = P.build_chunks(tmp_path, only)
    assert len(ch) >= 20
    bad = json.loads(FIXTURE.read_text()); bad["result"]["chunks"][0]["blocks"][10]["bbox"]["original_page"] = 999
    (tmp_path / "perpres_59_2024_perubahan_ketiga_jaminan_kesehatan__reducto-r-1.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="di luar cakupan"):
        P.build_chunks(tmp_path, only)


def test_build_chunks_missing_raw_is_loud_and_deferred_docs_not_required(tmp_path):
    cfg = corpus.load_config()
    with pytest.raises(FileNotFoundError):
        P.build_chunks(tmp_path, cfg)
    assert any(d["eval_role"] == "deferred" for d in cfg["documents"])


def test_retrieval_ok_hits_anchor_page_only():
    case = {"kind": "answerable", "source_doc_id": "d", "source_page": 8}
    assert P.retrieval_ok(case, [{"doc_id": "d", "page_start": 7, "page_end": 9}]) is True
    assert P.retrieval_ok(case, [{"doc_id": "d", "page_start": 9, "page_end": 9}]) is False
    assert P.retrieval_ok(case, [{"doc_id": "x", "page_start": 8, "page_end": 8}]) is False
    assert P.retrieval_ok({"kind": "not_in_corpus"}, []) is None


def lab(i, label="LAYAK", answer="Rp8.000,00 per peserta", locked=True, **kw):
    r = {"answer_id": f"A{i}", "case_id": f"R{i}", "group_id": f"g{i}", "evidence_group": f"e{i}", "track": "R", "answer_origin": "original_llm",
         "answer": answer, "kind": "answerable", "label": label, "manual_label_locked": locked, "chunk_ids": ["c1"]}
    r.update(kw)
    return r


CASES = {f"R{i}": {"case_id": f"R{i}", "kind": "answerable", "source_doc_id": "d", "source_page": 8, "source_quote": "ditetapkan sebesar Rp8.000,00 (delapan ribu rupiah) per peserta per bulan"} for i in range(1, 60)}
CHUNKS = {"c1": {"chunk_id": "c1", "doc_id": "d", "page_start": 8, "page_end": 8, "text": "tarif Rp8.000,00 per peserta"},
          "c2": {"chunk_id": "c2", "doc_id": "d", "page_start": 40, "page_end": 40, "text": "pasal lain yang tidak relevan"}}


def test_score_rows_refuses_unlocked_labels_and_skips_insufficient_and_probes_in_stage_i():
    with pytest.raises(ValueError, match="belum dikunci"):
        P.score_rows("I", [lab(1, locked=False)], CASES, CHUNKS, None)
    rows = [lab(1), lab(2, label="INSUFFICIENT_EVIDENCE"), lab(3, kind="not_in_corpus")]
    cases = {**CASES, "R3": {"case_id": "R3", "kind": "not_in_corpus"}}
    out = P.score_rows("I", rows, cases, CHUNKS, None)
    assert [r["answer_id"] for r in out] == ["A1"]
    out2 = P.score_rows("II", rows, cases, CHUNKS, None)
    assert [r["answer_id"] for r in out2] == ["A1", "A3"]  # tahap II memakai chunk terambil, termasuk probe


def test_score_rows_rejects_route_before_label_lock_schema():
    with pytest.raises(ValueError, match="labels tidak valid"):
        P.score_rows("I", [lab(1, locked=False, route="ACCEPT")], CASES, CHUNKS, None)


def synthetic_scored(n_pairs=20):
    labs = []
    for i in range(1, n_pairs + 1):
        labs.append(lab(i))
        labs.append({**lab(100 + i, label="TIDAK_LAYAK", answer="Rp16.000,00 per peserta", track="M", answer_origin="mutasi_terkontrol",
                          pair_id=f"P{i}", mutation_family="numeric_value", anchor_page_opposite=8, mutated_from_answer_id=f"A{i}"),
                     "group_id": f"g{i}", "evidence_group": f"e{i}", "case_id": f"R{i}"})
    cases = {f"R{i}": CASES["R1"] | {"case_id": f"R{i}"} for i in range(1, n_pairs + 1)}
    import numpy as np

    return P.score_rows("I", labs, cases, CHUNKS, lambda texts: np.ones((len(texts), 3)))  # S=1 untuk semua pasangan


def test_sweep_selects_from_validation_only_and_test_runs_once(tmp_path):
    scored = synthetic_scored()
    sel = P.run_sweep(scored, tmp_path / "I", PROTO)
    assert list(sel["configs"]) == ["A", "B", "C", "D", "D*"]
    assert sel["configs"]["D*"]["selection"]["status"] == "SELECTED" and sel["configs"]["D*"]["params"]["hard_fail"] is True
    assert (tmp_path / "I" / "stage_C.csv").read_text().count("\n") == 61
    out = tmp_path / "I" / "test_result.json"
    res = P.run_test(scored, sel, PROTO, out)
    assert res["status"] == "TEST_RUN_ONCE" and res["n_test"] > 0 and "validator tunggal" in res["claim_prefix_required"]
    d = res["configs"]["D*"]
    assert d["status"] == "TEST_RUN_ONCE_FROZEN_PARAMS"
    assert res["n_test_by_track"]["R"] + res["n_test_by_track"]["M"] == res["n_test"]
    assert d["R"]["FAR"]["defined"] is False and d["M"]["FAR"]["n"] == res["n_test_by_track"]["M"]  # R dan M tidak digabung
    per_case = (tmp_path / "I" / "per_case.csv").read_text().splitlines()
    assert len(per_case) == len(scored) + 1 and "route_D" in per_case[0] and "split" in per_case[0]
    with pytest.raises(FileExistsError, match="SEKALI"):
        P.run_test(scored, sel, PROTO, out)
    assert P.run_test(scored, sel, PROTO, out, acknowledge_rerun=True)["rerun"] is True


def test_test_refuses_when_data_changed_after_selection(tmp_path):
    scored = synthetic_scored()
    sel = P.run_sweep(scored, tmp_path / "I", PROTO)
    with pytest.raises(ValueError, match="split berbeda"):
        P.run_test(scored[:-2], sel, PROTO, tmp_path / "t.json")


def test_no_eligible_parameter_is_reported_as_finding_and_test_is_labelled_reference_only(tmp_path):
    # mutasi tak dapat dibedakan dari jawaban benar (skor sama tinggi, tanpa penanda hard-fail)
    scored = [{**s, "L": 0.95, "S": 0.95, "unsupported_numbers": []} for s in synthetic_scored()]
    sel = P.run_sweep(scored, tmp_path / "I", PROTO)
    assert {c["selection"]["status"] for c in sel["configs"].values()} == {"NO_ELIGIBLE_PARAMETER"}
    res = P.run_test(scored, sel, PROTO, tmp_path / "t.json")
    assert res["configs"]["C"]["status"] == "TEST_RUN_ONCE_R2_REFERENCE_NO_ELIGIBLE_PARAMETER"


def test_never_accepting_parameter_is_flagged_degenerate_not_celebrated(tmp_path):
    # semua skor rendah: tak ada yang di-ACCEPT, FAR=0 sepele dan CAR=0
    scored = [{**s, "L": 0.2, "S": 0.2, "unsupported_numbers": []} for s in synthetic_scored()]
    sel = P.run_sweep(scored, tmp_path / "I", PROTO)
    assert sel["configs"]["C"]["selection"]["status"] == "SELECTED" and "CAR_ZERO_DEGENERATE" in sel["configs"]["C"]["selection"]["warning"]
    assert "CAR_ZERO_DEGENERATE" in sel["configs"]["D"]["selection"]["warning"]
    assert P.run_test(scored, sel, PROTO, tmp_path / "t.json")["configs"]["C"]["selection_warning"].startswith("CAR_ZERO_DEGENERATE")


def test_far_undefined_selection_has_no_params_and_test_refuses(tmp_path):
    scored = [s for s in synthetic_scored() if s["label"] == "LAYAK"]  # tanpa Track M: seleksi (FAR_M) tak terdefinisi
    sel = P.run_sweep(scored, tmp_path / "I", PROTO)
    assert all(c["selection"]["status"] == "FAR_UNDEFINED_NO_SELECTION" and c["params"] is None for c in sel["configs"].values())
    with pytest.raises(ValueError, match="tidak ada parameter"):
        P.run_test(scored, sel, PROTO, tmp_path / "t.json")


def test_measure_latency_warms_up_counts_iterations_and_reports_hardware():
    import numpy as np

    ticks = iter(range(0, 10_000_000, 3))  # pewaktu palsu: tiap panggilan maju 3 satuan -> 3000 ms per iterasi
    calls = []

    def embed(texts):
        calls.append(1)
        return np.ones((len(texts), 3))

    r = P.measure_latency([("6 bulan", "paling singkat 6 bulan")], embed, 0.5, 0.78, True, iters=120, warmup=7, timer=lambda: next(ticks))
    assert r["n"] == 120 and r["warning"] is None and r["p50"] == pytest.approx(3000.0) and len(calls) == 127
    assert r["hardware"]["cpu_count"] and r["scope"].startswith("evaluator saja")
    short = P.measure_latency([("a", "b")], None, 0.0, 0.78, False, iters=20, warmup=1)
    assert short["warning"] == "kurang dari 100 iterasi"
    with pytest.raises(ValueError):
        P.measure_latency([], None, 0.0, 0.78, False)


def test_score_rows_passes_question_so_question_numbers_are_not_hard_fail():
    cases = {"R1": {"case_id": "R1", "kind": "answerable", "question": "Berapa tarif pada tahun 2023?", "source_quote": "dibayar Rp8.000,00 per peserta"}}
    row = lab(1, answer="Pada tahun 2023 dibayar Rp8.000,00 per peserta.")
    assert P.score_rows("I", [{**row, "case_id": "R1"}], cases, CHUNKS, None)[0]["unsupported_numbers"] == []


# ------------------------------------------------------------------ D14: tahap II deskriptif

def test_stage_ii_label_flips_to_layak_only_for_abstention_with_retrieval_miss_and_keeps_stage_i_label():
    rows = [lab(1, label="TIDAK_LAYAK", abstain=True, chunk_ids=["c2"]),   # abstain, retrieval meleset -> LAYAK di tahap II
            lab(2, label="TIDAK_LAYAK", abstain=True, chunk_ids=["c1"]),   # abstain, bukti ada di konteks -> tetap TIDAK_LAYAK
            lab(3, label="TIDAK_LAYAK", abstain=False, chunk_ids=["c2"]),  # salah, bukan abstain -> tetap TIDAK_LAYAK
            lab(4, label="LAYAK", abstain=False, chunk_ids=["c1"])]
    out = {r["answer_id"]: r for r in P.score_rows("II", rows, CASES, CHUNKS, None)}
    assert [out[f"A{i}"]["label"] for i in (1, 2, 3, 4)] == ["LAYAK", "TIDAK_LAYAK", "TIDAK_LAYAK", "LAYAK"]
    assert [out[f"A{i}"]["retrieval_ok"] for i in (1, 2, 3, 4)] == [False, True, False, True]
    assert out["A1"]["label_stage_I"] == "TIDAK_LAYAK"
    s1 = P.score_rows("I", [lab(1, label="TIDAK_LAYAK", abstain=True, chunk_ids=["c2"])], CASES, CHUNKS, None)[0]
    assert s1["label"] == "TIDAK_LAYAK"  # tahap I tidak pernah dibalik


def stage2_inputs(tmp_path):
    sel = P.run_sweep(synthetic_scored(), tmp_path / "I", PROTO)
    good = {"L": 0.9, "S": 0.9, "unsupported_numbers": [], "neg_mismatch": False, "track": "R", "group_id": "g", "evidence_group": "e", "case_id": "R1"}
    scored = [{**good, "answer_id": "A1", "kind": "answerable", "label": "LAYAK", "retrieval_ok": True, "label_stage_I": "LAYAK"},
              {**good, "answer_id": "A2", "kind": "not_in_corpus", "label": "TIDAK_LAYAK", "retrieval_ok": None, "label_stage_I": "TIDAK_LAYAK",
               "unsupported_numbers": ["999"]},
              {**good, "answer_id": "A3", "kind": "not_in_corpus", "label": "TIDAK_LAYAK", "retrieval_ok": None, "label_stage_I": "TIDAK_LAYAK"}]
    return sel, scored


def test_stage2_applies_frozen_stage_i_params_without_any_sweep_and_splits_answerable_from_probe(tmp_path):
    sel, scored = stage2_inputs(tmp_path)
    res = P.run_stage2(scored, sel, PROTO, tmp_path / "II")
    d = res["configs"]["D"]
    assert d["params"] == sel["configs"]["D"]["params"]
    assert d["all"]["n"] == 3 and d["answerable"]["n"] == 1 and d["probe"]["n"] == 2
    assert d["probe"]["FAR"]["n"] == 2 and d["probe"]["FAR"]["k"] == 1  # A2 ditahan hard-fail (999), A3 lolos
    assert res["n_by_kind"] == {"answerable": 1, "not_in_corpus": 2} and res["retrieval_ok"] == {"true": 1, "false": 0, "n/a": 2}
    assert "validator tunggal" in res["claim_prefix_required"] and res["status"] == "DESCRIPTIVE_NO_SELECTION_NO_TEST"
    assert not list((tmp_path / "II").glob("stage_*.csv")) and (tmp_path / "II" / "per_case_II.csv").exists()
    assert "retrieval_ok" in (tmp_path / "II" / "per_case_II.csv").read_text().splitlines()[0]


def test_stage2_skips_configs_without_frozen_params(tmp_path):
    sel, scored = stage2_inputs(tmp_path)
    sel["configs"]["B"]["params"] = None
    res = P.run_stage2(scored, sel, PROTO, tmp_path / "II")
    assert res["configs"]["B"] == {"params": None, "status": "NOT_APPLIED_NO_FROZEN_PARAMS"} and res["configs"]["A"]["all"]["n"] == 3


# ------------------------------------------------------------------ stabilitas antar-run (eksploratif pasca-test)

def test_route_stability_counts_cases_with_identical_route_in_every_run_and_skips_probes():
    import numpy as np

    quote = CASES["R1"]["source_quote"]
    cases = {"R1": {**CASES["R1"], "question": "Berapa?"}, "R2": {**CASES["R2"], "question": "Berapa?"}, "R17": {"case_id": "R17", "kind": "not_in_corpus"}}
    runs = {"run1": [{"case_id": "R1", "answer": quote}, {"case_id": "R2", "answer": quote}, {"case_id": "R17", "answer": "tidak ada"}],
            "run2": [{"case_id": "R1", "answer": quote}, {"case_id": "R2", "answer": "Rp9.000,00 per peserta"}, {"case_id": "R17", "answer": "x"}]}
    cfg = {"D": {"params": {"w_s": 0.0, "accept": 0.75, "hard_fail": True}}, "X": {"params": None}}
    res = P.route_stability(runs, cases, cfg, lambda t: np.ones((len(t), 3)))
    assert res["n_cases"] == 2 and res["same_route_all_runs"] == {"D": 1} and res["runs"] == ["run1", "run2"]
    assert res["per_case"]["R2"] == {"run1": {"D": "ACCEPT"}, "run2": {"D": "REJECT"}}  # angka 9.000 tak ada di evidence


def test_route_stability_rejects_case_missing_from_a_run():
    import numpy as np

    runs = {"run1": [{"case_id": "R1", "answer": "a"}], "run2": []}
    with pytest.raises(ValueError, match="tidak ada di semua run"):
        P.route_stability(runs, {"R1": CASES["R1"]}, {"A": {"params": {"w_s": 0.0, "accept": 0.75, "hard_fail": False}}}, lambda t: np.ones((len(t), 3)))


def test_sweep_stability_reproduces_locked_selection_and_uses_validation_only(tmp_path):
    scored = synthetic_scored()
    sel = P.run_sweep(scored, tmp_path / "I", PROTO)
    res = P.sweep_stability(scored, PROTO, selection=sel, n_boot=20)
    assert res["locked_selection_reproduced"] == {k: True for k in ("A", "B", "C", "D", "D*")}
    assert res["stability"]["n_boot"] == 20 and res["stability"]["n_units"] < len({s["group_id"] for s in scored})  # hanya komponen validation
    assert list(res["alpha_sensitivity"]) == ["0.05", "0.1", "0.2"]
    sel["configs"]["A"]["selection"]["chosen"] = "C:w0.0:t0.99"  # seleksi terkunci yang berbeda harus terdeteksi
    assert P.sweep_stability(scored, PROTO, selection=sel, n_boot=5)["locked_selection_reproduced"]["A"] is False


def test_run_sweep_and_test_support_config_e_via_protocol_grid_configs(tmp_path):
    import numpy as np

    labs, cases = [], {}
    for i in range(1, 21):
        labs.append(lab(i, answer="setelah jangka waktu 3 (tiga) bulan"))
        labs.append({**lab(100 + i, label="TIDAK_LAYAK", answer="setelah jangka waktu 3 (tiga) hari", track="M", answer_origin="mutasi_terkontrol",
                          pair_id=f"P{i}", mutation_family="unit", anchor_page_opposite=8, mutated_from_answer_id=f"A{i}"),
                     "group_id": f"g{i}", "evidence_group": f"e{i}", "case_id": f"R{i}"})
        cases[f"R{i}"] = CASES["R1"] | {"case_id": f"R{i}", "source_quote": "Peserta dapat mengganti FKTP setelah jangka waktu 3 (tiga) bulan atau 5 (lima) hari"}  # kedua kata satuan ada: skor leksikal asli = mutasi
    scored = P.score_rows("I", labs, cases, CHUNKS, lambda texts: np.ones((len(texts), 3)))
    # skor asli = mutasi, jadi α = 1,0 agar seleksi memilih parameter yang menerima semuanya (CAR tertinggi) dan hanya aturan satuan yang membedakan
    proto = PROTO | {"selection": PROTO["selection"] | {"grid_configs": ["C", "D", "E"], "alpha": 1.0}}
    sel = P.run_sweep(scored, tmp_path / "I", proto)
    assert list(sel["configs"]) == ["A", "B", "C", "D", "E", "D*"] and (tmp_path / "I" / "stage_C.csv").read_text().count("\n") == 91
    res = P.run_test(scored, sel, proto, tmp_path / "I" / "test_result.json")
    assert res["configs"]["D"]["M"]["FAR"]["k"] == res["configs"]["D"]["M"]["FAR"]["n"] > 0  # D menerima semua mutasi satuan
    assert res["configs"]["E"]["M"]["FAR"]["k"] == 0 and res["configs"]["E"]["M"]["FAR"]["n"] > 0  # E menolaknya


def test_stage_ii_best_unit_mode_scores_lexical_on_best_sentence_but_checks_numbers_on_full_context():
    import numpy as np

    chunks = {"c1": {"chunk_id": "c1", "doc_id": "d", "page_start": 8, "page_end": 8,
                     "text": "Pasal 1 hal lain\n" + " ".join(f"kata{i}" for i in range(200)) + "\nTarif ditetapkan sebesar Rp8.000,00 per peserta per bulan.\nPasal 9 Rp16.000,00 untuk hal lain."}}
    labs = [lab(1, answer="Tarif ditetapkan sebesar Rp8.000,00 per peserta per bulan", chunk_ids=["c1"])]
    embed = lambda texts: np.ones((len(texts), 3))
    concat = P.score_rows("II", labs, CASES, chunks, embed)[0]
    best = P.score_rows("II", labs, CASES, chunks, embed, stage_ii_evidence="best_unit")[0]
    assert concat["L"] < 0.2 and best["L"] == pytest.approx(1.0)  # konteks panjang menekan F1; satuan terbaik tidak
    assert best["unsupported_numbers"] == [] and best["evidence_mode"] == "best_unit" and concat["evidence_mode"] == "concat"
    with pytest.raises(ValueError, match="stage_ii_evidence"):
        P.score_rows("II", labs, CASES, chunks, embed, stage_ii_evidence="lainnya")


# ------------------------------------------------------------------ konfigurasi F (BERTScore) di pipeline

class StubBert:
    """F1 = 0,9 bila kandidat memuat 8.000 (nilai benar), selain itu 0,5; mencatat rujukan yang diterima."""
    hash = "stub_L9_no-idf"

    def __init__(self):
        self.refs = []

    def score(self, cands, refs):
        import numpy as np

        self.refs += list(refs)
        f = np.array([0.9 if "8.000" in c else 0.5 for c in cands])
        return f, f, f


def synthetic_labs(n_pairs=20):
    labs, cases = [], {}
    for i in range(1, n_pairs + 1):
        labs.append(lab(i))
        labs.append({**lab(100 + i, label="TIDAK_LAYAK", answer="Rp16.000,00 per peserta", track="M", answer_origin="mutasi_terkontrol",
                          pair_id=f"P{i}", mutation_family="numeric_value", anchor_page_opposite=8, mutated_from_answer_id=f"A{i}"),
                     "group_id": f"g{i}", "evidence_group": f"e{i}", "case_id": f"R{i}"})
        cases[f"R{i}"] = CASES["R1"] | {"case_id": f"R{i}"}
    return labs, cases


def test_score_rows_attaches_bert_f1_from_answer_and_evidence_pairs_only_when_scorer_given():
    import numpy as np

    labs, cases = synthetic_labs(3)
    embed = lambda texts: np.ones((len(texts), 3))
    assert all("bert_f1" not in r for r in P.score_rows("I", labs, cases, CHUNKS, embed))
    stub = StubBert()
    rows = P.score_rows("I", labs, cases, CHUNKS, embed, bert_scorer=stub)
    assert {r["answer_id"]: r["bert_f1"] for r in rows if r["track"] == "R"} == {"A1": 0.9, "A2": 0.9, "A3": 0.9}
    assert all(r["bert_f1"] == 0.5 for r in rows if r["track"] == "M")
    assert set(stub.refs) == {CASES["R1"]["source_quote"]}  # rujukan = evidence oracle Tahap I


def test_run_sweep_and_test_with_config_f_write_36_f_rows_and_route_by_bert(tmp_path):
    import numpy as np

    labs, cases = synthetic_labs()
    scored = P.score_rows("I", labs, cases, CHUNKS, lambda texts: np.ones((len(texts), 3)), bert_scorer=StubBert())
    proto = PROTO | {"selection": PROTO["selection"] | {"grid_configs": ["C", "D", "F"]}}
    sel = P.run_sweep(scored, tmp_path / "I", proto)
    assert list(sel["configs"]) == ["A", "B", "C", "D", "F", "D*"] and (tmp_path / "I" / "stage_C.csv").read_text().count("\n") == 1 + 60 + 36
    f = sel["configs"]["F"]
    assert f["selection"]["status"] == "SELECTED" and 0.5 < f["params"]["accept"] <= 0.9  # memisahkan 0,9 dari 0,5
    res = P.run_test(scored, sel, proto, tmp_path / "I" / "test_result.json")
    assert res["configs"]["F"]["M"]["FAR"]["k"] == 0 and res["configs"]["F"]["R"]["CAR"]["k"] == res["configs"]["F"]["R"]["CAR"]["n"] > 0
    import csv

    rows = list(csv.DictReader(open(tmp_path / "I" / "per_case.csv", encoding="utf-8")))
    assert "bert_f1" in rows[0] and {"route_F", "H_F"} <= set(rows[0]) and {r["route_F"] for r in rows if r["track"] == "M"} == {"REJECT"}


def test_measure_latency_bert_times_one_pair_per_call_and_reports_hardware():
    stub, ticks = StubBert(), iter(i * 0.004 for i in range(10_000))
    res = P.measure_latency_bert([("a 8.000", "e")], stub, iters=5, warmup=2, timer=lambda: next(ticks))
    assert res["n"] == 5 and res["unit"] == "ms" and res["p50"] == pytest.approx(4.0) and "hardware" in res and res["config"] == "F"


def test_sweep_stability_follows_protocol_grid_configs_including_f(tmp_path):
    import numpy as np

    labs, cases = synthetic_labs()
    scored = P.score_rows("I", labs, cases, CHUNKS, lambda texts: np.ones((len(texts), 3)), bert_scorer=StubBert())
    proto = PROTO | {"selection": PROTO["selection"] | {"grid_configs": ["C", "D", "F"]}}
    sel = P.run_sweep(scored, tmp_path / "I", proto)
    res = P.sweep_stability(scored, proto, selection=sel, n_boot=10)
    assert res["locked_selection_reproduced"] == {k: True for k in ("A", "B", "C", "D", "F", "D*")}
    assert "F" in res["stability"]["configs"] and "F" in res["alpha_sensitivity"]["0.05"]


# ------------------------------------------------------------------ analisis klaster Studi 2: tiga lari dan hipotesis H1-H3

OPS = {"alpha_family": 0.05, "n_hypotheses": 3, "min_diff": 0.10,
       "H1": {"higher": "B", "lower": "D", "outcome": "ACCEPT", "families": None},
       "H2": {"higher": "E", "lower": "D", "outcome": "REJECT", "families": ["unit"]},
       "H3": {"higher": "F", "lower": "D", "outcome": "ACCEPT", "families": ["numeric_value", "date"]}}
CFGS = {"B": {"params": {"config": "C", "w_s": 1.0, "accept": 0.78, "hard_fail": False}},
        "D": {"params": {"config": "C", "w_s": 0.6, "accept": 0.78, "hard_fail": True}},
        "E": {"params": {"config": "C", "w_s": 0.6, "accept": 0.78, "hard_fail": True, "unit_fail": True}},
        "F": {"params": {"config": "F", "w_s": 0.0, "accept": 0.78, "hard_fail": False}}}
PROTO2 = PROTO | {"significance_claims": {"operationalization": OPS}}


def srow(aid, grp, run, track, label, fam=None, good=True, **kw):
    """Baris skor sintetis tanpa embedding: good -> L=S=bert=0,9 (ACCEPT di semua konfigurasi); bukan good -> 0,6 (REVIEW; F: REJECT)."""
    v = 0.9 if good else 0.6
    return {"answer_id": aid, "group_id": grp, "run_id": run, "track": track, "label": label, "mutation_family": fam, "L": v, "S": v, "bert_f1": v,
            "unsupported_numbers": [], "neg_mismatch": False, "unit_mismatch": [], **kw}


def multi_run_test_rows(n_q=12):
    rows = []
    for i in range(n_q):
        for k in (1, 2, 3):
            rows.append(srow(f"run{k}:T{i}", f"g{i}", f"run{k}", "R", "LAYAK", good=not (k == 3 and i < 3)))  # lari 3: tiga jawaban LAYAK turun ke REVIEW
        value = i < n_q // 2  # separuh mutasi nilai (angka tak didukung), separuh mutasi satuan (angka sama, satuan beda)
        rows.append(srow(f"M1:T{i}", f"g{i}", "run1", "M", "TIDAK_LAYAK", "numeric_value" if value else "unit",
                         unsupported_numbers=["16000"] if value else [], unit_mismatch=[] if value else ["3 hari"]))
    return rows


def test_clustered_analysis_gives_pooled_per_run_spread_and_hypotheses_with_tracks_apart():
    cl = P.clustered_analysis(multi_run_test_rows(), CFGS, PROTO2)
    assert cl["runs"] == ["run1", "run2", "run3"] and set(cl["configs"]) == {"B", "D", "E", "F"}
    d = cl["configs"]["D"]
    assert (d["pooled"]["R"]["CAR"]["k"], d["pooled"]["R"]["CAR"]["n"], d["pooled"]["R"]["CAR"]["n_clusters"]) == (33, 36, 12)
    assert [d["per_run"][r]["CAR"]["k"] for r in ("run1", "run2", "run3")] == [12, 12, 9] and d["per_run"]["run3"]["CAR"]["n"] == 12
    assert d["spread"]["CAR"]["mean"] == pytest.approx((1 + 1 + 0.75) / 3) and (d["spread"]["CAR"]["min"], d["spread"]["CAR"]["max"]) == (0.75, 1.0)
    assert d["pooled"]["R"]["FAR"]["defined"] is False  # tanpa TIDAK_LAYAK alami: tak terdefinisi, bukan 0
    assert [(k, d["pooled"]["M"]["FAR"][k]) for k in ("k", "n")] == [("k", 6), ("n", 12)]  # mutasi hanya Track M, tidak masuk Track R
    assert [cl["configs"][c]["pooled"]["M"]["FAR"]["k"] for c in ("B", "D", "E", "F")] == [12, 6, 0, 12]
    h = cl["hypotheses"]
    assert [h[k]["verdict"] for k in ("H1", "H2", "H3")] == ["TERDUKUNG"] * 3
    assert h["H1"]["diff"] == pytest.approx(0.5) and h["H1"]["n"] == 12  # semua mutasi
    assert h["H2"]["n"] == 6 and h["H2"]["diff"] == 1.0  # hanya family unit
    assert h["H3"]["n"] == 6 and h["H3"]["diff"] == 1.0  # hanya numeric_value/date
    assert h["H1"]["level"] == pytest.approx(1 - 0.05 / 3) and h["H1"]["higher"] == "B" and h["H1"]["lower"] == "D"
    json.dumps(cl)  # harus dapat ditulis ke test_result.json


def test_clustered_analysis_hypothesis_uses_family_filter_and_reports_no_evidence_or_missing_params():
    other = {**OPS, "H3": {**OPS["H3"], "families": ["unit"]}}  # D sama-sama menerima mutasi satuan, F juga: tak ada selisih
    h = P.clustered_analysis(multi_run_test_rows(), CFGS, PROTO | {"significance_claims": {"operationalization": other}})["hypotheses"]
    assert h["H3"]["verdict"] == "TIDAK_ADA_BUKTI_PERBEDAAN" and h["H3"]["diff"] == 0.0 and h["H3"]["n"] == 6
    nofreeze = {k: v for k, v in CFGS.items() if k != "E"} | {"E": {"params": None}}
    cl = P.clustered_analysis(multi_run_test_rows(), nofreeze, PROTO2)
    assert cl["hypotheses"]["H2"]["verdict"] == "NOT_EVALUATED_NO_FROZEN_PARAMS" and "E" not in cl["configs"]
    assert "hypotheses" not in P.clustered_analysis(multi_run_test_rows(), CFGS, PROTO)  # protokol tanpa operasionalisasi: tidak ada uji
    strict = P.clustered_analysis(multi_run_test_rows(), CFGS, PROTO | {"significance_claims": {"operationalization": {**OPS, "min_diff": 0.9}}})["hypotheses"]
    assert [strict[k]["verdict"] for k in ("H1", "H2", "H3")] == ["TIDAK_ADA_BUKTI_PERBEDAAN", "TERDUKUNG", "TERDUKUNG"]  # ambang praktis dibaca dari protokol (H1: 0,5 < 0,9)


def test_clustered_analysis_is_absent_for_single_run_studies_without_run_id():
    rows = [{k: v for k, v in r.items() if k != "run_id"} for r in multi_run_test_rows()]
    assert P.clustered_analysis(rows, CFGS, PROTO2) is None


def multi_run_labs(n_q=20):
    labs, cases = [], {}
    for i in range(1, n_q + 1):
        for k in (1, 2, 3):
            labs.append({**lab(i), "answer_id": f"run{k}:R{i}", "run_id": f"run{k}"})
        labs.append({**lab(100 + i, label="TIDAK_LAYAK", answer="Rp16.000,00 per peserta", track="M", answer_origin="mutasi_terkontrol", pair_id=f"P{i}",
                          mutation_family="numeric_value", anchor_page_opposite=8, mutated_from_answer_id=f"run1:R{i}", run_id="run1"),
                     "group_id": f"g{i}", "evidence_group": f"e{i}", "case_id": f"R{i}"})
        cases[f"R{i}"] = CASES["R1"] | {"case_id": f"R{i}"}
    return labs, cases


def test_score_rows_carries_run_id_and_mutation_family_only_when_labels_have_them():
    import numpy as np

    labs, cases = multi_run_labs(2)
    out = {r["answer_id"]: r for r in P.score_rows("I", labs, cases, CHUNKS, lambda t: np.ones((len(t), 3)))}
    assert out["run2:R1"]["run_id"] == "run2" and "mutation_family" not in out["run2:R1"]
    assert out["A101"]["run_id"] == "run1" and out["A101"]["mutation_family"] == "numeric_value"
    plain = P.score_rows("I", [lab(1)], cases, CHUNKS, lambda t: np.ones((len(t), 3)))[0]
    assert "run_id" not in plain and "mutation_family" not in plain  # Studi 1: skema skor tidak berubah


def test_run_test_adds_clustered_section_from_the_same_test_rows(tmp_path):
    import numpy as np

    labs, cases = multi_run_labs()
    scored = P.score_rows("I", labs, cases, CHUNKS, lambda t: np.ones((len(t), 3)))
    sel = P.run_sweep(scored, tmp_path / "I", PROTO2)
    res = P.run_test(scored, sel, PROTO2, tmp_path / "I" / "test_result.json")
    cl = res["clustered"]
    assert cl["runs"] == ["run1", "run2", "run3"] and json.loads((tmp_path / "I" / "test_result.json").read_text())["clustered"]["runs"] == cl["runs"]
    for name in ("B", "D"):  # hitungan sama dengan ringkasan Clopper-Pearson dari baris test yang sama; hanya interval yang berbeda
        pooled, cp = cl["configs"][name]["pooled"]["R"], res["configs"][name]["R"]
        assert [pooled["CAR"][k] for k in ("k", "n")] == [cp["CAR"]["k"], cp["CAR"]["n"]] and "bootstrap" in pooled["CAR"]["interval"]
        assert sum(r["n"] for r in cl["configs"][name]["per_run"].values()) == cp["n"]
    assert cl["hypotheses"]["H2"]["verdict"] == "NOT_EVALUATED_NO_FROZEN_PARAMS"  # E tidak ada di grid bawaan


# ------------------------------------------------------------------ latency pra-seleksi (S33) dan Tahap II per lari (Studi 2)

def test_latency_default_measures_a_c_d_and_adds_e_and_f_only_when_the_grid_has_them():
    import numpy as np

    pairs, embed = [("tiga bulan 8.000", "paling singkat 3 (tiga) bulan")], (lambda texts: np.ones((len(texts), 3)))
    ticks = iter(range(0, 10_000_000, 2))
    tick = lambda: next(ticks)
    base = P.latency_default(pairs, embed, ("C", "D"), iters=100, timer=tick)
    assert list(base) == ["A", "C", "D", "p95_ms_by_config"] and set(base["p95_ms_by_config"]) == {"A", "C", "D"}  # Studi 1: keluaran tidak berubah
    full = P.latency_default(pairs, embed, ("C", "D", "E", "F"), bert_scorer=StubBert(), iters=100, timer=tick)
    assert list(full) == ["A", "C", "D", "E", "F", "p95_ms_by_config"] and full["F"]["config"] == "F" and full["E"]["hard_fail"] is True
    assert full["p95_ms_by_config"] == {c: full[c]["p95"] for c in "ACDEF"} and all(full[c]["n"] == 100 for c in "ACDEF")


def test_latency_default_gives_each_config_its_preregistered_rule_flags(monkeypatch):
    rec = lambda pairs, embed, w_s, accept, hard_fail, unit_fail=False, iters=100, warmup=10, timer=None: {"p95": 1.0, "args": (w_s, accept, hard_fail, unit_fail)}
    monkeypatch.setattr(P, "measure_latency", rec)
    monkeypatch.setattr(P, "measure_latency_bert", lambda pairs, scorer, iters=100, warmup=10, timer=None: {"p95": 2.0, "scorer": scorer})
    res = P.latency_default([("a", "b")], None, ("C", "D", "E", "F"), bert_scorer="stub")
    assert {c: res[c]["args"] for c in "ACDE"} == {"A": (0.0, 0.78, False, False), "C": (0.6, 0.78, False, False), "D": (0.6, 0.78, True, False), "E": (0.6, 0.78, True, True)}
    assert res["F"]["scorer"] == "stub" and res["p95_ms_by_config"] == {"A": 1.0, "C": 1.0, "D": 1.0, "E": 1.0, "F": 2.0}


def stage2_multi_run(tmp_path):
    """Tahap II sintetis tiga lari: 8 pertanyaan berjawab (LAYAK, skor tinggi) dan 2 probe; probe g8 di lari 3 mengarang angka (TIDAK_LAYAK, 999)."""
    sel = P.run_sweep(synthetic_scored(), tmp_path / "I", PROTO)
    base = {"L": 0.9, "S": 0.9, "unsupported_numbers": [], "neg_mismatch": False, "track": "R", "label_stage_I": "LAYAK", "retrieval_ok": None}
    scored = []
    for k in (1, 2, 3):
        for i in range(8):
            scored.append({**base, "answer_id": f"run{k}:T{i}", "case_id": f"T{i}", "group_id": f"g{i}", "evidence_group": f"e{i}", "run_id": f"run{k}", "kind": "answerable",
                           "label": "LAYAK", "retrieval_ok": True})
        for i in (8, 9):
            bad = k == 3 and i == 8
            scored.append({**base, "answer_id": f"run{k}:T{i}", "case_id": f"T{i}", "group_id": f"g{i}", "evidence_group": f"e{i}", "run_id": f"run{k}", "kind": "not_in_corpus",
                           "label": "TIDAK_LAYAK" if bad else "LAYAK", "unsupported_numbers": ["999"] if bad else []})
    return sel, scored, P.run_stage2(scored, sel, PROTO, tmp_path / "II")


def test_stage2_adds_clustered_pooled_and_per_run_summaries_only_for_rows_with_run_id(tmp_path):
    sel, scored, res = stage2_multi_run(tmp_path)
    d, a = res["configs"]["D"], res["configs"]["A"]
    assert list(d["per_run"]) == ["run1", "run2", "run3"] and all(d["per_run"][k]["answerable"]["n"] == 8 and d["per_run"][k]["probe"]["n"] == 2 for k in d["per_run"])
    assert d["clustered"]["answerable"]["CAR"]["n"] == 24 and d["clustered"]["answerable"]["CAR"]["n_clusters"] == 8
    assert all(d["clustered"][g][m]["k"] == d[g][m]["k"] for g in ("all", "answerable", "probe") for m in ("CAR", "review_rate", "reject_rate"))  # hitungan sama dengan ringkasan gabungan; hanya CI-nya yang klaster
    assert d["probe"]["FAR"]["n"] == 1 and d["clustered"]["probe"]["FAR"]["n"] == 1 and d["clustered"]["probe"]["FAR"]["n_clusters"] == 1  # satu TIDAK_LAYAK di seluruh lari
    assert (d["per_run"]["run1"]["probe"]["FAR"]["defined"], d["per_run"]["run3"]["probe"]["FAR"]["defined"]) == (False, True)  # lari 1: tak ada TIDAK_LAYAK, bukan 0%
    assert (d["per_run"]["run3"]["probe"]["FAR"]["k"], a["per_run"]["run3"]["probe"]["FAR"]["k"]) == (0, 1)  # hard-fail D menolak angka 999; A menerimanya
    sel1, scored1 = stage2_inputs(tmp_path / "x")
    one = P.run_stage2(scored1, sel1, PROTO, tmp_path / "x" / "II")
    assert "per_run" not in one["configs"]["D"] and "clustered" not in one["configs"]["D"]  # Studi 1: keluaran tidak berubah


# ------------------------------------------------------------------ rincian deskriptif: FAR Track R menurut jenis, kutipan dalam konteks, sensitivitas tahap II

def far_row(aid, grp, label, abstain, v, track="R", **kw):
    """Baris skor sintetis tanpa embedding (L = S = v): v 0,9 -> ACCEPT dan v 0,2 -> REJECT pada parameter D. Bukan hasil penelitian."""
    return {"answer_id": aid, "case_id": f"c{aid}", "group_id": grp, "evidence_group": f"e{grp}", "track": track, "label": label, "abstain": abstain,
            "L": v, "S": v, "unsupported_numbers": [], "neg_mismatch": False, **kw}


def frozen_all_test(rows, cfgs):
    """(protokol, selection) buatan tangan dengan parameter beku. validation_fraction 0 menjatuhkan semua baris ke test, jadi hitungan dapat ditulis tangan."""
    import hashlib

    from ta_rag import data

    proto = PROTO | {"split": PROTO["split"] | {"validation_fraction": 0.0}}
    splits = data.assign_splits(rows, proto["split"]["seed"], 0.0)
    sha = hashlib.sha256(json.dumps(sorted(splits.items())).encode()).hexdigest()
    return proto, {"configs": {n: {"params": p, "selection": {"status": "SELECTED"}} for n, p in cfgs.items()}, "splits_sha256": sha}


def far_by_type_rows():
    return ([far_row(f"A{i}", f"g{i}", "TIDAK_LAYAK", True, 0.2) for i in range(1, 6)]                    # 5 abstain, semuanya REJECT
            + [far_row("W1", "gw1", "TIDAK_LAYAK", False, 0.9),                                          # jawaban salah yang diterima (ACCEPT)
               far_row("W2", "gw2", "TIDAK_LAYAK", None, 0.2), far_row("W3", "gw3", "TIDAK_LAYAK", False, 0.2),  # abstain None/False = jawaban_salah
               far_row("W4", "gw4", "TIDAK_LAYAK", False, 0.6)]                                          # REVIEW: ditahan, bukan diterima
            + [far_row(f"L{i}", f"gl{i}", "LAYAK", False, 0.9) for i in range(1, 4)]
            + [far_row("M1", "gm1", "TIDAK_LAYAK", True, 0.9, track="M")])                               # Track M tidak ikut rincian


def test_run_test_splits_track_r_far_into_abstain_and_wrong_answer_and_leaves_the_overall_far_unchanged(tmp_path):
    from ta_rag import metrics

    rows = far_by_type_rows()
    proto, sel = frozen_all_test(rows, {"D": CFGS["D"]["params"]})
    d = P.run_test(rows, sel, proto, tmp_path / "t.json")["configs"]["D"]
    by = d["R_far_by_type"]
    assert list(by) == ["abstain", "jawaban_salah"]
    assert by["abstain"] == metrics.rate(0, 5) and by["jawaban_salah"] == metrics.rate(1, 4)  # 0/5 dan 1/4
    assert d["R"]["FAR"] == metrics.rate(1, 9) and d["M"]["FAR"] == metrics.rate(1, 1)  # FAR gabungan tetap; Track M terpisah dan tak ikut rincian
    assert [by["abstain"][k] + by["jawaban_salah"][k] for k in ("k", "n")] == [d["R"]["FAR"]["k"], d["R"]["FAR"]["n"]]
    assert json.loads((tmp_path / "t.json").read_text())["configs"]["D"]["R_far_by_type"]["jawaban_salah"]["k"] == 1  # tertulis di test_result.json


def test_far_by_type_is_undefined_not_zero_when_a_type_has_no_tidak_layak_rows(tmp_path):
    from ta_rag import metrics

    layak = far_row("L1", "gl1", "LAYAK", False, 0.9)
    cases = {"hanya_abstain": ([far_row(f"A{i}", f"g{i}", "TIDAK_LAYAK", True, 0.2) for i in (1, 2, 3)] + [layak], metrics.rate(0, 3), metrics.rate(0, 0)),
             "hanya_salah": ([far_row("W1", "gw1", "TIDAK_LAYAK", False, 0.9), layak], metrics.rate(0, 0), metrics.rate(1, 1)),
             "tanpa_tidak_layak": ([layak], metrics.rate(0, 0), metrics.rate(0, 0))}
    for name, (rows, want_abstain, want_wrong) in cases.items():
        proto, sel = frozen_all_test(rows, {"D": CFGS["D"]["params"]})
        by = P.run_test(rows, sel, proto, tmp_path / f"{name}.json")["configs"]["D"]["R_far_by_type"]
        assert (by["abstain"], by["jawaban_salah"]) == (want_abstain, want_wrong), name
    assert (by["abstain"]["defined"], by["abstain"]["point"], by["jawaban_salah"]["defined"], by["jawaban_salah"]["point"]) == (False, None, False, None)  # n=0: bukan 0%


def far_by_type_multi_run_rows(wrong=True):
    out = [far_row(f"run{k}:A{i}", f"g{i}", "TIDAK_LAYAK", True, 0.2, run_id=f"run{k}") for i in range(10) for k in (1, 2, 3)]  # 10 pertanyaan x 3 lari, abstain ditolak
    if wrong:  # gw0 diterima di ketiga lari, gw1 ditolak
        out += [far_row(f"run{k}:W{i}", f"gw{i}", "TIDAK_LAYAK", False, 0.9 if i == 0 else 0.2, run_id=f"run{k}") for i in (0, 1) for k in (1, 2, 3)]
    return out


def test_clustered_analysis_far_by_type_uses_cluster_rate_over_questions_and_stays_undefined_when_empty():
    from ta_rag import metrics

    pooled = P.clustered_analysis(far_by_type_multi_run_rows(), {"D": CFGS["D"]}, PROTO)["configs"]["D"]["pooled"]
    by = pooled["R_far_by_type"]
    assert by["abstain"] == metrics.cluster_rate([(f"g{i}", False) for i in range(10) for _ in range(3)])
    assert [by["abstain"][k] for k in ("k", "n", "n_clusters")] == [0, 30, 10] and by["abstain"]["ci_fallback"] is True  # bootstrap berlebar nol -> CP atas klaster
    assert by["jawaban_salah"] == metrics.cluster_rate([("gw0", True)] * 3 + [("gw1", False)] * 3)
    assert [by["jawaban_salah"][k] for k in ("k", "n", "n_clusters")] == [3, 6, 2]
    assert [pooled["R"]["FAR"][k] for k in ("k", "n")] == [3, 36]  # FAR gabungan tidak berubah: jumlah kedua jenis
    assert set(pooled) == {"R", "M", "R_far_by_type"}
    empty = P.clustered_analysis(far_by_type_multi_run_rows(wrong=False), {"D": CFGS["D"]}, PROTO)["configs"]["D"]["pooled"]["R_far_by_type"]["jawaban_salah"]
    assert empty == metrics.cluster_rate([]) and (empty["defined"], empty["point"], empty["n"]) == (False, None, 0)  # n=0: bukan 0%
    json.dumps(pooled)


def test_score_rows_stage_ii_marks_whether_the_oracle_quote_is_inside_the_retrieved_context():
    ch = lambda text: {"chunk_id": "x", "doc_id": "d", "page_start": 8, "page_end": 8, "text": text}
    chunks = {"c1": CHUNKS["c1"],  # halaman jangkar, tetapi tanpa kalimat kutipan
              "a": ch("Pasal 2 Besaran iuran ditetapkan sebesar Rp8.000,00 (delapan ribu"), "b": ch("rupiah) per peserta per bulan. Pasal 3 hal lain"),
              "fmt": ch("**DITETAPKAN**   sebesar\nRp８.０００,００ (delapan ribu _rupiah_) per  peserta per bulan")}  # huruf besar, penanda, spasi/baris baru, angka lebar penuh
    cases = {**CASES, "R3": {"case_id": "R3", "kind": "not_in_corpus", "source_quote": CASES["R1"]["source_quote"]},  # probe: None walau ada kutipan
             "R4": {"case_id": "R4", "kind": "answerable", "source_doc_id": "d", "source_page": 8}}  # berjawab tanpa kutipan: None
    labs = [lab(1, chunk_ids=["a", "b"]),  # kutipan melintasi dua chunk
            lab(2, chunk_ids=["fmt"]),     # beda hanya huruf besar/kecil, markdown, spasi, bentuk angka
            lab(3, kind="not_in_corpus", chunk_ids=["c1"]), lab(4, chunk_ids=["c1"]),  # probe; berjawab tanpa source_quote
            lab(6, label="TIDAK_LAYAK", abstain=True, chunk_ids=["c1"])]  # halaman cocok, kalimat tidak
    out = {r["answer_id"]: r for r in P.score_rows("II", labs, cases, chunks, None)}
    assert [out[f"A{i}"]["quote_in_context"] for i in (1, 2, 6, 3, 4)] == [True, True, False, None, None]
    assert [out[f"A{i}"]["retrieval_ok"] for i in (1, 2, 6, 3, 4)] == [True, True, True, None, True]  # definisi tingkat halaman tidak berubah
    assert out["A6"]["label"] == "TIDAK_LAYAK" and out["A6"]["label_stage_I"] == "TIDAK_LAYAK"  # label tidak ikut berubah
    assert "quote_in_context" not in P.score_rows("I", [lab(1)], cases, chunks, None)[0]  # Tahap I: baris sama seperti sebelumnya


def stage2_quote_rows():
    """Baris skor tahap II sintetis (L = S = v) dengan label primer menurut aturan terkunci (abstain + retrieval_ok salah -> LAYAK). Bukan hasil penelitian."""
    T, L_ = "TIDAK_LAYAK", "LAYAK"
    spec = [("A1", "answerable", T, True, False, False, 0.2),   # abstain, halaman tidak terambil, kalimat tidak ada: LAYAK di kedua definisi
            ("A2", "answerable", T, True, True, False, 0.2),    # halaman terambil, kalimat tidak: primer TIDAK_LAYAK, sensitivitas LAYAK
            ("A8", "answerable", T, True, True, False, 0.2),    # idem
            ("A3", "answerable", T, True, True, True, 0.2),     # kalimat ada di konteks: tetap TIDAK_LAYAK
            ("A4", "answerable", T, False, True, False, 0.9),   # jawaban salah (bukan abstain) yang diterima: tak pernah dibalik
            ("A5", "answerable", T, True, False, True, 0.2),    # halaman tidak terambil tetapi kalimat ada: primer LAYAK, sensitivitas TIDAK_LAYAK
            ("A6", "answerable", T, True, True, None, 0.2),     # tanpa kutipan (None): tidak dibalik
            ("A7", "answerable", L_, False, True, True, 0.9),
            ("P1", "not_in_corpus", T, True, None, False, 0.2)]  # probe (abstain + klaim status hukum) tak pernah dibalik, walau penanda salah (mustahil dari score_rows)
    return [far_row(aid, f"g{aid}", "LAYAK" if kind == "answerable" and ab and rok is False else lab_i, ab, v, kind=kind, label_stage_I=lab_i, retrieval_ok=rok, quote_in_context=qic)
            for aid, kind, lab_i, ab, rok, qic, v in spec]


def test_stage2_sensitivity_flips_only_abstain_rows_without_the_quote_and_leaves_the_primary_block_untouched(tmp_path):
    sel = P.run_sweep(synthetic_scored(), tmp_path / "I", PROTO)
    rows = stage2_quote_rows()
    res = P.run_stage2(rows, sel, PROTO, tmp_path / "II")
    sq = res["sensitivity_quote_level"]
    assert sq["flipped_answer_ids"] == ["A2", "A5", "A8"]  # terurut; dua arah: A2/A8 menjadi LAYAK, A5 kembali ke TIDAK_LAYAK
    assert isinstance(sq["definition"], str) and "tingkat kutipan" in sq["definition"] and "\n" not in sq["definition"]
    d, s = res["configs"]["D"], sq["configs"]["D"]
    kn = lambda x, m: (x["answerable"][m]["k"], x["answerable"][m]["n"])
    assert (kn(d, "CAR"), kn(d, "FAR")) == ((1, 3), (1, 5))  # primer: LAYAK = A1, A5, A7; TIDAK_LAYAK = A2, A8, A3, A4, A6
    assert (kn(s, "CAR"), kn(s, "FAR")) == ((1, 4), (1, 4))  # sensitivitas: LAYAK = A1, A2, A8, A7; TIDAK_LAYAK = A3, A4, A5, A6
    assert s["probe"] == d["probe"] and s["params"] == d["params"] and list(sq["configs"]) == list(res["configs"])
    old_rows = [{k: v for k, v in r.items() if k != "quote_in_context"} for r in rows]  # skor dari kode lama: tanpa penanda
    old = P.run_stage2(old_rows, sel, PROTO, tmp_path / "II_old")
    assert "sensitivity_quote_level" not in old and list(res)[-1] == "sensitivity_quote_level"
    assert json.dumps({k: v for k, v in res.items() if k != "sensitivity_quote_level"}) == json.dumps(old)  # blok primer sama persis, termasuk urutan kunci
    assert (tmp_path / "II" / "per_case_II.csv").read_bytes() == (tmp_path / "II_old" / "per_case_II.csv").read_bytes()
    assert json.loads((tmp_path / "II" / "stage2_result.json").read_text())["sensitivity_quote_level"]["flipped_answer_ids"] == ["A2", "A5", "A8"]


def stage2_multi_run_quote_rows(tmp_path):
    """stage2_multi_run dengan penanda tahap II: semua kutipan ada di konteks, kecuali run3:T0 (abstain, TIDAK_LAYAK) yang kalimatnya tidak ada."""
    sel, scored, _ = stage2_multi_run(tmp_path)
    rows = [{**s, "label_stage_I": s["label"], "abstain": False, "quote_in_context": True if s["kind"] == "answerable" else None} for s in scored]
    return sel, [{**r, "label": "TIDAK_LAYAK", "label_stage_I": "TIDAK_LAYAK", "abstain": True, "quote_in_context": False} if r["answer_id"] == "run3:T0" else r for r in rows]


def test_stage2_sensitivity_mirrors_clustered_and_per_run_summaries_when_rows_have_run_id(tmp_path):
    sel, rows = stage2_multi_run_quote_rows(tmp_path)
    res = P.run_stage2(rows, sel, PROTO, tmp_path / "II2")
    sq = res["sensitivity_quote_level"]
    assert sq["flipped_answer_ids"] == ["run3:T0"]
    p, s = res["configs"]["D"], sq["configs"]["D"]
    assert list(s["per_run"]) == ["run1", "run2", "run3"] and s["clustered"]["answerable"]["CAR"]["n_clusters"] == 8
    assert (p["per_run"]["run3"]["answerable"]["CAR"]["n"], s["per_run"]["run3"]["answerable"]["CAR"]["n"]) == (7, 8)  # run3:T0 berlabel LAYAK hanya pada sensitivitas
    assert (p["per_run"]["run1"] == s["per_run"]["run1"]) and p["probe"] == s["probe"]
    sel1, scored1 = stage2_inputs(tmp_path / "x")
    assert "sensitivity_quote_level" not in P.run_stage2(scored1, sel1, PROTO, tmp_path / "x" / "II")  # skor tanpa penanda: tanpa blok
