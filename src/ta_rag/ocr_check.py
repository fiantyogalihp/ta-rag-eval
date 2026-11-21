"""Pemeriksaan silang OCR independen untuk dokumen SCAN (CLAUDE.md aturan 11).

Teks bawaan dokumen scan adalah OCR tak kasatmata milik penerbit dan memuat salah baca. Modul ini membaca ulang tiap halaman sebagai
gambar dengan mesin OCR lain (RapidOCR/PP-OCRv4 via ONNX; lokal, tanpa jaringan), lalu membandingkannya dengan lapisan teks bawaan:
kesepakatan per halaman, istilah probe `not_in_corpus` yang HARUS nihil (beserta kontrol positif dari audit), dan kutipan jawaban.

Ini alat bantu, BUKAN verifikasi manusia: nihilnya sebuah KATA pada dua pembacaan OCR bukan bukti nihilnya TOPIK, dan keluaran tidak
mengubah status pertanyaan, workflow, atau ledger. Pemeriksaan gambar halaman oleh validator (S07/S08) tetap wajib.

    pip install -e ".[ocr]"        # rapidocr-onnxruntime; hanya Python < 3.13
    python -m ta_rag.ocr_check --cases data/cases/questions_draft.jsonl --pdf-dir data/raw_pdf \
        --audit data/cases/absence_audit.json --out-dir data/qa/ocr_crosscheck
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from .corpus import count_pages, load_config, sha256_file
from .numbers import extract_numbers
from .questions import load_cases, norm, range_pages

DPI = 300
MAX_SIDE = 3400  # RapidOCR mengecilkan gambar ke sisi terpanjang 2000 px sebelum membaca; pada 300 dpi itu terlalu kasar
MIN_WORD = 5  # kesepakatan dihitung pada kata huruf >= 5
LOW_AGREEMENT = 0.90  # dugaan awal (heuristik): halaman dengan recall/presisi di bawah ini ditandai
MIN_CONTROL_RECALL = 0.80  # dugaan awal (heuristik): kontrol positif lolos bila OCR menemukan >= 80% halaman yang ditemukan lapisan bawaan


def squash(text: str) -> str:
    """Hanya [a-z0-9]: OCR menyatukan atau memecah kata ('bidangketenagakerjaan'), jadi kedua bentuk dicocokkan."""
    return re.sub(r"[^a-z0-9]", "", norm(text))


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", norm(text)) if len(w) >= MIN_WORD}


# ------------------------------------------------------------------ urutan baca dan kesepakatan

def reading_order(lines: list[dict]) -> list[dict]:
    """Kotak teks ({text,x,cy,h}) dikelompokkan ke baris visual menurut pusat vertikal (toleransi setengah tinggi median), lalu kiri ke
    kanan. Penanda ayat '(5)' dan teksnya sebaris; pita tetap per-y menyisipkannya di tengah kalimat."""
    if not lines:
        return []
    tol = statistics.median(l["h"] for l in lines) / 2
    rows: list[list[dict]] = []
    for l in sorted(lines, key=lambda l: l["cy"]):
        if rows and l["cy"] - rows[-1][0]["cy"] <= tol:
            rows[-1].append(l)
        else:
            rows.append([l])
    return [l for row in rows for l in sorted(row, key=lambda l: l["x"])]


def page_text(lines: list[dict]) -> str:
    return norm("\n".join(l["text"] for l in reading_order(lines)))


def agreement(ocr: str, layer: str) -> dict:
    """Kesepakatan dua pembacaan (BUKAN akurasi): recall = kata lapisan bawaan yang ada di OCR; presisi = kata OCR yang ada di lapisan."""
    so, sl, wo, wl = squash(ocr), squash(layer), _words(ocr), _words(layer)
    only_layer = sorted(w for w in wl if w not in so)
    only_ocr = sorted(w for w in wo if w not in sl)
    return {"recall": 1 - len(only_layer) / max(1, len(wl)), "precision": 1 - len(only_ocr) / max(1, len(wo)),
            "only_layer": only_layer[:10], "only_ocr": only_ocr[:10]}


# ------------------------------------------------------------------ pencarian istilah

def max_edits(n: int) -> int:
    """Toleransi salah-baca: istilah < 7 huruf hanya eksak; 7-9 huruf 1 sunting; selanjutnya 20% panjang."""
    return 0 if n < 7 else 1 if n < 10 else n // 5


def near_edits(pattern: str, text: str, k: int) -> int | None:
    """Jarak sunting terkecil `pattern` ke substring mana pun dari `text` (Sellers); None bila > k."""
    m = len(pattern)
    if m == 0 or not text:
        return None
    step = m // (k + 1)
    # prafilter pigeonhole: <= k sunting merusak paling banyak k dari k+1 potongan, jadi satu potongan harus cocok persis
    if step == 0 or not any(pattern[i:i + step] in text for i in range(0, step * (k + 1), step)):
        return None
    prev = [0] * (len(text) + 1)
    for i, ch in enumerate(pattern, 1):
        cur = [i]
        for j in range(1, len(text) + 1):
            cur.append(min(prev[j - 1] + (text[j - 1] != ch), prev[j] + 1, cur[j - 1] + 1))
        prev = cur
    best = min(prev)
    return best if best <= k else None


def search_term(term: str, pages: dict[int, str]) -> dict:
    """Halaman tempat `term` muncul: `exact` (apa adanya), `squashed` (hanya setelah spasi dibuang), `near` ([halaman, sunting])."""
    t = norm(term)
    sq = squash(t)
    out: dict = {"exact": [], "squashed": [], "near": []}
    if not sq:
        return out
    k = max_edits(len(sq))
    for page, text in sorted(pages.items()):
        s = squash(text)
        if t in norm(text):
            out["exact"].append(page)
        elif sq in s:
            out["squashed"].append(page)
        elif k and (e := near_edits(sq, s, k)) is not None:
            out["near"].append([page, e])
    return out


def _hits(term: str, docs: dict[str, dict[int, str]]) -> dict:
    out: dict = {"exact": [], "squashed": [], "near": []}
    for doc, pages in docs.items():
        r = search_term(term, pages)
        out["exact"] += [f"{doc}:{p}" for p in r["exact"]]
        out["squashed"] += [f"{doc}:{p}" for p in r["squashed"]]
        out["near"] += [[f"{doc}:{p}", e] for p, e in r["near"]]
    return out


def check_probes(cases: list[dict], audit: dict, ocr: dict, layer: dict) -> dict:
    """Probe: tiap istilah harus nihil pada OCR baru DAN lapisan bawaan. Kontrol positif (audit): istilah topik tetangga yang ADA harus
    ditemukan OCR pada halaman yang sama dengan lapisan bawaan (bukti bahwa OCR ini sensitif). `controls_ok` None = tak ada kontrol. Ambang recall,
    bukan kesamaan persis: kedua mesin salah baca 'I' kapital sebagai 'l' ('Iuran' -> 'luran') pada halaman yang berbeda."""
    ctrl = {p["case_id"]: p.get("control_terms", {}) for p in audit.get("probes", [])}
    out = {}
    for c in cases:
        if c["kind"] != "not_in_corpus":
            continue
        terms = {t: {"ocr": _hits(t, ocr), "layer": _hits(t, layer)} for t in c["absence_terms"]}
        controls = {}
        for term, per_doc in ctrl.get(c["case_id"], {}).items():
            for doc, expected in per_doc.items():
                if doc in ocr:
                    r = search_term(term, ocr[doc])
                    got = set(r["exact"]) | set(r["squashed"])
                    missing = sorted(set(expected) - got)
                    controls[f"{term} @ {doc}"] = {"expected": expected, "missing": missing, "extra": sorted(got - set(expected)),
                                                   "recall": round(1 - len(missing) / max(1, len(expected)), 3)}
        out[c["case_id"]] = {
            "terms": terms, "controls": controls,
            "clean": not any(v for t in terms.values() for src in t.values() for v in src.values()),
            "controls_ok": all(x["recall"] >= MIN_CONTROL_RECALL for x in controls.values()) if controls else None,
        }
    return out


def check_quotes(cases: list[dict], ocr: dict, layer: dict) -> dict:
    """Kutipan jawaban pada dokumen scan: harus ada persis (spasi/tanda baca diabaikan) pada OCR baru; selisih kata/angka dirinci."""
    out = {}
    for c in cases:
        doc = c["source_doc_id"]
        if c["kind"] != "answerable" or doc not in ocr:
            continue
        page = c["source_page"]
        text, lyr, quote = ocr[doc].get(page, ""), layer[doc].get(page, ""), norm(c["source_quote"])
        exact = squash(quote) in squash(text)
        out[c["case_id"]] = {
            "doc": doc, "page": page, "status": "COCOK" if exact else "PERIKSA", "exact_ocr": exact,
            "exact_layer": squash(quote) in squash(lyr),
            "words_absent": sorted({w for w in re.findall(r"[a-z]+", quote) if len(w) >= 4} - set(re.findall(r"[a-z]+", norm(text)))),
            "numbers_absent": sorted(extract_numbers(c["source_quote"]) - extract_numbers(text)),
        }
    return out


# ------------------------------------------------------------------ mesin OCR dan dokumen

def render_page(pdf: Path, page: int, dpi: int, dest: Path) -> Path:
    stem = dest / f"p{page}"
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-f", str(page), "-l", str(page), "-singlefile", str(pdf), str(stem)],
                   check=True, capture_output=True)
    return stem.with_suffix(".png")


def rapidocr_engine():
    """(fungsi gambar -> kotak teks, info mesin). Impor malas supaya modul ini tetap ringan tanpa extra `ocr`."""
    try:
        from importlib.metadata import version

        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError('rapidocr-onnxruntime belum terpasang: pip install -e ".[ocr]" (hanya Python < 3.13)') from exc
    eng = RapidOCR()
    eng.max_side_len = MAX_SIDE  # shortcut: atribut internal v1.4.4 (versi dipin di extra `ocr`); periksa ulang bila versi naik

    def read(img: Path) -> list[dict]:
        res, _ = eng(str(img), use_cls=False)  # pengklasifikasi sudut 0/180 membalik baris panjang pada halaman yang tegak
        out = []
        for box, text, conf in res or []:
            ys = [float(p[1]) for p in box]
            out.append({"text": text, "conf": round(float(conf), 3), "x": int(min(p[0] for p in box)),
                        "cy": (min(ys) + max(ys)) / 2, "h": max(ys) - min(ys)})
        return out

    return read, {"engine": "rapidocr-onnxruntime", "version": version("rapidocr_onnxruntime"), "max_side_len": MAX_SIDE, "use_cls": False}


def ocr_document(pdf: Path, digest: str, engine, info: dict, cache: Path, dpi: int = DPI) -> dict[int, list[dict]]:
    """{halaman: kotak teks} untuk seluruh PDF. Cache JSON dipakai ulang hanya bila sha256 PDF, dpi, dan parameter mesin sama
    (OCR lambat, analisis murah: pertanyaan boleh berubah tanpa membaca ulang gambar)."""
    meta = {"sha256": digest, "dpi": dpi, **info}
    if cache.is_file():
        old = json.loads(cache.read_text(encoding="utf-8"))
        if old["meta"] == meta:
            return {int(p): ls for p, ls in old["pages"].items()}
    pages: dict[int, list[dict]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for p in range(1, count_pages(pdf) + 1):
            pages[p] = engine(render_page(pdf, p, dpi, Path(tmp)))
            print(f"  OCR {pdf.name} hlm {p}", file=sys.stderr, flush=True)
    cache.write_text(json.dumps({"meta": meta, "pages": pages}, ensure_ascii=False), encoding="utf-8")
    return pages


def summarize(rep: dict) -> dict:
    mean = {d: [round(statistics.mean(a[k] for a in v["agreement"].values()), 3) for k in ("recall", "precision")]
            for d, v in rep["docs"].items() if v["agreement"]}
    low = [f"{d}:{p}" for d, v in rep["docs"].items() for p, a in v["agreement"].items() if min(a["recall"], a["precision"]) < LOW_AGREEMENT]
    dirty = [c for c, v in rep["probes"].items() if not v["clean"]]
    ctrl = [c for c, v in rep["probes"].items() if v["controls_ok"] is False]
    bad = [c for c, v in rep["quotes"].items() if v["status"] != "COCOK"]
    return {"agreement_mean_recall_precision": mean, "low_agreement_pages": low, "probes": f"{len(rep['probes']) - len(dirty)}/{len(rep['probes'])} bersih",
            "probes_with_hits": dirty, "controls_failed": ctrl, "quotes": f"{len(rep['quotes']) - len(bad)}/{len(rep['quotes'])} cocok",
            "quotes_to_check": bad, "flagged": bool(low or dirty or ctrl or bad)}


def run(cfg: dict, cases: list[dict], audit: dict, pdf_dir: Path, out_dir: Path, engine, info: dict,
        doc_ids: list[str] | None = None, dpi: int = DPI) -> dict:
    docs = {d["doc_id"]: d for d in cfg["documents"]}
    ids = doc_ids or audit.get("manual_check_required_docs", [])
    if not ids or any(i not in docs for i in ids):
        raise ValueError(f"dokumen scan tidak ada/tak dikenal: {ids} (isi manual_check_required_docs pada audit atau beri --doc-id)")
    out_dir.mkdir(parents=True, exist_ok=True)
    ocr, layer, per_doc = {}, {}, {}
    for did in ids:
        pdf = pdf_dir / docs[did]["file"]
        digest = sha256_file(pdf)
        if digest != docs[did]["sha256"]:
            raise ValueError(f"{did}: sha256 PDF berbeda dari corpus.json")
        raw = ocr_document(pdf, digest, engine, info, out_dir / f"ocr_{did}.json", dpi)
        ocr[did] = {p: page_text(ls) for p, ls in raw.items()}
        layer[did] = range_pages(pdf, 1, len(raw))
        (out_dir / f"ocr_{did}.txt").write_text(
            "".join(f"===== hlm {p} =====\n" + "\n".join(l["text"] for l in reading_order(ls)) + "\n" for p, ls in sorted(raw.items())),
            encoding="utf-8")
        per_doc[did] = {"file": docs[did]["file"], "sha256": digest, "pages": len(raw),
                        "agreement": {p: agreement(ocr[did][p], layer[did].get(p, "")) for p in sorted(raw)}}
    rep = {"date": date.today().isoformat(), "engine": info, "dpi": dpi, "docs": per_doc,
           "probes": check_probes(cases, audit, ocr, layer), "quotes": check_quotes(cases, ocr, layer)}
    rep["summary"] = summarize(rep)
    (out_dir / "crosscheck_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", required=True)
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--audit", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--config")
    ap.add_argument("--doc-id", action="append", help="bawaan: manual_check_required_docs pada audit")
    ap.add_argument("--dpi", type=int, default=DPI)
    a = ap.parse_args(argv)
    try:
        engine, info = rapidocr_engine()
        rep = run(load_config(Path(a.config)) if a.config else load_config(), load_cases(Path(a.cases)),
                  json.loads(Path(a.audit).read_text(encoding="utf-8")), Path(a.pdf_dir), Path(a.out_dir), engine, info, a.doc_id, a.dpi)
    except (RuntimeError, ValueError) as exc:
        print(f"GAGAL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rep["summary"], ensure_ascii=False, indent=1))
    print("Ini pemeriksaan silang OCR, BUKAN verifikasi manusia: nihil KATA bukan nihil TOPIK; validator tetap memeriksa gambar halaman.")
    return 1 if rep["summary"]["flagged"] else 0


if __name__ == "__main__":
    sys.exit(main())
