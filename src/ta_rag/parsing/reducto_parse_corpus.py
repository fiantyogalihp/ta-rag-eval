#!/usr/bin/env python3
"""
Parse batch PDF korpus via Reducto API -> JSON mentah + Markdown bukti baca + manifest + QA teknis.

Prinsip:
  * JSON Reducto = sumber kebenaran. Markdown hanya untuk mata manusia.
  * Model di-pin eksplisit (default r-1). Default SDK = legacy, BUKAN r-1.
  * Idempotent: jika JSON mentah sudah ada, API TIDAK dipanggil lagi (hemat kredit),
    kecuali --force (file lama dipindah ke *__superseded_*, tidak ditimpa).
  * QA di sini bersifat TEKNIS. QA fidelity manusia (human_fidelity_qa) tidak pernah
    diisi otomatis.

Pemakaian:
    pip install reductoai pypdf
    export REDUCTO_API_KEY=...                       # jangan ditaruh di argumen CLI
    python reducto_parse_corpus.py --pdf-dir data/raw_pdf --out-dir data/reducto --dry-run
    python reducto_parse_corpus.py --pdf-dir data/raw_pdf --out-dir data/reducto --only perpres_59_2024 --page-range 1-3
    python reducto_parse_corpus.py --pdf-dir data/raw_pdf --out-dir data/reducto

Keluaran di --out-dir:
    raw/<doc>__reducto-<model>.json         respons Reducto (bentuk sama dengan unduhan Studio)
    markdown/<doc>__reducto-<model>.md      bukti baca manusia
    manifests/<doc>__reducto-<model>.manifest.json
    corpus_manifest.json, corpus_summary.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reducto_json_to_md as r2md  # noqa: E402

SCRIPT_VERSION = "2026-11-03.1"
DEFAULT_MODEL = "r-1"
WIB = timezone(timedelta(hours=7))

# Ambang heuristik pemeriksaan teks-bawaan-PDF vs hasil parse. [Dugaan awal]
# Sesuaikan setelah melihat distribusi nyata pada korpus; catat nilai yang dipakai di paper.
LOW_SIM_DICE = 0.85
MIN_TEXT_LAYER_WORDS = 5
# Vonis tingkat-dokumen: jika sebagian besar halaman "berbeda", yang tidak bisa dipercaya adalah
# PEMBANDINGNYA (teks bawaan PDF = OCR tak-kasatmata dari scan), bukan hasil parse.
# Bukti nyata: Perpres 59/2024 (scan) -> 30/33 halaman ditandai; hlm. 7 gambar menunjukkan Reducto
# benar "(2)" sedangkan teks bawaan salah "(21". [Dugaan awal: 0.5 dan 3 halaman, belum dikalibrasi]
UNRELIABLE_FLAG_RATIO = 0.5
MIN_PAGES_FOR_VERDICT = 3

NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
WORD_RE = re.compile(r"\w+", re.UNICODE)
TAG_RE = re.compile(r"<[^>]+>")


# --------------------------------------------------------------------------- util
def now_iso() -> str:
    return datetime.now(WIB).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "doc"


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_page_range(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", text)
    if not m or int(m.group(1)) < 1 or int(m.group(2)) < int(m.group(1)):
        raise SystemExit(f"--page-range harus 'MULAI-AKHIR' (1-indexed), diterima: {text!r}")
    return int(m.group(1)), int(m.group(2))


# ------------------------------------------------------------------ inspeksi PDF lokal
def inspect_pdf(path: Path) -> dict:
    """Cek byte (bukan ekstensi), hitung halaman. Sudah pernah ada file HTML berekstensi .pdf."""
    info = {"is_pdf": False, "pages": None, "issues": []}
    head = path.read_bytes()[:1024]
    info["is_pdf"] = b"%PDF-" in head
    if not info["is_pdf"]:
        info["issues"].append("BUKAN_PDF: header %PDF- tidak ditemukan (mungkin HTML berekstensi .pdf)")
        return info
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if reader.is_encrypted:
            info["issues"].append("PDF_TERENKRIPSI: pypdf tidak dapat membaca tanpa password")
        else:
            info["pages"] = len(reader.pages)
    except Exception as exc:  # pragma: no cover - tergantung berkas
        info["issues"].append(f"PYPDF_GAGAL_MEMBACA: {type(exc).__name__}: {exc}")
    return info


def pdf_page_texts(path: Path, pages: list[int]) -> dict[int, str]:
    """Teks bawaan PDF per halaman fisik. Dipakai HANYA sebagai pembanding QA, bukan evidence."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    out: dict[int, str] = {}
    for p in pages:
        try:
            out[p] = reader.pages[p - 1].extract_text() or ""
        except Exception:
            out[p] = ""
    return out


# ------------------------------------------------------------------------ panggilan API
def default_fetch_json(url: str):
    """Ambil hasil besar (result.type='url'). Tanpa header Authorization ke URL presigned."""
    import httpx

    resp = httpx.get(url, timeout=300.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def response_to_dict(resp) -> dict:
    if isinstance(resp, dict):
        return resp
    if hasattr(resp, "model_dump"):
        return resp.model_dump(mode="json")
    if hasattr(resp, "to_dict"):
        return resp.to_dict()
    raise TypeError(f"Tidak bisa mengubah respons {type(resp).__name__} ke dict")


def resolve_result(d: dict, fetch_json: Callable[[str], object]) -> tuple[dict, bool]:
    """Jika result.type == 'url', unduh dan jadikan inline (type 'full'). Mengembalikan (dict, was_url)."""
    res = d.get("result") or {}
    if res.get("type") != "url":
        return d, False
    payload = fetch_json(res["url"])
    if isinstance(payload, list):
        chunks = payload
    elif isinstance(payload, dict) and "chunks" in payload:
        chunks = payload["chunks"]
    elif isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        chunks = payload["result"].get("chunks")
    else:
        chunks = None
    if chunks is None:
        raise ValueError("Format hasil URL tidak dikenali: tidak ada 'chunks'. Simpan respons dan periksa manual.")
    d = dict(d)
    d["result"] = {"type": "full", "chunks": chunks, "ocr": None, "custom": None}
    return d, True


def call_reducto(client, pdf_path: Path, model: str, page_range: tuple[int, int] | None):
    settings: dict = {"model": model}
    if page_range:
        settings["page_range"] = {"start": page_range[0], "end": page_range[1]}
    upload = client.upload(file=pdf_path)
    resp = client.parse.run(input=upload.file_id, settings=settings)
    return settings, response_to_dict(resp)


# -------------------------------------------------------------------------------- QA
def qa_structure(d: dict, expected_pages: list[int]) -> dict:
    blocks = list(r2md.iter_blocks(d))
    exp = set(expected_pages)
    seen = {p for p in (r2md.block_page(b) for b in blocks) if p}
    missing = sorted(exp - seen)
    unexpected = sorted(seen - exp)
    types = Counter(b.get("type") for b in blocks)
    low_pages = sorted({r2md.block_page(b) for b in blocks if b.get("confidence") == "low"} - {None})
    models = sorted({str((b.get("extra") or {}).get("model")) for b in blocks if (b.get("extra") or {}).get("model")})
    usage_pages = (d.get("usage") or {}).get("num_pages")

    flags = []
    if usage_pages is not None and usage_pages != len(exp):
        flags.append(f"USAGE_PAGES_MISMATCH: usage.num_pages={usage_pages}, diharapkan={len(exp)}")
    if missing:
        flags.append(f"HALAMAN_TANPA_BLOCK: {missing[:20]}{'...' if len(missing) > 20 else ''}")
    if unexpected and exp:
        flags.append(f"HALAMAN_DI_LUAR_CAKUPAN: {unexpected[:20]}")
    if low_pages:
        flags.append(f"BLOCK_LOW_CONFIDENCE di halaman: {low_pages[:20]}{'...' if len(low_pages) > 20 else ''}")
    empty = sum(1 for b in blocks if not (b.get("content") or "").strip())
    if empty:
        flags.append(f"BLOCK_KOSONG: {empty}")

    return {
        "expected_pages": [min(exp), max(exp)] if exp else None,
        "expected_page_count": len(exp),
        "usage_num_pages": usage_pages,
        "pages_without_blocks": missing,
        "pages_outside_scope": unexpected,
        "block_count": len(blocks),
        "block_types": dict(types),
        "figure_or_signature_blocks": types.get("Figure", 0) + types.get("Signature", 0),
        "low_confidence_pages": low_pages,
        "models_observed": models,
        "flags": flags,
    }


def _norm_nums(text: str) -> Counter:
    return Counter(re.sub(r"[.,]", "", t) for t in NUM_RE.findall(text))


def qa_text_layer(d: dict, pdf_texts: dict[int, str], pages: list[int]) -> dict:
    """Bandingkan angka & kata per halaman antara teks bawaan PDF dan hasil parse.

    Ini PENDETEKSI halaman mencurigakan, bukan bukti kebenaran. Halaman 'OK' belum tentu benar;
    halaman bertanda wajib dilihat manusia terhadap gambar PDF asli. Halaman tanpa teks bawaan
    (scan) tidak bisa diperiksa dengan cara ini -> NO_TEXT_LAYER, wajib QA manusia penuh.
    """
    by_page: dict[int, list[str]] = defaultdict(list)
    for b in r2md.iter_blocks(d):
        if b.get("type") in r2md.AI_DESCRIBED_TYPES:
            continue
        p = r2md.block_page(b)
        if p:
            by_page[p].append(b.get("content") or "")

    rows, summary = [], Counter()
    for p in pages:
        pdf_text = pdf_texts.get(p, "")
        red_text = TAG_RE.sub(" ", "\n".join(by_page.get(p, [])))
        pdf_words = Counter(w.lower() for w in WORD_RE.findall(pdf_text))
        red_words = Counter(w.lower() for w in WORD_RE.findall(red_text))

        if sum(pdf_words.values()) < MIN_TEXT_LAYER_WORDS:
            status, dice, only_pdf, only_red = "NO_TEXT_LAYER", None, [], []
        else:
            overlap = sum((pdf_words & red_words).values())
            total = sum(pdf_words.values()) + sum(red_words.values())
            dice = round(2 * overlap / total, 4) if total else 0.0
            n_pdf, n_red = _norm_nums(pdf_text), _norm_nums(red_text)
            only_pdf = sorted((n_pdf - n_red).elements())
            only_red = sorted((n_red - n_pdf).elements())
            if only_pdf or only_red:
                status = "NUM_MISMATCH"
            elif dice < LOW_SIM_DICE:
                status = "LOW_SIM"
            else:
                status = "OK"
        summary[status] += 1
        if status != "OK":
            rows.append({
                "page": p, "status": status, "dice": dice,
                "numbers_only_in_pdf_text": only_pdf[:15],
                "numbers_only_in_reducto": only_red[:15],
            })
    checked = sum(v for k, v in summary.items() if k != "NO_TEXT_LAYER")
    differing = summary.get("NUM_MISMATCH", 0) + summary.get("LOW_SIM", 0)
    ratio = round(differing / checked, 4) if checked else None
    if checked == 0:
        verdict = "NO_REFERENCE"          # tidak ada teks bawaan sama sekali (scan murni)
    elif checked >= MIN_PAGES_FOR_VERDICT and ratio >= UNRELIABLE_FLAG_RATIO:
        verdict = "UNRELIABLE_REFERENCE"  # teks bawaan kemungkinan OCR bawaan scan yang berisik
    else:
        verdict = "USABLE_REFERENCE"
    return {
        "method": "pypdf_text_layer_vs_reducto_blocks",
        "thresholds": {
            "low_sim_dice": LOW_SIM_DICE, "min_text_layer_words": MIN_TEXT_LAYER_WORDS,
            "unreliable_flag_ratio": UNRELIABLE_FLAG_RATIO, "min_pages_for_verdict": MIN_PAGES_FOR_VERDICT,
        },
        "page_status_counts": dict(summary),
        "differing_ratio": ratio,
        "reference_reliability": verdict,
        "pages_to_review": rows,
        "note": ("Pendeteksi, bukan bukti kebenaran. Halaman OK tidak menggantikan QA manusia. "
                 "Jika reference_reliability = UNRELIABLE_REFERENCE/NO_REFERENCE, pemeriksaan ini TIDAK "
                 "informatif untuk dokumen tsb; verifikasi harus lewat gambar halaman PDF asli."),
    }


# ----------------------------------------------------------------------- proses satu PDF
def file_stem(doc_id: str, args) -> str:
    suffix = f"__p{args.page_range[0]:03d}-{args.page_range[1]:03d}" if args.page_range else ""
    return f"{doc_id}{suffix}__reducto-{args.model}"


def process_one(pdf: Path, doc_id: str, args, client, fetch_json) -> dict:
    out = Path(args.out_dir)
    stem = file_stem(doc_id, args)
    raw_path = out / "raw" / f"{stem}.json"
    md_path = out / "markdown" / f"{stem}.md"
    man_path = out / "manifests" / f"{stem}.manifest.json"

    prev = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else None
    info = inspect_pdf(pdf)
    manifest: dict = {
        "doc_id": doc_id,
        "source_pdf_path": str(pdf),
        "source_pdf_sha256": sha256_file(pdf),
        "source_pdf_bytes": pdf.stat().st_size,
        "local_page_count": info["pages"],
        "provider": "reducto",
        "script_version": SCRIPT_VERSION,
        "issues": list(info["issues"]),
        "status": None,
    }

    if not info["is_pdf"]:
        manifest["status"] = "REJECTED_NOT_PDF"
        return manifest

    n_local = info["pages"]
    if args.page_range:
        start, end = args.page_range
        end = min(end, n_local) if n_local else end
        expected = list(range(start, end + 1))
    else:
        expected = list(range(1, n_local + 1)) if n_local else []

    reuse = raw_path.exists() and not args.force
    if raw_path.exists() and args.force:
        stamp = datetime.now(WIB).strftime("%Y%m%d%H%M%S")
        old = raw_path.with_name(f"{raw_path.stem}__superseded_{stamp}.json")
        raw_path.rename(old)
        manifest["supersedes_raw_sha256"] = sha256_file(old)
        manifest["issues"].append(f"RAW_LAMA_DIPINDAH: {old.name}")

    if reuse:
        d = json.loads(raw_path.read_text(encoding="utf-8"))
        manifest["reused_existing_raw"] = True
        if prev:
            for k in ("request", "timing", "sdk_version"):
                manifest[k] = prev.get(k)
            manifest["job_result_was_url"] = prev.get("job_result_was_url")
        else:
            manifest["request"] = "TIDAK_DIKETAHUI: raw dipakai ulang tanpa manifest sebelumnya"
            manifest["timing"] = None
    else:
        import reducto as _sdk

        started = now_iso()
        settings, resp = call_reducto(client, pdf, args.model, args.page_range)
        if resp.get("response_type") != "parse":
            raise ValueError(f"response_type tak terduga: {resp.get('response_type')!r}")
        d, was_url = resolve_result(resp, fetch_json)
        write_json(raw_path, d)
        manifest.update({
            "reused_existing_raw": False,
            "sdk_version": getattr(_sdk, "__version__", None),
            "request": {
                "model": args.model, "settings": settings,
                "formatting": None, "enhance": None, "retrieval": None,
                "note": "Hanya settings.model (dan page_range bila ada) yang dikirim; sisanya default server.",
            },
            "timing": {"started_at": started, "completed_at": now_iso()},
            "job_result_was_url": was_url,
        })
        if was_url:
            manifest["issues"].append("RESULT_TYPE_URL: hasil diunduh & di-inline-kan; JSON tersimpan = bentuk 'full'.")

    manifest["job"] = {
        "job_id": d.get("job_id"), "studio_link": d.get("studio_link"),
        "duration_s": d.get("duration"), "usage": d.get("usage"),
    }
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(r2md.render_markdown(d), encoding="utf-8")
    manifest["files"] = {
        "raw_json": str(raw_path), "raw_json_sha256": sha256_file(raw_path),
        "markdown": str(md_path), "markdown_sha256": sha256_file(md_path),
    }

    qa = qa_structure(d, expected)
    manifest["technical_qa"] = qa
    flags = list(qa["flags"])
    if n_local is None:
        flags.append("JUMLAH_HALAMAN_LOKAL_TIDAK_DIKETAHUI")
    if args.model not in qa["models_observed"] and qa["models_observed"]:
        flags.append(f"MODEL_TERAMATI_BERBEDA: diminta={args.model}, teramati={qa['models_observed']}")

    if n_local and expected:
        try:
            tl = qa_text_layer(d, pdf_page_texts(pdf, expected), expected)
            manifest["text_layer_check"] = tl
            counts = tl["page_status_counts"]
            verdict = tl["reference_reliability"]
            if verdict == "USABLE_REFERENCE":
                for key in ("NUM_MISMATCH", "LOW_SIM", "NO_TEXT_LAYER"):
                    if counts.get(key):
                        flags.append(f"TEXT_LAYER_{key}: {counts[key]} halaman")
            else:
                # Satu flag jelas, bukan puluhan flag palsu per halaman.
                n_diff = counts.get("NUM_MISMATCH", 0) + counts.get("LOW_SIM", 0)
                flags.append(
                    f"TEXT_LAYER_{verdict}: {n_diff} dari {sum(counts.values())} halaman berbeda; "
                    "pembanding tidak dapat dipercaya (scan + OCR bawaan?) -> wajib QA berbasis gambar halaman"
                )
        except Exception as exc:  # pragma: no cover
            manifest["text_layer_check"] = {"error": f"{type(exc).__name__}: {exc}"}
            flags.append("TEXT_LAYER_CHECK_GAGAL")

    manifest["technical_qa_flags"] = flags
    manifest["status"] = "TECH_QA_FLAGS" if flags else "TECH_QA_PASS"

    # Status QA manusia dipertahankan jika raw tidak berubah; tidak pernah diisi otomatis.
    keep = prev and reuse and prev.get("human_fidelity_qa")
    manifest["human_fidelity_qa"] = prev["human_fidelity_qa"] if keep else {
        "status": "NOT_DONE", "reviewer": None, "reviewed_at": None, "notes": None,
    }
    return manifest


# -------------------------------------------------------------------------------- main
def select_pdfs(pdf_dir: Path, only: str | None) -> list[tuple[Path, str]]:
    files = sorted(p for p in pdf_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    pairs, seen = [], {}
    for p in files:
        did = slugify(p.stem)
        if did in seen:
            raise SystemExit(f"doc_id bentrok: {p.name} dan {seen[did]} -> {did!r}. Ubah salah satu nama berkas.")
        seen[did] = p.name
        pairs.append((p, did))
    if only:
        wanted = {slugify(x) for x in only.split(",") if x.strip()}
        pairs = [(p, d) for p, d in pairs if d in wanted or slugify(p.stem) in wanted]
        missing = wanted - {d for _, d in pairs}
        if missing:
            raise SystemExit(f"--only tidak ditemukan: {sorted(missing)}")
    return pairs


def write_corpus_summary(out: Path, manifests: list[dict], args) -> None:
    slim = []
    for m in manifests:
        qa = m.get("technical_qa") or {}
        slim.append({
            "doc_id": m["doc_id"], "status": m["status"], "source_pdf_sha256": m.get("source_pdf_sha256"),
            "local_page_count": m.get("local_page_count"), "flags": m.get("technical_qa_flags", m.get("issues")),
            "raw_json": (m.get("files") or {}).get("raw_json"),
            "block_count": qa.get("block_count"),
        })
    write_json(out / "corpus_manifest.json", {
        "generated_at": now_iso(), "script_version": SCRIPT_VERSION, "model": args.model,
        "page_range": args.page_range, "documents": slim,
    })
    lines = [
        f"# Ringkasan parsing Reducto — model `{args.model}`", "",
        f"Dibuat: {now_iso()} · skrip {SCRIPT_VERSION}", "",
        "| doc_id | halaman | status | halaman perlu dilihat manusia | catatan |",
        "|---|---:|---|---|---|",
    ]
    for m in manifests:
        tlc = m.get("text_layer_check") or {}
        tl = tlc.get("page_status_counts") or {}
        review = ", ".join(f"{k}={v}" for k, v in tl.items() if k != "OK") or "—"
        if tlc.get("reference_reliability") in ("UNRELIABLE_REFERENCE", "NO_REFERENCE"):
            review = f"{tlc['reference_reliability']} ({review})"
        note = "; ".join((m.get("technical_qa_flags") or m.get("issues") or [])[:2]) or "—"
        lines.append(f"| {m['doc_id']} | {m.get('local_page_count') or '?'} | {m['status']} | {review} | {note[:110]} |")
    lines += ["", "QA fidelity manusia: belum dilakukan oleh skrip ini (human_fidelity_qa = NOT_DONE).", ""]
    (out / "corpus_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None, client=None, fetch_json=default_fetch_json) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", help="doc_id/nama berkas dipisah koma")
    ap.add_argument("--model", default=DEFAULT_MODEL, choices=["r-1", "legacy"])
    ap.add_argument("--page-range", help="MULAI-AKHIR, mis. 1-3 (untuk pilot hemat kredit)")
    ap.add_argument("--force", action="store_true", help="parse ulang; raw lama dipindah, tidak ditimpa")
    ap.add_argument("--dry-run", action="store_true", help="tanpa panggilan API; tampilkan rencana")
    ap.add_argument("--max-retries", type=int, default=None, help="override retry SDK (default SDK)")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--base-url", default=None, help="mis. endpoint regional Reducto")
    args = ap.parse_args(argv)
    args.page_range = parse_page_range(args.page_range)

    pdf_dir, out = Path(args.pdf_dir), Path(args.out_dir)
    pairs = select_pdfs(pdf_dir, args.only)
    if not pairs:
        raise SystemExit(f"Tidak ada .pdf di {pdf_dir}")

    if args.dry_run:
        total = 0
        print(f"[DRY-RUN] model={args.model} page_range={args.page_range} — tidak ada panggilan API\n")
        for p, did in pairs:
            info = inspect_pdf(p)
            raw = out / "raw" / f"{file_stem(did, args)}.json"
            n = info["pages"] or 0
            if args.page_range and n:
                n = max(0, min(args.page_range[1], n) - args.page_range[0] + 1)
            action = "AKAN DI-PARSE"
            if not info["is_pdf"]:
                action = "DITOLAK (bukan PDF)"
            elif raw.exists() and not args.force:
                action = "SKIP (raw sudah ada)"
            else:
                total += n
            print(f"  {did:<45} {n:>5} hal  {action}  {'; '.join(info['issues'])}")
        print(f"\nTotal halaman yang akan dikirim ke API: {total}")
        return 0

    if client is None:
        api_key = os.environ.get("REDUCTO_API_KEY")
        if not api_key:
            raise SystemExit("REDUCTO_API_KEY belum diset (export REDUCTO_API_KEY=...).")
        from reducto import Reducto

        kw = {"api_key": api_key, "timeout": args.timeout}
        if args.max_retries is not None:
            kw["max_retries"] = args.max_retries
        if args.base_url:
            kw["base_url"] = args.base_url
        client = Reducto(**kw)

    manifests, failed = [], 0
    for p, did in pairs:
        print(f"[{len(manifests) + 1}/{len(pairs)}] {did} ...", flush=True)
        try:
            m = process_one(p, did, args, client, fetch_json)
        except Exception as exc:
            failed += 1
            m = {
                "doc_id": did, "source_pdf_path": str(p), "status": "PARSE_FAILED",
                "error": f"{type(exc).__name__}: {exc}", "issues": [traceback.format_exc(limit=3)],
            }
            # Jejak kegagalan disimpan terpisah; tidak menimpa manifest sukses sebelumnya.
            write_json(out / "manifests" / f"{file_stem(did, args)}.FAILED.manifest.json", m)
            print(f"    GAGAL: {m['error']}", flush=True)
        else:
            write_json(out / "manifests" / f"{file_stem(did, args)}.manifest.json", m)
            if m["status"] == "REJECTED_NOT_PDF":
                failed += 1
            print(f"    {m['status']}  {'; '.join(m.get('technical_qa_flags') or [])[:160]}", flush=True)
        manifests.append(m)

    write_corpus_summary(out, manifests, args)
    print(f"\nSelesai: {len(manifests) - failed}/{len(manifests)} dokumen tanpa kegagalan. Ringkasan: {out / 'corpus_summary.md'}")
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
