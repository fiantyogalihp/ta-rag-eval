"""Tes pemeriksaan silang OCR dokumen scan. Hermetik: mesin OCR palsu diinjeksikan, PDF sintetis reportlab (poppler dipakai nyata).
Tes mesin RapidOCR asli hanya jalan bila `rapidocr_onnxruntime` terpasang. Fixture sintetis ini TIDAK boleh masuk data/ (aturan 16/23)."""

import importlib.metadata
import importlib.util
import json
import struct
import sys
import types
from pathlib import Path

import pytest

from ta_rag import ocr_check as O
from ta_rag.corpus import sha256_file

reportlab = pytest.importorskip("reportlab")
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

PAGES = [
    ["Pasal 1", "Peserta dapat mengganti FKTP setelah jangka waktu 3 (tiga) bulan sejak terdaftar."],
    ["Pasal 2", "Klaim dibayarkan paling lambat 15 hari setelah berkas klaim diterima lengkap oleh pihak BPJS."],
]
HAS_RAPIDOCR = importlib.util.find_spec("rapidocr_onnxruntime") is not None


def make_pdf(path, pages=PAGES):
    c = canvas.Canvas(str(path), pagesize=A4)
    for lines in pages:
        y = 780
        for ln in lines:
            c.drawString(60, y, ln)
            y -= 20
        c.showPage()
    c.save()


def L(text, x=100, cy=100.0, h=30.0):
    return {"text": text, "conf": 0.99, "x": x, "cy": cy, "h": h}


def lines_of(texts):
    return [L(t, cy=100.0 + 60 * i) for i, t in enumerate(texts)]


class FakeEngine:
    """Meniru OCR sempurna: mengembalikan teks halaman sintetis yang sama dengan lapisan teks PDF-nya."""

    def __init__(self, pages=PAGES):
        self.pages, self.calls = pages, []

    def __call__(self, img):
        assert img.read_bytes()[:4] == b"\x89PNG"
        self.calls.append(img.name)
        return lines_of(self.pages[int(img.stem[1:]) - 1])


# ------------------------------------------------------------------ fungsi murni

def test_squash_keeps_only_lowercase_alnum_and_normalizes_first():
    assert O.squash("Rp 8.000,00 Bidang-Kerja") == "rp800000bidangkerja"


def test_reading_order_puts_verse_marker_before_its_own_line():
    lines = [L("Apabila reviu", x=200, cy=100), L("(5)", x=50, cy=104, h=20), L("diselesaikan sesuai", x=120, cy=160)]
    assert [l["text"] for l in O.reading_order(lines)] == ["(5)", "Apabila reviu", "diselesaikan sesuai"]


def test_reading_order_keeps_tight_lines_apart_but_merges_at_half_height():
    tight = [L("baris satu", x=200, cy=100), L("baris dua", x=50, cy=118)]  # selisih 18 > 15: baris berbeda
    assert [l["text"] for l in O.reading_order(tight)] == ["baris satu", "baris dua"]
    edge = [L("kanan", x=200, cy=100), L("kiri", x=50, cy=115)]  # selisih = toleransi: sebaris, kiri dulu
    assert [l["text"] for l in O.reading_order(edge)] == ["kiri", "kanan"]
    assert O.reading_order([]) == []


def test_page_text_is_normalized_in_reading_order():
    assert O.page_text([L("Pasal  17", x=50, cy=200), L("(1) TARIF", x=50, cy=100)]) == "(1) tarif pasal 17"


def test_agreement_identical_and_empty_are_perfect():
    a = O.agreement("peserta jaminan kesehatan", "peserta jaminan kesehatan")
    assert (a["recall"], a["precision"], a["only_layer"], a["only_ocr"]) == (1.0, 1.0, [], [])
    assert O.agreement("dan atau", "dan atau")["recall"] == 1.0  # kata < 5 huruf tidak dihitung: tidak ada pembagian nol


def test_agreement_reports_direction_of_each_miss():
    a = O.agreement("peserta jaminan kesehatan", "peserta jaminan kesehatan nasional")
    assert a["only_layer"] == ["nasional"] and a["only_ocr"] == []
    assert a["recall"] == pytest.approx(0.75) and a["precision"] == 1.0
    b = O.agreement("peserta jaminan kesehatan nasional", "peserta jaminan kesehatan")
    assert b["only_ocr"] == ["nasional"] and b["only_layer"] == []
    assert b["precision"] == pytest.approx(0.75) and b["recall"] == 1.0
    assert O.agreement("peserta", "peserta tarif")["only_layer"] == ["tarif"]  # kata tepat 5 huruf tetap dihitung


def test_agreement_tolerates_merged_and_split_words():
    assert O.agreement("bidangketenagakerjaan", "bidang ketenagakerjaan")["recall"] == 1.0
    assert O.agreement("bidang ketenagakerjaan", "bidangketenagakerjaan")["precision"] == 1.0


@pytest.mark.parametrize("n,k", [(0, 0), (6, 0), (7, 1), (9, 1), (10, 2), (14, 2), (15, 3), (27, 5)])
def test_max_edits_scales_with_term_length(n, k):
    assert O.max_edits(n) == k


@pytest.mark.parametrize("text,dist", [
    ("xxinsentifxx", 0), ("xxinsentitxx", 1), ("xxinsntifxx", 1), ("xxinsenxtifxx", 1),  # persis, ganti, hapus, sisip
    ("nsentif", 1), ("insentxf", 1), ("insantif", 1),  # kerusakan di awal / akhir / tengah
])
def test_near_edits_finds_minimum_distance_for_each_edit_kind(text, dist):
    assert O.near_edits("insentif", text, 1) == dist


def test_near_edits_rejects_beyond_tolerance_and_degenerate_input():
    assert O.near_edits("insentif", "inxentxf", 1) is None  # jarak 2 > k
    assert O.near_edits("insentif", "inxentxf", 2) == 2
    assert O.near_edits("insentif", "kalimatbiasatanpakaitan", 1) is None
    assert O.near_edits("", "abc", 1) is None and O.near_edits("abc", "", 1) is None


def test_search_term_classifies_exact_squashed_near_and_none():
    pages = {1: "tarif insentif fktp", 2: "insen tif", 3: "pemberian insentf kepada", 4: "tidak ada", 5: "insentif"}
    r = O.search_term("Insentif", pages)
    assert r == {"exact": [1, 5], "squashed": [2], "near": [[3, 1]]}


def test_search_term_short_terms_are_exact_only_and_empty_term_matches_nothing():
    assert O.search_term("bonus", {1: "bonas", 2: "ada bonus"}) == {"exact": [2], "squashed": [], "near": []}
    assert O.search_term(" - ", {1: "apa saja"}) == {"exact": [], "squashed": [], "near": []}


def test_search_term_multiword_matches_across_line_break():
    assert O.search_term("home care", {1: "layanan home\ncare rumah"})["exact"] == [1]


def case(cid, kind, **kw):
    return {"case_id": cid, "kind": kind, **kw}


def test_check_probes_flags_hits_in_either_source_and_scores_controls():
    ocr = {"d": {1: "tidak ada istilah di sini kecuali hubungan kerja", 2: "pemutusan hubungan kerja"}}
    layer = {"d": {1: "ada pesangon di lapisan bawaan", 2: "pemutusan hubungan kerja"}}
    cases = [case("T1", "not_in_corpus", absence_terms=["pesangon"]), case("T2", "not_in_corpus", absence_terms=["jampersal"]),
             case("T3", "answerable")]
    audit = {"probes": [{"case_id": "T2", "control_terms": {"hubungan kerja": {"d": [2], "d_lain": [1]}}},
                        {"case_id": "T1", "control_terms": {"pemutusan": {"d": [1, 2]}}}]}
    r = O.check_probes(cases, audit, ocr, layer)
    assert set(r) == {"T1", "T2"}
    assert r["T1"]["clean"] is False and r["T1"]["terms"]["pesangon"]["layer"]["exact"] == ["d:1"]
    assert r["T1"]["terms"]["pesangon"]["ocr"] == {"exact": [], "squashed": [], "near": []}
    assert r["T1"]["controls"]["pemutusan @ d"]["missing"] == [1] and r["T1"]["controls_ok"] is False  # OCR tidak sensitif
    assert r["T2"]["clean"] is True and r["T2"]["controls_ok"] is True
    assert list(r["T2"]["controls"]) == ["hubungan kerja @ d"]  # doc kontrol yang bukan dokumen scan diabaikan
    assert r["T2"]["controls"]["hubungan kerja @ d"] == {"expected": [2], "missing": [], "extra": [1], "recall": 1.0}  # OCR juga menemukan hlm 1
    assert r["T1"]["controls"]["pemutusan @ d"]["recall"] == 0.5


def test_control_passes_at_recall_threshold_and_fails_below():
    case_ = [case("T1", "not_in_corpus", absence_terms=["zzz"])]
    audit = {"probes": [{"case_id": "T1", "control_terms": {"iuran": {"d": [1, 2, 3, 4, 5]}}}]}
    ocr_ok = {"d": {p: "iuran" for p in (1, 2, 3, 4)} | {5: "x"}}
    r = O.check_probes(case_, audit, ocr_ok, {"d": {}})["T1"]
    assert r["controls"]["iuran @ d"]["recall"] == 0.8 and r["controls_ok"] is True  # tepat di ambang: lolos
    ocr_low = {"d": {p: "iuran" for p in (1, 2, 3)} | {4: "x", 5: "x"}}
    r = O.check_probes(case_, audit, ocr_low, {"d": {}})["T1"]
    assert r["controls"]["iuran @ d"]["recall"] == 0.6 and r["controls_ok"] is False
    audit2 = {"probes": [{"case_id": "T1", "control_terms": {"iuran": {"d": [1, 2, 3, 4, 5]}, "klaim": {"d": [1]}}}]}
    assert O.check_probes(case_, audit2, ocr_ok, {"d": {}})["T1"]["controls_ok"] is False  # satu kontrol gagal sudah cukup


def test_check_probes_without_controls_is_not_applicable_and_ocr_hit_is_not_clean():
    r = O.check_probes([case("T1", "not_in_corpus", absence_terms=["insentif"])], {}, {"d": {1: "pemberian insentf", 2: "insen tif"}}, {"d": {1: "x"}})
    assert r["T1"]["controls_ok"] is None and r["T1"]["clean"] is False
    assert r["T1"]["terms"]["insentif"]["ocr"] == {"exact": [], "squashed": ["d:2"], "near": [["d:1", 1]]}


def test_check_quotes_exact_and_detail_of_differences():
    q = "Peserta dapat mengganti FKTP setelah 3 (tiga) bulan."
    cases = [case("A", "answerable", source_doc_id="d", source_page=1, source_quote=q),
             case("B", "answerable", source_doc_id="d", source_page=2, source_quote=q),
             case("C", "answerable", source_doc_id="lain", source_page=1, source_quote=q),
             case("P", "not_in_corpus", source_doc_id="d", source_page=1)]
    ocr = {"d": {1: O.norm("(1) Peserta dapat mengganti FKTP setelah 3 (tiga) bulan."), 2: O.norm("Peserta dapat menggantl FKTP setelah 8 (tiga) bulan.")}}
    layer = {"d": {1: "x", 2: O.norm(q)}}
    r = O.check_quotes(cases, ocr, layer)
    assert set(r) == {"A", "B"}  # dokumen non-scan dan probe dilewati
    assert r["A"]["status"] == "COCOK" and r["A"]["exact_ocr"] and not r["A"]["exact_layer"]
    assert r["A"]["words_absent"] == [] and r["A"]["numbers_absent"] == []
    assert r["B"]["status"] == "PERIKSA" and not r["B"]["exact_ocr"] and r["B"]["exact_layer"]
    assert r["B"]["words_absent"] == ["mengganti"] and r["B"]["numbers_absent"] == ["3"]


def test_summarize_flags_each_kind_of_finding():
    ok = {"docs": {"d": {"agreement": {1: {"recall": 1.0, "precision": 0.96}}}},
          "probes": {"T1": {"clean": True, "controls_ok": None}}, "quotes": {"A": {"status": "COCOK"}}}
    s = O.summarize(ok)
    assert s["flagged"] is False and s["agreement_mean_recall_precision"] == {"d": [1.0, 0.96]}
    assert s["probes"] == "1/1 bersih" and s["quotes"] == "1/1 cocok"
    low = {**ok, "docs": {"d": {"agreement": {1: {"recall": 1.0, "precision": 1.0}, 2: {"recall": 0.95, "precision": 0.85}}}}}
    assert O.summarize(low)["low_agreement_pages"] == ["d:2"] and O.summarize(low)["flagged"]
    dirty = {**ok, "probes": {"T1": {"clean": False, "controls_ok": True}, "T2": {"clean": True, "controls_ok": False}}}
    s = O.summarize(dirty)
    assert s["probes_with_hits"] == ["T1"] and s["controls_failed"] == ["T2"] and s["probes"] == "1/2 bersih" and s["flagged"]
    bad = {**ok, "quotes": {"A": {"status": "COCOK"}, "B": {"status": "PERIKSA"}}}
    assert O.summarize(bad)["quotes_to_check"] == ["B"] and O.summarize(bad)["quotes"] == "1/2 cocok" and O.summarize(bad)["flagged"]


# ------------------------------------------------------------------ PDF, cache, dan alur penuh

def png_size(path):
    return struct.unpack(">II", path.read_bytes()[16:24])


def test_render_page_scales_with_dpi(tmp_path):
    pdf = tmp_path / "d.pdf"
    make_pdf(pdf)
    a, b = O.render_page(pdf, 1, 50, tmp_path), O.render_page(pdf, 2, 100, tmp_path)
    assert a.name == "p1.png" and b.name == "p2.png"
    (wa, ha), (wb, hb) = png_size(a), png_size(b)
    assert abs(wb - 2 * wa) <= 2 and abs(hb - 2 * ha) <= 2 and 410 <= wa <= 417


def test_ocr_document_reuses_cache_only_when_every_input_is_unchanged(tmp_path):
    pdf, cache, eng = tmp_path / "d.pdf", tmp_path / "c.json", FakeEngine()
    make_pdf(pdf)
    d = sha256_file(pdf)
    p1 = O.ocr_document(pdf, d, eng, {"engine": "f"}, cache, dpi=40)
    assert eng.calls == ["p1.png", "p2.png"] and sorted(p1) == [1, 2]
    assert O.ocr_document(pdf, d, eng, {"engine": "f"}, cache, dpi=40) == p1 and len(eng.calls) == 2  # cache dipakai, kunci halaman int
    O.ocr_document(pdf, d, eng, {"engine": "g"}, cache, dpi=40)
    assert len(eng.calls) == 4  # parameter mesin berubah
    O.ocr_document(pdf, d, eng, {"engine": "g"}, cache, dpi=41)
    assert len(eng.calls) == 6  # dpi berubah
    O.ocr_document(pdf, "0" * 64, eng, {"engine": "g"}, cache, dpi=41)
    assert len(eng.calls) == 8  # PDF berubah
    assert json.loads(cache.read_text())["meta"] == {"sha256": "0" * 64, "dpi": 41, "engine": "g"}


@pytest.fixture()
def world(tmp_path):
    pdf_dir = tmp_path / "pdf"
    pdf_dir.mkdir()
    make_pdf(pdf_dir / "Dok_Scan.pdf")
    cfg = {"documents": [{"doc_id": "dok_scan", "file": "Dok_Scan.pdf", "sha256": sha256_file(pdf_dir / "Dok_Scan.pdf")}]}
    cases = [case("T1", "answerable", source_doc_id="dok_scan", source_page=1, source_quote=PAGES[0][1]),
             case("T2", "answerable", source_doc_id="dok_digital", source_page=1, source_quote="tidak diperiksa"),
             case("T3", "not_in_corpus", absence_terms=["pesangon"], source_doc_id="dok_scan")]
    audit = {"manual_check_required_docs": ["dok_scan"], "probes": [{"case_id": "T3", "control_terms": {"klaim": {"dok_scan": [2]}}}]}
    return cfg, cases, audit, pdf_dir, tmp_path / "out"


def go(world, engine=None, **kw):
    cfg, cases, audit, pdf_dir, out = world
    return O.run(cfg, cases, audit, pdf_dir, out, engine or FakeEngine(), {"engine": "fake"}, dpi=40, **kw)


def test_run_clean_document_writes_report_and_text_and_flags_nothing(world):
    rep = go(world)
    out = world[4]
    assert rep["summary"]["flagged"] is False and rep["summary"]["probes"] == "1/1 bersih" and rep["summary"]["quotes"] == "1/1 cocok"
    assert set(rep["quotes"]) == {"T1"} and rep["probes"]["T3"]["controls_ok"] is True
    ag = rep["docs"]["dok_scan"]["agreement"]
    assert rep["docs"]["dok_scan"]["pages"] == 2 and ag[1]["recall"] == ag[2]["recall"] == ag[1]["precision"] == 1.0
    assert rep["docs"]["dok_scan"]["sha256"] == world[0]["documents"][0]["sha256"] and rep["engine"] == {"engine": "fake"}
    assert json.loads((out / "crosscheck_report.json").read_text())["summary"] == json.loads(json.dumps(rep["summary"]))
    txt = (out / "ocr_dok_scan.txt").read_text()
    assert "===== hlm 1 =====\nPasal 1\nPeserta dapat" in txt and "===== hlm 2 =====" in txt
    assert (out / "ocr_dok_scan.json").is_file()


def test_run_flags_probe_term_found_by_ocr(world):
    eng = FakeEngine([PAGES[0], PAGES[1] + ["Uang pesangon dibayarkan sekali."]])
    rep = go(world, eng)
    assert rep["summary"]["probes_with_hits"] == ["T3"] and rep["summary"]["flagged"] is True
    assert rep["probes"]["T3"]["terms"]["pesangon"]["ocr"]["exact"] == ["dok_scan:2"]


def test_run_flags_page_where_ocr_and_text_layer_disagree(world):
    rep = go(world, FakeEngine([PAGES[0], ["qqqqq wwwww eeeee rrrrr"]]))
    assert rep["summary"]["low_agreement_pages"] == ["dok_scan:2"] and rep["summary"]["flagged"] is True
    assert rep["docs"]["dok_scan"]["agreement"][2]["recall"] == 0.0
    assert rep["summary"]["controls_failed"] == ["T3"]  # OCR tak menemukan kontrol 'klaim' pada hlm 2


def test_run_rejects_pdf_that_differs_from_registered_hash_and_unknown_docs(world):
    cfg = world[0]
    cfg["documents"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="sha256"):
        go(world)
    cfg["documents"][0]["sha256"] = sha256_file(world[3] / "Dok_Scan.pdf")
    with pytest.raises(ValueError, match="tak dikenal"):
        go(world, doc_ids=["tidak_ada"])
    world[2]["manual_check_required_docs"] = []
    with pytest.raises(ValueError, match="tak dikenal"):
        go(world)
    assert go(world, doc_ids=["dok_scan"])["summary"]["flagged"] is False  # --doc-id mengganti daftar audit


def write_inputs(world, tmp_path):
    cfg, cases, audit, pdf_dir, out = world
    paths = {"config": tmp_path / "corpus.json", "cases": tmp_path / "cases.jsonl", "audit": tmp_path / "audit.json"}
    paths["config"].write_text(json.dumps(cfg))
    paths["cases"].write_text("\n".join(json.dumps(c) for c in cases))
    paths["audit"].write_text(json.dumps(audit))
    return ["--config", str(paths["config"]), "--cases", str(paths["cases"]), "--audit", str(paths["audit"]),
            "--pdf-dir", str(pdf_dir), "--out-dir", str(out), "--dpi", "40"]


def test_main_exit_codes_and_disclaimer(world, tmp_path, monkeypatch, capsys):
    args = write_inputs(world, tmp_path)
    monkeypatch.setattr(O, "rapidocr_engine", lambda: (FakeEngine(), {"engine": "fake"}))
    assert O.main(args) == 0
    out = capsys.readouterr().out
    assert '"flagged": false' in out and "BUKAN verifikasi manusia" in out
    monkeypatch.setattr(O, "rapidocr_engine", lambda: (FakeEngine([PAGES[0], ["qqqqq wwwww"]]), {"engine": "fake2"}))
    assert O.main(args) == 1
    monkeypatch.setattr(O, "rapidocr_engine", lambda: (_ for _ in ()).throw(RuntimeError("tanpa mesin")))
    assert O.main(args) == 2 and "GAGAL: tanpa mesin" in capsys.readouterr().err
    monkeypatch.setattr(O, "rapidocr_engine", lambda: (FakeEngine(), {"engine": "fake"}))
    cfg_path = tmp_path / "corpus.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["documents"][0]["sha256"] = "0" * 64
    cfg_path.write_text(json.dumps(cfg))
    assert O.main(args) == 2 and "sha256" in capsys.readouterr().err  # ValueError (PDF tak sesuai corpus.json) juga galat, bukan crash


def test_rapidocr_engine_explains_missing_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)  # None di sys.modules = impor gagal
    with pytest.raises(RuntimeError, match=r"\.\[ocr\]"):
        O.rapidocr_engine()


def test_rapidocr_adapter_sets_params_and_converts_boxes(monkeypatch):
    seen = {}

    class FakeRapid:
        def __init__(self):
            seen["eng"] = self

        def __call__(self, img, **kw):
            seen["img"], seen["kw"] = img, kw
            return [([[10, 20], [110, 22], [112, 50], [8, 48]], "Pasal 17", 0.987654)], None

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", types.SimpleNamespace(RapidOCR=FakeRapid))
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "9.9.9")
    read, info = O.rapidocr_engine()
    assert seen["eng"].max_side_len == O.MAX_SIDE
    assert info == {"engine": "rapidocr-onnxruntime", "version": "9.9.9", "max_side_len": O.MAX_SIDE, "use_cls": False}
    assert read(Path("x.png")) == [{"text": "Pasal 17", "conf": 0.988, "x": 8, "cy": 35.0, "h": 30.0}]
    assert seen["img"] == "x.png" and seen["kw"] == {"use_cls": False}  # sudut 0/180 tidak diklasifikasi
    FakeRapid.__call__ = lambda self, img, **kw: (None, None)
    assert read(Path("y.png")) == []


@pytest.mark.skipif(not HAS_RAPIDOCR, reason="butuh rapidocr-onnxruntime (pip install -e '.[ocr]')")
def test_real_engine_reads_an_image_only_pdf(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.utils import ImageReader

    img = Image.new("L", (1240, 520), 255)
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=56)
    d.text((60, 60), "Pasal 17", fill=0, font=font)
    d.text((60, 220), "Tarif Non Kapitasi sebesar Rp200.000,00 per hari", fill=0, font=font)
    pdf = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(pdf), pagesize=(1240 / 300 * 72, 520 / 300 * 72))  # tanpa lapisan teks: hanya gambar
    c.drawImage(ImageReader(img), 0, 0, width=1240 / 300 * 72, height=520 / 300 * 72)
    c.save()
    engine, info = O.rapidocr_engine()
    pages = O.ocr_document(pdf, sha256_file(pdf), engine, info, tmp_path / "c.json", dpi=300)
    assert info["engine"] == "rapidocr-onnxruntime" and info["use_cls"] is False
    box = pages[1][0]
    assert set(box) == {"text", "conf", "x", "cy", "h"} and box["h"] > 0
    s = O.squash(O.page_text(pages[1]))
    assert "pasal17" in s and "200000" in s and "kapitasi" in s
