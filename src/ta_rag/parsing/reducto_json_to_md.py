"""
Konversi hasil parse Reducto (JSON) ke Markdown untuk BUKTI BACA MANUSIA.

JSON tetap sumber kebenaran untuk chunking/retrieval. Markdown ini hanya
membantu QA manusia membaca hasil parse.

Dibangun dari result.chunks[].blocks (bukan chunk.content) supaya:
  1. Setiap halaman fisik PDF asli punya penanda <!-- PDF_PAGE:N --> (memakai
     bbox.original_page, jadi tetap benar saat parse dengan page_range).
  2. Block Figure/Signature (deskripsi buatan model, BUKAN hasil OCR teks)
     ditandai terpisah dan tidak tercampur dengan teks asli.
  3. Block berconfidence "low" diberi penanda agar mudah ditemukan reviewer.
  4. Tipe block yang tidak dikenal tidak dibuang diam-diam.

Pemakaian:
    python reducto_json_to_md.py <input.json> <output.md>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterator

LOW_CONF_TAG = " [⚠ LOW_CONFIDENCE]"
AI_DESCRIBED_TYPES = ("Figure", "Signature")


def normalize_inline(text: str) -> str:
    """Ubah tag inline HTML sederhana ke sintaks Markdown."""
    for old, new in (
        ("<b>", "**"), ("</b>", "**"),
        ("<strong>", "**"), ("</strong>", "**"),
        ("<i>", "_"), ("</i>", "_"),
        ("<em>", "_"), ("</em>", "_"),
    ):
        text = text.replace(old, new)
    return text.strip()


def _one_line(text: str) -> str:
    return " ".join(text.split())


def block_page(block: dict) -> int | None:
    """Halaman fisik PDF asli (1-indexed) tempat block berada."""
    bbox = block.get("bbox") or {}
    return bbox.get("original_page") or bbox.get("page")


def iter_blocks(data: dict) -> Iterator[dict]:
    """Semua block dari semua chunk, dalam urutan baca yang dikembalikan Reducto."""
    result = data.get("result") or {}
    rtype = result.get("type")
    if rtype != "full":
        raise ValueError(
            f"result.type={rtype!r}: konten belum inline. Untuk type 'url', "
            "resolve dulu (reducto_parse_corpus.py melakukannya otomatis)."
        )
    for chunk in result.get("chunks") or []:
        yield from chunk.get("blocks") or []


def render_markdown(data: dict) -> str:
    out: list[str] = []
    current_page = None

    for block in iter_blocks(data):
        raw = block.get("content") or ""
        if not raw.strip():
            continue

        btype = block.get("type") or "Unknown"
        page = block_page(block)
        if page != current_page:
            out.append(f"<!-- PDF_PAGE:{page} -->")
            current_page = page

        low = LOW_CONF_TAG if block.get("confidence") == "low" else ""

        if btype == "Table":
            # Isi tabel (HTML/Markdown, tergantung table_output_format) dibiarkan apa adanya.
            out.append(f"<!-- TABLE p.{page} -->\n{raw.strip()}{low}")
            continue

        text = normalize_inline(raw)
        if btype == "Title":
            out.append(f"# {_one_line(text)}{low}")
        elif btype == "Section Header":
            out.append(f"## {_one_line(text)}{low}")
        elif btype in AI_DESCRIBED_TYPES:
            out.append(
                f"> **[{btype.upper()} / DESKRIPSI MODEL — bukan teks OCR asli]**: "
                f"{_one_line(text)}{low}"
            )
        elif btype == "Header":
            out.append(f"*(header halaman)* {text}{low}")
        elif btype == "Footer":
            out.append(f"*(footer halaman)* {text}{low}")
        elif btype == "Page Number":
            out.append(f"*(nomor halaman tercetak)* {_one_line(text)}{low}")
        elif btype == "List Item":
            out.append(f"- {text}{low}")
        elif btype == "Key Value":
            out.append(f"**{text}**{low}")
        elif btype == "Text":
            out.append(f"{text}{low}")
        else:
            out.append(f"*({btype})* {text}{low}")

    return "\n\n".join(out) + "\n"


def reducto_json_to_md(json_path: str | Path, md_path: str | Path) -> int:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    md = render_markdown(data)
    Path(md_path).write_text(md, encoding="utf-8")
    return md.count("<!-- PDF_PAGE:")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Pemakaian: python reducto_json_to_md.py <input.json> <output.md>")
        sys.exit(1)
    n_pages = reducto_json_to_md(sys.argv[1], sys.argv[2])
    print(f"Ditulis: {sys.argv[2]} ({n_pages} penanda halaman)")
