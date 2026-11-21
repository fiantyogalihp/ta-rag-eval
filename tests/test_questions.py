"""Tes verifier pertanyaan. Hermetik (PDF sintetis reportlab) + tes PDF asli bila TA_RAG_PDF_DIR diset.

Tiap tes "gagal-benar" adalah MUTASI: rekaman valid diubah satu hal, verifier WAJIB menolak.
"""

import copy
import json
import os
from pathlib import Path

import pytest

from ta_rag import questions as Q
from ta_rag.corpus import sha256_file

reportlab = pytest.importorskip("reportlab")
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PAGES = [
    ["Pasal 1", "Peserta dapat mengganti FKTP setelah jangka waktu 3 (tiga) bulan sejak terdaftar."],
    ["Pasal 2", "Klaim dibayarkan paling lambat 15 hari setelah berkas klaim diterima lengkap oleh pihak BPJS."],
    ["Pasal 3", "Ketentuan penutup yang tidak memuat angka apa pun untuk pengujian ini saja."],
]


def make_pdf(path: Path, pages=PAGES):
    c = canvas.Canvas(str(path), pagesize=A4)
    for lines in pages:
        y = 780
        for ln in lines:
            c.drawString(60, y, ln)
            y -= 20
        c.showPage()
    c.save()


@pytest.fixture()
def env(tmp_path):
    pdf = tmp_path / "Dok_Uji.pdf"
    make_pdf(pdf)
    cfg = {"documents": [{
        "doc_id": "dok_uji", "file": "Dok_Uji.pdf", "sha256": sha256_file(pdf), "pages": 3, "pilot_pages": 3,
        "eval_role": "evidence_source", "index_page_scope": "1-3", "question_page_ranges": [[1, 3]],
        "provenance": {"class": "digital_asli"},
    }, {
        "doc_id": "dok_riwayat", "file": "Dok_Uji.pdf", "sha256": sha256_file(pdf), "pages": 3, "pilot_pages": 3,
        "eval_role": "distractor_only", "index_page_scope": "1-3", "provenance": {"class": "digital_asli"},
    }]}
    good = {
        "case_id": "R01", "track": "R", "kind": "answerable",
        "question": "Menurut Dokumen Uji, setelah berapa lama Peserta dapat mengganti FKTP?",
        "source_doc_id": "dok_uji", "source_page": 1,
        "source_quote": "Peserta dapat mengganti FKTP setelah jangka waktu 3 (tiga) bulan",
        "group_id": "uji:ganti", "evidence_group": "uji:p1", "question_type": "numeric_duration",
        "status": "DRAFT_UNVERIFIED_BY_HUMAN", "human_verified": False, "absence_terms": None,
        "reference_answer_draft": "3 (tiga) bulan.",
        "web_crosscheck": {"performed": False, "reason": "uji hermetik"},
    }
    probe = {
        "case_id": "R02", "track": "R", "kind": "not_in_corpus",
        "question": "Menurut Dokumen Uji, berapa tarif ambulans udara?", "source_doc_id": "dok_uji",
        "source_page": None, "source_quote": None, "absence_terms": ["ambulans udara"],
        "group_id": "uji:amb", "evidence_group": "uji:ABSENT:amb", "question_type": "not_in_corpus",
        "status": "DRAFT_UNVERIFIED_BY_HUMAN", "human_verified": False,
        "web_crosscheck": {"performed": False, "reason": "uji hermetik"},
    }
    return pdf.parent, cfg, good, probe


def issues(rec, pdf_dir, cfg):
    return Q.verify_record(rec, pdf_dir, cfg)


def test_valid_answerable_and_probe_pass(env):
    d, cfg, good, probe = env
    assert issues(good, d, cfg) == []
    assert issues(probe, d, cfg) == []


def test_quote_survives_line_wrap_and_case(env):
    d, cfg, good, _ = env
    good["source_quote"] = "KLAIM dibayarkan paling lambat 15 hari"
    good["reference_answer_draft"] = "Paling lambat 15 hari."
    good["source_page"] = 2
    assert issues(good, d, cfg) == []


def test_mutation_wrong_page_is_rejected(env):
    d, cfg, good, _ = env
    good["source_page"] = 2
    assert any("KUTIPAN TIDAK DITEMUKAN" in i for i in issues(good, d, cfg))


def test_mutation_altered_number_in_quote_is_rejected(env):
    d, cfg, good, _ = env
    good["source_quote"] = good["source_quote"].replace("3 (tiga)", "6 (enam)")
    good["reference_answer_draft"] = "6 (enam) bulan."  # supaya hanya kutipan yang salah, bukan skema
    assert any("KUTIPAN TIDAK DITEMUKAN" in i for i in issues(good, d, cfg))


def test_mutation_page_outside_question_range_is_rejected(env):
    d, cfg, good, _ = env
    cfg["documents"][0]["question_page_ranges"] = [[2, 3]]
    assert any("di luar rentang jangkar" in i for i in issues(good, d, cfg))


def test_mutation_distractor_doc_cannot_anchor_question(env):
    d, cfg, good, _ = env
    good["source_doc_id"] = "dok_riwayat"
    assert any("bukan evidence_source" in i for i in issues(good, d, cfg))


def test_mutation_tampered_pdf_hash_is_rejected(env):
    d, cfg, good, _ = env
    cfg["documents"][0]["sha256"] = "0" * 64
    assert any("sha256" in i for i in issues(good, d, cfg))


def test_mutation_record_hash_mismatch_is_rejected(env):
    d, cfg, good, _ = env
    good["source_pdf_sha256"] = "f" * 64
    assert any("source_pdf_sha256" in i for i in issues(good, d, cfg))


def test_mutation_missing_pdf_is_reported_not_silently_passed(env):
    d, cfg, good, _ = env
    cfg["documents"][0]["file"] = "Tidak_Ada.pdf"
    assert any("PDF tidak ditemukan" in i for i in issues(good, d, cfg))


def test_ambiguous_quote_on_two_pages_is_flagged(tmp_path):
    pdf = tmp_path / "Dok_Uji.pdf"
    make_pdf(pdf, [["Kalimat sama persis di dua halaman berbeda."], ["Kalimat sama persis di dua halaman berbeda."]])
    cfg = {"documents": [{"doc_id": "d", "file": "Dok_Uji.pdf", "sha256": sha256_file(pdf), "pilot_pages": 2,
                          "eval_role": "evidence_source", "index_page_scope": "1-2", "question_page_ranges": [[1, 2]]}]}
    rec = {"case_id": "R01", "track": "R", "kind": "answerable", "question": "Menurut D, apa itu?", "source_doc_id": "d",
           "source_page": 1, "source_quote": "Kalimat sama persis di dua halaman berbeda", "group_id": "g",
           "evidence_group": "e", "question_type": "x", "status": "DRAFT_UNVERIFIED_BY_HUMAN", "human_verified": False,
           "web_crosscheck": {"performed": False, "reason": "uji"}}
    assert any("jangkar ambigu" in i for i in issues(rec, tmp_path, cfg))


def test_mutation_probe_term_actually_present_is_rejected(env):
    d, cfg, _, probe = env
    probe["absence_terms"] = ["klaim dibayarkan"]  # ada di hlm. 2
    out = issues(probe, d, cfg)
    assert any("ADA di" in i and "bukan probe bersih" in i for i in out)


def test_probe_absence_checks_distractor_docs_too(env):
    d, cfg, _, probe = env
    probe["absence_terms"] = ["ketentuan penutup"]
    cfg["documents"][0]["index_page_scope"] = "1-2"  # hlm. 3 tidak terindeks pada dok utama...
    # ...tetapi dok distraktor mengindeks hlm. 1-3 sehingga istilah tetap terdeteksi.
    assert any("dok_riwayat" in i for i in issues(probe, d, cfg))


@pytest.mark.parametrize("mut, needle", [
    ({"question": "Berapa lama ganti FKTP?"}, "Menurut"),
    ({"question": "Menurut Dokumen Uji, berapa dosis obat per hari"}, "tanda tanya"),
    ({"question": "Menurut Dokumen Uji, berapa mg dosis yang dijamin?"}, "dosis/klinis"),
    ({"source_quote": "pendek"}, "terlalu pendek"),
    ({"source_page": 0}, "source_page"),
    ({"source_page": "1"}, "source_page"),
    ({"kind": "lainnya"}, "kind"),
    ({"status": "HUMAN_VERIFIED", "human_verified": True}, "validator"),
    ({"human_verified": True}, "human_verified=false"),
    ({"absence_terms": ["x"]}, "tidak boleh punya absence_terms"),
])
def test_schema_mutations_are_rejected(env, mut, needle):
    d, cfg, good, _ = env
    good.update(mut)
    assert any(needle in i for i in Q.check_schema(good)), Q.check_schema(good)


def test_probe_must_not_carry_source_fields(env):
    _, _, _, probe = env
    probe["source_quote"] = "sesuatu"
    assert any("tidak boleh punya source_page/source_quote" in i for i in Q.check_schema(probe))
    probe["source_quote"] = None
    probe["absence_terms"] = []
    assert any("butuh absence_terms" in i for i in Q.check_schema(probe))


def test_set_validation_counts_duplicates_and_leak_guard(env):
    _, cfg, good, probe = env
    dup = copy.deepcopy(good)  # case_id, pertanyaan, evidence_group sama
    out = Q.validate_set([good, dup, probe], cfg, expect_total=2, expect_answerable=1)
    assert any("jumlah pertanyaan 3 != 2" in i for i in out)
    assert any("case_id ganda" in i for i in out)
    assert any("evidence_group ganda" in i for i in out)
    assert any("pertanyaan ganda" in i for i in out)


def test_cli_returns_nonzero_on_failure(env, tmp_path, capsys):
    d, cfg, good, probe = env
    cfgp = tmp_path / "cfg.json"
    cfgp.write_text(json.dumps(cfg), encoding="utf-8")
    ok = tmp_path / "ok.jsonl"
    ok.write_text("\n".join(json.dumps(r) for r in (good, probe)), encoding="utf-8")
    assert Q.main(["verify", "--cases", str(ok), "--pdf-dir", str(d), "--config", str(cfgp),
                   "--expect-total", "2", "--expect-answerable", "1"]) == 0
    good["source_page"] = 3
    bad = tmp_path / "bad.jsonl"
    bad.write_text("\n".join(json.dumps(r) for r in (good, probe)), encoding="utf-8")
    assert Q.main(["verify", "--cases", str(bad), "--pdf-dir", str(d), "--config", str(cfgp),
                   "--expect-total", "2", "--expect-answerable", "1"]) == 1


# ------------------------------------------------------------------ PDF ASLI (opsional)

REAL = os.environ.get("TA_RAG_PDF_DIR")
needs_real = pytest.mark.skipif(not REAL, reason="set TA_RAG_PDF_DIR ke folder 13 PDF asli")


@needs_real
def test_real_draft_set_passes_against_original_pdfs():
    cfg = Q.load_config()
    rows = Q.load_cases(REPO / "tests" / "fixtures" / "studi1" / "questions_draft.jsonl")
    assert Q.validate_set(rows, cfg) == []
    for r in rows:
        assert Q.verify_record(r, Path(REAL), cfg) == [], r["case_id"]


@needs_real
def test_real_set_rejects_mutations_of_each_answerable_record():
    """Tiap rekaman asli diubah (halaman +1 dan angka dibalik) -> verifier harus menolak semuanya."""
    cfg = Q.load_config()
    rows = [r for r in Q.load_cases(REPO / "tests" / "fixtures" / "studi1" / "questions_draft.jsonl") if r["kind"] == "answerable"]
    for r in rows:
        shifted = dict(r, source_page=r["source_page"] + 1)
        assert Q.verify_record(shifted, Path(REAL), cfg), f"{r['case_id']}: halaman salah lolos"
        altered = dict(r, source_quote=r["source_quote"] + " dan tambahan yang tidak pernah ada di halaman")
        assert Q.verify_record(altered, Path(REAL), cfg), f"{r['case_id']}: kutipan palsu lolos"


@needs_real
def test_real_probe_terms_are_really_absent_but_neighbor_terms_are_present():
    """Kontrol positif: istilah tetangga (mis. 'payudara klinis') HARUS terdeteksi, agar absensi probe bermakna."""
    cfg = Q.load_config()
    pos = {"case_id": "R99", "track": "R", "kind": "not_in_corpus", "question": "Menurut X, berapa?",
           "source_doc_id": "bpjs_03_2024_skrining_peserta_jkn", "source_page": None, "source_quote": None,
           "absence_terms": ["payudara klinis"], "group_id": "g", "evidence_group": "e", "question_type": "x",
           "status": "DRAFT_UNVERIFIED_BY_HUMAN", "human_verified": False,
           "web_crosscheck": {"performed": False, "reason": "uji"}}
    assert any("ADA di" in i for i in Q.verify_record(pos, Path(REAL), cfg))


# ------------------------------------------------------------------ audit ketiadaan (v4.2.1)

def _probe(terms, controls):
    return {"case_id": "R02", "kind": "not_in_corpus", "question": "Menurut Dokumen Uji, berapa tarif ambulans udara?",
            "absence_terms": terms, "control_terms": controls}


def test_absence_audit_documents_scope_terms_and_controls(env):
    d, cfg, _, _ = env
    cfg["documents"][0]["provenance"] = {"class": "scan_dengan_OCR_bawaan_tak_kasatmata"}
    rep = Q.absence_audit([_probe(["ambulans udara"], ["klaim dibayarkan"])], d, cfg, "2026-11-04")
    assert [s["doc_id"] for s in rep["scope"]] == ["dok_uji", "dok_riwayat"]
    assert all(s["n_pages"] == 3 and s["pages_searched"] == [1, 3] for s in rep["scope"])
    p = rep["probes"][0]
    assert p["result"] == "ABSENT_ALL" and p["controls_ok"] is True
    assert rep["manual_check_required_docs"] == ["dok_uji"]  # dokumen scan wajib dicek manual
    assert rep["limits"] and rep["method"]


def test_absence_audit_mutation_term_present_is_reported_as_found(env):
    d, cfg, _, _ = env
    rep = Q.absence_audit([_probe(["klaim dibayarkan"], ["pasal 3"])], d, cfg, "2026-11-04")
    p = rep["probes"][0]
    assert p["result"] == "FOUND" and p["found"]["klaim dibayarkan"]["dok_uji"] == [2]


def test_absence_audit_control_term_missing_flags_useless_search(env):
    """Bila istilah kontrol (yang seharusnya ada) tak ditemukan, pencarian tak bisa dipercaya -> controls_ok False."""
    d, cfg, _, _ = env
    rep = Q.absence_audit([_probe(["ambulans udara"], ["istilah yang tidak ada di mana pun"])], d, cfg, "2026-11-04")
    assert rep["probes"][0]["controls_ok"] is False


def test_cli_absence_audit_exit_code_and_file(env, tmp_path):
    d, cfg, _, probe = env
    probe["control_terms"] = ["klaim dibayarkan"]
    cfgp = tmp_path / "cfg.json"
    cfgp.write_text(json.dumps(cfg), encoding="utf-8")
    cases = tmp_path / "c.jsonl"
    cases.write_text(json.dumps(probe), encoding="utf-8")
    out = tmp_path / "audit.json"
    args = ["absence-audit", "--cases", str(cases), "--pdf-dir", str(d), "--config", str(cfgp), "--out", str(out),
            "--date", "2026-11-04"]
    assert Q.main(args) == 0 and json.loads(out.read_text(encoding="utf-8"))["probes"][0]["result"] == "ABSENT_ALL"
    probe["absence_terms"] = ["klaim dibayarkan"]  # mutasi: istilah probe ternyata ada
    cases.write_text(json.dumps(probe), encoding="utf-8")
    assert Q.main(args) == 1


@needs_real
def test_real_probes_absent_and_controls_present():
    cfg = Q.load_config()
    rows = Q.load_cases(REPO / "tests" / "fixtures" / "studi1" / "questions_draft.jsonl")
    rep = Q.absence_audit(rows, Path(REAL), cfg, "2026-11-04")
    assert sum(s["n_pages"] for s in rep["scope"]) == 267
    assert len(rep["probes"]) == 4
    for p in rep["probes"]:
        assert p["result"] == "ABSENT_ALL", p["case_id"]
        assert p["controls_ok"] is True, p["case_id"]


# ------------------------------------------------------------------ paket verifikasi (alat bantu)

def test_verification_pack_interleaves_cover_and_exact_source_page(env, tmp_path):
    from pypdf import PdfReader

    from ta_rag import verification_pack as VP

    d, cfg, good, probe = env
    good["source_page"] = 2
    good["source_quote"] = "Klaim dibayarkan paling lambat 15 hari setelah berkas klaim diterima lengkap"
    good["reference_answer_draft"] = "15 hari"
    probe["trap_note"] = "jebakan uji"
    cfgp = tmp_path / "cfg.json"
    cfgp.write_text(json.dumps(cfg), encoding="utf-8")
    cases = tmp_path / "c.jsonl"
    cases.write_text("\n".join(json.dumps(r) for r in (good, probe)), encoding="utf-8")
    out = tmp_path / "pack.pdf"
    n = VP.build_pack(cases, d, out, None, cfgp)
    assert n == 3  # lembar + hlm sumber (answerable) + lembar (probe)
    pages = PdfReader(str(out)).pages
    assert "R01" in pages[0].extract_text() and "15 hari" in pages[0].extract_text()
    assert "Pasal 2" in pages[1].extract_text()  # halaman FISIK 2 dari PDF sumber, bukan halaman lain
    assert "R02" in pages[2].extract_text()


# ------------------------------------------------------------------ web_crosscheck + dukungan angka rujukan (v4.2.2)

@pytest.mark.parametrize("bad", [
    None,
    {},
    {"performed": "ya"},
    {"performed": False},
    {"performed": False, "reason": "   "},
    {"performed": True, "url": "https://x.example"},
])
def test_mutation_web_crosscheck_invalid_forms_are_rejected(env, bad):
    _, _, good, _ = env
    rec = {**good, "web_crosscheck": bad}
    assert any("web_crosscheck" in i for i in Q.check_schema(rec))


def test_web_crosscheck_valid_forms_pass(env):
    _, _, good, _ = env
    done = {"performed": True, "url": "https://x.example", "result": "CONFIRMED_SECONDARY", "checked_on": "2026-11-03"}
    assert not any("web_crosscheck" in i for i in Q.check_schema({**good, "web_crosscheck": done}))
    assert not any("web_crosscheck" in i for i in Q.check_schema(good))


def test_mutation_reference_answer_with_number_absent_from_quote_is_rejected(env):
    _, _, good, _ = env
    rec = {**good, "reference_answer_draft": "6 (enam) bulan."}
    assert any("angka" in i and "kutipan" in i for i in Q.check_schema(rec))


def test_summary_counts_only_performed_crosschecks(env):
    _, cfg, good, probe = env
    done = {"performed": True, "url": "https://x.example", "result": "CONFIRMED_SECONDARY", "checked_on": "2026-11-03"}
    s = Q.summary([{**good, "web_crosscheck": done}, probe])
    assert s["web_crosschecked"] == ["R01"]


@needs_real
def test_real_set_every_row_documents_crosscheck_and_reference_is_one_fact():
    rows = Q.load_cases(REPO / "tests" / "fixtures" / "studi1" / "questions_draft.jsonl")
    assert all(isinstance(r["web_crosscheck"], dict) for r in rows)
    ref = {r["case_id"]: r["reference_answer_draft"] for r in rows}
    assert ref["R09"] == "Minimal 2 (dua) hari."
    assert "NON PONED" not in ref["R09"] and "kapitasi tidak" not in ref["R11"] and "sisanya" not in ref["R13"]


# ------------------------------------------------------------------ kandidat kutipan untuk pertanyaan baru (Studi 2)

CAND_PAGES = [
    ["Pasal 1.", "Peserta adalah setiap orang yang telah membayar iuran jaminan kesehatan.",
     "Peserta dapat mengganti FKTP setelah jangka waktu 3 (tiga) bulan sejak terdaftar."],
    ["Pasal 2.", "Klaim dibayarkan paling lambat tanggal 15 bulan berikutnya setelah diterima.",
     "Tarif ditetapkan sebesar Rp8.000,00 (delapan ribu rupiah) per peserta per bulan.",
     "Perubahan Peraturan Presiden Nomor 59 Tahun 2024 tentang jaminan kesehatan nasional."],
    ["Pasal 3", "Ketentuan penutup yang tidak memuat angka apa pun untuk pengujian ini saja.",
     "Pemberian dosis 500 mg tablet selama 14 (empat belas) hari dilakukan oleh dokter."],
    ["Pasal 4.", "Pembayaran paling lambat 15 hari sejak tahun 2OL8 diterima sepenuhnya oleh badan.",
     "Pemeriksaan meliputi: a. gula darah sewaktu; b. gula darah puasa selama 14 hari kerja.",
     "Pelayanan ini diberikan kepada peserta yang telah terdaftar dan memenuhi seluruh ketentuan",
     "yang berlaku pada fasilitas kesehatan tingkat pertama maupun fasilitas rujukan tingkat lanjut",
     "dengan pemantauan selama 21 (dua puluh satu) minggu sejak pelayanan diberikan kepada peserta",
     "dan keluarganya sebagaimana diatur dalam ketentuan pelaksanaan yang ditetapkan oleh badan",
     "penyelenggara melalui peraturan turunan sesuai kebutuhan layanan di seluruh wilayah negara."],
]



def test_extract_candidates_types_sentences_verifies_quotes_and_skips_clinical_and_citations(env, tmp_path):
    pdf_dir, cfg, good, _ = env
    Q_pdf = pdf_dir / "Dok_Uji.pdf"
    make_pdf(Q_pdf, CAND_PAGES)
    make_pdf(pdf_dir / "Dok_Riwayat.pdf", [["Biaya sebesar Rp5.000,00 dibayarkan oleh peserta setiap bulan."]])  # dokumen pengecoh: bukan jangkar
    cfg["documents"][0]["sha256"] = sha256_file(Q_pdf)
    cfg["documents"][1]["file"] = "Dok_Riwayat.pdf"
    cfg["documents"][0]["question_page_ranges"] = [[1, 4]]  # fixture berhalaman 4
    got = Q.extract_candidates(pdf_dir, cfg)
    by_type = {}
    for c in got:
        by_type.setdefault(c["type"], []).append(c)
    assert [c["page"] for c in by_type["numeric_duration"]] == [1] and "3 (tiga) bulan" in by_type["numeric_duration"][0]["quote"]
    assert by_type["numeric_date"][0]["page"] == 2 and "tanggal 15" in by_type["numeric_date"][0]["quote"]
    assert by_type["numeric_money"][0]["page"] == 2 and "Rp8.000,00" in by_type["numeric_money"][0]["quote"]
    assert by_type["definition"][0]["page"] == 1 and by_type["definition"][0]["quote"].startswith("Peserta adalah setiap orang")
    assert not any("Tahun 2024" in c["quote"] and c["type"] == "numeric_duration" for c in got)  # sitasi bukan satuan waktu
    assert not any("dosis" in c["quote"].lower() for c in got)  # domain administratif: tanpa dosis/klinis
    assert not any("2OL8" in c["quote"] for c in got)  # galat OCR (digit-huruf-digit) pada dokumen pindai
    assert not any("gula darah" in c["quote"] for c in got)  # daftar huruf a./b. bukan satu fakta
    assert not any("21 (dua puluh satu) minggu" in c["quote"] for c in got)  # kalimat > 300 karakter terlalu panjang untuk satu fakta
    assert max(len(c["quote"]) for c in got) <= Q.CANDIDATE_MAX_CHARS
    assert got and all(c["doc_id"] == "dok_uji" for c in got)  # hanya dokumen sumber evidence; pengecoh tidak menjadi kandidat jangkar
    for c in got:  # setiap kutipan lolos pemeriksaan yang sama dengan verifier
        assert Q.norm(c["quote"]) in Q.range_pages(Q_pdf, c["page"], c["page"])[c["page"]]


def test_extract_candidates_excludes_quotes_already_used_in_other_cases(env):
    pdf_dir, cfg, good, _ = env
    make_pdf(pdf_dir / "Dok_Uji.pdf", CAND_PAGES)
    cfg["documents"][0]["sha256"] = sha256_file(pdf_dir / "Dok_Uji.pdf")
    used = ["Peserta dapat mengganti FKTP setelah jangka waktu 3 (tiga) bulan"]
    assert not any("3 (tiga) bulan" in c["quote"] for c in Q.extract_candidates(pdf_dir, cfg, exclude_quotes=used))
    assert any("3 (tiga) bulan" in c["quote"] for c in Q.extract_candidates(pdf_dir, cfg))
