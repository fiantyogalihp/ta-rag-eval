"""Uji KODE protokol pra-registrasi. Data sintetis; tidak ada data penelitian."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ta_rag import protocol as P  # noqa: E402

SEED = "TA-RAG-TRACKM-v1-20261104"
DOCS = ["pm28", "bpjs3", "kep", "p59", "pm3"]


def cands(n_per_doc=(3, 3, 3, 4, 3)):
    out, i = [], 1
    for d, n in zip(DOCS, n_per_doc):
        for _ in range(n):
            out.append({"case_id": f"R{i:02d}", "source_doc_id": d})
            i += 1
    return out


# ------------------------------------------------------------------ Track M

def test_track_m_order_is_deterministic_and_input_order_independent():
    a = P.track_m_order(cands(), SEED)
    b = P.track_m_order(list(reversed(cands())), SEED)
    assert a == b
    assert sorted(a) == sorted(c["case_id"] for c in cands())


def test_track_m_order_first_phase_covers_every_document():
    order = P.track_m_order(cands(), SEED)
    by_doc = {c["case_id"]: c["source_doc_id"] for c in cands()}
    assert {by_doc[i] for i in order[:5]} == set(DOCS)


def test_track_m_order_changes_with_seed_and_ignores_extra_fields():
    base = P.track_m_order(cands(), SEED)
    assert P.track_m_order(cands(), SEED + "x") != base
    noisy = [{**c, "evaluator_score": 0.99 - i / 100} for i, c in enumerate(cands())]
    assert P.track_m_order(noisy, SEED) == base


def test_track_m_order_rejects_duplicate_case_id():
    with pytest.raises(ValueError):
        P.track_m_order(cands() + [{"case_id": "R01", "source_doc_id": "pm3"}], SEED)


def test_track_m_order_fewer_than_ten_returns_all_no_substitution():
    out = P.track_m_order(cands((1, 1, 1, 1, 1)), SEED)
    assert len(out) == 5


def test_track_m_order_is_pinned_so_nobody_can_reseed_silently():
    # nilai ini membeku bersama protocol.json; mengubah seed/algoritma harus mengubah tes ini secara sadar
    proto = P.load_protocol(REPO / "tests" / "fixtures" / "studi1" / "protocol.json")  # fixture Studi 1: seed Studi 2 berbeda
    assert proto["track_m"]["seed"] == SEED
    # nilai hash diverifikasi terpisah dengan `printf ... | sha256sum`
    assert P._key(SEED, "R01") == "130b74a8bebcc21b27dd39a31cf9ed4b77f290626bdbf92ebe1eb13e52a2b03b"
    assert P.track_m_order(cands(), SEED) == ["R06", "R07", "R10", "R01", "R15", "R02", "R03", "R13", "R11", "R04", "R05", "R14", "R16", "R08", "R09", "R12"]


# ------------------------------------------------------------------ verifikasi mutasi

ANCHOR = "Peserta dapat mengganti FKTP setelah jangka waktu 3 (tiga) bulan sejak terdaftar."


def test_mutation_numeric_ok_and_single_block():
    assert P.verify_mutation("Jangka waktunya 3 (tiga) bulan.", "Jangka waktunya 6 (enam) bulan.", "numeric_value", ANCHOR) == []


def test_mutation_numeric_value_on_anchor_page_is_flagged():
    probs = P.verify_mutation("Jangka waktunya 3 bulan.", "Jangka waktunya 6 bulan.", "numeric_value", ANCHOR + " Enam 6 hal lain.")
    assert any("muncul di halaman jangkar" in p for p in probs)


def test_mutation_two_separate_changes_is_flagged():
    probs = P.verify_mutation("Minimal 2 hari sejak 9 Januari 2023.", "Minimal 4 hari sejak 9 Januari 2024.", "numeric_value", "")
    assert any("satu blok" in p for p in probs)


def test_mutation_unchanged_is_flagged():
    assert P.verify_mutation("a 3 b", "a 3 b", "numeric_value", "") == ["mutasi tidak mengubah apa pun"]


def test_mutation_unit_family_requires_unit_change_and_same_numbers():
    assert P.verify_mutation("Paling lambat 3 bulan.", "Paling lambat 3 hari.", "unit", ANCHOR) == []
    assert any("tidak boleh mengubah angka" in p for p in P.verify_mutation("3 bulan", "6 hari", "unit", ""))
    assert any("tidak berubah" in p for p in P.verify_mutation("3 bulan lagi", "3 bulan lalu", "unit", ""))


def test_mutation_unknown_family():
    assert P.verify_mutation("a", "b", "ngawur", "")[0].startswith("family tidak dikenal")


def test_mutation_rupiah_format_is_not_confused_by_thousands_separator():
    # regresi cacat regex lama: 'Rp8.000,00' vs 'Rp16.000,00' harus terbaca sebagai angka BERBEDA
    assert P.verify_mutation("Rp8.000,00 per peserta", "Rp16.000,00 per peserta", "numeric_value", "Rp8.000,00 per peserta") == []


@pytest.mark.parametrize("mark", ["", "**", "`"])
def test_mutation_number_and_parenthesized_words_count_as_one_block(mark):
    original = f"Tarif {mark}Rp3.600,00 (tiga ribu enam ratus rupiah){mark} per bulan."
    mutated = f"Tarif {mark}Rp7.200,00 (tujuh ribu dua ratus rupiah){mark} per bulan."
    assert P.verify_mutation(original, mutated, "numeric_value", original) == []


@pytest.mark.parametrize("original,mutated", [
    ("Tarif Rp3.600,00 (tiga ribu enam ratus rupiah) per bulan.",
     "Tarif Rp7.200,00 (tujuh ribu dua ratus rupiah) per tahun."),
    ("Biaya 3 (tiga) rupiah dan 5 (lima) rupiah.",
     "Biaya 6 (enam) rupiah dan 10 (sepuluh) rupiah."),
    ("Tarif 3600 (untuk pasien rawat inap) berlaku.",
     "Tarif 7200 (untuk peserta rawat inap) berlaku.")
])
def test_mutation_numeric_group_does_not_hide_separate_or_non_numeric_changes(original, mutated):
    assert any("satu blok" in p for p in P.verify_mutation(original, mutated, "numeric_value", ""))


def test_mutation_numeric_group_still_rejects_new_value_on_anchor():
    original = "Tarif Rp3.600,00 (tiga ribu enam ratus rupiah) per bulan."
    mutated = "Tarif Rp7.200,00 (tujuh ribu dua ratus rupiah) per bulan."
    assert any("muncul di halaman jangkar" in p for p in P.verify_mutation(
        original, mutated, "numeric_value", original + " Tarif lain Rp7.200,00."))


# ------------------------------------------------------------------ relabel

def answers():
    items = []
    for i in range(1, 17):
        items.append({"answer_id": f"A{i:02d}", "origin": "natural", "kind": "answerable", "label": "LAYAK"})
    for i in range(17, 21):
        items.append({"answer_id": f"A{i:02d}", "origin": "natural", "kind": "not_in_corpus", "label": "LAYAK"})
    for i in range(1, 11):
        items.append({"answer_id": f"M{i:02d}", "origin": "mutation", "kind": "answerable", "label": "TIDAK_LAYAK"})
    items[3]["label"] = "TIDAK_LAYAK"
    items[9]["label"] = "TIDAK_LAYAK"
    return items


MIN = {"mutation": 2, "probe": 2, "natural_tidak_layak": 2}


def test_relabel_sample_size_composition_and_determinism():
    s1 = P.relabel_sample(answers(), 8, "S", MIN)
    s2 = P.relabel_sample(list(reversed(answers())), 8, "S", MIN)
    assert s1 == s2
    assert len(s1["answer_ids"]) == 8 == len(set(s1["answer_ids"]))
    comp = s1["composition"]
    assert comp["mutation"] >= 2 and comp["probe"] >= 2 and comp["natural_tidak_layak"] >= 2
    assert sum(comp.values()) == 8


def test_relabel_sample_when_no_natural_bad_answers_records_shortfall():
    items = [{**a, "label": "LAYAK"} if a["origin"] == "natural" else a for a in answers()]
    s = P.relabel_sample(items, 8, "S", MIN)
    assert s["strata_short"] == {"natural_tidak_layak": 2}
    assert len(s["answer_ids"]) == 8


def test_relabel_sample_rejects_too_large_n_and_duplicate_ids():
    with pytest.raises(ValueError):
        P.relabel_sample(answers()[:5], 8, "S", MIN)
    with pytest.raises(ValueError):
        P.relabel_sample(answers() + [answers()[0]], 8, "S", MIN)


# ------------------------------------------------------------------ kesepakatan

def test_agreement_all_same_labels_kappa_undefined_not_zero():
    a = P.agreement([(f"A{i}", "LAYAK", "LAYAK") for i in range(6)])
    assert a["pct"] == 100.0 and a["kappa"] is None and "tidak terdefinisi" in a["kappa_note"]


def test_agreement_five_layak_one_tidak_relabeled_all_layak_shows_pct_and_zero_kappa():
    pairs = [(f"A{i}", "LAYAK", "LAYAK") for i in range(5)] + [("A5", "TIDAK_LAYAK", "LAYAK")]
    a = P.agreement(pairs)
    assert a["pct"] == 83.3 and a["kappa"] == 0.0
    assert a["discrepancies"] == [{"answer_id": "A5", "label1": "TIDAK_LAYAK", "label2": "LAYAK"}]


def test_agreement_known_kappa_value():
    pairs = [("1", "LAYAK", "LAYAK")] * 4 + [("2", "TIDAK_LAYAK", "TIDAK_LAYAK")] * 2 + [("3", "LAYAK", "TIDAK_LAYAK")] + [("4", "TIDAK_LAYAK", "LAYAK")]
    a = P.agreement(pairs)
    # po=6/8=.75; p1(L)=5/8,p2(L)=5/8,p1(T)=3/8,p2(T)=3/8 -> pe=.390625+.140625=.53125; kappa=(.75-.53125)/.46875=.4667
    assert a["kappa"] == pytest.approx(0.4667, abs=1e-4)


def test_agreement_empty():
    assert P.agreement([])["pct"] is None


# ------------------------------------------------------------------ pemilihan parameter

def row(i, far, car, rev=0.1, p95=10.0, w=0.5, acc=0.78):
    return {"id": i, "far": far, "car": car, "review_rate": rev, "p95_ms": p95, "w_s": w, "accept": acc}


def test_selection_r1_highest_car_among_far_within_alpha():
    r = P.select_parameters([row("a", 0.0, 0.7), row("b", 0.04, 0.9), row("c", 0.20, 1.0)])
    assert r == {"status": "SELECTED", "rule": "R1", "chosen": "b"}


def test_selection_tie_chain_review_then_latency_then_ws_then_threshold():
    rows = [row("a", 0.0, 0.9, rev=0.2), row("b", 0.0, 0.9, rev=0.1, p95=20), row("c", 0.0, 0.9, rev=0.1, p95=10, w=0.6)]
    assert P.select_parameters(rows)["chosen"] == "c"
    # latency dalam 10% dianggap seri -> w_s lebih kecil menang
    rows = [row("a", 0.0, 0.9, p95=10.0, w=0.6), row("b", 0.0, 0.9, p95=10.9, w=0.4)]
    assert P.select_parameters(rows)["chosen"] == "b"
    # seri penuh -> ACCEPT threshold lebih besar
    rows = [row("a", 0.0, 0.9, acc=0.75), row("b", 0.0, 0.9, acc=0.85)]
    assert P.select_parameters(rows)["chosen"] == "b"


def test_selection_no_eligible_reports_finding_and_does_not_loosen_alpha():
    r = P.select_parameters([row("a", 0.10, 0.9), row("b", 0.30, 1.0)], alpha=0.05)
    assert r["status"] == "NO_ELIGIBLE_PARAMETER" and r["rule"] == "R2" and r["chosen"] == "a"


def test_selection_far_undefined_everywhere_means_no_selection():
    r = P.select_parameters([row("a", None, 0.9), row("b", None, 1.0)])
    assert r["status"] == "FAR_UNDEFINED_NO_SELECTION" and r["chosen"] is None


def test_selection_undefined_far_rows_are_never_eligible():
    r = P.select_parameters([row("a", None, 1.0), row("b", 0.0, 0.5)])
    assert r["chosen"] == "b"


# ------------------------------------------------------------------ ringkasan + kunci

def test_pre_evaluator_summary_flags_undefined_far_and_has_no_scores():
    labels = [{"origin": "natural", "question_type": "numeric_date", "label": "LAYAK"},
              {"origin": "natural", "question_type": "numeric_money", "label": "LAYAK"}]
    rel = P.agreement([("A1", "LAYAK", "LAYAK")] * 6)
    md = P.pre_evaluator_summary(labels, [{"case_id": "R05", "family": "numeric_value", "anchor_page_opposite": 8}],
                                 [{"case_id": "R14", "reason": "angka kunci tidak ada"}], rel, [])
    assert "tidak terdefinisi (n=0" in md and "R05" in md and "tidak terdefinisi" in md.split("Kappa")[1]
    assert "skor" not in md.lower().replace("tidak memuat skor", "")


def test_pre_evaluator_summary_lists_label_counts_per_run_only_when_labels_have_run_id():
    mk = lambda run, label: {"origin": "natural", "question_type": "numeric_money", "label": label, **({"run_id": run} if run else {})}
    rel = P.agreement([("A1", "LAYAK", "LAYAK")] * 6)
    labels = [mk("run1", "LAYAK")] * 3 + [mk("run1", "TIDAK_LAYAK")] + [mk("run2", "LAYAK")] * 2 + [mk("run3", "TIDAK_LAYAK")] * 2
    md = P.pre_evaluator_summary(labels, [], [], rel, [])
    assert "| lari | n LAYAK | n TIDAK_LAYAK |" in md and "| run1 | 3 | 1 |" in md and "| run2 | 2 | 0 |" in md and "| run3 | 0 | 2 |" in md and "skor" not in md.lower()
    assert md.index("Per lari") < md.index("## 2. Track M")  # tabel per lari ada di bagian distribusi label, sebelum Track M
    assert "| run2 | 1 | 0 |" in P.pre_evaluator_summary([mk("run1", "LAYAK"), mk("run2", "LAYAK")], [], [], rel, [])  # dua lari sudah cukup untuk tabel
    for one in ([mk(None, "LAYAK")], [mk("run1", "LAYAK"), mk("run1", "TIDAK_LAYAK")]):  # tanpa run_id, atau satu lari saja (label Studi 1 memuat run1)
        assert "Per lari" not in P.pre_evaluator_summary(one, [], [], rel, [])  # Studi 1: keluaran tidak berubah


def test_pre_evaluator_summary_adds_natural_only_and_stratum_lines_only_when_the_relabel_result_has_them():
    old = P.agreement([(f"A{i}", "LAYAK", "LAYAK") for i in range(5)] + [("A5", "TIDAK_LAYAK", "LAYAK")])  # hasil lama: tanpa natural_only/by_stratum
    section = lambda md: md.split("## 3. Relabel intra-rater\n\n")[1].split("\n\n## 4.")[0]
    md_old = P.pre_evaluator_summary([], [], [], old, [])
    assert section(md_old) == ("Kesepakatan 5/6 = 83.3%.\nKappa: 0.0 (dilaporkan hanya sebagai pelengkap persentase kesepakatan; n kecil).\n"
                               "- selisih A5: TIDAK_LAYAK → LAYAK")  # keluaran Studi 1 tidak berubah
    strata = {"natural_answerable": {"n": 4, "agree": 3, "pct": 75.0}, "mutation": {"n": 2, "agree": 2, "pct": 100.0}, "probe": {"n": 2, "agree": 2, "pct": 100.0}}
    new = {**old, "natural_only": {"n": 6, "agree": 5, "pct": 83.3, "kappa": 0.0, "kappa_note": "n kecil"}, "by_stratum": strata}  # urutan kunci sengaja diacak
    lines = ["Tanpa mutasi (jawaban asli saja): 5/6 = 83.3%.", "- mutation: 2/2 = 100.0%", "- probe: 2/2 = 100.0%", "- natural_answerable: 3/4 = 75.0%"]
    md_new = P.pre_evaluator_summary([], [], [], new, [])
    assert section(md_new) == section(md_old) + "\n\n" + "\n".join(lines)  # baris lama utuh dan berurutan; baris baru hanya ditambahkan, urutan stratum tetap
    assert md_new == md_old.replace("\n\n## 4.", "\n\n" + "\n".join(lines) + "\n\n## 4.", 1) and "skor" not in md_new.lower()
    only_nat = P.pre_evaluator_summary([], [], [], {**old, "natural_only": new["natural_only"]}, [])
    only_strata = P.pre_evaluator_summary([], [], [], {**old, "by_stratum": {"probe": strata["probe"]}}, [])
    assert section(only_nat) == section(md_old) + "\n\n" + lines[0] and section(only_strata) == section(md_old) + "\n\n- probe: 2/2 = 100.0%"
    assert P.pre_evaluator_summary([], [], [], {**old, "natural_only": {"n": 0, "agree": 0, "pct": None}, "by_stratum": {}}, []) == md_old  # tanpa jawaban asli: tak ada baris "None%"


def test_lock_records_hash_and_is_sensitive_to_content(tmp_path):
    p = tmp_path / "protocol.json"
    p.write_text(json.dumps({"version": "1.0", "status": "DRAFT_UNLOCKED"}), encoding="utf-8")
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    r1 = P.lock(p, now)
    p.write_text(json.dumps({"version": "1.0", "status": "DRAFT_UNLOCKED", "x": 1}), encoding="utf-8")
    r2 = P.lock(p, now)
    assert r1["protocol_sha256"] != r2["protocol_sha256"]
    assert (tmp_path / "protocol.lock.json").exists()


# ------------------------------------------------------------------ konsistensi protocol.json dengan kode/spec

FIX = REPO / "tests" / "fixtures" / "studi1"


def test_active_protocol_has_required_sections_and_known_status():
    """Konfigurasi AKTIF (Studi 1 di main, Studi 2 di cabangnya): bagian wajib tidak boleh hilang."""
    proto = P.load_protocol()
    assert {"label_rubric", "track_m", "relabel", "selection", "split", "determinism", "claim_prefix", "test_policy", "intervals"} <= set(proto)
    assert proto["status"] in ("DRAFT_UNLOCKED", "LOCKED") and proto["selection"]["alpha"] > 0
    assert proto["determinism"]["generator_runs"]["k"] >= 1 and proto["test_policy"]["runs_allowed"] == 1


def test_study1_protocol_fixture_is_consistent_with_code():
    proto = P.load_protocol(FIX / "protocol.json")
    assert proto["status"] in ("DRAFT_UNLOCKED", "LOCKED")
    gr = proto["determinism"]["generator_runs"]
    assert gr["k"] == 1 and gr["primary_run"] == 1 and "dilepas" in gr["released_runs"]  # D15
    fams = {f for fl in proto["track_m"]["mutation"]["families_by_question_type"].values() for f in fl}
    assert fams <= set(P.FAMILIES)
    assert proto["relabel"]["n_sample"] >= proto["relabel"]["minimum_n"] >= 6
    assert proto["track_m"]["n_pairs"] is None  # D13: semua kandidat LAYAK
    assert sum(proto["relabel"]["strata_min"].values()) <= proto["relabel"]["n_sample"]
    qtypes = {json.loads(l)["question_type"] for l in (FIX / "questions_draft.jsonl").read_text().splitlines() if l.strip()}
    covered = set(proto["track_m"]["mutation"]["families_by_question_type"])
    assert {q for q in qtypes if q != "not_in_corpus"} <= covered, "ada question_type tanpa aturan mutasi"


# ------------------------------------------------------------------ k run generator

def test_generator_run_count_matches_protocol():
    proto = P.load_protocol()
    generator = json.loads((REPO / "config/generator.json").read_text())
    assert generator["runs"] == proto["determinism"]["generator_runs"]["k"]


def test_answer_key_ignores_case_spacing_and_edge_punctuation():
    assert P.answer_key("  Minimal 2 (dua)  hari. ") == P.answer_key("minimal 2 (dua) hari")
    assert P.answer_key("Minimal 2 hari") != P.answer_key("Minimal 3 hari")


def test_distinct_answers_identical_runs_need_no_extra_labels():
    runs = {"r1": {"R01": "6 bulan.", "R02": "3 bulan"}, "r2": {"R01": "6 bulan", "R02": "3 bulan."}, "r3": {"R01": "6 BULAN.", "R02": "3 bulan"}}
    d = P.distinct_answers(runs)
    assert d["need_label"] == [] and d["cases_with_variation"] == []


def test_distinct_answers_flags_only_answers_that_differ_from_primary():
    runs = {"r1": {"R01": "6 bulan."}, "r2": {"R01": "Enam bulan."}, "r3": {"R01": "enam bulan"}}
    d = P.distinct_answers(runs)
    assert d["cases_with_variation"] == ["R01"] and d["distinct_per_case"] == {"R01": 2}
    assert d["need_label"] == [{"case_id": "R01", "runs": ["r2", "r3"], "answer": "Enam bulan."}]


def test_distinct_answers_rejects_incomplete_or_empty_runs():
    with pytest.raises(ValueError):
        P.distinct_answers({"r1": {"R01": "a", "R02": "b"}, "r2": {"R01": "a"}})
    with pytest.raises(ValueError):
        P.distinct_answers({})


# ------------------------------------------------------------------ D13: family mutasi ditetapkan deterministik

FAM = {"numeric_duration": ["numeric_value", "unit"], "numeric_date": ["date"], "numeric_money": ["numeric_value"],
       "definition": ["negation", "clause_deletion"]}


def test_assign_mutation_families_alternates_duration_in_sheet_order_and_uses_first_family_otherwise():
    ordered = [{"case_id": "a", "question_type": "numeric_duration"}, {"case_id": "b", "question_type": "numeric_date"},
               {"case_id": "c", "question_type": "numeric_duration"}, {"case_id": "d", "question_type": "definition"},
               {"case_id": "e", "question_type": "numeric_duration"}, {"case_id": "f", "question_type": "numeric_money"}]
    got = P.assign_mutation_families(ordered, FAM)
    assert got == {"a": "numeric_value", "b": "date", "c": "unit", "d": "negation", "e": "numeric_value", "f": "numeric_value"}


def test_assign_mutation_families_depends_only_on_order_not_on_input_dict_ordering_or_extra_keys():
    ordered = [{"case_id": "x", "question_type": "numeric_duration", "note": 1}, {"case_id": "y", "question_type": "numeric_duration"}]
    assert P.assign_mutation_families(ordered, FAM) == {"x": "numeric_value", "y": "unit"}
    assert P.assign_mutation_families(list(reversed(ordered)), FAM) == {"y": "numeric_value", "x": "unit"}  # urutan lembar menentukan
    with pytest.raises(KeyError):
        P.assign_mutation_families([{"case_id": "z", "question_type": "tak_dikenal"}], FAM)


# ------------------------------------------------------------------ mutasi lebih dari satu per jawaban (Studi 2, D20)

def test_assign_mutation_slots_uses_first_k_families_per_type_and_rejects_too_few():
    fam = {"numeric_duration": ["numeric_value", "unit"], "definition": ["negation", "clause_deletion"], "numeric_count": ["numeric_value"]}
    ordered = [{"case_id": "A", "question_type": "numeric_duration"}, {"case_id": "B", "question_type": "definition"}]
    assert P.assign_mutation_slots(ordered, fam, 2) == {"A": ["numeric_value", "unit"], "B": ["negation", "clause_deletion"]}
    assert P.assign_mutation_slots(ordered, fam, 1) == {"A": ["numeric_value"], "B": ["negation"]}
    with pytest.raises(ValueError, match="numeric_count"):
        P.assign_mutation_slots([{"case_id": "C", "question_type": "numeric_count"}], fam, 2)
