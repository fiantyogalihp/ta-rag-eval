"""Uji pembuat tabel/grafik naskah. Data sintetis HANYA di tmp_path (tidak pernah di data/); angka di sini bukan hasil penelitian."""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
pytest.importorskip("numpy")
pytest.importorskip("matplotlib")
import test_pipeline as TP  # noqa: E402  (fixture sintetis yang sama: lab, CASES, CHUNKS, PROTO)
from ta_rag import pipeline as P, report as R  # noqa: E402


def test_fmt_rate_shows_numerator_denominator_ci_and_never_zero_for_undefined():
    from ta_rag import metrics as M

    assert R.fmt_rate(M.rate(1, 4)).startswith("1/4 = 25.0%") and "[" in R.fmt_rate(M.rate(1, 4))
    assert R.fmt_rate(M.rate(0, 0)) == "tidak terdefinisi (n=0)"
    assert "0.0%" in R.fmt_rate(M.rate(0, 5))  # 0/5 terdefinisi: 0,0% dengan batas atas, bukan 'tak terdefinisi'


def build_inputs(tmp_path):
    labs, cases = [], {}
    for i in range(1, 21):
        labs.append(TP.lab(i))
        labs.append({**TP.lab(100 + i, label="TIDAK_LAYAK", answer="Rp16.000,00 per peserta", track="M", answer_origin="mutasi_terkontrol",
                             pair_id=f"P{i}", mutation_family="numeric_value", anchor_page_opposite=8, mutated_from_answer_id=f"A{i}"),
                     "group_id": f"g{i}", "evidence_group": f"e{i}", "case_id": f"R{i}", "origin": "mutation"})
        cases[f"R{i}"] = {**TP.CASES["R1"], "case_id": f"R{i}", "question": f"Pertanyaan {i}?"}
    import numpy as np

    scored = P.score_rows("I", labs, cases, TP.CHUNKS, lambda texts: np.ones((len(texts), 3)))
    sel = P.run_sweep(scored, tmp_path / "res" / "I", TP.PROTO)
    P.run_test(scored, sel, TP.PROTO, tmp_path / "res" / "I" / "test_result.json")
    cp = tmp_path / "cases.jsonl"; cp.write_text("\n".join(json.dumps(c) for c in cases.values()) + "\n", encoding="utf-8")
    lp = tmp_path / "labels_all.jsonl"; lp.write_text("\n".join(json.dumps({**r, "validator": "V", "labeled_at": "2026-11-08T10:00:00+00:00"}) for r in labs) + "\n", encoding="utf-8")
    return cp, lp


def test_build_report_writes_all_artifacts_from_results(tmp_path):
    cp, lp = build_inputs(tmp_path)
    out = R.build_report(tmp_path / "res", cp, lp, tmp_path / "rep", latency_path=None)
    for name in ("table11.md", "table11.csv", "table12.csv", "table12.md", "fig_stage_A.png", "fig_stage_B.png", "confusion_test.md", "kasus_tabel14.md", "kasus_tabel14_B.md"):
        assert (tmp_path / "rep" / name).stat().st_size > 0, name
    assert (tmp_path / "rep" / "fig_stage_A.png").read_bytes()[:4] == b"\x89PNG"
    t12 = list(csv.DictReader(open(tmp_path / "rep" / "table12.csv", encoding="utf-8")))
    assert len(t12) == 60 and {"far_M", "lolos_batas_FAR"} <= set(t12[0])
    t11 = list(csv.DictReader(open(tmp_path / "rep" / "table11.csv", encoding="utf-8")))
    assert [r["konfigurasi"] for r in t11] == ["A", "B", "C", "D", "D*"]
    assert "validator tunggal" in (tmp_path / "rep" / "table11.md").read_text(encoding="utf-8")  # prefiks klaim wajib ada
    assert out["table11_rows"] == 5
    assert not any((tmp_path / "rep" / n).exists() for n in ("table11_klaster.md", "per_lari.md", "hipotesis.md"))  # Studi 1: satu lari, tanpa tabel klaster
    assert "Studi 2" not in (tmp_path / "rep" / "table11.md").read_text(encoding="utf-8")


def test_table11_keeps_tracks_in_separate_columns_and_p95_comes_from_latency(tmp_path):
    cp, lp = build_inputs(tmp_path)
    lat = tmp_path / "latency.json"; lat.write_text(json.dumps({"p95_ms_by_config": {"A": 1.0, "C": 20.0, "D": 21.0}}), encoding="utf-8")
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "rep", latency_path=lat)
    rows = {r["konfigurasi"]: r for r in csv.DictReader(open(tmp_path / "rep" / "table11.csv", encoding="utf-8"))}
    assert {"car_R", "far_R", "far_M", "review_R", "reject_R"} <= set(rows["D"])
    assert rows["A"]["p95_ms"] == "1.00" and rows["B"]["p95_ms"] == "20.00 (proksi C)" and rows["D*"]["p95_ms"] == "21.00 (proksi D)"
    lat.write_text(json.dumps({"p95_ms_by_config": {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "D*": 5.0}}), encoding="utf-8")
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "rep", latency_path=lat)
    rows = {r["konfigurasi"]: r for r in csv.DictReader(open(tmp_path / "rep" / "table11.csv", encoding="utf-8"))}
    assert rows["D*"]["p95_ms"] == "5.00"  # diukur pada parameter konfigurasi itu sendiri: tanpa label proksi
    assert rows["D"]["far_R"] == "tidak terdefinisi (n=0)"  # Track R sintetis tanpa TIDAK_LAYAK: bukan 0%


def row(aid, label, route, split="test"):
    return {"answer_id": aid, "case_id": "R1", "track": "R", "label": label, "split": split, "L": "0.9", "S": "0.9", "route_D": route, "H_D": "0.9"}


def test_pick_cases_takes_first_by_answer_id_prefers_test_then_flags_validation_and_reports_search_count():
    rows = [row("A3", "LAYAK", "ACCEPT"), row("A1", "LAYAK", "ACCEPT"), row("A2", "TIDAK_LAYAK", "REJECT"),
            row("A9", "TIDAK_LAYAK", "ACCEPT", split="validation")]
    got = R.pick_cases(rows, "D")
    assert got["benar_ACCEPT"]["row"]["answer_id"] == "A1" and got["benar_ACCEPT"]["source"] == "test"
    assert got["salah_tertahan"]["row"]["answer_id"] == "A2"
    assert got["salah_tetap_ACCEPT"]["row"]["answer_id"] == "A9" and got["salah_tetap_ACCEPT"]["source"] == "validation (cadangan)"
    none = R.pick_cases([row("A1", "TIDAK_LAYAK", "REJECT")], "D")
    assert none["salah_tetap_ACCEPT"]["row"] is None and none["salah_tetap_ACCEPT"]["searched"] == 1  # jumlah yang dicari, bukan klaim 'tanpa kesalahan'
    assert R.pick_cases([], "D")["benar_ACCEPT"]["row"] is None


def test_claim_prefix_is_filled_from_relabel_result_and_left_visible_without_it(tmp_path):
    cp, lp = build_inputs(tmp_path)
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "rep")
    assert "intra-rater agreement X%" in (tmp_path / "rep" / "table11.md").read_text(encoding="utf-8")
    rl = tmp_path / "relabel_result.json"; rl.write_text(json.dumps({"pct": 87.5, "n": 8}), encoding="utf-8")
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "rep", relabel_path=rl)
    assert "intra-rater agreement 87,5%, n=8" in (tmp_path / "rep" / "table11.md").read_text(encoding="utf-8")


def test_table12_reports_review_and_reject_with_counts_and_ci():
    g = {"id": "C:w0.5:t0.8", "config": "C", "w_s": "0.5", "accept": "0.8", "n_R": "12", "review_rate_R": "0.25", "reject_rate_R": "0.0",
         **{f"{m}_{s}": v for m in ("car_R", "far_R", "far_M") for s, v in (("k", "0"), ("n", "0"))}, "car_R": "", "far_R": "", "far_M": ""}
    row = R.table12([g], 0.05)[0]
    assert row["review_R"].startswith("3/12 = 25.0%") and "[" in row["review_R"] and row["reject_R"].startswith("0/12")


def test_family_rows_count_routes_per_mutation_family_and_split():
    pc = [{"answer_id": "M:R1", "track": "M", "split": "test", "route_B": "ACCEPT", "route_D": "REJECT"},
          {"answer_id": "M:R2", "track": "M", "split": "test", "route_B": "ACCEPT", "route_D": "ACCEPT"},
          {"answer_id": "M:R3", "track": "M", "split": "validation", "route_B": "REVIEW", "route_D": "REJECT"},
          {"answer_id": "run1:R1", "track": "R", "split": "test", "route_B": "ACCEPT", "route_D": "ACCEPT"}]
    labels = {"M:R1": {"mutation_family": "numeric_value"}, "M:R2": {"mutation_family": "unit"}, "M:R3": {"mutation_family": "numeric_value"}}
    rows = {(r["family"], r["split"]): r for r in R.family_rows(pc, labels)}
    assert rows[("unit", "test")] == {"family": "unit", "split": "test", "n": 1, "B": "1/0/0", "D": "1/0/0"}
    assert rows[("numeric_value", "validation")]["D"] == "0/0/1" and len(rows) == 3  # Track R tidak ikut


def test_stage2_rows_and_score_means_keep_groups_separate():
    from ta_rag import metrics as M

    s = {"n": 1, "CAR": M.rate(0, 1), "FAR": M.rate(0, 0), "review_rate": M.rate(0, 1), "reject_rate": M.rate(1, 1)}
    rows = R.stage2_rows({"configs": {"D": {"params": {}, "all": s, "answerable": s, "probe": s}}})
    assert [r["kelompok"] for r in rows] == ["all", "answerable", "probe"] and rows[0]["far"] == "tidak terdefinisi (n=0)"
    m = R.score_means([{"track": "R", "kind": "answerable", "L": 0.2, "S": 0.8}, {"track": "R", "kind": "answerable", "L": 0.4, "S": 0.6},
                       {"track": "M", "kind": "answerable", "L": 1.0, "S": 1.0}])
    assert m == {"n": 2, "L": 0.3, "S": 0.7}


def test_series_ci_gives_percent_points_with_band_and_nan_when_undefined():
    rows = [{"w_s": "0.5", "car_R": "0.5", "car_R_lo95": "0.1", "car_R_hi95": "0.9", "far_M": "", "far_M_lo95": "", "far_M_hi95": ""}]
    s = R.series_ci(rows, "w_s", 100)
    assert s["xs"] == [50.0] and s["car"] == [50.0] and s["car_lo"] == [10.0] and s["car_hi"] == [90.0]
    assert math.isnan(s["far"][0]) and math.isnan(s["far_lo"][0]) and math.isnan(s["far_hi"][0])  # FAR tak terdefinisi: bukan 0


def test_extra_table14_for_config_b_is_labelled_as_not_preregistered(tmp_path):
    cp, lp = build_inputs(tmp_path)
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "rep")
    md = (tmp_path / "rep" / "kasus_tabel14_B.md").read_text(encoding="utf-8")
    assert "konfigurasi B" in md and "tambahan, tidak dipra-registrasi" in md
    assert "konfigurasi D" in (tmp_path / "rep" / "kasus_tabel14.md").read_text(encoding="utf-8")


def test_table11_labels_config_f_by_bertscore_not_by_weights(tmp_path):
    import numpy as np

    labs, cases = [], {}
    for i in range(1, 21):
        labs.append(TP.lab(i))
        labs.append({**TP.lab(100 + i, label="TIDAK_LAYAK", answer="Rp16.000,00 per peserta", track="M", answer_origin="mutasi_terkontrol",
                              pair_id=f"P{i}", mutation_family="numeric_value", anchor_page_opposite=8, mutated_from_answer_id=f"A{i}"),
                     "group_id": f"g{i}", "evidence_group": f"e{i}", "case_id": f"R{i}"})
        cases[f"R{i}"] = {**TP.CASES["R1"], "case_id": f"R{i}", "question": f"Pertanyaan {i}?"}

    class Stub:
        hash = "stub"

        def score(self, cands, refs):
            f = np.array([0.9 if "8.000" in c else 0.5 for c in cands])
            return f, f, f

    scored = P.score_rows("I", labs, cases, TP.CHUNKS, lambda texts: np.ones((len(texts), 3)), bert_scorer=Stub())
    proto = TP.PROTO | {"selection": TP.PROTO["selection"] | {"grid_configs": ["C", "D", "F"]}}
    sel = P.run_sweep(scored, tmp_path / "res" / "I", proto)
    P.run_test(scored, sel, proto, tmp_path / "res" / "I" / "test_result.json")
    cp = tmp_path / "cases.jsonl"; cp.write_text("\n".join(json.dumps(c) for c in cases.values()) + "\n", encoding="utf-8")
    lp = tmp_path / "labels_all.jsonl"; lp.write_text("\n".join(json.dumps({**r, "validator": "V", "labeled_at": "2026-11-08T10:00:00+00:00"}) for r in labs) + "\n", encoding="utf-8")
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "rep")
    rows = {r["konfigurasi"]: r for r in csv.DictReader(open(tmp_path / "rep" / "table11.csv", encoding="utf-8"))}
    assert rows["F"]["bobot_SL"] == "BERTScore F1" and rows["F"]["threshold"] and rows["C"]["bobot_SL"] != "BERTScore F1"
    t12 = list(csv.DictReader(open(tmp_path / "rep" / "table12.csv", encoding="utf-8")))
    assert len(t12) == 96 and {r["config"] for r in t12} == {"C", "D", "F"}


# ------------------------------------------------------------------ Studi 2: gabungan lari (CI klaster), per lari, hipotesis

def clustered_test_result():
    """test_result sintetis dari baris skor buatan tangan (TP.multi_run_test_rows) dengan konfigurasi B, D, E, F beku. Bukan hasil penelitian."""
    cl = P.clustered_analysis(TP.multi_run_test_rows(), TP.CFGS, TP.PROTO2)
    return {"n_test_by_track": {"R": 36, "M": 12}, "claim_prefix_required": "Di bawah pelabelan validator tunggal (intra-rater agreement {pct}%, n={n}): ",
            "configs": {k: {"params": v["params"], "status": "TEST_RUN_ONCE_FROZEN_PARAMS"} for k, v in TP.CFGS.items()}, "clustered": cl}


def test_fmt_rate_shows_point_without_interval_when_cluster_ci_is_not_computable():
    from ta_rag import metrics as M

    assert R.fmt_rate(M.cluster_rate([("a", True)])) == "1/1 = 100.0% [CI tidak dihitung: klaster < 2]"
    assert R.fmt_rate(M.cluster_rate([])) == "tidak terdefinisi (n=0)"
    assert R.fmt_rate({"defined": True, "k": 3, "n": 3, "point": 1.0, "lo": 0.29, "hi": 1.0, "ci_fallback": True}) == "3/3 = 100.0% [29.0–100.0]†"  # CI pengganti ditandai


def test_table12_labels_config_f_rows_by_bertscore_and_others_by_weights():
    g = {"id": "F:t0.8", "config": "F", "w_s": "0.0", "accept": "0.8", "n_R": "4", "review_rate_R": "0.0", "reject_rate_R": "0.0",
         **{f"{m}_{s}": "0" for m in ("car_R", "far_R", "far_M") for s in ("k", "n")}, "car_R": "", "far_R": "", "far_M": ""}
    rows = R.table12([g, {**g, "id": "C:w0.6:t0.8", "config": "C", "w_s": "0.6"}], 0.05)
    assert [r["bobot_SL"] for r in rows] == ["BERTScore F1", "60:40"]


def test_table_klaster_lists_every_frozen_config_with_tracks_apart_and_f_by_bertscore():
    rows = {r["konfigurasi"]: r for r in R.table_klaster(clustered_test_result())}
    assert list(rows) == ["B", "D", "E", "F"]
    assert rows["F"]["bobot_SL"] == "BERTScore F1" and rows["E"]["bobot_SL"] == "60:40" and rows["D"]["threshold"] == 0.78
    assert rows["D"]["car_R"].startswith("33/36 = 91.7% [") and rows["D"]["far_R"] == "tidak terdefinisi (n=0)"  # tanpa TIDAK_LAYAK alami: bukan 0%
    assert [rows[c]["far_M"].split(" ")[0] for c in "BDEF"] == ["12/12", "6/12", "0/12", "12/12"]
    assert rows["B"]["far_M"] == "12/12 = 100.0% [73.5–100.0]†" and rows["E"]["far_M"] == "0/12 = 0.0% [0.0–26.5]†"  # bootstrap berlebar nol -> CP atas 12 klaster
    assert "†" not in rows["D"]["car_R"] and "†" not in rows["D"]["far_M"]
    assert {"review_M", "reject_M", "review_R", "reject_R"} <= set(rows["D"])  # REVIEW dan REJECT terpisah, Track R dan M di kolom berbeda


def test_table_per_lari_has_one_row_per_run_then_mean_and_range_and_never_zero_for_undefined():
    rows = [r for r in R.table_per_lari(clustered_test_result()) if r["konfigurasi"] == "D"]
    assert [r["lari"] for r in rows] == ["run1", "run2", "run3", "rata-rata [rentang]"]
    assert rows[0]["car_R"].startswith("12/12") and rows[2]["car_R"].startswith("9/12") and rows[0]["n_R"] == 12
    assert rows[3]["car_R"] == "91.7% [75.0–100.0] (3 lari)" and rows[3]["far_R"] == "tidak terdefinisi (n=0)"
    assert rows[2]["review_R"].startswith("3/12 = 25.0%") and rows[2]["reject_R"].startswith("0/12")  # D: tiga jawaban lari 3 turun ke REVIEW
    f3 = next(r for r in R.table_per_lari(clustered_test_result()) if r["konfigurasi"] == "F" and r["lari"] == "run3")
    assert f3["review_R"].startswith("0/12") and f3["reject_R"].startswith("3/12 = 25.0%")  # F: skor 0,6 < ambang - 0,10, jadi REJECT; REVIEW dan REJECT tidak tertukar
    assert len(R.table_per_lari(clustered_test_result())) == 4 * 4  # empat konfigurasi x (tiga lari + baris rata-rata)


def test_hypothesis_rows_show_effect_ci_discordant_and_warn_below_ten_clusters():
    hyp = clustered_test_result()["clustered"]["hypotheses"]
    rows = {r["hipotesis"]: r for r in R.hypothesis_rows(hyp)}
    assert rows["H1"]["selisih_poin"] == "+50.0" and rows["H1"]["putusan"] == "TERDUKUNG" and rows["H1"]["n_klaster"] == 12
    assert "McNemar eksak p=0.0312 > 0.0167" in rows["H1"]["catatan"] and "klaster < 10" not in rows["H1"]["catatan"]  # 12 klaster, tetapi aturan umum klaim belum terpenuhi
    assert rows["H2"]["diskordan_b_c"] == "6/0" and rows["H2"]["ci_bootstrap_klaster"] == "[+100.0; +100.0]"
    assert "klaster < 10" in rows["H2"]["catatan"] and "CI berlebar nol" in rows["H2"]["catatan"]
    assert rows["H2"]["perbandingan"] == "REJECT: E vs D; unit" and rows["H1"]["perbandingan"].endswith("semua mutasi")
    v = {**hyp["H1"], "mcnemar_p": 0.001}  # McNemar signifikan: hanya aturan jumlah klaster yang diuji di sini
    edge = {r["hipotesis"]: r["catatan"] for r in R.hypothesis_rows({"H9": {**v, "n_clusters": 10}, "H8": {**v, "n_clusters": 9}})}
    assert edge == {"H9": "", "H8": "klaster < 10: CI bootstrap tidak andal"}  # tepat 10 klaster tidak diperingatkan
    bonf = 1 - v["level"]
    note = lambda **kw: R.hypothesis_rows({"H1": {**v, **kw}})[0]["catatan"]
    assert note(mcnemar_p=bonf) == "" and "McNemar" in note(mcnemar_p=bonf + 1e-6)  # tepat di ambang Bonferroni belum diperingatkan
    assert note(verdict="TIDAK_ADA_BUKTI_PERBEDAAN", mcnemar_p=0.5) == ""  # catatan klaim hanya untuk putusan TERDUKUNG
    nv = R.hypothesis_rows({"H2": {**TP.OPS["H2"], "verdict": "NOT_EVALUATED_NO_FROZEN_PARAMS"}})[0]
    assert nv["selisih_poin"] == "-" and nv["putusan"].startswith("NOT_EVALUATED") and nv["n_mutasi"] == "-"
    assert R.hypothesis_rows({"H1": {**TP.OPS["H1"], "n": 3, "n_clusters": 1, "diff": 1.0, "lo": None, "hi": None, "discordant": (3, 0), "mcnemar_p": 0.25, "level": 0.9833,
                                      "verdict": "CI_TIDAK_DAPAT_DIHITUNG"}})[0]["ci_bootstrap_klaster"] == "tidak dihitung"


def test_hypotheses_md_states_the_preregistered_rule_the_claim_prefix_and_h4_as_descriptive():
    cl = clustered_test_result()["clustered"]
    md = R.hypotheses_md(cl, "Di bawah pelabelan validator tunggal (intra-rater agreement X%, n=…)")
    assert "98,3%" in md and "10 poin persentase" in md and "validator tunggal" in md and "McNemar eksak hanya informasi" in md
    assert "H4 (deskriptif, tanpa uji)" in md and "CAR Track R = 33/36" in md
    assert "D tidak dievaluasi" in R.hypotheses_md({**cl, "configs": {k: v for k, v in cl["configs"].items() if k != "D"}}, "x")


def build_multi_inputs(tmp_path):
    import numpy as np

    labs, cases = TP.multi_run_labs()
    scored = P.score_rows("I", labs, cases, TP.CHUNKS, lambda texts: np.ones((len(texts), 3)))
    sel = P.run_sweep(scored, tmp_path / "res" / "I", TP.PROTO2)
    P.run_test(scored, sel, TP.PROTO2, tmp_path / "res" / "I" / "test_result.json")
    cp = tmp_path / "cases.jsonl"; cp.write_text("\n".join(json.dumps(c) for c in cases.values()) + "\n", encoding="utf-8")
    lp = tmp_path / "labels_all.jsonl"; lp.write_text("\n".join(json.dumps({**r, "validator": "V", "labeled_at": "2026-11-08T10:00:00+00:00"}) for r in labs) + "\n", encoding="utf-8")
    return cp, lp


def test_build_report_writes_clustered_tables_when_results_have_three_runs(tmp_path):
    cp, lp = build_multi_inputs(tmp_path)
    out = R.build_report(tmp_path / "res", cp, lp, tmp_path / "rep")
    rep = tmp_path / "rep"
    for name in ("table11_klaster.md", "table11_klaster.csv", "per_lari.md", "per_lari.csv", "hipotesis.md", "table11.md"):
        assert (rep / name).stat().st_size > 0, name
    tk = list(csv.DictReader(open(rep / "table11_klaster.csv", encoding="utf-8")))
    assert [r["konfigurasi"] for r in tk] == ["A", "B", "C", "D", "D*"] and out["table11_rows"] == 5
    assert len(list(csv.DictReader(open(rep / "per_lari.csv", encoding="utf-8")))) == 5 * 4
    md = (rep / "table11_klaster.md").read_text(encoding="utf-8")
    assert "run1, run2, run3" in md and "bootstrap persentil" in md and "†" in md and "validator tunggal" in md
    assert "H1" in (rep / "hipotesis.md").read_text(encoding="utf-8")
    assert "table11_klaster.md" in (rep / "table11.md").read_text(encoding="utf-8")  # Clopper-Pearson gabungan diberi peringatan


# ------------------------------------------------------------------ Tahap II Studi 2: gabungan klaster dan per lari

def test_stage2_rows_show_status_for_unapplied_config_and_multi_run_rows_split_by_run(tmp_path):
    _, _, res = TP.stage2_multi_run(tmp_path)
    res["configs"]["B"] = {"params": None, "status": "NOT_APPLIED_NO_FROZEN_PARAMS"}
    rows = R.stage2_rows(res)
    assert [r for r in rows if r["konfigurasi"] == "B"] == [{"konfigurasi": "B", "kelompok": "-", "n": "-", "car": "NOT_APPLIED_NO_FROZEN_PARAMS", "far": "-", "review": "-", "reject": "-"}]
    assert list(rows[0]) == ["konfigurasi", "kelompok", "n", "car", "far", "review", "reject"] and len([r for r in rows if r["konfigurasi"] == "D"]) == 3
    kl, per = R.stage2_klaster_rows(res), R.stage2_per_lari_rows(res)
    assert {r["konfigurasi"] for r in kl} == {"A", "C", "D", "D*"} and len(kl) == 4 * 3 and len(per) == 4 * 3 * 3  # B tanpa parameter: tak ada baris klaster/per lari
    assert list(per[0]) == ["konfigurasi", "lari", "kelompok", "n", "car", "far", "review", "reject"]
    klp = {(r["konfigurasi"], r["kelompok"]): r for r in kl}
    assert klp[("D", "answerable")]["car"] == "24/24 = 100.0% [63.1–100.0]†"  # 24 jawaban = 8 pertanyaan x 3 lari: CP atas 8 klaster, bukan atas 24 jawaban
    assert next(r for r in rows if (r["konfigurasi"], r["kelompok"]) == ("D", "answerable"))["car"].startswith("24/24 = 100.0% [85.8")  # tabel gabungan lama tetap CP per record
    pr = {(r["konfigurasi"], r["lari"], r["kelompok"]): r for r in per}
    assert pr[("A", "run3", "probe")]["far"].startswith("1/1 = 100.0%") and pr[("D", "run3", "probe")]["far"].startswith("0/1 = 0.0%")
    assert pr[("D", "run1", "probe")]["far"] == "tidak terdefinisi (n=0)"  # lari tanpa TIDAK_LAYAK: bukan 0%
    assert pr[("D", "run3", "probe")]["reject"].startswith("1/2 = 50.0%") and pr[("D", "run3", "probe")]["review"].startswith("0/2")  # REVIEW dan REJECT tidak tertukar
    assert pr[("D", "run2", "answerable")]["n"] == 8 and pr[("D", "run2", "answerable")]["car"].startswith("8/8 = 100.0%")
    sel1, scored1 = TP.stage2_inputs(tmp_path / "one")
    assert R.stage2_klaster_rows(P.run_stage2(scored1, sel1, TP.PROTO, tmp_path / "one" / "II")) == []  # Studi 1: tidak ada tabel klaster


def test_build_report_adds_stage2_clustered_and_per_run_tables_only_when_stage2_has_runs(tmp_path):
    import shutil

    cp, lp = build_multi_inputs(tmp_path)
    TP.stage2_multi_run(tmp_path / "s2")
    shutil.copytree(tmp_path / "s2" / "II", tmp_path / "res" / "II")
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "rep")
    md = (tmp_path / "rep" / "stage2.md").read_text(encoding="utf-8")
    assert "## Gabungan lari (CI bootstrap klaster pertanyaan)" in md and "## Per lari (Clopper–Pearson per lari)" in md and "run3" in md
    assert "terlalu sempit" in md and md.startswith("# Tahap II (deskriptif")


# ------------------------------------------------------------------ rincian deskriptif: FAR Track R menurut jenis dan sensitivitas tingkat kutipan Tahap II

def strip_keys(obj, *keys):
    """Salinan JSON tanpa kunci tertentu di kedalaman mana pun: meniru berkas hasil dari kode sebelum rincian deskriptif ditambahkan."""
    if isinstance(obj, dict):
        return {k: strip_keys(v, *keys) for k, v in obj.items() if k not in keys}
    return [strip_keys(v, *keys) for v in obj] if isinstance(obj, list) else obj


def test_table_far_jenis_puts_both_types_next_to_the_overall_far_and_never_shows_zero_for_undefined(tmp_path):
    from ta_rag import metrics as M

    rows = TP.far_by_type_rows()
    proto, sel = TP.frozen_all_test(rows, {"D": TP.CFGS["D"]["params"]})
    test = P.run_test(rows, sel, proto, tmp_path / "t.json")
    got = R.table_far_jenis(test)
    assert got == [{"konfigurasi": "D", "far_R": R.fmt_rate(M.rate(1, 9)), "far_R_abstain": R.fmt_rate(M.rate(0, 5)), "far_R_jawaban_salah": R.fmt_rate(M.rate(1, 4)), "catatan": ""}]
    assert got[0]["far_R_abstain"].startswith("0/5 = 0.0% [") and got[0]["far_R_jawaban_salah"].startswith("1/4 = 25.0% [")
    assert got[0]["far_R"] == R.table11(test, None)[0]["far_R"]  # FAR gabungan identik dengan Tabel 11
    only = [TP.far_row(f"A{i}", f"g{i}", "TIDAK_LAYAK", True, 0.2) for i in (1, 2)] + [TP.far_row("L1", "gl1", "LAYAK", False, 0.9)]
    proto, sel = TP.frozen_all_test(only, {"D": TP.CFGS["D"]["params"]})
    row = R.table_far_jenis(P.run_test(only, sel, proto, tmp_path / "t2.json"))[0]
    assert row["far_R_jawaban_salah"] == "tidak terdefinisi (n=0)" and row["far_R_abstain"].startswith("0/2 = 0.0%")  # n=0: tidak terdefinisi, bukan 0%
    test["configs"]["B"] = {"params": None, "status": "NOT_EVALUATED_FAR_UNDEFINED_NO_SELECTION"}
    assert R.table_far_jenis(test)[-1] == {"konfigurasi": "B", "far_R": "NOT_EVALUATED_FAR_UNDEFINED_NO_SELECTION", "far_R_abstain": "-", "far_R_jawaban_salah": "-", "catatan": ""}
    old = {**test, "configs": {n: strip_keys(c, "R_far_by_type") for n, c in test["configs"].items()}}
    assert R.table_far_jenis(old) == []  # berkas lama tanpa kunci baru: tanpa tabel


def test_table_far_jenis_uses_cluster_ci_and_the_small_cluster_note_for_study_two_results():
    cl = P.clustered_analysis(TP.far_by_type_multi_run_rows(), {"D": TP.CFGS["D"]}, TP.PROTO)
    by = cl["configs"]["D"]["pooled"]["R_far_by_type"]
    test = {"configs": {"D": {"params": TP.CFGS["D"]["params"], "status": "TEST_RUN_ONCE_FROZEN_PARAMS"}}, "clustered": cl}
    row = R.table_far_jenis(test)[0]
    assert row["far_R_abstain"] == R.fmt_rate(by["abstain"]) and row["far_R_abstain"].startswith("0/30 = 0.0% [") and row["far_R_abstain"].endswith("†")
    assert row["far_R_jawaban_salah"] == R.fmt_rate(by["jawaban_salah"]) and row["far_R_jawaban_salah"].startswith("3/6 = 50.0% [") and "†" not in row["far_R_jawaban_salah"]
    assert row["far_R"] == R.fmt_rate(cl["configs"]["D"]["pooled"]["R"]["FAR"]) and row["far_R"].startswith("3/36 = ")
    assert row["catatan"] == "jawaban_salah: " + R.FEW_CLUSTERS  # 2 klaster diperingatkan; abstain tepat 10 klaster tidak
    nine = P.clustered_analysis([r for r in TP.far_by_type_multi_run_rows() if r["group_id"] != "g9"], {"D": TP.CFGS["D"]}, TP.PROTO)
    assert R.table_far_jenis({**test, "clustered": nine})[0]["catatan"] == f"abstain: {R.FEW_CLUSTERS}; jawaban_salah: {R.FEW_CLUSTERS}"  # 9 klaster: keduanya


def test_build_report_writes_far_by_type_file_and_every_other_text_file_stays_identical_for_old_results(tmp_path):
    cp, lp = build_inputs(tmp_path)
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "new")
    tr = tmp_path / "res" / "I" / "test_result.json"
    tr.write_text(json.dumps(strip_keys(json.loads(tr.read_text(encoding="utf-8")), "R_far_by_type")), encoding="utf-8")  # hasil dari kode sebelum rincian
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "old")
    text_files = lambda d: {p.name for p in (tmp_path / d).iterdir() if p.suffix in (".md", ".csv")}
    assert text_files("new") - text_files("old") == {"table11_jenis.md", "table11_jenis.csv"} and text_files("old") < text_files("new")
    for name in text_files("old"):
        assert (tmp_path / "old" / name).read_bytes() == (tmp_path / "new" / name).read_bytes(), name
    md = (tmp_path / "new" / "table11_jenis.md").read_text(encoding="utf-8")
    assert "validator tunggal" in md and "abstain" in md and "jawaban_salah" in md and "Clopper–Pearson dua sisi 95%" in md and "klaster" not in md
    assert md.count("tidak terdefinisi (n=0)") == 5 * 3  # Track R sintetis tanpa TIDAK_LAYAK: tiga sel x lima konfigurasi tak terdefinisi, bukan 0%
    assert list(csv.DictReader(open(tmp_path / "new" / "table11_jenis.csv", encoding="utf-8")))[0].keys() == {"konfigurasi", "far_R", "far_R_abstain", "far_R_jawaban_salah", "catatan"}


def test_build_report_far_by_type_file_follows_the_cluster_analysis_for_three_run_results(tmp_path):
    cp, lp = build_multi_inputs(tmp_path)
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "rep")
    md = (tmp_path / "rep" / "table11_jenis.md").read_text(encoding="utf-8")
    assert "bootstrap persentil" in md and "klaster = pertanyaan" in md and "†" in md and "validator tunggal" in md
    assert [r["konfigurasi"] for r in csv.DictReader(open(tmp_path / "rep" / "table11_jenis.csv", encoding="utf-8"))] == ["A", "B", "C", "D", "D*"]


def test_stage2_sensitivity_rows_pair_primary_and_quote_level_answerable_summaries(tmp_path):
    sel = P.run_sweep(TP.synthetic_scored(), tmp_path / "I", TP.PROTO)
    res = P.run_stage2(TP.stage2_quote_rows(), sel, TP.PROTO, tmp_path / "II")
    rows = R.stage2_sensitivity_rows(res)
    d = [r for r in rows if r["konfigurasi"] == "D"]
    assert [r["dasar_label"] for r in d] == ["halaman (primer)", "kutipan (sensitivitas)"] and {r["kelompok"] for r in rows} == {"answerable"} and len(rows) == 5 * 2
    assert [(r["n"], r["car"][:11], r["far"][:11]) for r in d] == [(8, "1/3 = 33.3%", "1/5 = 20.0%"), (8, "1/4 = 25.0%", "1/4 = 25.0%")]
    primary = next(r for r in R.stage2_rows(res) if (r["konfigurasi"], r["kelompok"]) == ("D", "answerable"))
    assert (d[0]["n"], d[0]["car"], d[0]["far"], d[0]["review"], d[0]["reject"]) == (primary["n"], primary["car"], primary["far"], primary["review"], primary["reject"])  # baris primer = tabel primer
    res["configs"]["B"] = {"params": None, "status": "NOT_APPLIED_NO_FROZEN_PARAMS"}
    assert "B" not in {r["konfigurasi"] for r in R.stage2_sensitivity_rows(res)}
    assert R.stage2_sensitivity_rows(strip_keys(res, "sensitivity_quote_level")) == []  # berkas lama: tanpa tabel


def test_stage2_sensitivity_rows_use_the_pooled_cluster_summary_when_the_result_has_runs(tmp_path):
    sel, rows = TP.stage2_multi_run_quote_rows(tmp_path)
    res = P.run_stage2(rows, sel, TP.PROTO, tmp_path / "II2")
    d = [r for r in R.stage2_sensitivity_rows(res) if r["konfigurasi"] == "D"]
    assert d[0]["car"] == R.fmt_rate(res["configs"]["D"]["clustered"]["answerable"]["CAR"]) and d[0]["car"].startswith("23/23 = 100.0%") and d[0]["car"].endswith("†")
    assert d[1]["car"] == R.fmt_rate(res["sensitivity_quote_level"]["configs"]["D"]["clustered"]["answerable"]["CAR"]) and d[1]["car"].startswith("24/24 = 100.0%")
    assert d[0]["car"] != R.stage2_rows(res)[2]["car"]  # bukan Clopper-Pearson per jawaban (tabel primer lama)


def test_build_report_appends_the_quote_level_sensitivity_section_only_when_stage2_has_it(tmp_path):
    import shutil

    cp, lp = build_inputs(tmp_path)
    sel = P.run_sweep(TP.synthetic_scored(), tmp_path / "s2" / "I", TP.PROTO)
    P.run_stage2(TP.stage2_quote_rows(), sel, TP.PROTO, tmp_path / "s2" / "II")
    shutil.copytree(tmp_path / "s2" / "II", tmp_path / "res" / "II")
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "new")
    new = (tmp_path / "new" / "stage2.md").read_text(encoding="utf-8")
    assert "## Sensitivitas tingkat kutipan" in new and "3 jawaban (A2, A5, A8)" in new and "halaman (primer)" in new and "kutipan (sensitivitas)" in new
    s2 = tmp_path / "res" / "II" / "stage2_result.json"
    s2.write_text(json.dumps(strip_keys(json.loads(s2.read_text(encoding="utf-8")), "sensitivity_quote_level")), encoding="utf-8")  # hasil dari kode sebelum rincian
    R.build_report(tmp_path / "res", cp, lp, tmp_path / "old")
    old = (tmp_path / "old" / "stage2.md").read_text(encoding="utf-8")
    assert "Sensitivitas" not in old and new.startswith(old) and new != old  # berkas lama tetap sama; yang baru = lama + satu bagian
