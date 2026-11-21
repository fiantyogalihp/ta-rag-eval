"""Paket verifikasi manusia: per pertanyaan, lembar cek + halaman FISIK asli dari PDF sumber.

Ini alat bantu, BUKAN verifikasi. Validator (manusia) tetap memutuskan; paket hanya menaruh kutipan dan halaman
aslinya berdampingan agar pencocokan angka/negasi/tabel pada gambar halaman cepat dikerjakan.

    python -m ta_rag.verification_pack --cases data/cases/questions_draft.jsonl --pdf-dir data/raw_pdf \
        --audit data/cases/absence_audit.json --out verification_pack.pdf
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from .corpus import load_config
from .questions import load_cases


def _cover_pdfs(rows: list[dict], audit: dict | None, cfg: dict) -> list[bytes]:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    st = getSampleStyleSheet()
    docs = {d["doc_id"]: d for d in cfg["documents"]}
    out = []
    for r in rows:
        buf = io.BytesIO()
        flow = [Paragraph(f"<b>{escape(r['case_id'])}</b> &mdash; {escape(r['kind'])}", st["Title"])]
        d = docs[r["source_doc_id"]]
        flow.append(Paragraph(f"<b>Dokumen:</b> {escape(d['file'])}<br/><b>SHA256:</b> {d['sha256'][:16]}&hellip; "
                              f"(jenis teks: {escape(str(d.get('provenance', {}).get('class')))})", st["Normal"]))
        flow.append(Spacer(1, 8))
        flow.append(Paragraph(f"<b>Pertanyaan:</b> {escape(r['question'])}", st["Normal"]))
        flow.append(Spacer(1, 8))
        if r["kind"] == "answerable":
            flow.append(Paragraph(f"<b>Halaman fisik:</b> {r['source_page']} (halaman berikutnya di paket ini)", st["Normal"]))
            flow.append(Paragraph(f"<b>Kutipan yang harus ada di halaman itu (verbatim):</b><br/><i>{escape(r['source_quote'])}</i>", st["Normal"]))
            flow.append(Paragraph(f"<b>Jawaban rujukan (draf, BUKAN ground truth):</b> {escape(r['reference_answer_draft'])}", st["Normal"]))
            checks = ["Kutipan terbaca PERSIS pada gambar halaman (bukan hanya pada lapisan teks)",
                      "Angka, satuan, dan tanggal sama persis",
                      "Tidak ada negasi/pengecualian di kalimat sekitarnya yang mengubah makna",
                      "Nomor halaman fisik benar; kutipan tidak ambigu dengan halaman lain",
                      "Pertanyaan bisa dijawab dari kutipan ini saja"]
        else:
            flow.append(Paragraph(f"<b>Tidak ada halaman jangkar</b> (ketiadaan fakta tak dibuktikan satu halaman). "
                                  f"Istilah yang dicari: <b>{escape(', '.join(r['absence_terms']))}</b>", st["Normal"]))
            if audit:
                p = next((x for x in audit["probes"] if x["case_id"] == r["case_id"]), None)
                if p:
                    ctl = "; ".join(f"{t}: " + ", ".join(f"{k[:22]} hlm {v[:5]}" for k, v in h.items()) for t, h in p["control_terms"].items())
                    flow.append(Paragraph(f"<b>Hasil audit otomatis:</b> {escape(p['result'])}. <b>Kontrol (topik tetangga yang ADA):</b> {escape(ctl)}", st["Normal"]))
                scan = ", ".join(audit.get("manual_check_required_docs", []))
                flow.append(Paragraph(f"<b>Cek manual wajib pada dokumen scan:</b> {escape(scan)}", st["Normal"]))
            flow.append(Paragraph(f"<b>Jebakan:</b> {escape(r.get('trap_note', '').removeprefix('Jebakan: '))}", st["Normal"]))
            checks = ["Cari tiap istilah (Ctrl+F) di semua PDF pilot; pada dokumen scan, telusuri halaman bertopik terkait secara visual",
                      "Tidak ada ungkapan setara (sinonim/penulisan lain) yang menjawab pertanyaan",
                      "Jebakan benar-benar ada di korpus (kontrol)"]
        flow.append(Spacer(1, 10))
        flow.append(Paragraph("<b>Daftar cek (isi dengan tangan):</b>", st["Normal"]))
        for c in checks:
            flow.append(Paragraph("[&nbsp;&nbsp;&nbsp;] " + escape(c), st["Normal"]))
        flow.append(Spacer(1, 8))
        flow.append(Paragraph("Hasil: [&nbsp;&nbsp;] VERIFIED &nbsp;&nbsp; [&nbsp;&nbsp;] PERBAIKI &nbsp;&nbsp; [&nbsp;&nbsp;] BUANG &nbsp;&nbsp; "
                              "Catatan: ______________________________", st["Normal"]))
        flow.append(Paragraph("Status: DRAFT_UNVERIFIED_BY_HUMAN sampai Anda mengubahnya di JSONL (validator + validated_at).", st["Italic"]))
        SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm).build(flow)
        out.append(buf.getvalue())
    return out


def build_pack(cases: Path, pdf_dir: Path, out: Path, audit_path: Path | None = None, config: Path | None = None) -> int:
    from pypdf import PdfReader, PdfWriter

    cfg = load_config(config) if config else load_config()
    rows = load_cases(cases)
    audit = json.loads(Path(audit_path).read_text(encoding="utf-8")) if audit_path else None
    docs = {d["doc_id"]: d for d in cfg["documents"]}
    covers = _cover_pdfs(rows, audit, cfg)
    w = PdfWriter()
    for r, cover in zip(rows, covers):
        cr = PdfReader(io.BytesIO(cover))
        if len(cr.pages) != 1:
            raise ValueError(f"{r['case_id']}: lembar cek lebih dari 1 halaman; pendekkan teks")
        w.add_page(cr.pages[0])
        if r["kind"] == "answerable":
            src = PdfReader(str(pdf_dir / docs[r["source_doc_id"]]["file"]))
            w.add_page(src.pages[r["source_page"] - 1])
    with open(out, "wb") as f:
        w.write(f)
    return len(w.pages)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", required=True)
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--audit")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    n = build_pack(Path(a.cases), Path(a.pdf_dir), Path(a.out), Path(a.audit) if a.audit else None,
                   Path(a.config) if a.config else None)
    print(f"ditulis {a.out}: {n} halaman")
    return 0


if __name__ == "__main__":
    sys.exit(main())
