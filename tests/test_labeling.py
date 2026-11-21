"""Uji antarmuka pelabelan. Pertanyaan dan protokol = berkas nyata repo; jawaban 'generator' dibuat dari jawaban rujukan draf HANYA
untuk menguji pemeriksaan impor (bukan hasil penelitian)."""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ta_rag import data, labeling, protocol as P

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
CASES = [json.loads(x) for x in (REPO / "tests" / "fixtures" / "studi1" / "questions_draft.jsonl").read_text(encoding="utf-8").splitlines()]
PROTO = P.load_protocol(REPO / "tests" / "fixtures" / "studi1" / "protocol.json")
ABSTAIN = "Informasi tersebut tidak ada dalam konteks yang diberikan."


def answers_file(tmp_path, statuses=None, run="run1") -> Path:
    rows = []
    for c in CASES:
        ans = c["reference_answer_draft"] if c["kind"] == "answerable" else ABSTAIN
        st = (statuses or {}).get(c["case_id"], "OK")
        rows.append({"run_id": run, "case_id": c["case_id"], "question": c["question"], "answer": None if st != "OK" else ans,
                     "answer_status": st, "chunk_ids": [f"ch-{c['case_id']}"]})
    p = tmp_path / f"answers_{run}.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def chunks_file(tmp_path) -> list[dict]:
    return [{"chunk_id": f"ch-{c['case_id']}", "doc_id": c["source_doc_id"], "page_start": c["source_page"], "page_end": c["source_page"],
             "text": c["source_quote"]} for c in CASES if c["kind"] == "answerable"]


def fill(sheet: Path, label_for, col="label"):
    rows = list(csv.DictReader(open(sheet, newline="", encoding="utf-8-sig")))
    for r in rows:
        r[col] = label_for(r)
        if col == "label" and "abstain" in r and not r["abstain"]:
            r["abstain"] = "tidak" if r.get("kind") == "answerable" else ""
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    return rows


def label_all(tmp_path, bad_probe="R18") -> Path:
    """Alur sehat: sheet -> manusia mengisi -> impor. Satu probe diberi TIDAK_LAYAK agar stratum alami ada."""
    ans = answers_file(tmp_path)
    labeling.export_label_sheet(ans, CASES, PROTO, tmp_path / "sheet.csv")
    fill(tmp_path / "sheet.csv", lambda r: "TIDAK_LAYAK" if r["case_id"] == bad_probe else "LAYAK")
    labeling.import_label_sheet(tmp_path / "sheet.csv", ans, CASES, "Galih", tmp_path / "labels.jsonl", now=T0)
    return tmp_path / "labels.jsonl"


# ------------------------------------------------------------------ lembar & impor label

def test_sheet_is_blind_shuffled_deterministic_and_excludes_non_ok(tmp_path):
    ans = answers_file(tmp_path, statuses={"R05": "ANSWER_EMPTY"})
    info = labeling.export_label_sheet(ans, CASES, PROTO, tmp_path / "s1.csv")
    assert info["rows"] == 19 and info["excluded"] == [{"case_id": "R05", "answer_status": "ANSWER_EMPTY"}]
    rows = list(csv.DictReader(open(tmp_path / "s1.csv", newline="", encoding="utf-8-sig")))
    assert not {"H", "L", "S", "route", "score", "reference_answer_draft"} & set(rows[0].keys())  # tanpa skor, tanpa kunci jawaban
    assert [r["case_id"] for r in rows] != sorted(r["case_id"] for r in rows)  # acak
    assert all(r["label"] == "" for r in rows)
    labeling.export_label_sheet(ans, CASES, PROTO, tmp_path / "s2.csv")
    assert (tmp_path / "s1.csv").read_bytes() == (tmp_path / "s2.csv").read_bytes()  # deterministik
    with pytest.raises(FileExistsError):
        labeling.export_label_sheet(ans, CASES, PROTO, tmp_path / "s1.csv")  # tidak menimpa lembar yang mungkin sudah diisi


def test_import_builds_locked_records_that_pass_data_validation(tmp_path):
    lp = label_all(tmp_path)
    rows = [json.loads(x) for x in lp.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 20 and data.validate_records(rows) == []
    r = next(x for x in rows if x["case_id"] == "R02")
    assert r["manual_label_locked"] and r["validator"] == "Galih" and r["labeled_at"] == T0.isoformat(timespec="seconds")
    assert r["origin"] == "natural" and r["answer_origin"] == "original_llm" and r["track"] == "R" and r["chunk_ids"] == ["ch-R02"]
    assert r["group_id"] == "p59:ganti-fktp" and r["evidence_group"] == "p59:p8" and re.fullmatch(r"[0-9a-f]{64}", r["sheet_sha256"])
    assert not {"H", "route", "L", "S"} & set(r)


def test_import_rejects_invalid_missing_edited_or_duplicate_rows(tmp_path):
    ans = answers_file(tmp_path)

    def sheet_with(modify):
        for f in tmp_path.glob("sheet*.csv"):
            f.unlink()
        labeling.export_label_sheet(ans, CASES, PROTO, tmp_path / "sheet.csv")
        rows = fill(tmp_path / "sheet.csv", lambda r: "LAYAK")
        rows = list(csv.DictReader(open(tmp_path / "sheet.csv", newline="", encoding="utf-8-sig")))
        modify(rows)
        with open(tmp_path / "sheet.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    def imp(out="labels.jsonl", validator="Galih"):
        return labeling.import_label_sheet(tmp_path / "sheet.csv", ans, CASES, validator, tmp_path / out, now=T0)

    sheet_with(lambda rows: rows[0].update(label=""))
    with pytest.raises(ValueError, match="bukan salah satu"):
        imp("a.jsonl")
    sheet_with(lambda rows: rows[0].update(label="mungkin"))
    with pytest.raises(ValueError, match="bukan salah satu"):
        imp("b.jsonl")
    sheet_with(lambda rows: rows.pop())
    with pytest.raises(ValueError, match="belum ada di lembar"):
        imp("c.jsonl")
    sheet_with(lambda rows: rows[0].update(answer=rows[0]["answer"] + " dan tambahan"))
    with pytest.raises(ValueError, match="disunting|berbeda dari hasil capture"):
        imp("d.jsonl")
    sheet_with(lambda rows: rows.append(dict(rows[0])))
    with pytest.raises(ValueError, match="ganda"):
        imp("e.jsonl")
    sheet_with(lambda rows: None)
    with pytest.raises(ValueError, match="validator wajib"):
        imp("f.jsonl", validator="  ")
    assert not list(tmp_path.glob("[a-f].jsonl"))  # tidak ada keluaran parsial
    imp("ok.jsonl")
    with pytest.raises(FileExistsError):
        imp("ok.jsonl")  # label manusia tidak boleh tertimpa


def test_import_is_tolerant_to_whitespace_but_stores_captured_text(tmp_path):
    ans = answers_file(tmp_path)
    labeling.export_label_sheet(ans, CASES, PROTO, tmp_path / "sheet.csv")
    fill(tmp_path / "sheet.csv", lambda r: "layak")  # huruf kecil dinormalkan
    rows = list(csv.DictReader(open(tmp_path / "sheet.csv", newline="", encoding="utf-8-sig")))
    rows[0]["answer"] = "  " + rows[0]["answer"].replace(" ", "  ") + "\r\n"
    with open(tmp_path / "sheet.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    labeling.import_label_sheet(tmp_path / "sheet.csv", ans, CASES, "Galih", tmp_path / "l.jsonl", now=T0)
    stored = {r["case_id"]: r for r in map(json.loads, (tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines())}
    cap = {r["case_id"]: r for r in map(json.loads, ans.read_text(encoding="utf-8").splitlines())}
    assert all(stored[c]["answer"] == cap[c]["answer"] for c in stored) and all(r["label"] == "LAYAK" for r in stored.values())


# ------------------------------------------------------------------ Track M

def mutate_first_number(answer: str) -> str:
    return re.sub(r"\d[\d.,]*", "997", answer, count=1)


def mutate_for(family: str, answer: str) -> str:
    """Mutasi mekanis HANYA untuk menguji pemeriksaan impor (bukan hasil penelitian)."""
    if family == "unit":
        swap = {"hari": "bulan", "minggu": "bulan", "bulan": "hari", "tahun": "bulan"}
        return re.sub(r"\b(hari|minggu|bulan|tahun)\b", lambda m: swap[m.group(1).lower()], answer, count=1)
    if family in ("negation", "clause_deletion"):
        return "tidak " + answer
    return mutate_first_number(answer)


def mutant_sheet(tmp_path, labels, fill_n=None, skip_rows=(), out="msheet.csv", proto=None):
    """Mengisi SEMUA baris (D13): dimutasi, atau skip_reason bila di skip_rows / melebihi fill_n."""
    info = labeling.export_mutant_sheet(labels, CASES, chunks_file(tmp_path), proto or PROTO, tmp_path / out)
    rows = list(csv.DictReader(open(tmp_path / out, newline="", encoding="utf-8-sig")))
    used = 0
    for i, r in enumerate(rows):
        if i in skip_rows or (fill_n is not None and used >= fill_n):
            r["skip_reason"] = "angka kunci tidak dapat diganti secara mekanis"
            continue
        r["mutated_answer"] = mutate_for(r["mutation_family"], r["original_answer"])
        r["anchor_page_opposite"] = f"hlm. {r['source_page']}: kutipan membuktikan nilai lain"
        used += 1
    with open(tmp_path / out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    return info, rows


def test_mutant_sheet_follows_preregistered_order_prefills_families_and_only_liked_natural_answerable(tmp_path):
    lp = label_all(tmp_path)
    info, rows = mutant_sheet(tmp_path, lp, fill_n=0)
    assert info["candidates"] == 16 and info["target_pairs"] == 16  # D13: semua kandidat, bukan 10
    expected = P.track_m_order([{"case_id": c["case_id"], "source_doc_id": c["source_doc_id"]} for c in CASES if c["kind"] == "answerable"],
                               PROTO["track_m"]["seed"])
    assert [r["case_id"] for r in rows] == expected
    assert all(not r["case_id"] in ("R17", "R18", "R19", "R20") for r in rows)  # probe tidak pernah dimutasi
    fam = PROTO["track_m"]["mutation"]["families_by_question_type"]
    assert {r["case_id"]: r["mutation_family"] for r in rows} == P.assign_mutation_families(
        [{"case_id": r["case_id"], "question_type": r["question_type"]} for r in rows], fam)
    dur = [r["mutation_family"] for r in rows if r["question_type"] == "numeric_duration"]
    assert dur == ["numeric_value", "unit"] * 3 + ["numeric_value"]  # 7 pertanyaan durasi bergantian menurut urutan lembar
    assert "allowed_families" not in rows[0]
    # jawaban berlabel TIDAK_LAYAK tidak menjadi kandidat
    rows_l = [json.loads(x) for x in lp.read_text(encoding="utf-8").splitlines()]
    rows_l = [{**r, "label": "TIDAK_LAYAK"} if r["case_id"] == "R02" else r for r in rows_l]
    lp2 = tmp_path / "labels2.jsonl"; lp2.write_text("\n".join(json.dumps(r) for r in rows_l) + "\n", encoding="utf-8")
    labeling.export_mutant_sheet(lp2, CASES, [], PROTO, tmp_path / "m2.csv")
    assert "R02" not in [r["case_id"] for r in csv.DictReader(open(tmp_path / "m2.csv", newline="", encoding="utf-8-sig"))]


def test_mutant_import_happy_path_mutates_every_candidate_and_merges_cleanly(tmp_path):
    lp = label_all(tmp_path)
    mutant_sheet(tmp_path, lp)
    res = labeling.import_mutant_sheet(tmp_path / "msheet.csv", lp, CASES, chunks_file(tmp_path), PROTO, "Galih", tmp_path / "mutants.jsonl",
                                       tmp_path / "mlog.json", now=T0 + timedelta(hours=1))
    assert res["n_pairs"] == 16 and res["shortfall"] == 0
    muts = [json.loads(x) for x in (tmp_path / "mutants.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(m["label"] == "TIDAK_LAYAK" and m["track"] == "M" and m["origin"] == "mutation" and m["mutated_from_answer_id"].startswith("run1:") for m in muts)
    assert sum(m["mutation_family"] == "unit" for m in muts) == 3 and {"negation", "date"} <= {m["mutation_family"] for m in muts}
    merged = labeling.merge_labels(lp, tmp_path / "mutants.jsonl", tmp_path / "all.jsonl")
    assert merged == {"n": 36, "natural": 20, "mutation": 16}
    assert data.validate_records([json.loads(x) for x in (tmp_path / "all.jsonl").read_text(encoding="utf-8").splitlines()]) == []


def test_anchor_text_rejects_cross_page_chunks_without_page_text():
    case = {"source_doc_id": "regulation", "source_page": 3}
    chunks = [{"doc_id": "regulation", "page_start": 3, "page_end": 4,
               "text": "Halaman 3: 6 bulan. Halaman 4: 12 bulan."}]
    with pytest.raises(ValueError, match="lintas halaman"):
        labeling._anchor_text(case, chunks)
    assert labeling._anchor_text(case, [{**chunks[0], "page_end": 3, "text": "6 bulan."}]) == "6 bulan."


def test_mutation_anchor_texts_use_original_page_blocks_not_neighboring_chunks(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    raw = {"result": {"type": "full", "chunks": [{"blocks": [
        {"type": "Text", "content": "Nilai <b>6</b> bulan.", "bbox": {"original_page": 3, "page": 1}},
        {"type": "Text", "content": "Nilai 12 bulan.", "bbox": {"original_page": 4, "page": 3}},
        {"type": "Figure", "content": "Deskripsi model 12", "bbox": {"original_page": 3}},
        {"type": "Footer", "content": "Footer 12", "bbox": {"original_page": 3}}
    ]}]}}
    (raw_dir / "regulation__reducto-r-1.json").write_text(json.dumps(raw))
    superseded = {"result": {"type": "full", "chunks": [{"blocks": [
        {"type": "Text", "content": "Nilai lama 999 bulan.", "bbox": {"original_page": 3}}
    ]}]}}
    (raw_dir / "regulation__reducto-r-1__superseded_old.json").write_text(json.dumps(superseded))
    cases = [{"case_id": "A", "kind": "answerable", "source_doc_id": "regulation", "source_page": 3},
             {"case_id": "B", "kind": "answerable", "source_doc_id": "regulation", "source_page": 4},
             {"case_id": "P", "kind": "not_in_corpus", "source_doc_id": "regulation", "source_page": None}]
    anchors = labeling._load_mutation_anchor_texts(cases, raw_dir)
    assert anchors == {"A": "Nilai 6 bulan.", "B": "Nilai 12 bulan."}
    assert P.verify_mutation("Nilai 6 bulan.", "Nilai 12 bulan.", "numeric_value", anchors["A"]) == []
    assert any("muncul di halaman jangkar" in p for p in P.verify_mutation(
        "Nilai 6 bulan.", "Nilai 12 bulan.", "numeric_value", anchors["B"]))
    with pytest.raises(ValueError, match="halaman fisik 5"):
        labeling._load_mutation_anchor_texts([{**cases[0], "source_page": 5}], raw_dir)
    with pytest.raises(FileNotFoundError):
        labeling._load_mutation_anchor_texts([{**cases[0], "source_doc_id": "missing"}], raw_dir)


def test_mutant_import_uses_explicit_page_texts_for_cross_page_chunks(tmp_path):
    labels = label_all(tmp_path)
    mutant_sheet(tmp_path, labels)
    chunks = [{**c, "page_end": c["page_start"] + 1} for c in chunks_file(tmp_path)]
    anchors = {c["case_id"]: c["source_quote"] for c in CASES if c["kind"] == "answerable"}
    result = labeling.import_mutant_sheet(tmp_path / "msheet.csv", labels, CASES, chunks, PROTO, "Galih",
                                         tmp_path / "mutants.jsonl", tmp_path / "log.json", now=T0,
                                         anchor_texts=anchors)
    assert result["n_pairs"] == 16


def test_mutant_import_rejects_missing_explicit_page_text(tmp_path):
    labels = label_all(tmp_path)
    mutant_sheet(tmp_path, labels)
    with pytest.raises(ValueError, match="teks halaman jangkar"):
        labeling.import_mutant_sheet(tmp_path / "msheet.csv", labels, CASES, chunks_file(tmp_path), PROTO, "Galih",
                                     tmp_path / "mutants.jsonl", tmp_path / "log.json", now=T0,
                                     anchor_texts={})
    assert not (tmp_path / "mutants.jsonl").exists()


def test_mutant_import_rejects_skipping_blank_rows_failed_verification_and_chosen_family(tmp_path):
    lp = label_all(tmp_path)

    def run(rows_mod, out):
        mutant_sheet(tmp_path, lp, out="msheet.csv")
        rows = list(csv.DictReader(open(tmp_path / "msheet.csv", newline="", encoding="utf-8-sig")))
        rows_mod(rows)
        with open(tmp_path / "msheet.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        return labeling.import_mutant_sheet(tmp_path / "msheet.csv", lp, CASES, chunks_file(tmp_path), PROTO, "Galih", tmp_path / out, tmp_path / (out + ".log"), now=T0)

    def reset():
        (tmp_path / "msheet.csv").unlink()

    # 1) baris dikosongkan di tengah (dilompati tanpa alasan) padahal baris sesudahnya terisi
    def skip_middle(rows):
        rows[0].update(mutated_answer="", anchor_page_opposite="")
    with pytest.raises(ValueError, match="dilewati tanpa alasan"):
        run(skip_middle, "a.jsonl")
    reset()
    # 2) dua baris terisi bertukar tempat (tidak ada celah kosong, jadi hanya pemeriksaan urutan yang bisa menangkapnya)
    def swap(rows):
        rows[0], rows[1] = rows[1], rows[0]
        for i, r in enumerate(rows):
            r["order"] = str(i + 1)
    with pytest.raises(ValueError, match="lembar != urutan pra-registrasi"):
        run(swap, "b.jsonl")
    reset()
    # 3) D13: baris terakhir kosong (tidak dimutasi dan tidak ada skip_reason) ditolak: setiap kandidat wajib terisi
    def blank_last(rows):
        rows[-1].update(mutated_answer="", skip_reason="", anchor_page_opposite="")
    with pytest.raises(ValueError, match="belum diisi"):
        run(blank_last, "c.jsonl")
    reset()
    # 4) mutasi tanpa halaman jangkar kebalikan
    with pytest.raises(ValueError, match="anchor_page_opposite wajib"):
        run(lambda rows: next(r for r in rows if r["mutated_answer"]).update(anchor_page_opposite=" "), "d.jsonl")
    reset()
    # 5) mutasi yang tidak mengubah apa pun / bukan mutasi
    def lucky(rows):
        r = next(x for x in rows if x["mutated_answer"])
        r["mutated_answer"] = r["original_answer"] + " "
    with pytest.raises(ValueError, match="verifikasi mekanis gagal"):
        run(lucky, "e.jsonl")
    reset()
    # 6) D13: family dipilih peneliti, tidak sama dengan penetapan pra-registrasi
    def other_family(rows):
        r = next(x for x in rows if x["mutated_answer"])
        r["mutation_family"] = "negation" if r["mutation_family"] != "negation" else "date"
    with pytest.raises(ValueError, match="tidak sesuai penetapan"):
        run(other_family, "f.jsonl")
    reset()
    # 7) skip_reason dan mutated_answer bersamaan
    with pytest.raises(ValueError, match="sama-sama terisi"):
        run(lambda rows: next(r for r in rows if r["mutated_answer"]).update(skip_reason="x"), "g.jsonl")
    assert not list(tmp_path.glob("[a-g].jsonl"))


def test_mutant_skip_with_reason_is_logged_and_does_not_count(tmp_path):
    lp = label_all(tmp_path)
    mutant_sheet(tmp_path, lp, skip_rows=(0,))
    res = labeling.import_mutant_sheet(tmp_path / "msheet.csv", lp, CASES, chunks_file(tmp_path), PROTO, "Galih", tmp_path / "m.jsonl", tmp_path / "log.json", now=T0)
    log = json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))
    assert res["n_pairs"] == 15 and res["shortfall"] == 1 and len(log["skipped"]) == 1 and log["skipped"][0]["reason"].startswith("angka kunci")


def test_mutant_shortfall_is_reported_not_padded(tmp_path):
    lp = label_all(tmp_path)
    mutant_sheet(tmp_path, lp, fill_n=6)
    res = labeling.import_mutant_sheet(tmp_path / "msheet.csv", lp, CASES, chunks_file(tmp_path), PROTO, "Galih", tmp_path / "m.jsonl", tmp_path / "log.json", now=T0)
    assert res["n_pairs"] == 6 and res["shortfall"] == 10


# ------------------------------------------------------------------ relabel & ringkasan

def merged(tmp_path):
    lp = label_all(tmp_path)
    mutant_sheet(tmp_path, lp)
    labeling.import_mutant_sheet(tmp_path / "msheet.csv", lp, CASES, chunks_file(tmp_path), PROTO, "Galih", tmp_path / "mutants.jsonl", tmp_path / "mlog.json", now=T0)
    labeling.merge_labels(lp, tmp_path / "mutants.jsonl", tmp_path / "all.jsonl")
    return tmp_path / "all.jsonl"


OPPOSITE = {"LAYAK": "TIDAK_LAYAK", "TIDAK_LAYAK": "LAYAK"}


def sheet_items(tmp_path) -> dict:
    """item_id -> answer_id. Lembar relabel hanya memuat item_id; pemetaannya hanya di relabel_sample.json."""
    return json.loads((tmp_path / "rsample.json").read_text(encoding="utf-8"))["items"]


def first_by_item(allp, tmp_path) -> dict:
    """item_id (kolom lembar relabel) -> label pertama."""
    first = {r["answer_id"]: r["label"] for r in map(json.loads, allp.read_text(encoding="utf-8").splitlines())}
    return {item: first[aid] for item, aid in sheet_items(tmp_path).items()}


def rewrite_sheet(path, transform):
    """Baca lembar CSV, ganti seluruh barisnya dengan hasil transform(rows), tulis kembali."""
    rows = transform(list(csv.DictReader(open(path, newline="", encoding="utf-8-sig"))))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)


def relabel_case(tmp_path, flip_natural=False):
    """Lembar relabel (item_id) diisi menyalin label pertama tiap jawaban; flip_natural membalik SATU jawaban asli pertanyaan-berjawab (bukan probe).
    Mengembalikan (labels_all, {answer_id: record}, {item_id: answer_id}, item_id yang dibalik atau None)."""
    allp = merged(tmp_path)
    labeling.export_relabel_sheet(allp, CASES, PROTO, tmp_path / "rs.csv", tmp_path / "rsample.json")
    first = {r["answer_id"]: r for r in map(json.loads, allp.read_text(encoding="utf-8").splitlines())}
    items = sheet_items(tmp_path)
    flipped = next(i for i, a in items.items() if first[a]["origin"] == "natural" and first[a]["kind"] == "answerable") if flip_natural else None

    def second(r):
        label = first[items[r["item_id"]]]["label"]
        return OPPOSITE[label] if r["item_id"] == flipped else label
    fill(tmp_path / "rs.csv", second, col="label_baru")
    return allp, first, items, flipped


def test_relabel_sheet_has_no_first_label_and_meets_strata(tmp_path):
    allp = merged(tmp_path)
    info = labeling.export_relabel_sheet(allp, CASES, PROTO, tmp_path / "rs.csv", tmp_path / "rsample.json")
    # satu-satunya TIDAK_LAYAK alami di fixture ini adalah probe (stratum probe), jadi stratum natural_tidak_layak kurang 2: dicatat, tidak diisi paksa
    assert info["n"] == 8 and info["strata_short"] == {"natural_tidak_layak": 2}
    rows = list(csv.DictReader(open(tmp_path / "rs.csv", newline="", encoding="utf-8-sig")))
    assert not {"label", "label_first", "origin", "answer_origin"} & set(rows[0].keys())
    comp = info["composition"]
    assert comp["mutation"] >= 2 and comp["probe"] >= 2 and comp.get("natural_tidak_layak", 0) == 0


def test_relabel_import_computes_agreement_and_enforces_gap(tmp_path):
    allp = merged(tmp_path)
    labeling.export_relabel_sheet(allp, CASES, PROTO, tmp_path / "rs.csv", tmp_path / "rsample.json")
    first = first_by_item(allp, tmp_path)
    flip = {"v": 0}

    def second(r):
        flip["v"] += 1
        return first[r["item_id"]] if flip["v"] != 1 else ("LAYAK" if first[r["item_id"]] == "TIDAK_LAYAK" else "TIDAK_LAYAK")
    fill(tmp_path / "rs.csv", second, col="label_baru")
    # 1 jam setelah label pertama -> ditolak
    with pytest.raises(ValueError, match="jeda minimum"):
        labeling.import_relabel_sheet(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, PROTO, tmp_path / "rl.jsonl", tmp_path / "rr.json", now=T0 + timedelta(hours=1))
    assert not (tmp_path / "rl.jsonl").exists()
    res = labeling.import_relabel_sheet(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, PROTO, tmp_path / "rl.jsonl", tmp_path / "rr.json", now=T0 + timedelta(hours=25))
    assert res["n"] == 8 and res["agree"] == 7 and res["pct"] == 87.5 and len(res["discrepancies"]) == 1 and not res["gap_deviation"]
    # deviasi diakui secara eksplisit
    res2 = labeling.import_relabel_sheet(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, PROTO, tmp_path / "rl2.jsonl", tmp_path / "rr2.json",
                                         now=T0 + timedelta(hours=3), accept_short_gap=True)
    assert res2["gap_deviation"] is True and all(json.loads(x)["gap_deviation_acknowledged"] for x in (tmp_path / "rl2.jsonl").read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize("saved_hours", [7, 12])
def test_relabel_import_does_not_hide_early_review_by_delaying_import(tmp_path, saved_hours):
    allp = merged(tmp_path)
    sheet = tmp_path / "rs.csv"
    sample = tmp_path / "rsample.json"
    labeling.export_relabel_sheet(allp, CASES, PROTO, sheet, sample)
    fill(sheet, lambda r: "LAYAK", col="label_baru")
    saved = T0 + timedelta(hours=saved_hours)
    os.utime(sheet, (saved.timestamp(), saved.timestamp()))
    out, result = tmp_path / "rl.jsonl", tmp_path / "rr.json"
    short = saved_hours < PROTO["relabel"]["min_gap_hours"]
    if short:
        with pytest.raises(ValueError, match="jeda minimum"):
            labeling.import_relabel_sheet(sheet, sample, allp, PROTO, out, result, now=T0 + timedelta(hours=25))
        assert not out.exists()
    res = labeling.import_relabel_sheet(sheet, sample, allp, PROTO, out, result,
                                        now=T0 + timedelta(hours=25), accept_short_gap=short)
    assert res["gap_deviation"] is short
    assert res["min_gap_hours_observed"] == saved_hours
    assert res["gap_is_upper_bound"] is True
    assert res["sheet_saved_at"] == saved.isoformat(timespec="seconds")
    assert res["imported_at"] == (T0 + timedelta(hours=25)).isoformat(timespec="seconds")
    records = [json.loads(s) for s in out.read_text().splitlines()]
    assert all(r["gap_hours"] == saved_hours and r["gap_deviation_acknowledged"] is short for r in records)
    assert all(r["sheet_saved_at"] == res["sheet_saved_at"] for r in records)
    (tmp_path / "second.json").write_text(json.dumps(["2026-11-06; rekan; menolak; tidak ada waktu"]))
    md = labeling.write_pre_evaluator_summary(allp, tmp_path / "mlog.json", result,
                                               tmp_path / "second.json", tmp_path / "summary.md")
    if short:
        assert "paling lama 7.0 jam" in md and "Deviasi" in md
    else:
        assert "**Deviasi:**" not in md


def test_relabel_rejects_rows_outside_the_sample(tmp_path):
    allp = merged(tmp_path)
    labeling.export_relabel_sheet(allp, CASES, PROTO, tmp_path / "rs.csv", tmp_path / "rsample.json")
    rows = fill(tmp_path / "rs.csv", lambda r: "LAYAK", col="label_baru")
    rows = list(csv.DictReader(open(tmp_path / "rs.csv", newline="", encoding="utf-8-sig")))[:-1]
    with open(tmp_path / "rs.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with pytest.raises(ValueError, match="sampel relabel"):
        labeling.import_relabel_sheet(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, PROTO, tmp_path / "x.jsonl", tmp_path / "x.json", now=T0 + timedelta(hours=30))


def test_relabel_sheet_hides_answer_origin_behind_item_ids_mapped_only_in_the_sample(tmp_path):
    allp = merged(tmp_path)
    info = labeling.export_relabel_sheet(allp, CASES, PROTO, tmp_path / "rs.csv", tmp_path / "rsample.json")
    rows = list(csv.DictReader(open(tmp_path / "rs.csv", newline="", encoding="utf-8-sig")))
    sample = json.loads((tmp_path / "rsample.json").read_text(encoding="utf-8"))
    assert list(rows[0])[0] == "item_id" and "answer_id" not in rows[0]
    assert [r["item_id"] for r in rows] == [f"R{n:02d}" for n in range(1, info["n"] + 1)]
    assert any(":" in a for a in sample["answer_ids"]) and not any(":" in r["item_id"] for r in rows)  # `M:R05` / `run1:R05` membuka asal; item_id tidak
    assert list(sample["items"]) == [r["item_id"] for r in rows]
    assert len(sample["items"]) == len(sample["answer_ids"]) and set(sample["items"].values()) == set(sample["answer_ids"])
    assert {"answer_ids", "composition", "strata_short"} <= set(sample) and info["composition"] == sample["composition"]
    assert list(sample["items"].values()) == sorted(sample["answer_ids"], key=lambda a: labeling._key(PROTO["relabel"]["seed"] + ":order", a))  # urutan baris tetap
    by = {r["answer_id"]: r for r in map(json.loads, allp.read_text(encoding="utf-8").splitlines())}
    assert all((by[sample["items"][r["item_id"]]]["case_id"], by[sample["items"][r["item_id"]]]["answer"]) == (r["case_id"], r["answer"]) for r in rows)  # baris = jawaban yang dipetakan


def test_relabel_import_pairs_each_item_id_with_its_own_first_label(tmp_path):
    allp, first, items, flipped = relabel_case(tmp_path, flip_natural=True)
    assert {first[a]["label"] for a in items.values()} == set(OPPOSITE)  # sampel memuat kedua label, jadi pemetaan yang salah mengubah kesepakatan
    res = labeling.import_relabel_sheet(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, PROTO, tmp_path / "rl.jsonl", tmp_path / "rr.json", now=T0 + timedelta(hours=25))
    label = first[items[flipped]]["label"]
    assert res["n"] == 8 and res["agree"] == 7 and res["pct"] == 87.5
    assert res["discrepancies"] == [{"answer_id": items[flipped], "label1": label, "label2": OPPOSITE[label]}]
    recs = {r["answer_id"]: r for r in map(json.loads, (tmp_path / "rl.jsonl").read_text(encoding="utf-8").splitlines())}
    assert set(recs) == set(items.values()) and all(r["label_first"] == first[a]["label"] for a, r in recs.items())


def test_relabel_import_rejects_unknown_or_duplicate_item_ids_and_names_rows_by_item_id(tmp_path):
    allp, first, items, _ = relabel_case(tmp_path)
    good = (tmp_path / "rs.csv").read_bytes()

    def imp(name, modify):
        (tmp_path / "rs.csv").write_bytes(good)
        rewrite_sheet(tmp_path / "rs.csv", modify)
        return labeling.import_relabel_sheet(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, PROTO, tmp_path / f"{name}.jsonl", tmp_path / f"{name}.json",
                                             now=T0 + timedelta(hours=25))

    def blank_third(rows):
        rows[2]["label_baru"] = ""
        return rows
    with pytest.raises(ValueError, match="R99: item_id tidak ada"):  # baris tambahan: semua item sah tetap lengkap, hanya pemeriksaan item_id yang menolak
        imp("a", lambda rows: rows + [{**rows[0], "item_id": "R99"}])
    with pytest.raises(ValueError, match="R99: item_id tidak ada"):
        imp("b", lambda rows: [{**rows[0], "item_id": "R99"}] + rows[1:])
    with pytest.raises(ValueError, match="sampel relabel"):  # item_id ganda: satu jawaban dua kali, satu hilang
        imp("c", lambda rows: [{**rows[0], "item_id": rows[1]["item_id"]}] + rows[1:])
    with pytest.raises(ValueError) as ex:
        imp("d", blank_third)
    assert "R03: label ''" in str(ex.value) and not any(a in str(ex.value) for a in items.values())  # menyebut item_id; asal jawaban tidak bocor ke penilai
    assert not list(tmp_path.glob("[a-d].json*"))  # tanpa keluaran parsial
    assert imp("ok", lambda rows: rows)["n"] == 8


def test_relabel_importers_still_accept_old_answer_id_sheets_without_items(tmp_path):
    allp, first, items, _ = relabel_case(tmp_path)  # lembar Studi 1: kolom answer_id, sampel tanpa `items`
    rewrite_sheet(tmp_path / "rs.csv", lambda rows: [{"answer_id": items[r["item_id"]], **{k: v for k, v in r.items() if k != "item_id"}} for r in rows])
    sample = json.loads((tmp_path / "rsample.json").read_text(encoding="utf-8"))
    del sample["items"]
    (tmp_path / "rsample.json").write_text(json.dumps(sample), encoding="utf-8")
    res = labeling.import_relabel_sheet(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, PROTO, tmp_path / "rl.jsonl", tmp_path / "rr.json", now=T0 + timedelta(hours=25))
    assert res["n"] == 8 and res["agree"] == 8 and sum(v["n"] for v in res["by_stratum"].values()) == 8
    assert {r["answer_id"] for r in map(json.loads, (tmp_path / "rl.jsonl").read_text(encoding="utf-8").splitlines())} == set(items.values())
    sr = labeling.import_second_rater(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, tmp_path / "sr.jsonl", tmp_path / "sr.json",
                                      rater="Orang Kedua", ai_assistance="none", now=T0 + timedelta(hours=2))
    assert sr["n"] == 8 and sr["agree"] == 8 and sum(v["n"] for v in sr["by_stratum"].values()) == 8
    rewrite_sheet(tmp_path / "rs.csv", lambda rows: [{**r, "label_baru": ""} if r["answer_id"] == items["R03"] else r for r in rows])
    with pytest.raises(ValueError, match=re.escape(f"{items['R03']}: label ''")):  # lembar lama tidak punya item_id: pesan memakai answer_id seperti dulu
        labeling.import_relabel_sheet(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, PROTO, tmp_path / "rl2.jsonl", tmp_path / "rr2.json", now=T0 + timedelta(hours=25))


def test_relabel_and_second_rater_report_agreement_by_stratum_and_without_mutations(tmp_path):
    allp, first, items, flipped = relabel_case(tmp_path, flip_natural=True)  # semua mutasi sepakat; satu jawaban asli (pertanyaan-berjawab) berbeda
    res = labeling.import_relabel_sheet(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, PROTO, tmp_path / "rl.jsonl", tmp_path / "rr.json", now=T0 + timedelta(hours=25))
    sr = labeling.import_second_rater(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, tmp_path / "sr.jsonl", tmp_path / "sr.json",
                                      rater="Orang Kedua", ai_assistance="none", now=T0 + timedelta(hours=2))
    count = lambda pred: sum(pred(first[a]) for a in items.values())
    n_mut, n_probe = count(lambda r: r["origin"] == "mutation"), count(lambda r: r["origin"] != "mutation" and r["kind"] == "not_in_corpus")
    n_nat = count(lambda r: r["origin"] != "mutation" and r["kind"] != "not_in_corpus")
    assert n_mut >= 2 and n_probe >= 2 and n_nat >= 1 and n_mut + n_probe + n_nat == 8
    for out in (res, sr):
        assert out["n"] == 8 and out["agree"] == 7 and out["pct"] == 87.5  # angka keseluruhan tetap
        assert [d["answer_id"] for d in out["discrepancies"]] == [items[flipped]]
        assert out["by_stratum"] == {"mutation": {"n": n_mut, "agree": n_mut, "pct": 100.0}, "probe": {"n": n_probe, "agree": n_probe, "pct": 100.0},
                                     "natural_answerable": {"n": n_nat, "agree": n_nat - 1, "pct": round(100 * (n_nat - 1) / n_nat, 1)}}
        nat = out["natural_only"]
        assert (nat["n"], nat["agree"], nat["pct"]) == (8 - n_mut, 7 - n_mut, round(100 * (7 - n_mut) / (8 - n_mut), 1)) and nat["pct"] < out["pct"]
        assert "discrepancies" not in nat and {"kappa", "kappa_note"} <= set(nat)
        assert json.loads((tmp_path / ("rr.json" if out is res else "sr.json")).read_text(encoding="utf-8"))["natural_only"] == nat


def test_second_rater_accepts_item_id_sheet_rejects_unknown_items_and_does_not_reveal_origin(tmp_path):
    allp, first, items, _ = relabel_case(tmp_path)
    kw = dict(rater="Orang Kedua", ai_assistance="none", now=T0 + timedelta(hours=2))
    args = (tmp_path / "rs.csv", tmp_path / "rsample.json", allp)
    good = (tmp_path / "rs.csv").read_bytes()
    res = labeling.import_second_rater(*args, tmp_path / "ok.jsonl", tmp_path / "ok.json", **kw)
    assert res["n"] == 8 and res["agree"] == 8 and res["eligible_as_inter_rater"] is True
    recs = [json.loads(x) for x in (tmp_path / "ok.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["answer_id"] for r in recs} == set(items.values()) and all(r["label_first"] == first[r["answer_id"]]["label"] for r in recs)
    rewrite_sheet(tmp_path / "rs.csv", lambda rows: rows + [{**rows[0], "item_id": "R99"}])
    with pytest.raises(ValueError, match="R99: item_id tidak ada"):
        labeling.import_second_rater(*args, tmp_path / "u.jsonl", tmp_path / "u.json", **kw)
    (tmp_path / "rs.csv").write_bytes(good)
    rewrite_sheet(tmp_path / "rs.csv", lambda rows: [{**r, "label_baru": ""} if r["item_id"] == "R04" else r for r in rows])
    with pytest.raises(ValueError) as ex:
        labeling.import_second_rater(*args, tmp_path / "v.jsonl", tmp_path / "v.json", **kw)
    assert "R04: label ''" in str(ex.value) and not any(a in str(ex.value) for a in items.values())
    assert not list(tmp_path.glob("[uv].json*"))


def test_written_summary_carries_natural_only_and_stratum_lines_from_the_relabel_result(tmp_path):
    allp, first, items, flipped = relabel_case(tmp_path, flip_natural=True)
    res = labeling.import_relabel_sheet(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, PROTO, tmp_path / "rl.jsonl", tmp_path / "rr.json", now=T0 + timedelta(hours=25))
    (tmp_path / "sv.json").write_text(json.dumps(["2026-11-06; rekan mahasiswa; menolak; tidak punya waktu"]))
    md = labeling.write_pre_evaluator_summary(allp, tmp_path / "mlog.json", tmp_path / "rr.json", tmp_path / "sv.json", tmp_path / "sum.md")
    nat = res["natural_only"]
    assert "Kesepakatan 7/8 = 87.5%." in md and f"Tanpa mutasi (jawaban asli saja): {nat['agree']}/{nat['n']} = {nat['pct']}%." in md
    assert all(f"- {k}: {v['agree']}/{v['n']} = {v['pct']}%" in md for k, v in res["by_stratum"].items()) and "- mutation: " in md


def test_pre_evaluator_summary_has_no_scores_and_requires_second_validator_log(tmp_path):
    allp = merged(tmp_path)
    labeling.export_relabel_sheet(allp, CASES, PROTO, tmp_path / "rs.csv", tmp_path / "rsample.json")
    first = first_by_item(allp, tmp_path)
    fill(tmp_path / "rs.csv", lambda r: first[r["item_id"]], col="label_baru")
    labeling.import_relabel_sheet(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, PROTO, tmp_path / "rl.jsonl", tmp_path / "rr.json", now=T0 + timedelta(hours=30))
    (tmp_path / "sv.json").write_text("[]")
    with pytest.raises(ValueError, match="minimal satu catatan"):
        labeling.write_pre_evaluator_summary(allp, tmp_path / "mlog.json", tmp_path / "rr.json", tmp_path / "sv.json", tmp_path / "sum.md")
    (tmp_path / "sv.json").write_text(json.dumps(["2026-11-06; rekan mahasiswa; menolak; tidak punya waktu"]))
    md = labeling.write_pre_evaluator_summary(allp, tmp_path / "mlog.json", tmp_path / "rr.json", tmp_path / "sv.json", tmp_path / "sum.md")
    assert "Track M: 16 pasangan" in md and "Kesepakatan 8/8 = 100.0%" in md and "rekan mahasiswa" in md
    assert "TIDAK_LAYAK alami: 1" in md
    assert not re.search(r"\bH\b\s*[=:]|\bF1\b|skor evaluator\s*[=:]", md)


def test_all_labeling_paths_refuse_to_overwrite(tmp_path):
    allp = merged(tmp_path)
    labeling.export_relabel_sheet(allp, CASES, PROTO, tmp_path / "rs.csv", tmp_path / "rsample.json")
    with pytest.raises(FileExistsError):
        labeling.merge_labels(tmp_path / "labels.jsonl", tmp_path / "mutants.jsonl", allp)
    with pytest.raises(FileExistsError):
        labeling.export_mutant_sheet(tmp_path / "labels.jsonl", CASES, [], PROTO, tmp_path / "msheet.csv")
    with pytest.raises(FileExistsError):
        labeling.export_relabel_sheet(allp, CASES, PROTO, tmp_path / "rs.csv", tmp_path / "rsample.json")


# ------------------------------------------------------------------ kolom abstain (D14: label tahap II diturunkan mekanis)

def _sheet_rows(tmp_path):
    return list(csv.DictReader(open(tmp_path / "sheet.csv", newline="", encoding="utf-8-sig")))


def _write_sheet(tmp_path, rows):
    with open(tmp_path / "sheet.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)


def test_sheet_has_blank_abstain_column_and_import_stores_it_as_bool_only_for_answerable(tmp_path):
    ans = answers_file(tmp_path)
    labeling.export_label_sheet(ans, CASES, PROTO, tmp_path / "sheet.csv")
    assert all(r["abstain"] == "" for r in _sheet_rows(tmp_path))  # lembar tidak menyarankan isi
    fill(tmp_path / "sheet.csv", lambda r: "LAYAK")
    rows = _sheet_rows(tmp_path)
    next(r for r in rows if r["case_id"] == "R03").update(abstain="  YA ", label="TIDAK_LAYAK")  # abstain pada berjawab = TIDAK_LAYAK (tahap I)
    _write_sheet(tmp_path, rows)
    labeling.import_label_sheet(tmp_path / "sheet.csv", ans, CASES, "Galih", tmp_path / "l.jsonl", now=T0)
    st = {r["case_id"]: r for r in map(json.loads, (tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines())}
    assert st["R03"]["abstain"] is True and st["R02"]["abstain"] is False and st["R17"]["abstain"] is None


def test_import_requires_abstain_for_answerable_and_rejects_layak_abstention_on_answerable(tmp_path):
    ans = answers_file(tmp_path)
    labeling.export_label_sheet(ans, CASES, PROTO, tmp_path / "sheet.csv")
    fill(tmp_path / "sheet.csv", lambda r: "LAYAK")
    rows = _sheet_rows(tmp_path)
    next(r for r in rows if r["case_id"] == "R02").update(abstain="")
    _write_sheet(tmp_path, rows)
    with pytest.raises(ValueError, match="abstain wajib"):
        labeling.import_label_sheet(tmp_path / "sheet.csv", ans, CASES, "Galih", tmp_path / "a.jsonl", now=T0)
    rows = _sheet_rows(tmp_path)
    next(r for r in rows if r["case_id"] == "R02").update(abstain="ya")  # label tetap LAYAK: bertentangan dengan rubrik tahap I
    _write_sheet(tmp_path, rows)
    with pytest.raises(ValueError, match="abstain.*TIDAK_LAYAK"):
        labeling.import_label_sheet(tmp_path / "sheet.csv", ans, CASES, "Galih", tmp_path / "b.jsonl", now=T0)
    assert not list(tmp_path.glob("[ab].jsonl"))


# ------------------------------------------------------------------ dua mutasi per jawaban (Studi 2, D20)

def proto_two_per_answer():
    import copy

    p = copy.deepcopy(PROTO)
    p["track_m"]["mutations_per_answer"] = 2
    p["track_m"]["mutation"]["families_by_question_type"] = {
        "numeric_duration": ["numeric_value", "unit"], "numeric_date": ["date", "negation"], "numeric_money": ["numeric_value", "negation"],
        "numeric_count": ["numeric_value", "negation"], "numeric_range": ["numeric_value", "negation"], "numeric_percent": ["numeric_value", "negation"],
        "definition": ["negation", "clause_deletion"]}
    return p


def test_two_per_answer_sheet_has_slot_rows_in_candidate_order_with_prefilled_families(tmp_path):
    p2 = proto_two_per_answer()
    lp = label_all(tmp_path)
    info, rows = mutant_sheet(tmp_path, lp, fill_n=0, proto=p2)
    assert info["candidates"] == 16 and info["target_pairs"] == 32 and info["mutations_per_answer"] == 2
    assert [r["order"] for r in rows] == [str(i) for i in range(1, 33)] and [r["slot"] for r in rows] == ["1", "2"] * 16
    assert [r["case_id"] for r in rows[0::2]] == [r["case_id"] for r in rows[1::2]]  # dua baris berurutan per jawaban
    fams = P.assign_mutation_slots([{"case_id": r["case_id"], "question_type": r["question_type"]} for r in rows[0::2]],
                                   p2["track_m"]["mutation"]["families_by_question_type"], 2)
    assert all([a["mutation_family"], b["mutation_family"]] == fams[a["case_id"]] for a, b in zip(rows[0::2], rows[1::2]))
    assert "slot" not in mutant_sheet(tmp_path, lp, fill_n=0, out="m1.csv")[1][0]  # K=1 tidak berubah


def test_two_per_answer_import_creates_unique_ids_pairs_and_merges_cleanly(tmp_path):
    p2 = proto_two_per_answer()
    lp = label_all(tmp_path)
    mutant_sheet(tmp_path, lp, proto=p2)
    res = labeling.import_mutant_sheet(tmp_path / "msheet.csv", lp, CASES, chunks_file(tmp_path), p2, "Galih", tmp_path / "mutants.jsonl",
                                       tmp_path / "mlog.json", now=T0 + timedelta(hours=1))
    assert res["n_pairs"] == 32 and res["shortfall"] == 0
    muts = [json.loads(x) for x in (tmp_path / "mutants.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len({m["answer_id"] for m in muts}) == 32 and len({m["pair_id"] for m in muts}) == 32
    assert {m["answer_id"] for m in muts if m["case_id"] == "R01"} == {"M1:R01", "M2:R01"}
    assert {m["mutated_from_answer_id"] for m in muts if m["case_id"] == "R01"} == {"run1:R01"}
    log = json.loads((tmp_path / "mlog.json").read_text(encoding="utf-8"))
    assert {a["slot"] for a in log["accepted"]} == {1, 2}
    merged = labeling.merge_labels(lp, tmp_path / "mutants.jsonl", tmp_path / "all.jsonl")
    assert merged == {"n": 52, "natural": 20, "mutation": 32}


def test_two_per_answer_import_rejects_changed_slot_family_and_missing_slot_rows(tmp_path):
    p2 = proto_two_per_answer()
    lp = label_all(tmp_path)
    _, rows = mutant_sheet(tmp_path, lp, proto=p2)
    other = "unit" if rows[0]["mutation_family"] != "unit" else "negation"
    rows[0]["mutation_family"] = other
    with open(tmp_path / "msheet.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with pytest.raises(ValueError, match="family"):
        labeling.import_mutant_sheet(tmp_path / "msheet.csv", lp, CASES, chunks_file(tmp_path), p2, "Galih", tmp_path / "m.jsonl", tmp_path / "l.json", now=T0)
    rows[0]["mutation_family"] = P.assign_mutation_slots([{"case_id": rows[0]["case_id"], "question_type": rows[0]["question_type"]}],
                                                         p2["track_m"]["mutation"]["families_by_question_type"], 2)[rows[0]["case_id"]][0]
    with open(tmp_path / "msheet.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows[:-1])  # baris slot terakhir dihapus
    with pytest.raises(ValueError, match="urutan"):
        labeling.import_mutant_sheet(tmp_path / "msheet.csv", lp, CASES, chunks_file(tmp_path), p2, "Galih", tmp_path / "m2.jsonl", tmp_path / "l2.json", now=T0)
    rows[0]["slot"], rows[1]["slot"] = "2", "1"  # nomor slot ditukar: urutan pra-registrasi dilanggar walau case_id sama
    with open(tmp_path / "msheet.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with pytest.raises(ValueError, match="urutan"):
        labeling.import_mutant_sheet(tmp_path / "msheet.csv", lp, CASES, chunks_file(tmp_path), p2, "Galih", tmp_path / "m3.jsonl", tmp_path / "l3.json", now=T0)


# ------------------------------------------------------------------ lari tambahan (Studi 2, k = 3)

def label_run(tmp_path, run):
    ans = answers_file(tmp_path, run=run)
    labeling.export_label_sheet(ans, CASES, PROTO, tmp_path / f"sheet_{run}.csv")
    fill(tmp_path / f"sheet_{run}.csv", lambda r: "LAYAK")
    labeling.import_label_sheet(tmp_path / f"sheet_{run}.csv", ans, CASES, "Galih", tmp_path / labeling.label_file(run).name, now=T0)
    return tmp_path / labeling.label_file(run).name


def test_label_file_names_keep_run1_path_and_separate_extra_runs():
    assert labeling.label_file("run1").name == "labels.jsonl" and labeling.label_file("run2").name == "labels_run2.jsonl"


def test_merge_includes_extra_run_labels_with_unique_ids_and_mutations_only_from_primary_run(tmp_path):
    lp = label_all(tmp_path)
    extra = [label_run(tmp_path, "run2"), label_run(tmp_path, "run3")]
    mutant_sheet(tmp_path, lp)
    labeling.import_mutant_sheet(tmp_path / "msheet.csv", lp, CASES, chunks_file(tmp_path), PROTO, "Galih", tmp_path / "mutants.jsonl", tmp_path / "mlog.json", now=T0 + timedelta(hours=1))
    merged = labeling.merge_labels(lp, tmp_path / "mutants.jsonl", tmp_path / "all.jsonl", extra_label_paths=extra)
    assert merged == {"n": 76, "natural": 60, "mutation": 16}
    rows = [json.loads(x) for x in (tmp_path / "all.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["run_id"] for r in rows if r["origin"] == "natural"} == {"run1", "run2", "run3"} and {r["run_id"] for r in rows if r["origin"] == "mutation"} == {"run1"}
    with pytest.raises(ValueError, match="answer_id ganda"):
        labeling.merge_labels(lp, tmp_path / "mutants.jsonl", tmp_path / "dup.jsonl", extra_label_paths=[extra[0], extra[0]])


# ------------------------------------------------------------------ validator kedua (Studi 2, D24)

def second_rater_sheet(tmp_path, flip_first=1):
    allp = merged(tmp_path)
    labeling.export_relabel_sheet(allp, CASES, PROTO, tmp_path / "rs.csv", tmp_path / "rsample.json")
    first = first_by_item(allp, tmp_path)
    n = {"v": 0}

    def second(r):
        n["v"] += 1
        return first[r["item_id"]] if n["v"] > flip_first else ("LAYAK" if first[r["item_id"]] == "TIDAK_LAYAK" else "TIDAK_LAYAK")
    fill(tmp_path / "rs.csv", second, col="label_baru")
    return allp


def test_second_rater_import_reports_inter_rater_agreement_by_stratum_and_disclosure(tmp_path):
    allp = second_rater_sheet(tmp_path)
    res = labeling.import_second_rater(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, tmp_path / "sr.jsonl", tmp_path / "sr.json",
                                       rater="Orang Kedua", ai_assistance="none", now=T0 + timedelta(hours=2))
    assert res["n"] == 8 and res["agree"] == 7 and res["pct"] == 87.5 and res["eligible_as_inter_rater"] is True
    assert res["rater"] == "Orang Kedua" and res["first_validator"] == "Galih" and res["ai_assistance"] == "none"
    comp = json.loads((tmp_path / "rsample.json").read_text(encoding="utf-8"))["composition"]
    assert res["by_stratum"]["mutation"]["n"] == comp["mutation"] and res["by_stratum"]["probe"]["n"] == comp["probe"]  # stratum benar-benar dibedakan
    assert sum(v["n"] for v in res["by_stratum"].values()) == 8 and sum(v["agree"] for v in res["by_stratum"].values()) == 7
    rows = [json.loads(x) for x in (tmp_path / "sr.jsonl").read_text(encoding="utf-8").splitlines()]
    first = {r["answer_id"]: r["label"] for r in map(json.loads, allp.read_text(encoding="utf-8").splitlines())}
    assert len(rows) == 8 and {r["rater"] for r in rows} == {"Orang Kedua"}
    assert all(r["label_first"] == first[r["answer_id"]] for r in rows)  # label_first = label peneliti; label_second = isian penilai kedua
    assert sum(r["label_first"] != r["label_second"] for r in rows) == 1
    ai = labeling.import_second_rater(tmp_path / "rs.csv", tmp_path / "rsample.json", allp, tmp_path / "sr2.jsonl", tmp_path / "sr2.json",
                                      rater="Orang Kedua", ai_assistance="disclosed", now=T0 + timedelta(hours=2))
    assert ai["eligible_as_inter_rater"] is False  # berbantuan AI: dilaporkan, tidak dihitung sebagai inter-rater independen


def test_second_rater_must_be_a_different_person_with_declared_ai_use_and_blind_sheet(tmp_path):
    allp = second_rater_sheet(tmp_path)
    kw = dict(now=T0 + timedelta(hours=2))
    args = (tmp_path / "rs.csv", tmp_path / "rsample.json", allp)
    with pytest.raises(ValueError, match="orang yang sama"):
        labeling.import_second_rater(*args, tmp_path / "a.jsonl", tmp_path / "a.json", rater=" galih ", ai_assistance="none", **kw)
    with pytest.raises(ValueError, match="ai_assistance"):
        labeling.import_second_rater(*args, tmp_path / "b.jsonl", tmp_path / "b.json", rater="Orang Kedua", ai_assistance="", **kw)
    rows = list(csv.DictReader(open(tmp_path / "rs.csv", newline="", encoding="utf-8-sig")))
    rows[0]["label_first"] = "LAYAK"  # lembar bocor label pertama
    with open(tmp_path / "leak.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with pytest.raises(ValueError, match="buta"):
        labeling.import_second_rater(tmp_path / "leak.csv", tmp_path / "rsample.json", allp, tmp_path / "c.jsonl", tmp_path / "c.json", rater="Orang Kedua", ai_assistance="none", **kw)
    assert not list(tmp_path.glob("[abc].json*"))  # tidak ada keluaran parsial
    labeling.import_second_rater(*args, tmp_path / "ok.jsonl", tmp_path / "ok.json", rater="Orang Kedua", ai_assistance="none", **kw)
    with pytest.raises(FileExistsError):
        labeling.import_second_rater(*args, tmp_path / "ok.jsonl", tmp_path / "ok2.json", rater="Orang Kedua", ai_assistance="none", **kw)
