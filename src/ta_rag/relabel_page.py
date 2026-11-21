"""Pembangun halaman pelabelan lokal (S26 relabel, S28 validator kedua): satu berkas HTML offline berisi lembar kosong + gambar halaman jangkar.

Halaman hanya alat tampilan. Ia tidak membaca label pertama, skor, atau asal jawaban, dan tidak pernah menyarankan label; manusia memutuskan.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import corpus, labeling, ocr_check

HERE = Path(__file__).resolve().parent
FORBIDDEN = ("answer_id", "label", "label_first", "origin", "route", "H")
FILL = ("label_baru", "alasan_bila_berbeda")
REQUIRED = ("item_id", "case_id", "question", "answer", "kind", "source_quote", "rubric", *FILL)
NOTE = "Halaman ini alat tampilan, bukan penilai: label tetap diputuskan manusia."


def _not_before(value: str | None) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"--not-before bukan waktu ISO 8601: {value!r}") from exc
    if dt.tzinfo is None:
        raise ValueError("--not-before harus memuat zona waktu (mis. 2026-11-19T20:12:00+07:00); tanpa zona, batas waktu ambigu")
    z = dt.strftime("%z")
    return int(dt.timestamp() * 1000), f"{dt:%Y-%m-%d %H:%M} (UTC{z[:3]}:{z[3:]})"


def _validate_sheet(rows: list[dict]) -> list[str]:
    if not rows:
        raise ValueError("lembar tidak memuat baris")
    cols = list(rows[0].keys())
    if "item_id" not in cols:
        raise ValueError("lembar tidak memiliki kolom item_id")
    lost = [c for c in REQUIRED if c not in cols]
    if lost:
        raise ValueError(f"kolom lembar tidak ada: {', '.join(lost)}")
    bad = [c for c in FORBIDDEN if c in cols]
    if bad:
        raise ValueError(f"kolom terlarang di lembar masukan (membuka asal/label pertama): {', '.join(bad)}")
    extra = [c for c in cols if c not in REQUIRED]
    if extra:
        raise ValueError(f"kolom tidak dikenal di lembar masukan (hanya {len(REQUIRED)} kolom lembar kosong yang diterima): {', '.join(map(str, extra))}")
    seen = set()
    for r in rows:
        if None in r or any(v is None for v in r.values()):
            raise ValueError(f"baris lembar tidak rapi (sel kurang atau berlebih) di sekitar item_id {r.get('item_id')!r}")
        if not r["item_id"].strip():
            raise ValueError("item_id kosong pada salah satu baris lembar")
        if r["item_id"] in seen:
            raise ValueError(f"item_id ganda: {r['item_id']}")
        seen.add(r["item_id"])
        for f in FILL:
            if (r.get(f) or "").strip():
                raise ValueError(f"{f} sudah terisi pada {r['item_id']}; halaman hanya dibangun dari lembar kosong")
    return cols


def build_page(sheet_csv, cases_jsonl, pdf_dir, out_html, download_name: str, not_before: str | None = None, dpi: int = 100) -> dict:
    labeling._guard_new(out_html)
    rows = labeling._read_csv(sheet_csv)
    columns = _validate_sheet(rows)
    if not re.fullmatch(r"[\w.-]+\.csv", download_name):
        raise ValueError(f"download_name tidak sah (harus ^[\\w.-]+\\.csv$): {download_name!r}")
    nb_ms, nb_text = _not_before(not_before)

    cases = {}
    for line in Path(cases_jsonl).read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            if not isinstance(c, dict) or not c.get("case_id"):
                raise ValueError(f"baris berkas kasus tanpa case_id: {line[:80]!r}")
            cases[c["case_id"]] = c
    page_of, pdfs, sha_ok = {}, {}, {}
    for r in rows:
        c = cases.get(r["case_id"])
        if c is None:
            raise ValueError(f"case_id tidak ada di berkas kasus: {r['case_id']} ({r['item_id']})")
        if c.get("source_page") is None:
            if r["kind"] != "not_in_corpus":  # hanya probe yang boleh tanpa halaman jangkar; cacat data tidak boleh lolos diam-diam
                raise ValueError(f"{r['item_id']}: kind {r['kind']!r} tanpa source_page di berkas kasus ({r['case_id']}); halaman jangkar wajib")
            continue  # probe: tidak ada halaman jangkar, tidak ada gambar
        if not isinstance(c["source_page"], int) or isinstance(c["source_page"], bool) or c["source_page"] < 1:
            raise ValueError(f"source_page tidak sah untuk {r['case_id']}: {c['source_page']!r}")
        for k in ("source_file", "source_pdf_sha256"):
            if not c.get(k):
                raise ValueError(f"kasus {r['case_id']} tidak memiliki {k}")
        pdf = Path(pdf_dir) / c["source_file"]
        if not pdf.is_file():
            raise ValueError(f"PDF tidak ada: {pdf}")
        sk = (pdf, c["source_pdf_sha256"])
        if sk not in sha_ok:
            sha_ok[sk] = corpus.sha256_file(pdf) == c["source_pdf_sha256"]
        if not sha_ok[sk]:
            raise ValueError(f"SHA256 PDF tidak cocok dengan berkas kasus: {c['source_file']}")
        key = f"{c['source_file']}#{c['source_page']}"
        page_of[r["case_id"]] = key
        pdfs[key] = (pdf, c["source_page"])

    images = {}
    for key, (pdf, page) in pdfs.items():
        with tempfile.TemporaryDirectory() as td:  # satu direktori per render: p{page}.png sama untuk PDF berbeda
            try:
                png = ocr_check.render_page(pdf, page, dpi, Path(td))
            except subprocess.CalledProcessError as exc:
                raise ValueError(f"gagal merender {key}: {exc.stderr.decode('utf-8', 'replace').strip()}") from exc
            except FileNotFoundError as exc:
                raise ValueError(f"gagal merender {key}: pdftoppm tidak ditemukan (pasang poppler-utils)") from exc
            images[key] = "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii")

    sheet_sha = corpus.sha256_file(Path(sheet_csv))
    payload = {"columns": columns, "rows": rows, "images": images, "page_of": page_of, "sheet_sha256": sheet_sha,
               "download_name": download_name, "not_before_ms": nb_ms, "not_before_text": nb_text}
    data_json = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    lib = (HERE / "relabel_page.js").read_text(encoding="utf-8")
    parts = {"__LIB__": lib, "__DATA__": data_json}
    html = re.sub("__LIB__|__DATA__", lambda m: parts[m.group(0)], (HERE / "relabel_page_template.html").read_text(encoding="utf-8"))  # sekali jalan: isi tak diproses ulang
    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return {"items": len(rows), "images": len(images), "bytes": out.stat().st_size, "sheet_sha256": sheet_sha}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bangun halaman pelabelan lokal (satu berkas HTML offline) dari lembar relabel kosong.")
    ap.add_argument("--sheet", required=True, help="lembar CSV kosong (label_baru dan alasan_bila_berbeda kosong)")
    ap.add_argument("--cases", required=True, help="berkas kasus JSONL (source_file, source_page, source_pdf_sha256)")
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--out", required=True, help="HTML keluaran; tidak menimpa")
    ap.add_argument("--download-name", required=True, help="nama berkas CSV ekspor, mis. relabel_validator2.csv")
    ap.add_argument("--not-before", default=None, help="ISO 8601 dengan zona waktu; isian ditolak sebelum waktu ini")
    ap.add_argument("--dpi", type=int, default=100)
    a = ap.parse_args(argv)
    try:
        info = build_page(a.sheet, a.cases, a.pdf_dir, a.out, a.download_name, a.not_before, a.dpi)
    except (ValueError, FileExistsError) as exc:
        print(f"GAGAL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(info, ensure_ascii=False, indent=2))
    print(NOTE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
