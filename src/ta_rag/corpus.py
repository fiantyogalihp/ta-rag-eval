"""Manajemen korpus 13 PDF JKN: buka zip -> verifikasi SHA256/halaman -> rencana perintah parsing.

Sumber kebenaran daftar dokumen = config/corpus.json (dihasilkan dari audit zip pengguna 2026-11-01).
Tidak ada panggilan jaringan di modul ini.

    python -m ta_rag.corpus unpack --zip <zip> --dest data/raw_pdf
    python -m ta_rag.corpus verify --pdf-dir data/raw_pdf
    python -m ta_rag.corpus plan   --pdf-dir data/raw_pdf --out-dir data/reducto
    python -m ta_rag.corpus manifest --out data/manifest/scope_manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO / "config" / "corpus.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [d["doc_id"] for d in cfg["documents"]]
    if len(ids) != len(set(ids)):
        raise ValueError("doc_id ganda di corpus.json")
    return cfg


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count_pages(path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages)


def unpack(zip_path: Path, dest: Path) -> list[Path]:
    """Ambil HANYA berkas .pdf, ratakan ke dest (nama dasar). Tolak nama bentrok dan path berbahaya."""
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad:
            raise ValueError(f"zip rusak pada {bad}")
        for info in z.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                continue
            name = Path(info.filename).name
            if not name or name.startswith("."):
                continue
            target = dest / name
            if target.exists() or target in written:
                raise ValueError(f"nama berkas bentrok saat meratakan: {name}")
            with z.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)
            written.append(target)
    return written


def verify(pdf_dir: Path, cfg: dict, check_pages: bool = True) -> list[str]:
    """Kembalikan daftar masalah (kosong = korpus identik dengan audit)."""
    problems: list[str] = []
    expected = {d["file"]: d for d in cfg["documents"]}
    present = {p.name: p for p in Path(pdf_dir).glob("*.pdf")}
    for name in sorted(set(expected) - set(present)):
        problems.append(f"HILANG: {name}")
    for name in sorted(set(present) - set(expected)):
        problems.append(f"TAK_DIKENAL (tidak ada di corpus.json): {name}")
    for name in sorted(set(expected) & set(present)):
        d, p = expected[name], present[name]
        with open(p, "rb") as f:
            if f.read(5) != b"%PDF-":
                problems.append(f"BUKAN_PDF (header salah): {name}")
                continue
        if sha256_file(p) != d["sha256"]:
            problems.append(f"SHA256_BEDA: {name}")
        if check_pages:
            try:
                n = count_pages(p)
            except Exception as exc:  # pragma: no cover
                problems.append(f"GAGAL_BACA_HALAMAN: {name}: {type(exc).__name__}")
                continue
            if n != d["pages"]:
                problems.append(f"HALAMAN_BEDA: {name}: {n} != {d['pages']}")
    return problems


def _parse_scope(scope: str) -> tuple[int, int]:
    a, b = scope.split("-")
    return int(a), int(b)


def plan_commands(cfg: dict, pdf_dir: str, out_dir: str, roles=("evidence_source", "distractor_only")) -> list[dict]:
    """Rencana perintah parsing untuk pilot. Dokumen yang dicakup penuh dikelompokkan dalam satu perintah;
    dokumen yang hanya sebagian (mis. Permenkes 3/2023 hlm. 1-91) memakai --page-range sendiri."""
    full, partial = [], []
    for d in cfg["documents"]:
        if d["eval_role"] not in roles or not d.get("index_page_scope"):
            continue
        a, b = _parse_scope(d["index_page_scope"])
        (full if (a, b) == (1, d["pages"]) else partial).append((d, a, b))

    base = f"python src/ta_rag/parsing/reducto_parse_corpus.py --pdf-dir {shlex.quote(pdf_dir)} --out-dir {shlex.quote(out_dir)}"
    plans = []
    if full:
        ids = ",".join(d["doc_id"] for d, _, _ in full)
        plans.append({
            "docs": [d["doc_id"] for d, _, _ in full], "pages": sum(d["pages"] for d, _, _ in full),
            "command": f"{base} --only {ids}", "stem_suffix": "",
        })
    for d, a, b in partial:
        plans.append({
            "docs": [d["doc_id"]], "pages": b - a + 1,
            "command": f"{base} --only {d['doc_id']} --page-range {a}-{b}", "stem_suffix": f"__p{a:03d}-{b:03d}",
        })
    return plans


# ---------------------------------------------------------------- cakupan indeks (peran halaman)

ROLE_ANCHOR = "evidence_and_anchor"
ROLE_IN_DOC_DISTRACTOR = "in_document_distractor_not_anchored"
ROLE_DISTRACTOR_DOC = "distractor_only"
ROLES = (ROLE_ANCHOR, ROLE_IN_DOC_DISTRACTOR, ROLE_DISTRACTOR_DOC)


def index_page_roles(doc: dict) -> list[tuple[int, int, str]]:
    """[(awal, akhir, peran)] halaman FISIK yang diindeks. Kosong untuk dokumen yang ditunda (deferred)."""
    scope = doc.get("index_page_scope")
    if not scope:
        return []
    if doc.get("index_page_roles"):
        return [(int(r["pages"][0]), int(r["pages"][1]), r["role"]) for r in doc["index_page_roles"]]
    a, b = _parse_scope(scope)
    return [(a, b, ROLE_ANCHOR if doc.get("eval_role") == "evidence_source" else ROLE_DISTRACTOR_DOC)]


def _pages_of(ranges) -> set[int]:
    out: set[int] = set()
    for a, b in ranges:
        out.update(range(a, b + 1))
    return out


def validate_scope_config(cfg: dict) -> list[str]:
    """Konsistensi konfigurasi cakupan: peran menutup index_page_scope tanpa celah/tumpang tindih;
    jangkar pertanyaan == halaman ber-peran evidence_and_anchor; dokumen deferred tidak punya cakupan."""
    problems: list[str] = []
    for d in cfg["documents"]:
        did, role = d["doc_id"], d.get("eval_role")
        if role == "deferred":
            if d.get("index_page_scope") or d.get("index_page_roles") or d.get("pilot_pages"):
                problems.append(f"{did}: dokumen deferred tidak boleh punya cakupan indeks")
            continue
        roles = index_page_roles(d)
        if not roles:
            problems.append(f"{did}: eval_role={role} tetapi tanpa index_page_scope")
            continue
        covered: list[int] = []
        for a, b, r in roles:
            if not (1 <= a <= b <= d["pages"]):
                problems.append(f"{did}: rentang {a}-{b} di luar 1..{d['pages']}")
            if r not in ROLES:
                problems.append(f"{did}: peran tidak dikenal: {r}")
            if role == "distractor_only" and r == ROLE_ANCHOR:
                problems.append(f"{did}: dokumen pengecoh tidak boleh berperan {ROLE_ANCHOR}")
            if role == "evidence_source" and r == ROLE_DISTRACTOR_DOC:
                problems.append(f"{did}: dokumen sumber bukti tidak boleh berperan {ROLE_DISTRACTOR_DOC}")
            covered.extend(range(a, b + 1))
        scope_pages = _pages_of([_parse_scope(d["index_page_scope"])])
        if len(covered) != len(set(covered)) or set(covered) != scope_pages:
            problems.append(f"{did}: peran halaman tidak menutup index_page_scope tepat sekali")
        if d.get("pilot_pages") != len(scope_pages):
            problems.append(f"{did}: pilot_pages {d.get('pilot_pages')} != jumlah halaman cakupan {len(scope_pages)}")
        if role == "evidence_source":
            anchors = _pages_of([(a, b) for a, b, r in roles if r == ROLE_ANCHOR])
            qr = _pages_of([tuple(x) for x in d.get("question_page_ranges", [])])
            if anchors != qr:
                problems.append(f"{did}: question_page_ranges != halaman ber-peran {ROLE_ANCHOR}")
    return problems


def check_chunk_scope(chunk_rows: list[dict], cfg: dict) -> list[str]:
    """Penjaga indeks: tiap chunk {chunk_id, doc_id, page_start, page_end} harus berada di dalam halaman yang diindeks.
    Mendeteksi dokumen deferred, doc_id tak dikenal, dan halaman di luar cakupan (mis. Permenkes 3/2023 hlm. 92+),
    termasuk chunk yang MELINTASI batas cakupan."""
    docs = {d["doc_id"]: d for d in cfg["documents"]}
    problems: list[str] = []
    for i, c in enumerate(chunk_rows):
        cid = c.get("chunk_id", f"#{i}")
        d = docs.get(c.get("doc_id"))
        if d is None:
            problems.append(f"{cid}: doc_id tak dikenal: {c.get('doc_id')}")
            continue
        a, b = c.get("page_start"), c.get("page_end")
        if type(a) is not int or type(b) is not int or a > b:
            problems.append(f"{cid}: page_start/page_end tidak valid: {a}-{b}")
            continue
        indexed = _pages_of([(x, y) for x, y, _ in index_page_roles(d)])
        if not indexed:
            problems.append(f"{cid}: {d['doc_id']} DITUNDA (deferred), tidak boleh ada di indeks")
            continue
        outside = sorted(set(range(a, b + 1)) - indexed)
        if outside:
            problems.append(f"{cid}: {d['doc_id']} hlm. {outside[0]}-{outside[-1]} di luar cakupan indeks "
                            f"({d['index_page_scope']})")
    return problems


def _ranges_str(pages: set[int]) -> list[str]:
    out, run = [], []
    for p in sorted(pages):
        if run and p == run[-1] + 1:
            run.append(p)
        else:
            if run:
                out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
            run = [p]
    if run:
        out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return out


def scope_manifest(cfg: dict) -> dict:
    """Manifest cakupan: membedakan PDF tersedia, halaman terindeks, jangkar pertanyaan, pengecoh, dan yang ditunda."""
    rows = []
    for d in cfg["documents"]:
        roles = index_page_roles(d)
        indexed = _pages_of([(a, b) for a, b, _ in roles])
        anchors = _pages_of([(a, b) for a, b, r in roles if r == ROLE_ANCHOR])
        in_doc = _pages_of([(a, b) for a, b, r in roles if r == ROLE_IN_DOC_DISTRACTOR])
        rows.append({
            "doc_id": d["doc_id"], "file": d["file"], "eval_role": d.get("eval_role"),
            "pdf_available_pages": d["pages"], "indexed_pages": len(indexed),
            "anchor_pages": _ranges_str(anchors), "in_document_distractor_pages": _ranges_str(in_doc),
            "distractor_doc_pages": _ranges_str(indexed) if d.get("eval_role") == "distractor_only" else [],
            "not_indexed_pages": _ranges_str(set(range(1, d["pages"] + 1)) - indexed),
        })
    return {
        "documents": rows,
        "totals": {"pdf_pages": sum(r["pdf_available_pages"] for r in rows),
                   "indexed_pages": sum(r["indexed_pages"] for r in rows)},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("unpack"); u.add_argument("--zip", required=True); u.add_argument("--dest", default="data/raw_pdf")
    v = sub.add_parser("verify"); v.add_argument("--pdf-dir", default="data/raw_pdf"); v.add_argument("--config", default=str(DEFAULT_CONFIG))
    m = sub.add_parser("manifest"); m.add_argument("--config", default=str(DEFAULT_CONFIG)); m.add_argument("--out", default="data/manifest/scope_manifest.json")
    pl = sub.add_parser("plan"); pl.add_argument("--pdf-dir", default="data/raw_pdf"); pl.add_argument("--out-dir", default="data/reducto"); pl.add_argument("--config", default=str(DEFAULT_CONFIG))
    a = ap.parse_args(argv)

    if a.cmd == "unpack":
        files = unpack(Path(a.zip), Path(a.dest))
        print(f"{len(files)} PDF -> {a.dest}")
        return 0
    cfg = load_config(Path(a.config))
    if a.cmd == "verify":
        problems = verify(Path(a.pdf_dir), cfg)
        for p in problems:
            print(p)
        print("KORPUS COCOK DENGAN AUDIT (13/13)" if not problems else f"{len(problems)} masalah")
        return 0 if not problems else 1
    if a.cmd == "manifest":
        problems = validate_scope_config(cfg)
        for p in problems:
            print(p)
        if problems:
            return 1
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        man = scope_manifest(cfg)
        out.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"manifest -> {out}: {man['totals']['indexed_pages']} dari {man['totals']['pdf_pages']} halaman terindeks")
        return 0
    if a.cmd == "plan":
        plans = plan_commands(cfg, a.pdf_dir, a.out_dir)
        total = sum(p["pages"] for p in plans)
        print(f"# Pilot: {total} halaman (estimasi kredit ~{round(total * 22 / 33)} [Dugaan: 22 kredit/33 hlm dari run Studio; kuota tak diketahui])")
        print("# Jalankan dulu dengan --dry-run, lalu satu dokumen --page-range 1-3, baru perintah di bawah.\n")
        for p in plans:
            print(f"# {', '.join(p['docs'])}  ({p['pages']} hlm)")
            print(p["command"] + "\n")
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
