"""Draf pertanyaan Track R + verifier kutipan terhadap PDF ASLI (bukan terhadap parser).

Aturan (lihat docs/SPEC, CLAUDE.md aturan 14):
  * Pertanyaan = bahan ground truth MANUSIA. File ini hanya DRAF; status `DRAFT_UNVERIFIED_BY_HUMAN`
    baru berubah setelah validator memeriksa kutipan pada GAMBAR halaman PDF.
  * Bukti harus kutipan verbatim dari halaman fisik PDF asli (lapisan teks PDF via poppler `pdftotext`).
    Hasil web search / HTML / teks tanpa halaman PDF TIDAK boleh menjadi bukti primer.
  * Label LAYAK/TIDAK_LAYAK diberikan per JAWABAN (bukan per pertanyaan) sesudah MiMo menjawab.
  * `reference_answer_draft` hanyalah alat bantu baca validator; BUKAN ground truth.

    python -m ta_rag.questions verify --cases data/cases/questions_draft.jsonl --pdf-dir data/raw_pdf
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from .corpus import load_config, sha256_file
from .numbers import unsupported_numbers

KINDS = ("answerable", "not_in_corpus")
STATUSES = ("DRAFT_UNVERIFIED_BY_HUMAN", "HUMAN_VERIFIED")
MIN_QUOTE_CHARS = 25
# Domain A: tidak ada pertanyaan dosis/klinis (keputusan D1).
CLINICAL_RE = re.compile(r"\b(dosis|mg|ml|mcg|tablet|kapsul|sirup|injeksi|infus)\b", re.I)
REQUIRED = (
    "case_id", "track", "kind", "question", "source_doc_id", "group_id", "evidence_group",
    "question_type", "status", "human_verified",
)


# ---------------------------------------------------------------- teks PDF

def norm(text: str) -> str:
    """Normalisasi pembanding: NFKC, buang soft-hyphen, rapatkan spasi, casefold."""
    text = unicodedata.normalize("NFKC", text or "").replace("­", "")
    return " ".join(text.split()).casefold()


def _pdftotext(pdf: Path, first: int, last: int, layout: bool) -> list[str]:
    cmd = ["pdftotext", "-enc", "UTF-8", "-f", str(first), "-l", str(last)]
    if layout:
        cmd.append("-layout")
    cmd += [str(pdf), "-"]
    out = subprocess.run(cmd, check=True, capture_output=True).stdout.decode("utf-8", "replace")
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def page_variants(pdf: Path, page: int) -> list[str]:
    """Teks halaman FISIK `page` (1-indeks) dalam dua mode baca (urutan baca & layout), ternormalisasi."""
    return [norm(_pdftotext(pdf, page, page, layout)[0]) for layout in (False, True)]


def range_pages(pdf: Path, first: int, last: int) -> dict[int, str]:
    """{halaman: teks ternormalisasi (gabungan dua mode)} untuk rentang halaman fisik."""
    a = _pdftotext(pdf, first, last, False)
    b = _pdftotext(pdf, first, last, True)
    return {first + i: norm(a[i] if i < len(a) else "") + " || " + norm(b[i] if i < len(b) else "")
            for i in range(max(len(a), len(b)))}


# ---------------------------------------------------------------- kandidat kutipan (Studi 2)

_MONTHS = "Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember"
# jenis -> pola kalimat bernilai. Hanya BAHAN: manusia memilih, menulis pertanyaan, dan memeriksa pada gambar halaman.
# urutan = prioritas bila satu kalimat cocok dengan beberapa jenis ("tanggal 10 bulan berikutnya" adalah tanggal, bukan durasi)
CANDIDATE_PATTERNS = {
    "numeric_date": re.compile(rf"\btanggal\s+\d{{1,2}}\b|\b\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}}\b", re.I),
    "numeric_money": re.compile(r"\bRp\s?\d"),
    "numeric_percent": re.compile(r"\d+(?:,\d+)?\s*%|\bpersen\b", re.I),
    "numeric_duration": re.compile(r"\b\d+\s*(?:\([^)]*\)\s*)?(?:hari|minggu|bulan|tahun(?!\s*\d{4}))\b", re.I),
    "numeric_count": re.compile(r"\b(?:paling|sekurang-kurangnya|minimal|maksimal|sebanyak)\b[^.;]{0,40}\b\d+\b", re.I),
    "definition": re.compile(r"^[A-Z][^.;]{2,80}\s+adalah\s+\S"),
}
_SENT_SPLIT = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")
CANDIDATE_MIN_CHARS, CANDIDATE_MAX_CHARS = MIN_QUOTE_CHARS, 300
_OCR_GARBLE = re.compile(r"\b\d[A-Za-z]+\d\b")  # "2OL8": galat OCR dokumen pindai; "Pasal 7A" (angka-huruf) sah
_LIST_ITEMS = re.compile(r";\s+[a-z]\.\s")  # daftar huruf a./b./c.: bukan satu fakta


def extract_candidates(pdf_dir: Path, cfg: dict, exclude_quotes: list[str] | None = None) -> list[dict]:
    """Kalimat bernilai dari halaman FISIK dokumen sumber evidence (rentang `question_page_ranges`), per jenis pertanyaan. Kutipan diambil
    dari teks PDF asli sehingga lolos `verify_answerable`; sitasi ("Nomor 3 Tahun 2023"), dosis/klinis, dan kutipan yang sudah dipakai
    (`exclude_quotes`) dibuang. Keluaran hanyalah bahan: pemilihan, penulisan pertanyaan, dan pemeriksaan pada gambar halaman tetap manusia."""
    used = [norm(q) for q in (exclude_quotes or [])]
    out, seen = [], set()
    for doc in cfg["documents"]:
        if doc.get("eval_role") != "evidence_source":
            continue
        pdf = Path(pdf_dir) / doc["file"]
        for first, last in question_ranges(doc):
            pages = range_pages(pdf, first, last)
            for page in range(first, last + 1):
                raw = _pdftotext(pdf, page, page, False)[0]
                for sent in (x for para in re.split(r"\n\s*\n", raw) for x in _SENT_SPLIT.split(" ".join(para.split()))):
                    n = norm(sent)
                    if not CANDIDATE_MIN_CHARS <= len(sent) <= CANDIDATE_MAX_CHARS or n in seen or CLINICAL_RE.search(sent) or _OCR_GARBLE.search(sent) or _LIST_ITEMS.search(sent):
                        continue
                    if n not in pages.get(page, "") or any(u in n or n in u for u in used):
                        continue
                    for kind, pat in CANDIDATE_PATTERNS.items():
                        if pat.search(sent):
                            seen.add(n)
                            out.append({"doc_id": doc["doc_id"], "page": page, "type": kind, "quote": sent})
                            break
    return out


# ---------------------------------------------------------------- konfigurasi

def question_ranges(doc: dict) -> list[tuple[int, int]]:
    ranges = doc.get("question_page_ranges")
    if ranges:
        return [(int(a), int(b)) for a, b in ranges]
    return [(1, int(doc.get("pilot_pages") or 0))]


def _doc_by_id(cfg: dict) -> dict[str, dict]:
    return {d["doc_id"]: d for d in cfg["documents"]}


def pilot_scope_pages(doc: dict) -> list[int]:
    """Halaman yang benar-benar terindeks pada pilot (bukan hanya yang boleh dijadikan jangkar pertanyaan)."""
    scope = doc.get("index_page_scope")
    if not scope:
        return []
    a, _, b = str(scope).partition("-")
    return list(range(int(a), int(b or a) + 1))


# ---------------------------------------------------------------- verifikasi per rekaman

def check_web_crosscheck(rec: dict) -> list[str]:
    """`web_crosscheck` wajib dict: {"performed": true, url, result, ...} atau {"performed": false, "reason": "..."}.
    Cek silang web selalu SEKUNDER (bukan bukti); `null` tidak diterima agar ketidaklakuannya terdokumentasi."""
    cid = rec.get("case_id", "?")
    xc = rec.get("web_crosscheck")
    if not isinstance(xc, dict) or type(xc.get("performed")) is not bool:
        return [f"{cid}: web_crosscheck harus dict dengan 'performed' bool (bukan null)"]
    if xc["performed"]:
        missing = [k for k in ("url", "result", "checked_on") if not xc.get(k)]
        return [f"{cid}: web_crosscheck performed=true butuh {missing}"] if missing else []
    if not (isinstance(xc.get("reason"), str) and xc["reason"].strip()):
        return [f"{cid}: web_crosscheck performed=false butuh 'reason' tidak kosong"]
    return []


def check_schema(rec: dict) -> list[str]:
    issues = []
    cid = rec.get("case_id", "?")
    for k in REQUIRED:
        if k not in rec or rec[k] in (None, ""):
            issues.append(f"{cid}: field wajib kosong: {k}")
    if rec.get("kind") not in KINDS:
        issues.append(f"{cid}: kind harus salah satu {KINDS}")
    if rec.get("status") not in STATUSES:
        issues.append(f"{cid}: status tidak valid")
    if rec.get("status") == "DRAFT_UNVERIFIED_BY_HUMAN" and rec.get("human_verified") is not False:
        issues.append(f"{cid}: draf harus human_verified=false")
    if rec.get("status") == "HUMAN_VERIFIED" and not (rec.get("validator") and rec.get("validated_at")):
        issues.append(f"{cid}: HUMAN_VERIFIED butuh validator dan validated_at")
    q = rec.get("question") or ""
    if not q.startswith("Menurut "):
        issues.append(f"{cid}: pertanyaan harus berbentuk 'Menurut <dokumen> …' (tanpa status 'berlaku sekarang')")
    if not q.rstrip().endswith("?"):
        issues.append(f"{cid}: pertanyaan harus diakhiri tanda tanya")
    if CLINICAL_RE.search(q):
        issues.append(f"{cid}: memuat kata dosis/klinis (domain A melarang)")
    issues += check_web_crosscheck(rec)
    if rec.get("kind") == "answerable":
        ref = rec.get("reference_answer_draft") or ""
        extra = unsupported_numbers(ref, rec.get("source_quote") or "")
        if extra:
            issues.append(f"{cid}: jawaban rujukan memuat angka yang tidak ada di kutipan: {sorted(extra)}")
        if type(rec.get("source_page")) is not int or rec["source_page"] < 1:
            issues.append(f"{cid}: source_page harus bilangan bulat halaman FISIK >= 1")
        if len(norm(rec.get("source_quote") or "")) < MIN_QUOTE_CHARS:
            issues.append(f"{cid}: source_quote kosong/terlalu pendek (< {MIN_QUOTE_CHARS} karakter)")
        if rec.get("absence_terms"):
            issues.append(f"{cid}: answerable tidak boleh punya absence_terms")
    elif rec.get("kind") == "not_in_corpus":
        if rec.get("source_page") is not None or rec.get("source_quote"):
            issues.append(f"{cid}: not_in_corpus tidak boleh punya source_page/source_quote")
        if not rec.get("absence_terms"):
            issues.append(f"{cid}: not_in_corpus butuh absence_terms")
    return issues


def verify_answerable(rec: dict, pdf_dir: Path, cfg: dict) -> list[str]:
    cid = rec["case_id"]
    docs = _doc_by_id(cfg)
    doc = docs.get(rec["source_doc_id"])
    if doc is None:
        return [f"{cid}: source_doc_id tidak ada di corpus.json"]
    issues = []
    if doc.get("eval_role") != "evidence_source":
        issues.append(f"{cid}: dokumen {doc['doc_id']} berperan {doc.get('eval_role')}, bukan evidence_source")
    page = rec["source_page"]
    if not any(a <= page <= b for a, b in question_ranges(doc)):
        issues.append(f"{cid}: hlm. {page} di luar rentang jangkar pertanyaan {question_ranges(doc)}")
        return issues
    pdf = pdf_dir / doc["file"]
    if not pdf.is_file():
        return issues + [f"{cid}: PDF tidak ditemukan: {pdf}"]
    digest = sha256_file(pdf)
    if digest != doc["sha256"]:
        issues.append(f"{cid}: sha256 PDF berbeda dari corpus.json")
    if rec.get("source_pdf_sha256") not in (None, digest):
        issues.append(f"{cid}: source_pdf_sha256 pada rekaman tidak cocok dengan PDF")
    quote = norm(rec["source_quote"])
    if not any(quote in v for v in page_variants(pdf, page)):
        issues.append(f"{cid}: KUTIPAN TIDAK DITEMUKAN pada hlm. fisik {page} {doc['file']}")
        return issues
    # Kutipan yang sama di halaman lain pada dokumen yang sama = jangkar ambigu bagi validator.
    first, last = question_ranges(doc)[0][0], question_ranges(doc)[-1][1]
    others = [p for p, t in range_pages(pdf, first, last).items() if p != page and quote in t]
    if others:
        issues.append(f"{cid}: kutipan yang sama juga ada di hlm. {others} (jangkar ambigu)")
    return issues


def verify_absence(rec: dict, pdf_dir: Path, cfg: dict) -> list[str]:
    """Probe: tiap istilah harus ABSEN pada semua halaman terindeks dari semua dokumen pilot (lapisan teks PDF)."""
    cid = rec["case_id"]
    issues = []
    terms = [norm(t) for t in rec["absence_terms"]]
    for doc in cfg["documents"]:
        if doc.get("eval_role") not in ("evidence_source", "distractor_only"):
            continue
        pages = pilot_scope_pages(doc)
        if not pages:
            continue
        pdf = pdf_dir / doc["file"]
        if not pdf.is_file():
            issues.append(f"{cid}: PDF tidak ditemukan: {pdf}")
            continue
        texts = range_pages(pdf, pages[0], pages[-1])
        for term in terms:
            hits = [p for p, t in texts.items() if term in t]
            if hits:
                issues.append(f"{cid}: istilah '{term}' ADA di {doc['doc_id']} hlm. {hits[:5]} -> bukan probe bersih")
    return issues


def absence_audit(rows: list[dict], pdf_dir: Path, cfg: dict, checked_on: str) -> dict:
    """Laporan audit cakupan untuk probe `not_in_corpus` (bukti ketiadaan harus terdokumentasi, bukan sekadar "tak ketemu").

    Isi: dokumen × rentang halaman yang dicari, metode, istilah, hasil per dokumen, dan istilah KONTROL (tetangga
    yang seharusnya ada) agar terbukti metode pencarian memang bisa menemukan topik terkait. Pencarian kata kunci
    pada lapisan teks BUKAN bukti semantik; dokumen scan wajib dicek manual pada gambar halaman.
    """
    docs = [d for d in cfg["documents"]
            if d.get("eval_role") in ("evidence_source", "distractor_only") and pilot_scope_pages(d)]
    texts: dict[str, dict[int, str]] = {}
    scope = []
    for d in docs:
        pages = pilot_scope_pages(d)
        texts[d["doc_id"]] = range_pages(pdf_dir / d["file"], pages[0], pages[-1])
        scope.append({"doc_id": d["doc_id"], "file": d["file"], "sha256": d["sha256"], "eval_role": d["eval_role"],
                      "text_layer_class": d.get("provenance", {}).get("class"),
                      "pages_searched": [pages[0], pages[-1]], "n_pages": len(texts[d["doc_id"]])})

    def hits(term: str) -> dict[str, list[int]]:
        t = norm(term)
        return {doc_id: [p for p, tx in pg.items() if t in tx] for doc_id, pg in texts.items()
                if any(t in tx for tx in pg.values())}

    probes = []
    for r in rows:
        if r.get("kind") != "not_in_corpus":
            continue
        found = {t: hits(t) for t in r["absence_terms"]}
        controls = {t: hits(t) for t in r.get("control_terms", [])}
        probes.append({"case_id": r["case_id"], "question": r["question"], "terms": r["absence_terms"],
                       "result": "ABSENT_ALL" if not any(found.values()) else "FOUND", "found": found,
                       "control_terms": controls,
                       "controls_ok": all(controls.values()) if controls else None})
    scan_docs = [s["doc_id"] for s in scope if str(s["text_layer_class"]).startswith("scan")]
    return {
        "checked_on": checked_on,
        "method": "pdftotext (poppler), dua mode baca (urutan baca & layout), casefold, pencocokan substring",
        "limits": ["kata kunci != makna: sinonim/penulisan lain bisa lolos",
                   "lapisan teks dokumen scan berisik: istilah salah-OCR bisa lolos",
                   "pencarian ini hanya halaman terindeks pilot, bukan seluruh PDF"],
        "manual_check_required_docs": scan_docs,
        "scope": scope,
        "probes": probes,
    }


def verify_record(rec: dict, pdf_dir: Path | None, cfg: dict) -> list[str]:
    issues = check_schema(rec)
    if issues or pdf_dir is None:
        return issues
    if rec["kind"] == "answerable":
        return verify_answerable(rec, pdf_dir, cfg)
    return verify_absence(rec, pdf_dir, cfg)


# ---------------------------------------------------------------- verifikasi himpunan

def load_cases(path: Path) -> list[dict]:
    rows = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{n}: JSON tidak valid: {exc}") from exc
    return rows


def validate_set(rows: list[dict], cfg: dict, expect_total: int = 20, expect_answerable: int = 16) -> list[str]:
    issues = []
    if len(rows) != expect_total:
        issues.append(f"jumlah pertanyaan {len(rows)} != {expect_total}")
    ids = [r.get("case_id") for r in rows]
    issues += [f"case_id ganda: {k}" for k, v in Counter(ids).items() if v > 1]
    kinds = Counter(r.get("kind") for r in rows)
    if kinds.get("answerable", 0) != expect_answerable:
        issues.append(f"answerable {kinds.get('answerable', 0)} != {expect_answerable}")
    if kinds.get("not_in_corpus", 0) != expect_total - expect_answerable:
        issues.append(f"not_in_corpus {kinds.get('not_in_corpus', 0)} != {expect_total - expect_answerable}")
    # Satu halaman fisik hanya boleh menjadi jangkar SATU pertanyaan (mencegah kebocoran evidence_group).
    egs = Counter(r.get("evidence_group") for r in rows)
    issues += [f"evidence_group ganda: {k}" for k, v in egs.items() if v > 1]
    qs = Counter(norm(r.get("question", "")) for r in rows)
    issues += [f"pertanyaan ganda: {k[:60]}" for k, v in qs.items() if v > 1]
    known = _doc_by_id(cfg)
    for r in rows:
        if r.get("track") != "R":
            issues.append(f"{r.get('case_id')}: track harus 'R'")
        if r.get("source_doc_id") not in known:
            issues.append(f"{r.get('case_id')}: source_doc_id tidak dikenal")
    return issues


def summary(rows: list[dict]) -> dict:
    return {
        "total": len(rows),
        "by_kind": dict(Counter(r["kind"] for r in rows)),
        "by_doc": dict(Counter(r["source_doc_id"] for r in rows)),
        "by_type": dict(Counter(r["question_type"] for r in rows)),
        "needs_visual_check": sorted(r["case_id"] for r in rows if r.get("needs_visual_check")),
        "web_crosschecked": sorted(r["case_id"] for r in rows if (r.get("web_crosscheck") or {}).get("performed")),
        "human_verified": sum(1 for r in rows if r.get("human_verified")),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="verifikasi skema, himpunan, dan kutipan terhadap PDF asli")
    v.add_argument("--cases", required=True)
    v.add_argument("--pdf-dir", help="folder PDF asli; tanpa ini hanya skema/himpunan yang dicek")
    v.add_argument("--config", default=None)
    v.add_argument("--expect-total", type=int, default=20)
    v.add_argument("--expect-answerable", type=int, default=16)
    c = sub.add_parser("candidates", help="kalimat bernilai dari halaman sumber evidence sebagai BAHAN penulisan pertanyaan")
    c.add_argument("--pdf-dir", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--exclude", nargs="*", default=[], help="berkas kasus (jsonl) yang kutipannya tidak boleh diulang")
    c.add_argument("--config", default=None)
    a = sub.add_parser("absence-audit", help="tulis laporan audit cakupan untuk probe not_in_corpus")
    a.add_argument("--cases", required=True)
    a.add_argument("--pdf-dir", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--config", default=None)
    a.add_argument("--date", required=True, help="tanggal pemeriksaan (YYYY-MM-DD)")
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config)) if args.config else load_config()
    if args.cmd == "candidates":
        used = [r["source_quote"] for p in args.exclude for r in load_cases(Path(p)) if r.get("source_quote")]
        cands = extract_candidates(Path(args.pdf_dir), cfg, used)
        Path(args.out).write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in cands) + "\n", encoding="utf-8")
        print(json.dumps(dict(Counter(x["type"] for x in cands)), ensure_ascii=False), "->", args.out)
        return 0
    rows = load_cases(Path(args.cases))
    if args.cmd == "absence-audit":
        report = absence_audit(rows, Path(args.pdf_dir), cfg, args.date)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        bad = [p["case_id"] for p in report["probes"] if p["result"] != "ABSENT_ALL" or p["controls_ok"] is False]
        print(f"ditulis {args.out}; probe={len(report['probes'])}; bermasalah={bad or 'tidak ada'}")
        return 1 if bad else 0
    pdf_dir = Path(args.pdf_dir) if args.pdf_dir else None
    issues = validate_set(rows, cfg, args.expect_total, args.expect_answerable)
    for r in rows:
        issues += verify_record(r, pdf_dir, cfg)
    print(json.dumps(summary(rows), ensure_ascii=False, indent=2))
    mode = "SKEMA+PDF" if pdf_dir else "SKEMA SAJA (PDF tidak diperiksa)"
    if issues:
        print(f"\nGAGAL [{mode}] — {len(issues)} masalah:")
        for i in issues:
            print(" -", i)
        return 1
    print(f"\nLOLOS [{mode}]. Ini BUKAN verifikasi manusia: validator tetap wajib memeriksa gambar halaman.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
