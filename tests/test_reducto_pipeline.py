"""
Uji KODE (bukan data penelitian) untuk reducto_parse_corpus.py + reducto_json_to_md.py.

Memakai SDK Reducto ASLI yang diarahkan ke server tiruan lokal, sehingga request yang
benar-benar dikirim SDK (path, body JSON) ikut terperiksa. Fixture sintetis di sini hanya
untuk menguji kode dan TIDAK boleh masuk dataset eksperimen.

Yang TIDAK teruji di sini: perilaku server Reducto yang sebenarnya (kuota, rate limit,
bentuk persis result.type='url'). Itu hanya bisa dipastikan dengan satu panggilan nyata.

Jalankan (dari akar repo):  python -m pytest -q tests/test_reducto_pipeline.py
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "ta_rag" / "parsing"))
import reducto_json_to_md as r2md  # noqa: E402
import reducto_parse_corpus as rpc  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
# Ekspor UI Reducto asli (r-1) untuk Perpres 59/2024 - fixture KODE, bukan data eksperimen.
REAL_JSON = REPO / "tests" / "fixtures" / "reducto_perpres_59_2024_r1_ui_export.json"
# PDF asli hanya dipakai bila ada (tidak di-commit). Atur TA_RAG_PDF_DIR bila lokasinya lain.
REAL_PDF_DIR = Path(os.environ.get("TA_RAG_PDF_DIR", REPO / "data" / "raw_pdf"))


# ------------------------------------------------------------------ helper fixture
def make_pdf(path: Path, pages_text: list[str]) -> None:
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    for text in pages_text:
        y = 800
        for line in text.split("\n"):
            c.drawString(50, y, line)
            y -= 16
        c.showPage()
    c.save()


def make_parse_json(pages: dict[int, list[tuple[str, str]]], num_pages: int, job_id="job-test") -> dict:
    blocks = []
    for page, items in pages.items():
        for typ, content in items:
            blocks.append({
                "type": typ, "content": content, "confidence": "high", "extra": {"model": "r-1"},
                "bbox": {"left": 0.1, "top": 0.1, "width": 0.5, "height": 0.1, "page": page, "original_page": page},
            })
    return {
        "response_type": "parse", "job_id": job_id, "duration": 1.0, "pdf_url": None, "studio_link": None,
        "usage": {"num_pages": num_pages, "credits": float(num_pages)},
        "result": {"type": "full", "chunks": [{"content": "x", "embed": "x", "blocks": blocks}]},
    }


class FakeReducto:
    """Server tiruan: mencatat request nyata dari SDK."""

    def __init__(self):
        self.requests: list[tuple[str, str, object]] = []
        self.file_names: dict[str, str] = {}
        self.responder = lambda filename, body: (200, {})
        self.url_payloads: dict[str, object] = {}
        self.n_upload = 0
        self.lock = threading.Lock()

    def start(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # senyap
                pass

            def _send(self, status, obj):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                with outer.lock:
                    outer.requests.append(("GET", self.path, None))
                if self.path in outer.url_payloads:
                    self._send(200, outer.url_payloads[self.path])
                else:
                    self._send(404, {"error": "nope"})

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                path = self.path.split("?")[0]
                if path.endswith("/upload"):
                    m = re.search(rb'filename="([^"]+)"', body)
                    with outer.lock:
                        outer.n_upload += 1
                        fid = f"reducto://fake-{outer.n_upload}"
                        outer.file_names[fid] = m.group(1).decode() if m else "?"
                        outer.requests.append(("POST", path, {"filename": outer.file_names[fid]}))
                    self._send(200, {"file_id": fid, "presigned_url": None})
                elif path.endswith("/parse"):
                    payload = json.loads(body)
                    with outer.lock:
                        outer.requests.append(("POST", path, payload))
                    status, obj = outer.responder(outer.file_names.get(payload.get("input"), "?"), payload)
                    self._send(status, obj)
                else:
                    self._send(404, {"error": path})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.httpd.shutdown()

    def parse_calls(self):
        return [r for r in self.requests if r[0] == "POST" and r[1].endswith("/parse")]

    def upload_calls(self):
        return [r for r in self.requests if r[0] == "POST" and r[1].endswith("/upload")]


@pytest.fixture()
def server():
    s = FakeReducto().start()
    yield s
    s.stop()


@pytest.fixture()
def client(server):
    from reducto import Reducto

    return Reducto(api_key="test-key", base_url=server.base_url, max_retries=0)


def run(tmp_path, server, client, *extra, pdf_dir=None):
    pdf_dir = pdf_dir or (tmp_path / "pdf")
    argv = ["--pdf-dir", str(pdf_dir), "--out-dir", str(tmp_path / "out"), *extra]
    return rpc.main(argv, client=client)


def manifest(tmp_path, stem):
    return json.loads((tmp_path / "out" / "manifests" / f"{stem}.manifest.json").read_text())


# ------------------------------------------------------------------------ konverter
@pytest.mark.skipif(not REAL_JSON.exists(), reason="JSON Reducto asli pengguna tidak tersedia")
def test_converter_real_json_has_every_page_marker_and_flags_figures():
    d = json.loads(REAL_JSON.read_text())
    md = r2md.render_markdown(d)
    pages = [int(x) for x in re.findall(r"<!-- PDF_PAGE:(\d+) -->", md)]
    assert pages == list(range(1, 34))
    assert md.count("DESKRIPSI MODEL") == sum(1 for b in r2md.iter_blocks(d) if b["type"] == "Figure")


def test_converter_does_not_drop_unknown_types_and_marks_low_confidence():
    d = make_parse_json({1: [("Weird Type", "isi aneh"), ("Table", "<table><tr><td>1</td></tr></table>")]}, 1)
    d["result"]["chunks"][0]["blocks"][0]["confidence"] = "low"
    md = r2md.render_markdown(d)
    assert "(Weird Type)" in md and "isi aneh" in md and "LOW_CONFIDENCE" in md
    assert "<table><tr><td>1</td></tr></table>" in md  # tabel tidak diubah


def test_converter_refuses_unresolved_url_result():
    with pytest.raises(ValueError):
        r2md.render_markdown({"result": {"type": "url", "url": "http://x"}})


# --------------------------------------------------------------------- dry run & key
def test_dry_run_makes_no_calls_and_needs_no_key(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("REDUCTO_API_KEY", raising=False)
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "a.pdf", ["satu", "dua"])
    assert rpc.main(["--pdf-dir", str(tmp_path / "pdf"), "--out-dir", str(tmp_path / "out"), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Total halaman yang akan dikirim ke API: 2" in out
    assert not (tmp_path / "out").exists()


def test_missing_api_key_stops_before_any_work(tmp_path, monkeypatch):
    monkeypatch.delenv("REDUCTO_API_KEY", raising=False)
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "a.pdf", ["satu"])
    with pytest.raises(SystemExit, match="REDUCTO_API_KEY"):
        rpc.main(["--pdf-dir", str(tmp_path / "pdf"), "--out-dir", str(tmp_path / "out")])


# ------------------------------------------------------- SDK asli -> request & manifest
@pytest.mark.skipif(not REAL_JSON.exists(), reason="JSON Reducto asli pengguna tidak tersedia")
def test_real_sdk_request_shape_and_manifest(tmp_path, server, client):
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "Perpres 59 2024.pdf", [f"halaman {i}" for i in range(1, 34)])
    (tmp_path / "pdf" / "palsu.pdf").write_text("<html>bukan pdf</html>")
    real = json.loads(REAL_JSON.read_text())
    server.responder = lambda fn, body: (200, real)

    code = run(tmp_path, server, client)

    assert code == 2  # palsu.pdf ditolak
    assert len(server.parse_calls()) == 1 and len(server.upload_calls()) == 1  # HTML tidak diunggah
    _, path, body = server.parse_calls()[0]
    assert body["input"].startswith("reducto://fake-")
    assert body["settings"] == {"model": "r-1"}  # pin eksplisit; default SDK = legacy
    assert set(body) == {"input", "settings"}  # tidak ada opsi lain yang bocor

    m = manifest(tmp_path, "perpres_59_2024__reducto-r-1")
    assert m["source_pdf_sha256"] == rpc.sha256_file(tmp_path / "pdf" / "Perpres 59 2024.pdf")
    assert m["technical_qa"]["pages_without_blocks"] == []
    assert not any("USAGE_PAGES_MISMATCH" in f for f in m["technical_qa_flags"])
    assert m["technical_qa"]["models_observed"] == ["r-1"]
    assert m["job"]["usage"]["num_pages"] == 33
    assert m["human_fidelity_qa"]["status"] == "NOT_DONE"
    assert m["request"]["model"] == "r-1"
    raw = tmp_path / "out" / "raw" / "perpres_59_2024__reducto-r-1.json"
    assert rpc.sha256_file(raw) == m["files"]["raw_json_sha256"]
    assert json.loads(manifest_path_text(tmp_path, "palsu__reducto-r-1"))["status"] == "REJECTED_NOT_PDF"
    assert (tmp_path / "out" / "corpus_summary.md").exists()


def manifest_path_text(tmp_path, stem):
    return (tmp_path / "out" / "manifests" / f"{stem}.manifest.json").read_text()


# --------------------------------------------------- idempotensi, force, QA manusia
def test_second_run_makes_no_api_calls_and_keeps_human_qa(tmp_path, server, client):
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "a.pdf", ["Pasal 1 berlaku sejak 2024 untuk semua peserta"])
    server.responder = lambda fn, body: (200, make_parse_json({1: [("Text", "Pasal 1 berlaku sejak 2024 untuk semua peserta")]}, 1))
    assert run(tmp_path, server, client) == 0
    assert len(server.parse_calls()) == 1

    mp = tmp_path / "out" / "manifests" / "a__reducto-r-1.manifest.json"
    m = json.loads(mp.read_text())
    m["human_fidelity_qa"] = {"status": "DONE", "reviewer": "penguji", "reviewed_at": "2026-11-04", "notes": "ok"}
    mp.write_text(json.dumps(m))

    assert run(tmp_path, server, client) == 0
    assert len(server.parse_calls()) == 1  # tidak ada panggilan baru
    m2 = json.loads(mp.read_text())
    assert m2["reused_existing_raw"] is True
    assert m2["human_fidelity_qa"]["status"] == "DONE"
    assert m2["request"]["model"] == "r-1"  # provenance panggilan asli terbawa


def test_force_moves_old_raw_and_resets_human_qa(tmp_path, server, client):
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "a.pdf", ["Pasal 1 berlaku sejak 2024 untuk semua peserta"])
    server.responder = lambda fn, body: (200, make_parse_json({1: [("Text", "Pasal 1 berlaku sejak 2024 untuk semua peserta")]}, 1))
    run(tmp_path, server, client)
    old_sha = manifest(tmp_path, "a__reducto-r-1")["files"]["raw_json_sha256"]
    run(tmp_path, server, client, "--force")
    assert len(server.parse_calls()) == 2
    m = manifest(tmp_path, "a__reducto-r-1")
    assert m["supersedes_raw_sha256"] == old_sha
    assert m["human_fidelity_qa"]["status"] == "NOT_DONE"
    assert len(list((tmp_path / "out" / "raw").glob("*superseded*"))) == 1


def test_page_range_is_sent_and_names_carry_suffix(tmp_path, server, client):
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "a.pdf", [f"halaman nomor {i} berisi teks cukup panjang" for i in range(1, 6)])
    server.responder = lambda fn, body: (200, make_parse_json(
        {i: [("Text", f"halaman nomor {i} berisi teks cukup panjang")] for i in (1, 2, 3)}, 3))
    assert run(tmp_path, server, client, "--page-range", "1-3") == 0
    assert server.parse_calls()[0][2]["settings"] == {"model": "r-1", "page_range": {"start": 1, "end": 3}}
    m = manifest(tmp_path, "a__p001-003__reducto-r-1")
    assert m["technical_qa"]["expected_pages"] == [1, 3]
    assert m["technical_qa_flags"] == []


# ------------------------------------------------------------------ result.type=url
@pytest.mark.parametrize("variant", ["dict_with_chunks", "bare_list"])
def test_url_result_is_resolved_inline(tmp_path, server, client, variant):
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "besar.pdf", ["Pasal 7 ayat 2 mengatur iuran peserta"])
    full = make_parse_json({1: [("Text", "Pasal 7 ayat 2 mengatur iuran peserta")]}, 1)
    chunks = full["result"]["chunks"]
    server.url_payloads["/result/r1.json"] = {"chunks": chunks} if variant == "dict_with_chunks" else chunks
    resp = copy.deepcopy(full)
    resp["result"] = {"type": "url", "result_id": "r1", "url": f"{server.base_url}/result/r1.json"}
    server.responder = lambda fn, body: (200, resp)

    assert run(tmp_path, server, client) == 0
    raw = json.loads((tmp_path / "out" / "raw" / "besar__reducto-r-1.json").read_text())
    assert raw["result"]["type"] == "full"
    assert len(list(r2md.iter_blocks(raw))) == 1
    m = manifest(tmp_path, "besar__reducto-r-1")
    assert m["job_result_was_url"] is True
    assert any("RESULT_TYPE_URL" in i for i in m["issues"])


# --------------------------------------------------------------- QA teks-bawaan PDF
def test_text_layer_check_flags_changed_digit_and_scan_page(tmp_path, server, client):
    (tmp_path / "pdf").mkdir()
    p1 = "Pasal 6 menyatakan iuran sebesar Rp 150.000 per bulan untuk peserta"
    p2 = "Peraturan ini berlaku sejak tanggal 1 Juli 2025 bagi seluruh peserta"
    make_pdf(tmp_path / "pdf" / "a.pdf", [p1, p2, ""])  # halaman 3 tanpa teks (meniru scan)
    server.responder = lambda fn, body: (200, make_parse_json({
        1: [("Text", p1)],
        2: [("Text", p2.replace("2025", "2026"))],  # angka diubah
        3: [("Text", "teks yang ditemukan OCR dari gambar")],
    }, 3))
    assert run(tmp_path, server, client) == 0

    m = manifest(tmp_path, "a__reducto-r-1")
    tl = m["text_layer_check"]
    rows = {r["page"]: r for r in tl["pages_to_review"]}
    assert 1 not in rows
    assert rows[2]["status"] == "NUM_MISMATCH"
    assert rows[2]["numbers_only_in_pdf_text"] == ["2025"] and rows[2]["numbers_only_in_reducto"] == ["2026"]
    assert rows[3]["status"] == "NO_TEXT_LAYER"
    assert m["status"] == "TECH_QA_FLAGS"


def test_text_layer_unreliable_when_most_pages_differ(tmp_path, server, client):
    """Scan + OCR bawaan berisik: sebagian besar halaman 'berbeda' -> yang tak andal adalah pembandingnya."""
    (tmp_path / "pdf").mkdir()
    pages = [f"Pasal {i} menyatakan iuran sebesar Rp {i}00.000 per bulan untuk peserta" for i in range(1, 5)]
    make_pdf(tmp_path / "pdf" / "a.pdf", pages)
    # Reducto benar; teks bawaan 'salah' pada 3 dari 4 halaman (angka berbeda)
    server.responder = lambda fn, body: (200, make_parse_json({
        1: [("Text", pages[0])],
        2: [("Text", pages[1].replace("200.000", "250.000"))],
        3: [("Text", pages[2].replace("300.000", "350.000"))],
        4: [("Text", pages[3].replace("400.000", "450.000"))],
    }, 4))
    assert run(tmp_path, server, client) == 0
    m = manifest(tmp_path, "a__reducto-r-1")
    tl = m["text_layer_check"]
    assert tl["reference_reliability"] == "UNRELIABLE_REFERENCE"
    assert tl["differing_ratio"] == 0.75
    flags = m["technical_qa_flags"]
    assert any("TEXT_LAYER_UNRELIABLE_REFERENCE" in f for f in flags)
    assert not any(f.startswith("TEXT_LAYER_NUM_MISMATCH") for f in flags)  # tidak ada flag palsu per halaman
    assert m["status"] == "TECH_QA_FLAGS"  # tetap butuh QA berbasis gambar


def test_text_layer_usable_when_few_pages_differ(tmp_path, server, client):
    (tmp_path / "pdf").mkdir()
    pages = [f"Pasal {i} menyatakan iuran sebesar Rp {i}00.000 per bulan untuk peserta" for i in range(1, 5)]
    make_pdf(tmp_path / "pdf" / "a.pdf", pages)
    server.responder = lambda fn, body: (200, make_parse_json({
        1: [("Text", pages[0])], 2: [("Text", pages[1])], 3: [("Text", pages[2])],
        4: [("Text", pages[3].replace("400.000", "450.000"))],
    }, 4))
    run(tmp_path, server, client)
    tl = manifest(tmp_path, "a__reducto-r-1")["text_layer_check"]
    assert tl["reference_reliability"] == "USABLE_REFERENCE"
    assert [r["page"] for r in tl["pages_to_review"]] == [4]


def test_text_layer_no_reference_for_pure_scan(tmp_path, server, client):
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "a.pdf", ["", "", ""])
    server.responder = lambda fn, body: (200, make_parse_json(
        {i: [("Text", "teks dari gambar halaman ini")] for i in (1, 2, 3)}, 3))
    run(tmp_path, server, client)
    m = manifest(tmp_path, "a__reducto-r-1")
    assert m["text_layer_check"]["reference_reliability"] == "NO_REFERENCE"
    assert any("TEXT_LAYER_NO_REFERENCE" in f for f in m["technical_qa_flags"])


@pytest.mark.skipif(not REAL_JSON.exists() or not (REAL_PDF_DIR / "Perpres_59_2024_Perubahan_Ketiga_Jaminan_Kesehatan.pdf").exists(),
                    reason="PDF asli Perpres 59/2024 tidak tersedia (tidak di-commit)")
def test_real_scan_perpres59_is_declared_unreliable_reference():
    """Data nyata: 30/33 halaman 'berbeda' padahal gambar hlm. 7 membuktikan Reducto benar."""
    d = json.loads(REAL_JSON.read_text())
    pdf = REAL_PDF_DIR / "Perpres_59_2024_Perubahan_Ketiga_Jaminan_Kesehatan.pdf"
    pages = list(range(1, 34))
    tl = rpc.qa_text_layer(d, rpc.pdf_page_texts(pdf, pages), pages)
    assert tl["reference_reliability"] == "UNRELIABLE_REFERENCE"
    assert tl["differing_ratio"] >= 0.8


def test_missing_page_in_blocks_is_flagged(tmp_path, server, client):
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "a.pdf", ["halaman satu berisi teks cukup", "halaman dua berisi teks cukup"])
    server.responder = lambda fn, body: (200, make_parse_json({1: [("Text", "halaman satu berisi teks cukup")]}, 2))
    run(tmp_path, server, client)
    m = manifest(tmp_path, "a__reducto-r-1")
    assert m["technical_qa"]["pages_without_blocks"] == [2]
    assert any("HALAMAN_TANPA_BLOCK" in f for f in m["technical_qa_flags"])


def test_usage_mismatch_is_flagged(tmp_path, server, client):
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "a.pdf", ["halaman satu berisi teks cukup", "halaman dua berisi teks cukup"])
    server.responder = lambda fn, body: (200, make_parse_json(
        {1: [("Text", "halaman satu berisi teks cukup")], 2: [("Text", "halaman dua berisi teks cukup")]}, 5))
    run(tmp_path, server, client)
    assert any("USAGE_PAGES_MISMATCH" in f for f in manifest(tmp_path, "a__reducto-r-1")["technical_qa_flags"])


# ------------------------------------------------------------ kegagalan terisolasi
def test_one_failure_does_not_stop_the_batch(tmp_path, server, client):
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "a_gagal.pdf", ["halaman satu berisi teks cukup"])
    make_pdf(tmp_path / "pdf" / "b_ok.pdf", ["halaman satu berisi teks cukup"])

    def responder(filename, body):
        if filename == "a_gagal.pdf":
            return 500, {"error": "boom"}
        return 200, make_parse_json({1: [("Text", "halaman satu berisi teks cukup")]}, 1)

    server.responder = responder
    assert run(tmp_path, server, client) == 2
    assert (tmp_path / "out" / "raw" / "b_ok__reducto-r-1.json").exists()
    assert not (tmp_path / "out" / "raw" / "a_gagal__reducto-r-1.json").exists()
    failed = json.loads((tmp_path / "out" / "manifests" / "a_gagal__reducto-r-1.FAILED.manifest.json").read_text())
    assert failed["status"] == "PARSE_FAILED"
    assert "corpus_summary.md" in os.listdir(tmp_path / "out")


def test_doc_id_collision_is_refused(tmp_path):
    (tmp_path / "pdf").mkdir()
    make_pdf(tmp_path / "pdf" / "Perpres 59.pdf", ["x"])
    make_pdf(tmp_path / "pdf" / "perpres_59.pdf", ["x"])
    with pytest.raises(SystemExit, match="bentrok"):
        rpc.select_pdfs(tmp_path / "pdf", None)
