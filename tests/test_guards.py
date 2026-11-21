"""Uji penjaga data asli. Berkas di sini sengaja dibuat tangan untuk memicu penolakan; ini menguji PENOLAKAN, bukan hasil penelitian."""

from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

import test_labeling as TL
from ta_rag import capture, guards, labeling

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "reducto_perpres_59_2024_r1_ui_export.json"
DOC = "perpres_59_2024_perubahan_ketiga_jaminan_kesehatan"


def sha(p: Path) -> str:
    return guards._sha256(p)


@pytest.fixture
def repo(tmp_path):
    for d in ("config", "data/reducto/raw", "data/reducto/manifests", "data/cases", "data/runs", "data/labels", "data/index"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "config" / "corpus.json", tmp_path / "config" / "corpus.json")
    shutil.copy(REPO / "tests" / "fixtures" / "studi1" / "protocol.json", tmp_path / "config" / "protocol.json")
    generator = json.loads((REPO / "config" / "generator.json").read_text())
    generator["status"] = "DRAFT_UNFROZEN"
    (tmp_path / "config" / "generator.json").write_text(json.dumps(generator))
    shutil.copy(REPO / "tests" / "fixtures" / "studi1" / "questions_draft.jsonl", tmp_path / "data" / "cases" / "questions_draft.jsonl")
    return tmp_path


def corpus_doc(repo: Path) -> dict:
    return next(d for d in json.loads((repo / "config" / "corpus.json").read_text())["documents"] if d["doc_id"] == DOC)


def write_parsed(repo: Path, **over) -> Path:
    """Satu dokumen terparsing lengkap dengan manifest yang konsisten (tangan; menguji logika penjaga)."""
    raw = repo / "data" / "reducto" / "raw" / f"{DOC}__reducto-r-1.json"
    shutil.copy(FIXTURE, raw)
    man = {"doc_id": DOC, "provider": "reducto", "status": "TECH_QA_PASS", "source_pdf_sha256": corpus_doc(repo)["sha256"],
           "job": {"job_id": "job-123"}, "technical_qa": {"models_observed": ["r-1"]}, "files": {"raw_json_sha256": sha(raw)},
           "human_fidelity_qa": {"status": "PASS", "reviewer": "Galih", "reviewed_at": "2026-11-05T10:00:00+07:00", "notes": None}}
    man.update(over)
    mp = repo / "data" / "reducto" / "manifests" / f"{DOC}__reducto-r-1.manifest.json"
    mp.write_text(json.dumps(man))
    return mp


# ------------------------------------------------------------------ parsing

def test_ui_export_copied_into_raw_without_manifest_is_rejected(repo):
    shutil.copy(FIXTURE, repo / "data" / "reducto" / "raw" / f"{DOC}__reducto-r-1.json")
    probs = guards.g_reducto_provenance(repo)
    assert any("tidak ada manifest" in p for p in probs)
    write_parsed(repo)  # ada satu manifest sah
    shutil.copy(FIXTURE, repo / "data" / "reducto" / "raw" / "dokumen_lain__reducto-r-1.json")
    assert any("RAW_TANPA_MANIFEST: dokumen_lain" in p for p in guards.g_reducto_provenance(repo))


def test_good_parse_passes_and_each_defect_is_caught(repo):
    write_parsed(repo)
    assert guards.g_reducto_provenance(repo) == []
    cases = [({"job": {"job_id": ""}}, "job_id kosong"), ({"provider": "lain"}, "provider"),
             ({"technical_qa": {"models_observed": ["legacy"]}}, "model teramati"), ({"source_pdf_sha256": "0" * 64}, "tidak cocok dengan PDF"),
             ({"status": "PARSE_FAILED"}, "status manifest")]
    for over, needle in cases:
        write_parsed(repo, **over)
        assert any(needle in p for p in guards.g_reducto_provenance(repo)), needle
    write_parsed(repo)
    (repo / "data" / "reducto" / "raw" / f"{DOC}__reducto-r-1.json").write_text("{}")  # diubah setelah parsing
    assert any("SHA256 raw tidak cocok" in p for p in guards.g_reducto_provenance(repo))


def test_human_qa_must_be_pass_with_reviewer_and_date(repo):
    write_parsed(repo)
    probs = guards.g_parse_human_qa(repo)
    # dokumen sumber bukti lain tidak punya manifest -> dilaporkan
    assert any("manifest tidak ada" in p for p in probs) and not any(DOC in p and "harus status" in p for p in probs)
    for bad in ({"status": "NOT_DONE", "reviewer": None, "reviewed_at": None}, {"status": "FAIL", "reviewer": "G", "reviewed_at": "x"},
                {"status": "PASS", "reviewer": "", "reviewed_at": "x"}, {"status": "PASS", "reviewer": "G", "reviewed_at": None}):
        write_parsed(repo, human_fidelity_qa=bad)
        assert any(DOC in p and "harus status" in p for p in guards.g_parse_human_qa(repo)), bad


# ------------------------------------------------------------------ pertanyaan, protokol, generator

def test_questions_must_be_human_verified_with_validator(repo):
    rows = [json.loads(x) for x in (repo / "data/cases/questions_draft.jsonl").read_text().splitlines()]
    for r in rows:
        r.update(status="DRAFT_UNVERIFIED_BY_HUMAN", human_verified=False, validator=None, validated_at=None)
    (repo / "data/cases/questions_draft.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    probs = guards.g_questions_verified(repo)
    assert sum("belum HUMAN_VERIFIED" in p for p in probs) == 20
    for r in rows:
        r.update(status="HUMAN_VERIFIED", human_verified=True, validator="Galih", validated_at="2026-11-05")
    (repo / "data/cases/questions_draft.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert guards.g_questions_verified(repo) == []
    rows[2]["validator"] = ""
    rows[3]["source_pdf_sha256"] = "0" * 64
    (repo / "data/cases/questions_draft.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    probs = guards.g_questions_verified(repo)
    assert any("validator/validated_at kosong" in p for p in probs) and any("tidak cocok dengan audit" in p for p in probs)


def test_protocol_lock_detects_later_edit(repo):
    assert any("tidak ada" in p for p in guards.g_protocol_locked(repo))
    from ta_rag import protocol
    protocol.lock(repo / "config" / "protocol.json")
    assert guards.g_protocol_locked(repo) == []
    (repo / "config" / "protocol.json").write_text((repo / "config" / "protocol.json").read_text() + " ")
    assert any("berubah setelah dikunci" in p for p in guards.g_protocol_locked(repo))


def freeze_generator(repo: Path, when="2026-11-05T08:00:00+00:00"):
    from datetime import datetime
    capture.freeze(repo / "config" / "generator.json", now=datetime.fromisoformat(when))


def test_generator_freeze_guard(repo):
    assert guards.g_generator_frozen(repo) == ["generator belum FROZEN"]
    freeze_generator(repo)
    assert guards.g_generator_frozen(repo) == []
    cfg = json.loads((repo / "config" / "generator.json").read_text()); cfg["temperature"] = 0.7
    (repo / "config" / "generator.json").write_text(json.dumps(cfg, indent=2) + "\n")
    assert any("berubah setelah dibekukan" in p for p in guards.g_generator_frozen(repo))


# ------------------------------------------------------------------ capture

def api_row(repo: Path, case_id: str, i: int, **over) -> dict:
    lock = json.loads((repo / "config" / "generator.lock.json").read_text())
    r = {"run_id": "run1", "case_id": case_id, "question": "q", "answer": f"jawaban {case_id}", "answer_status": "OK",
         "request_json": {"model": "mimo-v2.6-flash", "messages": []},
         "response_json_raw": {"id": f"chatcmpl-{i}", "model": "mimo-v2.6-flash", "choices": [{"message": {"content": "x"}}]},
         "response_model": "mimo-v2.6-flash", "usage": {"total_tokens": 321}, "prompt_sha256": lock["prompt_sha256"], "chunk_ids": ["c1"],
         "timestamp_utc": f"2026-11-05T09:00:{i:02d}+00:00", "top_k": 4}
    r.update(over)
    return r


def write_run(repo: Path, rows: list[dict], name="answers_run1.jsonl"):
    (repo / "data" / "runs" / name).write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def case_ids(repo):
    return [json.loads(x)["case_id"] for x in (repo / "data/cases/questions_draft.jsonl").read_text().splitlines()]


def test_capture_guard_accepts_api_shaped_rows_and_rejects_shortcuts(repo):
    freeze_generator(repo)
    ids = case_ids(repo)
    write_run(repo, [api_row(repo, c, i) for i, c in enumerate(ids)])
    assert guards.g_captures_real(repo) == []

    def bad(idx, **over):
        rows = [api_row(repo, c, i) for i, c in enumerate(ids)]
        rows[idx] = api_row(repo, ids[idx], idx, **over)
        write_run(repo, rows)
        return guards.g_captures_real(repo)

    assert any("respons API mentah" in p for p in bad(3, response_json_raw={"id": "x"}))
    assert any("bukan model MiMo" in p for p in bad(3, response_model="gpt-4"))
    assert any("usage kosong" in p for p in bad(3, usage=None))
    assert any("usage kosong" in p for p in bad(3, usage={"total_tokens": 0}))
    assert any("prompt_sha256" in p for p in bad(3, prompt_sha256="0" * 64))
    assert any("chunk_ids kosong" in p for p in bad(3, chunk_ids=[]))
    assert any("mendahului pembekuan" in p for p in bad(3, timestamp_utc="2026-11-05T07:00:00+00:00"))
    write_run(repo, [api_row(repo, c, 0) for c in ids])  # semua stempel identik
    assert any("stempel identik" in p for p in guards.g_captures_real(repo))
    write_run(repo, [api_row(repo, c, i) for i, c in enumerate(ids[:-1])])
    assert any("harus 20" in p for p in guards.g_captures_real(repo))


# ------------------------------------------------------------------ label

def natural_label(repo: Path, cid: str, run="run1", **over) -> dict:
    cases = {json.loads(x)["case_id"]: json.loads(x) for x in (repo / "data/cases/questions_draft.jsonl").read_text().splitlines()}
    c = cases[cid]
    r = {"answer_id": f"{run}:{cid}", "case_id": cid, "group_id": c["group_id"], "evidence_group": c["evidence_group"], "track": "R",
         "answer_origin": "original_llm", "origin": "natural", "answer": f"jawaban {cid}", "kind": c["kind"], "run_id": run,
         "label": "LAYAK", "manual_label_locked": True, "validator": "Galih", "labeled_at": "2026-11-05T12:00:00+00:00"}
    r.update(over)
    return r


def setup_labels(repo: Path):
    from ta_rag import protocol
    freeze_generator(repo)
    protocol.lock(repo / "config" / "protocol.json", now=__import__("datetime").datetime.fromisoformat("2026-11-05T09:30:00+00:00"))
    ids = case_ids(repo)
    write_run(repo, [api_row(repo, c, i) for i, c in enumerate(ids)])
    return ids


def test_labels_guard_enforces_single_human_blind_unedited_labels(repo):
    ids = setup_labels(repo)
    lp = repo / "data" / "labels" / "labels.jsonl"

    def put(rows):
        lp.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        return guards.g_labels_valid(repo)

    good = [natural_label(repo, c) for c in ids]
    assert put(good) == []
    assert any("validator harus satu orang" in p for p in put(good[:-1] + [natural_label(repo, ids[-1], validator="AI")]))
    assert any("validator harus satu orang" in p for p in put([{**g, "validator": ""} for g in good]))
    assert any("belum dikunci" in p for p in put([{**good[0], "manual_label_locked": False}] + good[1:]))
    assert any("buta skor" in p for p in put([{**good[0], "H": 0.9}] + good[1:]))
    assert any("sebelum protokol dikunci" in p for p in put([{**good[0], "labeled_at": "2026-11-05T08:00:00+00:00"}] + good[1:]))
    assert any("disunting" in p for p in put([{**good[0], "answer": "jawaban yang diubah"}] + good[1:]))
    assert any("tidak ada baris capture" in p for p in put([{**good[0], "run_id": "run9"}] + good[1:]))


def test_relabel_gap_guard_requires_gap_or_acknowledged_deviation(repo):
    setup_labels(repo)
    (repo / "data/labels/labels_all.jsonl").write_text(json.dumps(natural_label(repo, "R01")) + "\n")
    rl = repo / "data" / "labels" / "relabel.jsonl"
    rl.write_text(json.dumps({"answer_id": "run1:R01", "relabeled_at": "2026-11-05T20:00:00+00:00"}) + "\n")
    assert any("deviasi tidak diakui" in p for p in guards.g_relabel_gap(repo))
    rl.write_text(json.dumps({"answer_id": "run1:R01", "relabeled_at": "2026-11-05T20:00:00+00:00", "gap_deviation_acknowledged": True}) + "\n")
    assert guards.g_relabel_gap(repo) == []
    rl.write_text(json.dumps({"answer_id": "run1:R01", "relabeled_at": "2026-11-06T13:00:00+00:00"}) + "\n")
    assert guards.g_relabel_gap(repo) == []


def test_relabel_gap_guard_checks_mutation_against_its_own_first_label(repo):
    setup_labels(repo)
    original = natural_label(repo, "R01")
    mutation = {**original, "answer_id": "M:R01", "track": "M", "answer_origin": "mutasi_terkontrol",
                "origin": "mutation", "label": "TIDAK_LAYAK", "labeled_at": "2026-11-05T18:00:00+00:00"}
    (repo / "data/labels/labels.jsonl").write_text(json.dumps(original) + "\n")
    (repo / "data/labels/labels_all.jsonl").write_text("\n".join(json.dumps(r) for r in (original, mutation)) + "\n")
    path = repo / "data/labels/relabel.jsonl"
    relabel = [{"answer_id": r["answer_id"], "relabeled_at": "2026-11-06T02:00:00+00:00"} for r in (original, mutation)]
    path.write_text("\n".join(json.dumps(r) for r in relabel) + "\n")
    problems = guards.g_relabel_gap(repo)
    assert len(problems) == 1 and "M:R01" in problems[0] and "deviasi tidak diakui" in problems[0]
    relabel[1]["gap_deviation_acknowledged"] = True
    path.write_text("\n".join(json.dumps(r) for r in relabel) + "\n")
    assert guards.g_relabel_gap(repo) == []
    relabel[1].pop("gap_deviation_acknowledged")
    for r in relabel:
        r["relabeled_at"] = "2026-11-06T06:00:00+00:00"
    path.write_text("\n".join(json.dumps(r) for r in relabel) + "\n")
    assert guards.g_relabel_gap(repo) == []
    relabel[1]["answer_id"] = "M:UNKNOWN"
    path.write_text("\n".join(json.dumps(r) for r in relabel) + "\n")
    assert any("M:UNKNOWN: tidak ada label pertama" in p for p in guards.g_relabel_gap(repo))


def test_relabel_gap_guard_uses_earlier_sheet_save_even_when_import_is_late(repo):
    (repo / "data/labels/labels_all.jsonl").write_text(json.dumps(natural_label(repo, "R01")) + "\n")
    record = {"answer_id": "run1:R01", "relabeled_at": "2026-11-06T13:00:00+00:00",
              "sheet_saved_at": "2026-11-05T19:00:00+00:00"}
    path = repo / "data/labels/relabel.jsonl"
    path.write_text(json.dumps(record) + "\n")
    assert any("deviasi tidak diakui" in p for p in guards.g_relabel_gap(repo))
    record["gap_deviation_acknowledged"] = True
    path.write_text(json.dumps(record) + "\n")
    assert guards.g_relabel_gap(repo) == []


def test_relabel_gap_guard_requires_merged_labels(repo):
    (repo / "data/labels/labels.jsonl").write_text(json.dumps(natural_label(repo, "R01")) + "\n")
    (repo / "data/labels/relabel.jsonl").write_text(json.dumps({
        "answer_id": "run1:R01", "relabeled_at": "2026-11-06T13:00:00+00:00"}) + "\n")
    assert guards.g_relabel_gap(repo) == ["data/labels/labels_all.jsonl tidak ada"]


# ------------------------------------------------------------------ data buatan

def test_no_synthetic_flags_markers_and_fixture_paths(repo):
    assert guards.g_no_synthetic(repo) == []
    (repo / "data/runs/answers_run1.jsonl").write_text(json.dumps({"case_id": "R01", "synthetic": True}) + "\n")
    assert any("penanda data buatan" in p for p in guards.g_no_synthetic(repo))
    (repo / "data/runs/answers_run1.jsonl").write_text(json.dumps({"case_id": "R01", "stub": "ya"}) + "\n")
    assert any("penanda data buatan" in p for p in guards.g_no_synthetic(repo))
    (repo / "data/runs/answers_run1.jsonl").write_text(json.dumps({"case_id": "R01", "synthetic": False, "note": "bukan dummy"}) + "\n")
    assert guards.g_no_synthetic(repo) == []  # kunci bernilai false dan kata "dummy" di dalam teks bebas BUKAN penanda
    (repo / "data/runs/answers_run1.jsonl").unlink()
    shutil.copy(FIXTURE, repo / "data" / "reducto" / "raw" / "fixture_perpres.json")
    assert any("nama berkas menandakan data buatan" in p for p in guards.g_no_synthetic(repo))


def test_run_guards_rejects_unknown_name(repo):
    with pytest.raises(KeyError):
        guards.run_guards(["tidak_ada"], repo)


# ------------------------------------------------------------------ Studi 2: jumlah pertanyaan dari protokol, label lari tambahan

def test_questions_verified_expected_count_comes_from_protocol_track_r_and_defaults_to_20(repo):
    qp = repo / "data/cases/questions_draft.jsonl"
    rows = [{**json.loads(x), "status": "HUMAN_VERIFIED", "human_verified": True, "validator": "Galih", "validated_at": "2026-11-05"} for x in qp.read_text().splitlines()]
    qp.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert guards.g_questions_verified(repo) == []  # protokol tanpa track_r: bawaan 20 (Studi 1)
    pp = repo / "config" / "protocol.json"
    proto = json.loads(pp.read_text())
    pp.write_text(json.dumps({**proto, "track_r": {"n_questions": 21}}))
    assert guards.g_questions_verified(repo) == ["jumlah pertanyaan 20 != 21"]
    pp.write_text(json.dumps({**proto, "track_r": {"n_questions": 20}}))
    assert guards.g_questions_verified(repo) == []


def test_labels_valid_registry_guard_also_checks_extra_run_label_files(repo):
    ids = setup_labels(repo)
    write_run(repo, [api_row(repo, c, i) for i, c in enumerate(ids)], name="answers_run2.jsonl")
    (repo / "data/labels/labels.jsonl").write_text("\n".join(json.dumps(natural_label(repo, c)) for c in ids) + "\n")
    guard, extra = guards.REGISTRY["labels_valid"], repo / "data/labels/labels_run2.jsonl"
    assert guard(repo) == []  # tanpa berkas lari tambahan: perilaku Studi 1
    extra.write_text("\n".join(json.dumps(natural_label(repo, c, run="run2")) for c in ids) + "\n")
    assert guard(repo) == []  # lari tambahan yang valid
    extra.write_text("\n".join(json.dumps(natural_label(repo, c, run="run2", labeled_at="2026-11-05T08:00:00+00:00")) for c in ids) + "\n")
    assert any("sebelum protokol dikunci" in p for p in guard(repo))  # berkas lari tambahan ikut diperiksa


# ------------------------------------------------------------------ lembar manusia (S19, S22, S26): selesai hanya bila importirnya menerima

LAB = "data/labels"
SHEET_GUARDS = ["label_sheets_complete", "mutants_sheet_complete", "relabel_sheet_complete"]


def snapshot(repo: Path) -> dict[str, str]:
    """Semua berkas (hash isi) dan folder repo tiruan: penjaga lembar tidak boleh menambah atau mengubah apa pun di sana."""
    return {str(f.relative_to(repo)): sha(f) if f.is_file() else "dir" for f in sorted(repo.rglob("*"))}


def label_for(row: dict) -> str:
    return "TIDAK_LAYAK" if row["case_id"] == "R18" else "LAYAK"  # satu probe TIDAK_LAYAK, seperti TL.label_all


def set_protocol(repo: Path, edit) -> None:
    pp = repo / "config" / "protocol.json"
    proto = json.loads(pp.read_text())
    edit(proto)
    pp.write_text(json.dumps(proto))


def edit_sheet(sheet: Path, edit) -> None:
    rows = list(csv.DictReader(open(sheet, newline="", encoding="utf-8-sig")))
    edit(rows)
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)


def export_sheets(repo: Path, runs=("run1",)) -> None:
    """Lembar label BARU DIEKSPOR (kosong) seperti keluaran S18. Jawaban 'generator' = rujukan draf; hanya menguji penjaga, bukan data penelitian."""
    for run in runs:
        labeling.export_label_sheet(TL.answers_file(repo / "data" / "runs", run=run), TL.CASES, TL.PROTO, repo / LAB / f"sheet_{run}.csv")


def fill_sheets(repo: Path, runs=("run1",)) -> None:
    for run in runs:
        TL.fill(repo / LAB / f"sheet_{run}.csv", label_for)


def import_labels(repo: Path) -> Path:
    export_sheets(repo)
    fill_sheets(repo)
    out = repo / LAB / "labels.jsonl"
    labeling.import_label_sheet(repo / LAB / "sheet_run1.csv", repo / "data" / "runs" / "answers_run1.jsonl", TL.CASES, "Galih", out, now=TL.T0)
    return out


def mutants_repo(repo: Path, fill: bool = True) -> Path:
    """Sampai lembar mutasi (kosong, atau terisi oleh `TL.mutant_sheet`), plus chunks.jsonl dan raw Reducto tiruan: halaman jangkar = kutipan."""
    labels = import_labels(repo)
    (repo / "data" / "index" / "chunks.jsonl").write_text("".join(json.dumps(c) + "\n" for c in TL.chunks_file(repo)))
    for doc in sorted({c["source_doc_id"] for c in TL.CASES if c["kind"] == "answerable"}):
        blocks = [{"type": "Text", "content": c["source_quote"], "bbox": {"original_page": c["source_page"]}}
                  for c in TL.CASES if c["kind"] == "answerable" and c["source_doc_id"] == doc]
        (repo / "data" / "reducto" / "raw" / f"{doc}__reducto-r-1.json").write_text(json.dumps({"result": {"type": "full", "chunks": [{"blocks": blocks}]}}))
    if fill:
        TL.mutant_sheet(repo / LAB, labels, out="mutants_sheet.csv")
    else:
        labeling.export_mutant_sheet(labels, TL.CASES, TL.chunks_file(repo), TL.PROTO, repo / LAB / "mutants_sheet.csv")
    return labels


def relabel_repo(repo: Path, fill: bool = True) -> None:
    """Sampai lembar relabel: label + mutasi digabung ke labels_all.jsonl, sampel diekspor (kosong, atau label_baru terisi)."""
    labels, lab = mutants_repo(repo), repo / LAB
    labeling.import_mutant_sheet(lab / "mutants_sheet.csv", labels, TL.CASES, TL.chunks_file(repo), TL.PROTO, "Galih", lab / "mutants.jsonl", lab / "mutants_log.json", now=TL.T0)
    labeling.merge_labels(labels, lab / "mutants.jsonl", lab / "labels_all.jsonl")
    labeling.export_relabel_sheet(lab / "labels_all.jsonl", TL.CASES, TL.PROTO, lab / "relabel_sheet.csv", lab / "relabel_sample.json")
    if fill:
        TL.fill(lab / "relabel_sheet.csv", lambda r: "LAYAK", col="label_baru")


def test_sheet_guards_are_registered_and_report_problems_for_an_empty_repo(repo):
    res = guards.run_guards(SHEET_GUARDS, repo)  # tidak ada lembar sama sekali: masalah, bukan galat
    direct = [guards.g_label_sheets_complete(repo), guards.g_mutants_sheet_complete(repo), guards.g_relabel_sheet_complete(repo)]
    assert list(res) == SHEET_GUARDS and list(res.values()) == direct and all(direct)  # tiap nama menunjuk fungsinya sendiri


def test_label_sheets_complete_accepts_filled_sheet_and_rejects_fresh_or_missing_one(repo):
    assert guards.g_label_sheets_complete(repo) == [f"run1: {LAB}/sheet_run1.csv tidak ada"]
    export_sheets(repo)  # kejadian 15 Nov: S19 ditandai selesai 12 detik setelah lembar kosong ini diekspor
    probs = guards.g_label_sheets_complete(repo)
    assert probs and all(p.startswith("run1: ") for p in probs) and any("bukan salah satu" in p for p in probs)
    fill_sheets(repo)
    assert guards.g_label_sheets_complete(repo) == []
    TL.fill(repo / LAB / "sheet_run1.csv", lambda r: "mungkin" if r["case_id"] == "R03" else label_for(r))  # satu sel salah cukup untuk menolak
    assert any("run1:R03" in p and "bukan salah satu" in p for p in guards.g_label_sheets_complete(repo))


def test_label_sheets_complete_never_writes_inside_the_repo(repo):
    export_sheets(repo)
    before = snapshot(repo)
    assert guards.g_label_sheets_complete(repo)  # kosong: ditolak
    assert snapshot(repo) == before
    fill_sheets(repo)
    before = snapshot(repo)
    assert guards.g_label_sheets_complete(repo) == []  # terisi: diterima
    assert snapshot(repo) == before and not list(repo.rglob("labels*.jsonl"))


def test_label_sheets_complete_checks_every_run_up_to_protocol_k_and_names_the_bad_run(repo):
    runs = ("run1", "run2", "run3")
    set_protocol(repo, lambda p: p["determinism"]["generator_runs"].update(k=3))
    export_sheets(repo, runs)
    fill_sheets(repo, runs)
    assert guards.g_label_sheets_complete(repo) == []
    TL.fill(repo / LAB / "sheet_run2.csv", lambda r: "mungkin")  # satu lari dari tiga rusak
    probs = guards.g_label_sheets_complete(repo)
    assert probs and all(p.startswith("run2: ") for p in probs)
    (repo / LAB / "sheet_run3.csv").unlink()
    assert {p.split(":")[0] for p in guards.g_label_sheets_complete(repo)} == {"run2", "run3"}


@pytest.mark.parametrize("edit", [lambda p: p.pop("determinism"), lambda p: p["determinism"].pop("generator_runs"),
                                  lambda p: p["determinism"]["generator_runs"].pop("k")])
def test_label_sheets_complete_defaults_to_one_run_when_protocol_has_no_k(repo, edit):
    set_protocol(repo, edit)
    export_sheets(repo, ("run1", "run2"))
    fill_sheets(repo, ("run1",))  # run2 dibiarkan kosong
    assert guards.g_label_sheets_complete(repo) == []  # bawaan k = 1: hanya run1 yang diperiksa
    set_protocol(repo, lambda p: p.setdefault("determinism", {}).setdefault("generator_runs", {}).update(k=2))
    probs = guards.g_label_sheets_complete(repo)
    assert probs and all(p.startswith("run2: ") for p in probs)


def test_label_sheets_complete_reports_unreadable_input_as_problems_instead_of_raising(repo):
    export_sheets(repo)
    fill_sheets(repo)
    answers, sheet, proto = repo / "data" / "runs" / "answers_run1.jsonl", repo / LAB / "sheet_run1.csv", repo / "config" / "protocol.json"
    good_answers, good_sheet, good_proto = answers.read_text(), sheet.read_bytes(), proto.read_text()
    assert guards.g_label_sheets_complete(repo) == []
    answers.write_text("{bukan json\n")  # JSONDecodeError adalah ValueError satu baris: tidak boleh dianggap 'tanpa masalah'
    assert any("JSONDecodeError" in p for p in guards.g_label_sheets_complete(repo))
    answers.write_text("")  # capture kosong
    assert any("StopIteration" in p for p in guards.g_label_sheets_complete(repo))
    answers.write_text(good_answers)
    sheet.write_text("kolom,lain\n1,2\n")  # tanpa kolom answer_id
    assert any("KeyError" in p for p in guards.g_label_sheets_complete(repo))
    sheet.write_text("")  # lembar kosong
    assert any("belum ada di lembar" in p for p in guards.g_label_sheets_complete(repo))
    sheet.write_bytes(good_sheet)
    proto.write_text("{rusak")
    assert any("protocol.json tidak dapat dibaca" in p for p in guards.g_label_sheets_complete(repo))
    proto.write_text(good_proto)
    assert guards.g_label_sheets_complete(repo) == []


def test_mutants_sheet_complete_accepts_filled_sheet_and_catches_a_bad_mutation(repo):
    mutants_repo(repo)
    assert guards.g_mutants_sheet_complete(repo) == []
    edit_sheet(repo / LAB / "mutants_sheet.csv", lambda rows: rows[0].update(mutated_answer=rows[0]["original_answer"] + " "))  # mutasi yang tidak mengubah apa pun
    assert any("verifikasi mekanis gagal" in p for p in guards.g_mutants_sheet_complete(repo))


def test_mutants_sheet_complete_rejects_fresh_or_missing_sheet(repo):
    assert guards.g_mutants_sheet_complete(repo) == [f"{LAB}/mutants_sheet.csv tidak ada"]
    mutants_repo(repo, fill=False)  # persis keluaran S21
    assert any("baris belum diisi" in p for p in guards.g_mutants_sheet_complete(repo))


def test_mutants_sheet_complete_reads_page_text_from_raw_reducto_like_the_cli(repo):
    mutants_repo(repo)
    sheet = repo / LAB / "mutants_sheet.csv"
    row = next(r for r in csv.DictReader(open(sheet, newline="", encoding="utf-8-sig")) if r["mutation_family"] == "numeric_value")
    case = next(c for c in TL.CASES if c["case_id"] == row["case_id"])
    raw = repo / "data" / "reducto" / "raw" / f"{case['source_doc_id']}__reducto-r-1.json"
    doc = json.loads(raw.read_text())
    doc["result"]["chunks"][0]["blocks"].append({"type": "Text", "content": "angka 997 juga tertulis di halaman ini", "bbox": {"original_page": case["source_page"]}})
    raw.write_text(json.dumps(doc))  # chunks.jsonl tetap tanpa 997: hanya jalur raw yang melihatnya
    assert any(row["case_id"] in p and "muncul di halaman jangkar" in p for p in guards.g_mutants_sheet_complete(repo))


def test_mutants_sheet_complete_never_writes_inside_the_repo(repo):
    labels = mutants_repo(repo, fill=False)
    before = snapshot(repo)
    assert guards.g_mutants_sheet_complete(repo)  # kosong: ditolak
    assert snapshot(repo) == before
    (repo / LAB / "mutants_sheet.csv").unlink()
    TL.mutant_sheet(repo / LAB, labels, out="mutants_sheet.csv")
    before = snapshot(repo)
    assert guards.g_mutants_sheet_complete(repo) == []  # terisi: diterima
    assert snapshot(repo) == before and not list(repo.rglob("mutants*.jsonl")) and not list(repo.rglob("mutants_log*"))


def test_relabel_sheet_complete_accepts_filled_sheet_and_rejects_fresh_or_missing_one(repo):
    assert guards.g_relabel_sheet_complete(repo) == [f"{LAB}/relabel_sheet.csv tidak ada"]
    relabel_repo(repo, fill=False)  # persis keluaran S25
    probs = guards.g_relabel_sheet_complete(repo)
    assert probs and all("label '' bukan salah satu" in p for p in probs)
    TL.fill(repo / LAB / "relabel_sheet.csv", lambda r: "LAYAK", col="label_baru")
    assert guards.g_relabel_sheet_complete(repo) == []
    TL.fill(repo / LAB / "relabel_sheet.csv", lambda r: "mungkin", col="label_baru")
    assert any("bukan salah satu" in p for p in guards.g_relabel_sheet_complete(repo))


def test_relabel_sheet_complete_never_writes_inside_the_repo(repo):
    relabel_repo(repo, fill=False)
    before = snapshot(repo)
    assert guards.g_relabel_sheet_complete(repo)  # kosong: ditolak
    assert snapshot(repo) == before
    TL.fill(repo / LAB / "relabel_sheet.csv", lambda r: "LAYAK", col="label_baru")
    before = snapshot(repo)
    assert guards.g_relabel_sheet_complete(repo) == []  # terisi: diterima
    assert snapshot(repo) == before and not list(repo.rglob("relabel*.jsonl")) and not list(repo.rglob("relabel_result*"))


def test_relabel_sheet_complete_leaves_the_24h_gap_to_the_s26_gate_and_s27_guard(repo):
    relabel_repo(repo)
    lab, saved = repo / LAB, TL.T0 + timedelta(hours=1)  # lembar tersimpan 1 jam setelah label pertama
    os.utime(lab / "relabel_sheet.csv", (saved.timestamp(), saved.timestamp()))
    with pytest.raises(ValueError, match="jeda minimum"):  # importirnya sendiri menolak jeda ini tanpa --accept-short-gap
        labeling.import_relabel_sheet(lab / "relabel_sheet.csv", lab / "relabel_sample.json", lab / "labels_all.jsonl", TL.PROTO, repo / "kontrol.jsonl", repo / "kontrol.json")
    assert guards.g_relabel_sheet_complete(repo) == []


def test_mutants_and_relabel_sheet_guards_report_missing_or_corrupt_companions_instead_of_raising(repo):
    relabel_repo(repo)
    chunks, sample, protocol = repo / "data" / "index" / "chunks.jsonl", repo / LAB / "relabel_sample.json", repo / "config" / "protocol.json"
    good_chunks, good_sample, good_protocol = chunks.read_text(), sample.read_text(), protocol.read_text()
    assert guards.g_mutants_sheet_complete(repo) == [] and guards.g_relabel_sheet_complete(repo) == []
    chunks.unlink()
    assert any("chunks.jsonl" in p for p in guards.g_mutants_sheet_complete(repo))
    chunks.write_text(good_chunks)
    for raw in (repo / "data" / "reducto" / "raw").glob("*.json"):
        raw.rename(raw.with_suffix(".bak"))  # tanpa raw Reducto: teks halaman jangkar tidak tersedia
    assert any("tidak dapat diperiksa" in p and "raw Reducto" in p for p in guards.g_mutants_sheet_complete(repo))
    sample.write_text("{rusak")  # JSONDecodeError adalah ValueError satu baris
    assert any("JSONDecodeError" in p for p in guards.g_relabel_sheet_complete(repo))
    sample.unlink()
    assert any("relabel_sample.json" in p for p in guards.g_relabel_sheet_complete(repo))
    sample.write_text(good_sample)
    protocol.write_text("{rusak")
    assert any("JSONDecodeError" in p for p in guards.g_mutants_sheet_complete(repo) + guards.g_relabel_sheet_complete(repo))
    protocol.write_text(good_protocol)
    assert guards.g_relabel_sheet_complete(repo) == []
