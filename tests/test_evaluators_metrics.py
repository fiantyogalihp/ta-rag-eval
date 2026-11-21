"""Uji KODE evaluator A-D, metrik, interval, data dua jalur, sweep. Data sintetis; bukan hasil penelitian."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ta_rag import data as D  # noqa: E402
from ta_rag import evaluators as E  # noqa: E402
from ta_rag import metrics as M  # noqa: E402
from ta_rag import sweep as W  # noqa: E402

np = pytest.importorskip("numpy")


def vec_embed(table):
    return lambda texts: np.array([table[t] for t in texts], dtype=float)


# ------------------------------------------------------------------ evaluator

def test_lexical_f1_known_value_and_edges():
    assert E.lexical_f1("6 bulan", "paling singkat 6 bulan di Indonesia") == pytest.approx(0.5)
    assert E.lexical_f1("", "x") == 0.0 and E.lexical_f1("x", "") == 0.0 and E.lexical_f1("a", "b") == 0.0
    assert E.lexical_f1("Hari  BULAN", "bulan hari") == pytest.approx(1.0)  # urutan, huruf besar, spasi tak berpengaruh


def test_semantic_score_identical_opposite_orthogonal():
    emb = vec_embed({"a": [1, 0], "b": [1, 0], "c": [-1, 0], "d": [0, 1]})
    assert E.semantic_score("a", "b", emb) == pytest.approx(1.0)
    assert E.semantic_score("a", "c", emb) == pytest.approx(0.0)
    assert E.semantic_score("a", "d", emb) == pytest.approx(0.5)


def test_combine_rejects_bad_weight_and_missing_semantic():
    assert E.combine(0.4, None, 0.0) == pytest.approx(0.4)
    assert E.combine(0.4, 1.0, 0.5) == pytest.approx(0.7)
    with pytest.raises(ValueError):
        E.combine(0.4, None, 0.5)
    with pytest.raises(ValueError):
        E.combine(0.4, 0.5, 1.2)


def sc(L=0.9, S=0.9, nums=(), neg=False, units=()):
    return {"L": L, "S": S, "unsupported_numbers": list(nums), "neg_mismatch": neg, "unit_mismatch": list(units)}


def test_route_thresholds_and_accept_below_review_flag():
    assert E.route(sc(L=0.9), 0.0, 0.78, False)["route"] == "ACCEPT"
    assert E.route(sc(L=0.6), 0.0, 0.78, False)["route"] == "REVIEW"
    assert E.route(sc(L=0.3), 0.0, 0.78, False)["route"] == "REJECT"
    assert "ACCEPT_BELOW_REVIEW" in E.route(sc(L=0.3), 0.0, 0.2, False)["flags"]


def test_hard_fail_number_forces_reject_only_in_config_d():
    s = sc(L=0.95, S=0.95, nums=["16000"])
    assert E.route(s, 0.6, 0.78, hard_fail=True)["route"] == "REJECT"
    assert E.route(s, 0.6, 0.78, hard_fail=False)["route"] == "ACCEPT"  # mutasi: C tanpa hard-fail meloloskannya


def test_hard_fail_negation_downgrades_accept_to_review_only_above_f1_gate():
    assert E.route(sc(L=0.9, neg=True), 0.0, 0.78, True)["route"] == "REVIEW"
    assert E.route(sc(L=0.9, neg=True), 0.0, 0.78, False)["route"] == "ACCEPT"
    assert E.route(sc(L=0.6, neg=True), 0.0, 0.78, True)["route"] == "REVIEW"  # sudah REVIEW karena H, bukan karena negasi


def test_regression_rupiah_nominal_mutation_is_caught_by_score_pair():
    ev = "ditetapkan sebesar Rp8.000,00 (delapan ribu rupiah) per peserta per bulan"
    wrong = "Tarifnya Rp16.000,00 per peserta per bulan"
    s = E.score_pair(wrong, ev, None)
    assert s["unsupported_numbers"] == ["16000"]
    ok = E.score_pair("Rp8.000,00 per peserta per bulan", ev, None)
    assert ok["unsupported_numbers"] == []


def test_score_pair_without_embedder_leaves_s_none_and_semantic_route_raises():
    s = E.score_pair("6 bulan", "paling singkat 6 bulan", None)
    assert s["S"] is None
    with pytest.raises(ValueError):
        E.route(s, 0.5, 0.78, False)


def test_negation_mismatch_polarity():
    assert E.negation_mismatch("tidak wajib", "wajib") is True
    assert E.negation_mismatch("wajib", "tidak wajib") is True
    assert E.negation_mismatch("tidak wajib", "tidak wajib") is False


# ------------------------------------------------------------------ metrik

@pytest.mark.parametrize("k,n,two,hi", [(0, 10, True, 0.3085), (0, 20, True, 0.1684), (0, 10, False, 0.2589),
                                        (0, 20, False, 0.1391), (1, 10, True, 0.4450), (0, 30, True, 0.1157)])
def test_clopper_pearson_matches_published_values(k, n, two, hi):
    assert M.clopper_pearson(k, n, two_sided=two)[1] == pytest.approx(hi, abs=5e-4)


def test_clopper_pearson_lower_bound_and_edges():
    lo, hi = M.clopper_pearson(1, 10)
    assert lo == pytest.approx(0.0025, abs=5e-4)
    assert M.clopper_pearson(10, 10)[1] == 1.0
    with pytest.raises(ValueError):
        M.clopper_pearson(0, 0)
    with pytest.raises(ValueError):
        M.clopper_pearson(11, 10)


def test_rate_undefined_is_not_zero():
    r = M.rate(0, 0)
    assert r["defined"] is False and r["point"] is None and "tidak terdefinisi" in r["text"]
    assert M.rate(0, 10)["point"] == 0.0 and M.rate(0, 10)["defined"] is True


def rows(spec):
    return [{"label": l, "route": r} for l, r in spec]


def test_summarize_far_undefined_when_no_bad_answers_and_counts():
    s = M.summarize(rows([("LAYAK", "ACCEPT")] * 7 + [("LAYAK", "REVIEW")] * 2 + [("LAYAK", "REJECT")]))
    assert s["FAR"]["defined"] is False
    assert (s["CAR"]["k"], s["CAR"]["n"]) == (7, 10) and (s["false_rejection"]["k"], s["false_rejection"]["n"]) == (1, 10)
    assert s["review_rate"]["k"] == 2 and s["reject_rate"]["k"] == 1  # REVIEW dan REJECT terpisah


def test_summarize_far_numerator_denominator():
    s = M.summarize(rows([("TIDAK_LAYAK", "ACCEPT")] + [("TIDAK_LAYAK", "REJECT")] * 3 + [("LAYAK", "ACCEPT")] * 4))
    assert (s["FAR"]["k"], s["FAR"]["n"]) == (1, 4) and s["FAR"]["point"] == 0.25
    assert (s["CAR"]["k"], s["CAR"]["n"]) == (4, 4)


def test_summarize_ignores_insufficient_evidence_records():
    s = M.summarize(rows([("INSUFFICIENT_EVIDENCE", "ACCEPT"), ("LAYAK", "ACCEPT")]))
    assert s["n"] == 1


def test_percentile_nearest_rank_and_latency_stats_deterministic():
    assert M.percentile(list(range(1, 101)), 95) == 95 and M.percentile([5], 50) == 5
    xs = [float(i) for i in range(1, 121)]
    a, b = M.latency_stats(xs, n_boot=200), M.latency_stats(xs, n_boot=200)
    assert a == b and a["warning"] is None and a["p50"] == 60
    assert M.latency_stats([1.0] * 10, n_boot=50)["warning"] == "kurang dari 100 iterasi"


def test_mcnemar_exact_and_paired_diff():
    assert M.mcnemar_exact(0, 5) == pytest.approx(2 / 32)
    assert M.mcnemar_exact(3, 3) == 1.0 and M.mcnemar_exact(0, 0) == 1.0
    d = M.paired_diff([True] * 8 + [False] * 2, [True] * 5 + [False] * 5)
    assert d["diff"] == pytest.approx(0.3) and d["discordant"] == (3, 0) and d["ci95"][0] <= 0.3 <= d["ci95"][1]
    with pytest.raises(ValueError):
        M.paired_diff([True], [True, False])


# ------------------------------------------------------------------ data dua jalur

def rec(i, grp, ev=None, **kw):
    r = {"answer_id": f"A{i}", "case_id": f"R{i}", "group_id": grp, "evidence_group": ev or f"e{i}", "track": "R",
         "answer_origin": "original_llm", "answer": "x", "kind": "answerable", "label": "LAYAK", "manual_label_locked": True}
    r.update(kw)
    return r


def mut(i, src, **kw):
    r = rec(i, "g" + src[1:], ev="e" + src[1:], track="M", answer_origin="mutasi_terkontrol", label="TIDAK_LAYAK", pair_id="P1",
            mutation_family="numeric_value", anchor_page_opposite=8, mutated_from_answer_id=src)
    r.update(kw)
    return r


def test_valid_set_passes():
    rs = [rec(1, "g1"), mut(11, "A1")]
    assert D.validate_records(rs) == []


@pytest.mark.parametrize("bad,needle", [
    (rec(1, "g1", route="ACCEPT", manual_label_locked=False), "sebelum label manusia dikunci"),
    (rec(1, "g1", H=0.9, label=None, manual_label_locked=False), "sebelum label manusia dikunci"),
    (rec(1, "g1", track="M"), "berpasangan"),
    (rec(1, "g1", answer_origin="mutasi_terkontrol"), "berpasangan"),
    (rec(1, "g1", track="Z"), "track harus"),
    (rec(1, "g1", label="BENAR"), "label tidak valid"),
    (rec(1, "g1", answer=""), "field wajib kosong: answer"),
])
def test_mutation_record_schema_violations(bad, needle):
    assert any(needle in p for p in D.check_record(bad))


@pytest.mark.parametrize("field", ["pair_id", "mutation_family", "anchor_page_opposite", "mutated_from_answer_id"])
def test_mutation_requires_fields(field):
    m = mut(11, "A1"); m[field] = None
    assert any(field in p for p in D.check_record(m))


def test_mutation_label_must_be_tidak_layak_and_source_must_be_layak_original_same_group():
    assert any("TIDAK_LAYAK secara konstruksi" in p for p in D.check_record(mut(11, "A1", label="LAYAK")))
    assert any("berlabel LAYAK" in p for p in D.validate_records([rec(1, "g1", label="TIDAK_LAYAK"), mut(11, "A1")]))
    assert any("satu group_id" in p for p in D.validate_records([rec(1, "g1"), mut(11, "A1", group_id="gX")]))
    assert any("tidak ada" in p for p in D.validate_records([mut(11, "A9")]))
    assert any("ganda" in p for p in D.validate_records([rec(1, "g1"), rec(1, "g2")]))


def many(n=20):
    rs = []
    for i in range(1, n + 1):
        rs.append(rec(i, f"g{i}", label="LAYAK" if i % 5 else "TIDAK_LAYAK"))
    return rs


def test_assign_splits_deterministic_no_leak_and_proportion():
    rs = many()
    s1, s2 = D.assign_splits(rs, "S"), D.assign_splits(list(reversed(rs)), "S")
    assert s1 == s2 and D.check_split_leak(rs, s1) == []
    assert 12 <= sum(v == "validation" for v in s1.values()) <= 15
    assert D.assign_splits(rs, "S2") != s1


def test_pairs_and_shared_evidence_group_never_split():
    rs = [rec(1, "gA", ev="E1"), rec(2, "gB", ev="E1"), rec(3, "gB", ev="E2"), mut(11, "A1", group_id="gA", evidence_group="E1")] + [rec(i, f"g{i}") for i in range(20, 40)]
    s = D.assign_splits(rs, "S")
    assert len({s["A1"], s["A2"], s["A3"], s["A11"]}) == 1  # rantai gA-E1-gB-E2 + mutasi = satu komponen
    assert D.check_split_leak(rs, s) == []


def test_mutation_leak_guard_detects_manual_split_of_a_pair():
    rs = [rec(1, "g1"), mut(11, "A1")]
    leak = D.check_split_leak(rs, {"A1": "validation", "A11": "test"})
    assert any("group_id=g1" in p for p in leak) and any("evidence_group=e1" in p for p in leak)


def test_split_report_warns_when_test_has_no_bad_answers():
    rs = [rec(1, "g1"), rec(2, "g2", label="TIDAK_LAYAK")]
    rep = D.split_report(rs, {"A1": "test", "A2": "validation"})
    assert rep["test"]["warning"] and rep["validation"]["warning"] is None


# ------------------------------------------------------------------ sweep

def scored(n_good=12, n_bad=6):
    good = [{"answer_id": f"G{i}", "track": "R", "label": "LAYAK", **sc(L=0.9, S=0.92)} for i in range(n_good)]
    bad = [{"answer_id": f"B{i}", "track": "M", "label": "TIDAK_LAYAK", **sc(L=0.9, S=0.93, nums=["16000"])} for i in range(n_bad)]
    return good + bad


def test_stage_sizes_match_spec():
    s = scored()
    assert len(W.stage_a(s)) == 101 and len(W.stage_b(s)) == 101
    c = W.stage_c(s)
    assert len(c) == 60 and sum(r["config"] == "C" for r in c) == 30 and sum(r["config"] == "D" for r in c) == 30
    assert len({r["id"] for r in c}) == 60


def test_hard_fail_d_has_lower_far_than_c_on_number_mutations_and_tracks_stay_separate():
    c = W.stage_c(scored())
    assert {r["far_M"] for r in c if r["config"] == "C"} == {1.0} and {r["far_M"] for r in c if r["config"] == "D"} == {0.0}
    assert all(r["far_R"] is None and r["far_R_n"] == 0 for r in c)  # Track R tanpa TIDAK_LAYAK: tak terdefinisi, bukan 0%
    assert all(r["car_R_n"] == 12 and r["far_M_n"] == 6 for r in c)


def test_selection_uses_far_of_track_m_not_pooled_far():
    # Track R memuat satu TIDAK_LAYAK alami yang lolos semua; Track M ditahan hard-fail. FAR gabungan = 1/7 > alpha, FAR_M = 0
    s = scored() + [{"answer_id": "N0", "track": "R", "label": "TIDAK_LAYAK", **sc(L=0.9, S=0.92)}]
    out = W.select_all(W.stage_c(s), alpha=0.05)
    assert out["D*"]["selection"]["status"] == "SELECTED" and out["D*"]["params"]["hard_fail"] is True
    row = next(r for r in W.stage_c(s) if r["id"] == out["D*"]["selection"]["chosen"])
    assert row["far_R"] == 1.0 and row["far_M"] == 0.0


def test_select_all_per_config_pools_and_d_inherits_c_parameters():
    out = W.select_all(W.stage_c(scored()), alpha=0.05)
    assert list(out) == ["A", "B", "C", "D", "D*"]
    assert out["A"]["params"]["w_s"] == 0.0 and out["B"]["params"]["w_s"] == 1.0
    assert 0.0 < out["C"]["params"]["w_s"] < 1.0  # C = hybrid murni
    assert out["C"]["selection"]["status"] == "NO_ELIGIBLE_PARAMETER"  # tanpa hard-fail mutasi lolos
    c, d = out["C"]["params"], out["D"]["params"]
    assert d["hard_fail"] is True and (d["w_s"], d["accept"]) == (c["w_s"], c["accept"]) and c["hard_fail"] is False


def test_selection_no_eligible_when_alpha_unreachable():
    s = [{"answer_id": "B", "track": "M", "label": "TIDAK_LAYAK", **sc(L=0.9, S=0.9)}, {"answer_id": "G", "track": "R", "label": "LAYAK", **sc(L=0.9, S=0.9)}]
    out = W.select_all(W.stage_c(s), alpha=0.05)
    assert {k: v["selection"]["status"] for k, v in out.items()} == {k: "NO_ELIGIBLE_PARAMETER" for k in ("A", "B", "C", "D", "D*")}


def test_selection_far_undefined_without_track_m_answers():
    s = [{"answer_id": f"G{i}", "track": "R", "label": "LAYAK", **sc()} for i in range(5)]
    out = W.select_all(W.stage_c(s), alpha=0.05)
    assert all(v["selection"]["status"] == "FAR_UNDEFINED_NO_SELECTION" and v["params"] is None for v in out.values())


def test_write_csv_one_row_per_combination(tmp_path):
    p = tmp_path / "grid.csv"
    W.write_csv(W.stage_c(scored()), p)
    lines = p.read_text().splitlines()
    assert len(lines) == 61 and lines[0].startswith("id,config,w_s,accept")


def test_mutation_many_shared_evidence_groups_are_never_split():
    # 30 pasangan group_id berbeda yang berbagi evidence_group: bila union evidence_group dimatikan, hampir pasti ada yang terbelah
    rs = []
    for i in range(30):
        rs += [rec(2 * i, f"ga{i}", ev=f"E{i}"), rec(2 * i + 1, f"gb{i}", ev=f"E{i}")]
    s = D.assign_splits(rs, "S")
    assert D.check_split_leak(rs, s) == []
    assert {"validation", "test"} == set(s.values())


# ------------------------------------------------------------------ stabilitas seleksi (eksploratif pasca-test)

def unit_rows(i, n_r=1, n_m=1):
    """Satu komponen terhubung: n_r jawaban LAYAK Track R + n_m mutasi TIDAK_LAYAK Track M yang berbagi group_id/evidence_group."""
    base = {"group_id": f"g{i}", "evidence_group": f"e{i}"}
    return ([{"answer_id": f"G{i}_{j}", "track": "R", "label": "LAYAK", **base, **sc(L=0.9, S=0.92)} for j in range(n_r)]
            + [{"answer_id": f"B{i}_{j}", "track": "M", "label": "TIDAK_LAYAK", **base, **sc(L=0.9, S=0.93, nums=["16000"])} for j in range(n_m)])


def test_selection_stability_is_deterministic_and_reports_share_per_config():
    val = [r for i in range(10) for r in unit_rows(i)]
    a = W.selection_stability(val, alpha=0.05, n_boot=40, seed=7)
    assert a == W.selection_stability(val, alpha=0.05, n_boot=40, seed=7)
    assert a["n_units"] == 10 and a["n_boot"] == 40 and list(a["configs"]) == ["A", "B", "C", "D", "D*"]
    assert a["configs"]["D*"]["status_share"] == {"SELECTED": 1.0}  # hard-fail menolak semua mutasi pada setiap replikasi
    assert a["configs"]["D*"]["chosen_share"] == {"D:w0.0:t0.85": 1.0}
    assert a["configs"]["C"]["status_share"] == {"NO_ELIGIBLE_PARAMETER": 1.0}  # tanpa hard-fail, mutasi angka lolos


def test_selection_stability_resamples_connected_components_not_rows():
    # satu komponen besar (5 R + 5 M) dan satu komponen kecil (1 R). Resampling per komponen: peluang sampel tanpa mutasi = (1/2)^2 = 25%.
    # Resampling per baris akan memberi (6/11)^11 ~ 0,1%: ambang di bawah membedakan keduanya.
    val = unit_rows(0, n_r=5, n_m=5) + unit_rows(1, n_r=1, n_m=0)
    share = W.selection_stability(val, alpha=0.05, n_boot=400, seed=3)["configs"]["A"]["status_share"].get("FAR_UNDEFINED_NO_SELECTION", 0.0)
    assert 0.10 < share < 0.45


def test_alpha_sensitivity_shows_selection_changes_with_alpha():
    out = W.alpha_sensitivity(scored(), alphas=(0.05, 1.0))
    assert list(out) == ["0.05", "1.0"]
    assert out["0.05"]["C"]["status"] == "NO_ELIGIBLE_PARAMETER" and out["1.0"]["C"]["status"] == "SELECTED"
    assert out["1.0"]["C"]["far_M"].endswith("/6") and out["1.0"]["C"]["car_R"].endswith("/12")


def test_unit_fail_rejects_same_number_with_different_unit_only_when_enabled():
    s = sc(L=0.95, S=0.95, units=["3 hari"])
    assert E.route(s, 0.5, 0.78, True)["route"] == "ACCEPT"  # D tidak memeriksa satuan
    r = E.route(s, 0.5, 0.78, True, unit_fail=True)
    assert r["route"] == "REJECT" and "UNIT_MISMATCH" in r["flags"]
    assert E.route(s, 0.5, 0.78, False, unit_fail=True)["route"] == "ACCEPT"  # satuan hanya bagian dari hard-fail (E = D + satuan)
    assert E.route({k: v for k, v in s.items() if k != "unit_mismatch"}, 0.5, 0.78, True, unit_fail=True)["route"] == "ACCEPT"  # skor lama tanpa kunci


def test_score_pair_reports_unit_mismatch_with_question_and_citation_ignored():
    out = E.score_pair("Menurut Nomor 59 Tahun 2024, setelah 3 (tiga) hari", "setelah jangka waktu 3 (tiga) bulan", None)
    assert out["unit_mismatch"] == ["3 hari"] and out["unsupported_numbers"] == []


# ------------------------------------------------------------------ konfigurasi E (D + aturan satuan)

def scored_units(n_good=12, n_bad=6):
    """Mutasi satuan: angka sama dengan evidence (tak ada angka tak didukung), hanya satuannya berbeda."""
    good = [{"answer_id": f"G{i}", "track": "R", "label": "LAYAK", **sc(L=0.9, S=0.92)} for i in range(n_good)]
    bad = [{"answer_id": f"B{i}", "track": "M", "label": "TIDAK_LAYAK", **sc(L=0.9, S=0.93, units=["3 hari"])} for i in range(n_bad)]
    return good + bad


def test_route_params_applies_stored_parameters_including_unit_fail():
    s = sc(L=0.95, S=0.95, units=["3 hari"])
    d = {"w_s": 0.5, "accept": 0.78, "hard_fail": True}
    assert E.route_params(s, d)["route"] == "ACCEPT"
    assert E.route_params(s, {**d, "unit_fail": True})["route"] == "REJECT"


def test_stage_c_with_config_e_adds_30_rows_and_only_e_catches_unit_mutations():
    c = W.stage_c(scored_units(), configs=("C", "D", "E"))
    assert len(c) == 90 and sum(r["config"] == "E" for r in c) == 30 and len({r["id"] for r in c}) == 90
    assert {r["far_M"] for r in c if r["config"] == "D"} == {1.0} and {r["far_M"] for r in c if r["config"] == "E"} == {0.0}
    assert len(W.stage_c(scored_units())) == 60  # bawaan tetap C dan D (Studi 1)


def test_select_all_derives_e_from_c_parameters_only_when_e_rows_exist():
    base = W.select_all(W.stage_c(scored_units()), alpha=0.05)
    assert list(base) == ["A", "B", "C", "D", "D*"]
    out = W.select_all(W.stage_c(scored_units(), configs=("C", "D", "E")), alpha=0.05)
    assert list(out) == ["A", "B", "C", "D", "E", "D*"]
    c, e = out["C"]["params"], out["E"]["params"]
    assert e["hard_fail"] is True and e["unit_fail"] is True and (e["w_s"], e["accept"]) == (c["w_s"], c["accept"])
    assert "unit_fail" not in out["D"]["params"] and out["E"]["selection"]["status"] == out["C"]["selection"]["status"]


# ------------------------------------------------------------------ evidence Tahap II: satuan konteks terbaik

def test_evidence_units_split_lines_and_sentences_but_not_inside_rupiah_amounts():
    text = "Pasal 4\nTarif Rp3.600,00 (tiga ribu enam ratus rupiah) per bulan. Dibayar di muka; paling lambat tanggal 10.\n\n(2) Ayat dua"
    assert E.evidence_units(text) == ["Pasal 4", "Tarif Rp3.600,00 (tiga ribu enam ratus rupiah) per bulan.", "Dibayar di muka; paling lambat tanggal 10.", "(2) Ayat dua"]
    assert E.evidence_units("") == [] and E.evidence_units(None) == []


def test_best_unit_picks_highest_f1_first_on_ties_and_empty_when_no_context():
    ctx = "Hal lain yang tidak relevan.\nPeserta dapat mengganti FKTP setelah 3 bulan.\nPeserta dapat mengganti FKTP setelah 3 bulan."
    assert E.best_unit("mengganti FKTP setelah 3 bulan", ctx) == "Peserta dapat mengganti FKTP setelah 3 bulan."
    assert E.best_unit("apa saja", "") == ""
    assert E.best_unit("xx", "aa bb.\ncc dd.") == "aa bb."  # semua F1 = 0: yang pertama


def test_score_pair_support_text_governs_numbers_and_units_while_evidence_governs_lexical_and_negation():
    answer, best = "setelah 3 (tiga) hari dan Rp8.000,00", "Peserta dapat mengganti FKTP setelah 3 (tiga) bulan"
    ctx = best + "\nTarif Rp8.000,00 per peserta"
    only_best = E.score_pair(answer, best, None)
    assert only_best["unsupported_numbers"] == ["8000"] and only_best["unit_mismatch"] == ["3 hari"]
    with_ctx = E.score_pair(answer, best, None, support=ctx)
    assert with_ctx["unsupported_numbers"] == [] and with_ctx["unit_mismatch"] == ["3 hari"]  # angka didukung di konteks; satuan tetap salah
    assert with_ctx["L"] == only_best["L"]  # skor leksikal tetap terhadap satuan terbaik


# ------------------------------------------------------------------ CI bootstrap per klaster (lari berulang atas pertanyaan yang sama)

def test_cluster_bootstrap_resamples_clusters_not_records_and_is_deterministic():
    # dua klaster, masing-masing 5 record: klaster A semua 1, klaster B semua 0. Bootstrap per baris akan memberi CI sempit (~0,2-0,8);
    # per klaster, sampel bisa berisi A saja atau B saja, sehingga CI lebar penuh [0, 1]
    items = [("A", 1.0)] * 5 + [("B", 0.0)] * 5
    r = M.cluster_bootstrap_ci(items, n_boot=400, seed=1)
    assert r["point"] == 0.5 and r["lo"] == 0.0 and r["hi"] == 1.0 and r["n"] == 10 and r["n_clusters"] == 2
    assert r == M.cluster_bootstrap_ci(items, n_boot=400, seed=1)


def test_cluster_bootstrap_point_is_pooled_over_records_not_mean_of_cluster_means():
    r = M.cluster_bootstrap_ci([("A", 1.0)] * 3 + [("B", 0.0)], n_boot=50, seed=2)
    assert r["point"] == 0.75 and 0.0 <= r["lo"] <= r["point"] <= r["hi"] <= 1.0


def test_cluster_bootstrap_needs_at_least_two_clusters():
    with pytest.raises(ValueError, match="klaster"):
        M.cluster_bootstrap_ci([("A", 1.0), ("A", 0.0)])


# ------------------------------------------------------------------ rasio, ringkasan, dan hipotesis berpasangan dengan CI klaster (Studi 2)

def test_cluster_rate_undefined_single_cluster_and_wider_than_clopper_pearson_for_correlated_runs():
    assert M.cluster_rate([]) == {"k": 0, "n": 0, "point": None, "lo": None, "hi": None, "defined": False, "text": "tidak terdefinisi (n=0)"}
    one = M.cluster_rate([("A", True), ("A", False)])
    assert one["point"] == 0.5 and one["lo"] is None and one["n_clusters"] == 1 and "klaster < 2" in one["interval"]
    # 10 pertanyaan x 3 lari identik: 5 klaster kena semua, 5 luput semua. Clopper-Pearson menganggap 30 record independen, jadi terlalu sempit
    items = [(f"q{i}", i < 5) for i in range(10) for _ in range(3)]
    c, cp = M.cluster_rate(items, n_boot=400, seed=3), M.rate(15, 30)
    assert (c["k"], c["n"], c["n_clusters"], c["point"]) == (15, 30, 10, 0.5)
    assert c["hi"] - c["lo"] > cp["hi"] - cp["lo"] and c["lo"] <= 0.5 <= c["hi"]


def test_cluster_rate_replaces_a_zero_width_bootstrap_with_clopper_pearson_over_clusters():
    allhit = M.cluster_rate([(f"q{i}", True) for i in range(10) for _ in range(3)], n_boot=200, seed=1)
    assert allhit["ci_fallback"] is True and (allhit["lo"], allhit["hi"]) == M.clopper_pearson(10, 10) and allhit["lo"] < 0.75  # 30 jawaban, 10 klaster: n efektif 10, bukan 30
    assert "10 klaster" in allhit["interval"] and allhit["k"] == allhit["n"] == 30
    allmiss = M.cluster_rate([(f"q{i}", False) for i in range(10) for _ in range(3)], n_boot=200, seed=1)
    assert allmiss["ci_fallback"] is True and allmiss["lo"] == 0.0 and allmiss["hi"] == M.clopper_pearson(0, 10)[1] and allmiss["hi"] > 0.3
    mixed = M.cluster_rate([(f"q{i}", i < 5) for i in range(10) for _ in range(3)], n_boot=200, seed=1)
    assert "ci_fallback" not in mixed and mixed["interval"].startswith("bootstrap")  # CI berlebar > 0: bootstrap dipertahankan


def test_summarize_clustered_keeps_counts_and_matrix_and_uses_the_right_denominator_per_ratio():
    spec = [("LAYAK", "ACCEPT")] * 6 + [("LAYAK", "REVIEW")] * 2 + [("LAYAK", "REJECT")] * 2 + [("TIDAK_LAYAK", "ACCEPT")] + [("TIDAK_LAYAK", "REJECT")] * 3
    rs = [{"cluster": f"q{i % 7}", **r} for i, r in enumerate(rows(spec) + rows([("INSUFFICIENT_EVIDENCE", "ACCEPT")]))]
    s, base = M.summarize_clustered(rs, n_boot=100), M.summarize(rows(spec))
    got = {k: (s[k]["k"], s[k]["n"]) for k in ("CAR", "FAR", "false_rejection", "review_rate", "reject_rate")}
    assert got == {"CAR": (6, 10), "FAR": (1, 4), "false_rejection": (2, 10), "review_rate": (2, 14), "reject_rate": (5, 14)}
    assert s["confusion"] == base["confusion"] and s["n"] == 14  # INSUFFICIENT_EVIDENCE tidak ikut
    assert "bootstrap" in s["CAR"]["interval"] and s["CAR"]["n_clusters"] >= 2
    assert M.summarize_clustered(rs[:10], n_boot=50)["FAR"]["defined"] is False  # tanpa TIDAK_LAYAK: tak terdefinisi, bukan 0


def test_run_spread_gives_mean_and_range_over_defined_runs_only():
    mk = lambda car, far: {"CAR": {"defined": True, "point": car}, "FAR": {"defined": far is not None, "point": far}, "false_rejection": {"defined": True, "point": 0.0},
                           "review_rate": {"defined": True, "point": 0.2}, "reject_rate": {"defined": True, "point": 0.1}}
    sp = M.run_spread({"run1": mk(0.5, None), "run2": mk(0.7, 0.25), "run3": mk(0.9, 0.5)})
    assert sp["CAR"] == {"defined": True, "mean": pytest.approx(0.7), "min": 0.5, "max": 0.9, "n_runs": 3}
    assert sp["FAR"]["n_runs"] == 2 and sp["FAR"]["min"] == 0.25 and sp["FAR"]["max"] == 0.5  # lari tanpa FAR dilewati, bukan dihitung 0
    assert M.run_spread({"run1": mk(0.5, None)})["FAR"] == {"defined": False, "n_runs": 0}


def pairs(spec):
    """spec = [(klaster, a, b, jumlah)] -> item berpasangan."""
    return [(c, a, b) for c, a, b, n in spec for _ in range(n)]


def test_paired_cluster_diff_verdicts_follow_the_preregistered_rule_at_each_boundary():
    kw = dict(level=0.9833, min_diff=0.10, n_boot=400, seed=5)
    win = M.paired_cluster_diff(pairs([(f"q{i}", True, False, 1) for i in range(12)]), **kw)
    assert win["verdict"] == "TERDUKUNG" and win["diff"] == 1.0 and win["lo"] == 1.0 and win["discordant"] == (12, 0)
    assert win["mcnemar_p"] == pytest.approx(2 / 2**12) and win["n_clusters"] == 12 and win["degenerate"] is True  # semua klaster searah: CI berlebar nol
    lose = M.paired_cluster_diff(pairs([(f"q{i}", False, True, 1) for i in range(12)]), **kw)
    assert lose["verdict"] == "ARAH_BERLAWANAN" and lose["diff"] == -1.0 and lose["hi"] == -1.0
    assert lose["discordant"] == (0, 12) and lose["mcnemar_p"] == pytest.approx(2 / 2**12)  # b dan c tidak tertukar
    # selisih tepat 10 poin tetapi satu dari sepuluh klaster: CI memuat 0 -> bukan bukti
    thin = M.paired_cluster_diff(pairs([("q0", True, False, 1)] + [(f"q{i}", True, True, 1) for i in range(1, 10)]), **kw)
    assert thin["diff"] == pytest.approx(0.1) and thin["lo"] == 0.0 and thin["verdict"] == "TIDAK_ADA_BUKTI_PERBEDAAN"
    thin_neg = M.paired_cluster_diff(pairs([("q0", False, True, 1)] + [(f"q{i}", True, True, 1) for i in range(1, 10)]), **kw)
    assert thin_neg["diff"] == pytest.approx(-0.1) and thin_neg["hi"] == 0.0 and thin_neg["verdict"] == "TIDAK_ADA_BUKTI_PERBEDAAN"
    # CI > 0 tetapi selisih 5 poin < 10 poin: signifikan namun tidak bermakna secara praktis
    small = M.paired_cluster_diff(pairs([(f"q{i}", a, b, n) for i in range(40) for a, b, n in ((True, False, 1), (True, True, 19))]), **kw)
    assert small["lo"] > 0 and small["diff"] == pytest.approx(0.05) and small["verdict"] == "TIDAK_ADA_BUKTI_PERBEDAAN"
    # tepat di batas 10 poin dengan CI > 0 (semua klaster identik) -> terdukung
    edge = M.paired_cluster_diff(pairs([(f"q{i}", a, b, n) for i in range(20) for a, b, n in ((True, False, 1), (True, True, 9))]), **kw)
    assert edge["diff"] == 0.1 and edge["lo"] > 0 and edge["verdict"] == "TERDUKUNG"
    # sisi berlawanan memakai ambang yang sama: -5 poin dengan CI < 0 bukan temuan; tepat -10 poin dengan CI < 0 adalah temuan
    small_neg = M.paired_cluster_diff(pairs([(f"q{i}", a, b, n) for i in range(40) for a, b, n in ((False, True, 1), (True, True, 19))]), **kw)
    assert small_neg["hi"] < 0 and small_neg["diff"] == pytest.approx(-0.05) and small_neg["verdict"] == "TIDAK_ADA_BUKTI_PERBEDAAN"
    edge_neg = M.paired_cluster_diff(pairs([(f"q{i}", a, b, n) for i in range(20) for a, b, n in ((False, True, 1), (True, True, 9))]), **kw)
    assert edge_neg["diff"] == -0.1 and edge_neg["hi"] < 0 and edge_neg["verdict"] == "ARAH_BERLAWANAN"


def test_paired_cluster_diff_edges_and_level_widens_interval():
    assert M.paired_cluster_diff([], 0.98, 0.1)["verdict"] == "TIDAK_TERDEFINISI"
    one = M.paired_cluster_diff(pairs([("q0", True, False, 3)]), 0.98, 0.1)
    assert one["verdict"] == "CI_TIDAK_DAPAT_DIHITUNG" and one["lo"] is None and one["diff"] == 1.0
    mixed = pairs([(f"q{i}", True, False, 1) for i in range(8)] + [(f"q{i}", True, True, 1) for i in range(8, 14)] + [("q14", False, True, 1)])
    wide, narrow = M.paired_cluster_diff(mixed, 0.99, 0.1, n_boot=400, seed=7), M.paired_cluster_diff(mixed, 0.80, 0.1, n_boot=400, seed=7)
    assert wide["lo"] <= narrow["lo"] and wide["hi"] >= narrow["hi"] and (wide["lo"], wide["hi"]) != (narrow["lo"], narrow["hi"])
    assert wide["discordant"] == (8, 1) and wide["mcnemar_p"] == M.mcnemar_exact(8, 1) and wide["degenerate"] is False


# ------------------------------------------------------------------ konfigurasi F (BERTScore F1 sebagai evaluator terpilih)

def test_route_bert_uses_threshold_with_preregistered_review_offset_and_route_params_dispatches_on_config_f():
    assert E.BERT_REVIEW_OFFSET == 0.10
    assert E.route_bert(0.80, 0.78)["route"] == "ACCEPT" and E.route_bert(0.78, 0.78)["route"] == "ACCEPT"
    assert E.route_bert(0.70, 0.78)["route"] == "REVIEW" and E.route_bert(0.68, 0.78)["route"] == "REVIEW"  # t - 0,10
    assert E.route_bert(0.67, 0.78)["route"] == "REJECT"
    p = {"label": "F", "config": "F", "w_s": 0.0, "accept": 0.78, "hard_fail": False}
    r = E.route_params({"bert_f1": 0.7, "L": 0.0, "S": 0.0}, p)
    assert r["route"] == "REVIEW" and r["H"] == 0.7  # skor L/S/hard-fail tidak dipakai konfigurasi F


def scored_bert(n_good=12, n_bad=6, bad_f1=0.70):
    """Skor BERTScore: jawaban LAYAK 0,85; mutasi bad_f1 (0,70 = terbedakan; 0,85 = tak terbedakan)."""
    good = [{"answer_id": f"G{i}", "track": "R", "label": "LAYAK", "bert_f1": 0.85, **sc()} for i in range(n_good)]
    bad = [{"answer_id": f"B{i}", "track": "M", "label": "TIDAK_LAYAK", "bert_f1": bad_f1, **sc()} for i in range(n_bad)]
    return good + bad


def test_stage_f_has_one_row_per_threshold_with_tracks_separate_and_threshold_semantics():
    f = W.stage_f(scored_bert())
    assert len(f) == len(W.F_T_GRID) and all(r["config"] == "F" for r in f) and len({r["id"] for r in f}) == len(f)
    by_t = {r["accept"]: r for r in f}
    assert by_t[0.80]["car_R"] == 1.0 and by_t[0.80]["far_M"] == 0.0  # 0,85 >= 0,80 diterima; 0,70 < 0,80 ditahan
    assert by_t[0.60]["far_M"] == 1.0 and by_t[0.90]["car_R"] == 0.0
    assert all(r["far_R"] is None and r["far_R_n"] == 0 for r in f)  # Track R tanpa TIDAK_LAYAK: tak terdefinisi


def test_select_all_selects_f_only_when_grid_has_f_rows_and_reports_no_eligible_when_indistinguishable():
    base = W.select_all(W.stage_c(scored()), alpha=0.05)
    assert "F" not in base
    out = W.select_all(W.stage_c(scored_bert()) + W.stage_f(scored_bert()), alpha=0.05)
    assert list(out) == ["A", "B", "C", "D", "F", "D*"]
    # CAR = 1 dan FAR = 0 untuk semua ambang di (0,70; 0,85]; tie-break pra-registrasi memilih ambang TERBESAR
    assert out["F"]["selection"]["status"] == "SELECTED" and out["F"]["params"]["config"] == "F" and out["F"]["params"]["accept"] == 0.85
    assert out["F"]["params"]["hard_fail"] is False
    # skor mutasi = skor jawaban benar: hanya ambang di atas 0,85 yang menahan mutasi, dan itu menahan semua jawaban benar juga
    same = W.select_all(W.stage_f(scored_bert(bad_f1=0.85)), alpha=0.05)
    assert same["F"]["selection"]["status"] == "SELECTED" and same["F"]["selection"]["warning"].startswith("CAR_ZERO_DEGENERATE")
