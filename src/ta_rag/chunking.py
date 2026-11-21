"""Chunker Pasal-aware di atas JSON mentah Reducto (result.chunks[].blocks[], bbox.original_page = halaman FISIK PDF).

Aturan (spec §6): batas chunk = awal "Pasal N/NA" pada teks blok; ayat tetap dalam Pasal; Figure/Signature/Header/Footer/
Page Number TIDAK masuk; tabel = satu unit; halaman chunk = rentang halaman fisik blok-bloknya; teks blok dibersihkan dari tag HTML sederhana.
Setiap chunk membawa `page_start`/`page_end` agar `corpus.check_chunk_scope` dapat berjalan sebelum indeks dibangun.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

DROP_TYPES = frozenset({"Figure", "Signature", "Header", "Footer", "Page Number"})
PASAL_RE = re.compile(r"^\s*(?:BAB\s+[IVXLC]+\s+)?(Pasal\s+\d+[A-Z]?)\b", re.I)
_TAG = re.compile(r"</?(?:b|i|u|br|p|span|sup|sub)[^>]*>", re.I)


def clean(text: str) -> str:
    t = html.unescape(_TAG.sub(" ", text or ""))
    return " ".join(t.split())


def _blocks(raw: dict) -> list[dict]:
    res = raw.get("result", raw)
    out = []
    for ch in res.get("chunks") or []:
        out.extend(ch.get("blocks") or [])
    return out


def chunk_document(raw: dict, doc: dict, max_chars: int = 3500) -> list[dict]:
    """Daftar chunk untuk satu dokumen. Chunk yang melebihi `max_chars` dipecah pada batas blok (bukan di tengah blok)."""
    cur: list[tuple[int, str, str]] = []  # (halaman, tipe, teks)
    groups: list[tuple[str, list[tuple[int, str, str]]]] = []
    label = "Pembuka"
    for b in _blocks(raw):
        if b.get("type") in DROP_TYPES:
            continue
        text = clean(b.get("content", ""))
        if not text:
            continue
        page = (b.get("bbox") or {}).get("original_page")
        if not isinstance(page, int):
            raise ValueError(f"{doc['doc_id']}: blok tanpa bbox.original_page (halaman fisik tak dapat ditentukan)")
        m = PASAL_RE.match(text)
        if m and cur:
            groups.append((label, cur))
            cur = []
        if m:
            label = m.group(1).title()
        cur.append((page, b.get("type", ""), text))
    if cur:
        groups.append((label, cur))

    chunks = []
    for label, blocks in groups:
        part: list[tuple[int, str, str]] = []
        size = 0
        pieces = []
        for blk in blocks:
            if part and size + len(blk[2]) > max_chars:
                pieces.append(part)
                part, size = [], 0
            part.append(blk)
            size += len(blk[2]) + 1
        if part:
            pieces.append(part)
        for k, piece in enumerate(pieces):
            text = "\n".join(t for _, _, t in piece)
            pages = [p for p, _, _ in piece]
            cid = f"{doc['doc_id']}::{label.replace(' ', '')}::{min(pages):04d}-{max(pages):04d}::{k}"
            chunks.append({
                "chunk_id": cid, "doc_id": doc["doc_id"], "source_pdf_sha256": doc.get("sha256"),
                "page_start": min(pages), "page_end": max(pages), "heading_path": label, "text": text,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "ocr_quality_flag": (doc.get("provenance") or {}).get("class", ""), "eval_role": doc.get("eval_role"),
            })
    ids = [c["chunk_id"] for c in chunks]
    if len(ids) != len(set(ids)):  # label Pasal berulang di halaman sama
        seen: dict[str, int] = {}
        for c in chunks:
            n = seen.get(c["chunk_id"], 0)
            seen[c["chunk_id"]] = n + 1
            if n:
                c["chunk_id"] += f"#{n}"
    return chunks


def write_chunks(chunks: list[dict], path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(json.dumps(c, ensure_ascii=False, sort_keys=True) for c in chunks) + "\n", encoding="utf-8")
