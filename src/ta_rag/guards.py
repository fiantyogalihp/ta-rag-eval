"""Penjaga data asli: menolak masukan tanpa provenans sebelum sebuah langkah boleh jalan atau dianggap selesai.

Kontrak tiap penjaga: `guard(repo: Path) -> list[str]`; daftar kosong = lolos. Penjaga TIDAK memperbaiki apa pun dan TIDAK
membuktikan kebenaran ilmiah. Yang dibuktikannya hanya: berkas ini lahir dari jalur yang benar (PDF identik dengan audit, JSON
Reducto punya manifest dan job_id, jawaban punya respons API mentah dan cap waktu setelah pembekuan, label diberi manusia
sebelum skor). Seseorang yang sengaja memalsukan semua penanda sekaligus tetap bisa lolos; penjaga ini menangkap kecelakaan dan
pintasan, bukan kecurangan yang terencana.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import capture, corpus, data, labeling

SYNTHETIC_KEY_RE = re.compile(r'"(synthetic|is_synthetic|sintetis|dummy|fake|fixture|stub)"\s*:\s*(true|"[^"]+")', re.I)
ANCHOR_ROLES = ("evidence_source",)
FAIL_STATUSES = ("PARSE_FAILED", "REJECTED_NOT_PDF", None)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _cfg(repo: Path) -> dict:
    return corpus.load_config(repo / "config" / "corpus.json")


def _ts(s: str) -> datetime:
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- korpus & parsing

def g_pdfs_real(repo: Path) -> list[str]:
    """13 PDF identik dengan audit (SHA256, jumlah halaman)."""
    return corpus.verify(repo / "data" / "raw_pdf", _cfg(repo))


def g_reducto_provenance(repo: Path) -> list[str]:
    cfg = _cfg(repo)
    known = {d["sha256"] for d in cfg["documents"]}
    man_dir, raw_dir = repo / "data" / "reducto" / "manifests", repo / "data" / "reducto" / "raw"
    manifests = sorted(p for p in man_dir.glob("*.manifest.json") if ".FAILED." not in p.name) if man_dir.exists() else []
    raws = sorted(p for p in raw_dir.glob("*.json") if "__superseded_" not in p.name) if raw_dir.exists() else []
    if not manifests:
        return ["tidak ada manifest parsing: JSON Reducto harus lahir dari reducto_parse_corpus.py (bukan salinan manual)"]
    p: list[str] = []
    by_stem = {m.name[: -len(".manifest.json")]: m for m in manifests}
    for raw in raws:
        if raw.stem not in by_stem:
            p.append(f"RAW_TANPA_MANIFEST: {raw.name} (mungkin ekspor UI/fixture yang disalin; tolak)")
    for stem, mp in by_stem.items():
        m = json.loads(mp.read_text(encoding="utf-8"))
        if m.get("provider") != "reducto":
            p.append(f"{stem}: provider bukan reducto")
        if m.get("status") in FAIL_STATUSES:
            p.append(f"{stem}: status manifest {m.get('status')}")
        if m.get("source_pdf_sha256") not in known:
            p.append(f"{stem}: source_pdf_sha256 tidak cocok dengan PDF mana pun di audit korpus")
        if not (m.get("job") or {}).get("job_id"):
            p.append(f"{stem}: job_id kosong (tidak ada bukti panggilan API)")
        models = (m.get("technical_qa") or {}).get("models_observed") or []
        if models and models != ["r-1"]:
            p.append(f"{stem}: model teramati {models}, bukan ['r-1']")
        rawp = raw_dir / f"{stem}.json"
        rec = (m.get("files") or {}).get("raw_json_sha256")
        if not rawp.exists():
            p.append(f"{stem}: raw hilang")
        elif rec != _sha256(rawp):
            p.append(f"{stem}: SHA256 raw tidak cocok dengan manifest (raw diubah setelah parsing)")
    return p


def g_parse_human_qa(repo: Path) -> list[str]:
    """Dokumen sumber bukti: QA fidelitas manusia harus terisi (reviewer, tanggal, status selain NOT_DONE)."""
    cfg = _cfg(repo)
    evid = {d["doc_id"] for d in cfg["documents"] if d.get("eval_role") in ANCHOR_ROLES}
    p, seen = [], set()
    for mp in sorted((repo / "data" / "reducto" / "manifests").glob("*.manifest.json")):
        if ".FAILED." in mp.name:
            continue
        m = json.loads(mp.read_text(encoding="utf-8"))
        if m.get("doc_id") not in evid:
            continue
        seen.add(m["doc_id"])
        q = m.get("human_fidelity_qa") or {}
        if q.get("status") not in ("PASS", "PASS_WITH_NOTES") or not q.get("reviewer") or not q.get("reviewed_at"):
            p.append(f"{m['doc_id']}: human_fidelity_qa harus status PASS/PASS_WITH_NOTES + reviewer + reviewed_at (sekarang {q.get('status')})")
    p += [f"{d}: manifest tidak ada" for d in sorted(evid - seen)]
    return p


# --------------------------------------------------------------------------- pertanyaan, protokol, generator

def g_questions_verified(repo: Path) -> list[str]:
    cfg = _cfg(repo)
    known = {d["sha256"] for d in cfg["documents"]}
    path = repo / "data" / "cases" / "questions_draft.jsonl"
    if not path.exists():
        return ["questions_draft.jsonl tidak ada"]
    rows, p = _jsonl(path), []
    pj = repo / "config" / "protocol.json"
    expected = (json.loads(pj.read_text(encoding="utf-8")).get("track_r") or {}).get("n_questions", 20) if pj.exists() else 20  # Studi 1: 20; Studi 2 menyatakannya di protokol
    if len(rows) != expected:
        p.append(f"jumlah pertanyaan {len(rows)} != {expected}")
    for r in rows:
        cid = r.get("case_id")
        if r.get("status") != "HUMAN_VERIFIED":
            p.append(f"{cid}: status {r.get('status')}, belum HUMAN_VERIFIED")
        if not (r.get("validator") and r.get("validated_at")):
            p.append(f"{cid}: validator/validated_at kosong")
        if r.get("kind") == "answerable" and r.get("source_pdf_sha256") not in known:
            p.append(f"{cid}: source_pdf_sha256 tidak cocok dengan audit")
    return p


def g_protocol_locked(repo: Path) -> list[str]:
    pj, lj = repo / "config" / "protocol.json", repo / "config" / "protocol.lock.json"
    if not lj.exists():
        return ["protocol.lock.json tidak ada: kunci protokol sebelum melabeli"]
    lock = json.loads(lj.read_text(encoding="utf-8"))
    if lock.get("protocol_sha256") != _sha256(pj):
        return ["protocol.json berubah setelah dikunci (amandemen harus bertanggal, bukan menimpa)"]
    return []


def g_generator_frozen(repo: Path) -> list[str]:
    gj, lj = repo / "config" / "generator.json", repo / "config" / "generator.lock.json"
    cfg = json.loads(gj.read_text(encoding="utf-8"))
    if cfg.get("status") != "FROZEN" or not lj.exists():
        return ["generator belum FROZEN"]
    lock = json.loads(lj.read_text(encoding="utf-8"))
    p = []
    if lock.get("generator_json_sha256") != _sha256(gj):
        p.append("generator.json berubah setelah dibekukan")
    if lock.get("prompt_sha256") != capture.prompt_sha256(cfg):
        p.append("hash prompt tidak cocok dengan kunci")
    return p


# --------------------------------------------------------------------------- capture, label

def g_captures_real(repo: Path) -> list[str]:
    runs = sorted((repo / "data" / "runs").glob("answers_*.jsonl"))
    if not runs:
        return ["tidak ada data/runs/answers_*.jsonl"]
    cfg = json.loads((repo / "config" / "generator.json").read_text(encoding="utf-8"))
    lj = repo / "config" / "generator.lock.json"
    lock = json.loads(lj.read_text(encoding="utf-8")) if lj.exists() else {}
    frozen_at = _ts(lock["frozen_at"]) if lock.get("frozen_at") else None
    n_cases = len(_jsonl(repo / "data" / "cases" / "questions_draft.jsonl"))
    p: list[str] = []
    for rp in runs:
        rows = _jsonl(rp)
        if len(rows) != n_cases:
            p.append(f"{rp.name}: {len(rows)} baris, harus {n_cases}")
        stamps = set()
        for r in rows:
            cid = r.get("case_id")
            raw = r.get("response_json_raw")
            if not isinstance(raw, dict) or not raw.get("choices"):
                p.append(f"{rp.name}/{cid}: tidak ada respons API mentah (choices)")
                continue
            if "mimo" not in str(r.get("response_model") or "").lower():
                p.append(f"{rp.name}/{cid}: response_model {r.get('response_model')!r} bukan model MiMo")
            if not (r.get("request_json") or {}).get("model"):
                p.append(f"{rp.name}/{cid}: request_json tanpa model")
            if not isinstance(r.get("usage"), dict) or not (r["usage"].get("total_tokens") or 0) > 0:
                p.append(f"{rp.name}/{cid}: usage kosong (panggilan API sungguhan selalu memuat usage)")
            if lock.get("prompt_sha256") and r.get("prompt_sha256") != lock["prompt_sha256"]:
                p.append(f"{rp.name}/{cid}: prompt_sha256 != kunci pembekuan")
            if not r.get("chunk_ids"):
                p.append(f"{rp.name}/{cid}: chunk_ids kosong")
            try:
                t = _ts(r["timestamp_utc"])
                stamps.add(r["timestamp_utc"])
                if frozen_at and t < frozen_at:
                    p.append(f"{rp.name}/{cid}: cap waktu mendahului pembekuan generator")
            except (KeyError, ValueError):
                p.append(f"{rp.name}/{cid}: timestamp_utc tidak valid")
        if len(rows) >= 10 and len(stamps) == 1:
            p.append(f"{rp.name}: semua baris berstempel identik (bukan panggilan API sungguhan?)")
    return p


def g_labels_valid(repo: Path, name: str = "labels.jsonl") -> list[str]:
    lp = repo / "data" / "labels" / name
    if not lp.exists():
        return [f"data/labels/{name} tidak ada"]
    rows = _jsonl(lp)
    p = data.validate_records(rows)
    lock = repo / "config" / "protocol.lock.json"
    locked_at = _ts(json.loads(lock.read_text(encoding="utf-8"))["locked_at"]) if lock.exists() else None
    validators = {r.get("validator") for r in rows}
    if len(validators) != 1 or None in validators or "" in validators:
        p.append(f"validator harus satu orang dan terisi, ditemukan {sorted(map(str, validators))}")
    for r in rows:
        if not r.get("manual_label_locked"):
            p.append(f"{r.get('answer_id')}: label belum dikunci")
        if r.get("route") is not None or r.get("H") is not None:
            p.append(f"{r.get('answer_id')}: skor/route ada di berkas label (label harus buta skor)")
        try:
            if locked_at and _ts(r["labeled_at"]) < locked_at:
                p.append(f"{r.get('answer_id')}: dilabeli sebelum protokol dikunci")
        except (KeyError, ValueError):
            p.append(f"{r.get('answer_id')}: labeled_at tidak valid")
    # jawaban pada berkas label harus sama persis dengan jawaban yang ditangkap (tidak disunting)
    run_files = {f.stem.replace("answers_", ""): {x["case_id"]: x for x in _jsonl(f)} for f in (repo / "data" / "runs").glob("answers_*.jsonl")}
    for r in rows:
        if r.get("answer_origin") == "original_llm":
            cap = run_files.get(r.get("run_id"), {}).get(r.get("case_id"))
            if cap is None:
                p.append(f"{r['answer_id']}: tidak ada baris capture untuk run {r.get('run_id')}")
            elif (cap.get("answer") or "") != r["answer"]:
                p.append(f"{r['answer_id']}: teks jawaban berbeda dari hasil capture (disunting?)")
    return p


def g_labels_valid_all_runs(repo: Path) -> list[str]:
    """labels.jsonl (run 1) ditambah setiap labels_run*.jsonl (lari tambahan Studi 2), masing-masing dengan aturan yang sama."""
    names = ["labels.jsonl"] + sorted(f.name for f in (repo / "data" / "labels").glob("labels_run*.jsonl"))
    return [x for n in names for x in g_labels_valid(repo, n)]


def g_labels_all_valid(repo: Path) -> list[str]:
    return g_labels_valid(repo, "labels_all.jsonl")


def g_relabel_gap(repo: Path) -> list[str]:
    rp, lp = repo / "data" / "labels" / "relabel.jsonl", repo / "data" / "labels" / "labels_all.jsonl"
    if not rp.exists():
        return ["data/labels/relabel.jsonl tidak ada"]
    if not lp.exists():
        return ["data/labels/labels_all.jsonl tidak ada"]
    min_gap = json.loads((repo / "config" / "protocol.json").read_text(encoding="utf-8"))["relabel"]["min_gap_hours"]
    first = {r["answer_id"]: r for r in _jsonl(lp)}
    p = []
    for r in _jsonl(rp):
        f = first.get(r["answer_id"])
        if f is None:
            p.append(f"{r['answer_id']}: tidak ada label pertama")
            continue
        review_bound = _ts(r["relabeled_at"])
        if r.get("sheet_saved_at"):
            review_bound = min(review_bound, _ts(r["sheet_saved_at"]))
        gap = (review_bound - _ts(f["labeled_at"])).total_seconds() / 3600
        if gap < min_gap and not r.get("gap_deviation_acknowledged"):
            p.append(f"{r['answer_id']}: jeda {gap:.1f} jam < {min_gap} jam dan deviasi tidak diakui")
    return p


def g_no_synthetic(repo: Path) -> list[str]:
    """Penanda eksplisit data buatan pada berkas data (kunci synthetic/dummy/fake/fixture/stub = true) dan berkas berjalur fixture."""
    p = []
    for sub in ("cases", "runs", "labels", "index", "results", "reducto"):
        d = repo / "data" / sub
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if not f.is_file() or f.suffix not in (".json", ".jsonl"):
                continue
            if re.search(r"fixture|synthetic|sintetis|dummy", str(f.relative_to(repo)), re.I):
                p.append(f"{f.relative_to(repo)}: nama berkas menandakan data buatan")
                continue
            m = SYNTHETIC_KEY_RE.search(f.read_text(encoding="utf-8", errors="ignore"))
            if m:
                p.append(f"{f.relative_to(repo)}: penanda data buatan {m.group(0)}")
    return p


# --------------------------------------------------------------------------- lembar manusia (S19, S22, S26): baru selesai bila importirnya menerima

def _protocol(repo: Path) -> dict:
    return json.loads((repo / "config" / "protocol.json").read_text(encoding="utf-8"))


def _import_problems(repo: Path, sheet: str, call) -> list[str]:
    """Penolakan importir atas `sheet` (kosong = diterima). `call(tmp)` menjalankan importirnya dengan keluaran di direktori sementara: repo tidak ditulisi."""
    if not (repo / sheet).is_file():
        return [f"{sheet} tidak ada"]
    with tempfile.TemporaryDirectory() as tmp:
        try:
            call(Path(tmp))
        except Exception as ex:  # noqa: BLE001 - berkas hilang/rusak harus menjadi penolakan, bukan galat
            rejected = str(ex).split("\n")[1:] if isinstance(ex, ValueError) else []  # penolakan importir = judul + satu masalah per baris
            return rejected or [f"tidak dapat diperiksa: {type(ex).__name__}: {ex}"]
    return []


def g_label_sheets_complete(repo: Path) -> list[str]:
    """S19: lembar label tiap lari (run1..runK, K dari protokol; bawaan 1) lengkap dan sah menurut `labeling.import_label_sheet`."""
    try:
        k = int(((_protocol(repo).get("determinism") or {}).get("generator_runs") or {}).get("k", 1))
    except Exception as ex:  # noqa: BLE001
        return [f"config/protocol.json tidak dapat dibaca: {type(ex).__name__}: {ex}"]
    p: list[str] = []
    for run in (f"run{i}" for i in range(1, k + 1)):
        sheet = f"data/labels/sheet_{run}.csv"
        p += [f"{run}: {x}" for x in _import_problems(repo, sheet, lambda tmp: labeling.import_label_sheet(
            repo / sheet, repo / "data" / "runs" / f"answers_{run}.jsonl", _jsonl(repo / "data" / "cases" / "questions_draft.jsonl"),
            "pemeriksa", tmp / "labels.jsonl"))]
    return p


def g_mutants_sheet_complete(repo: Path) -> list[str]:
    """S22: lembar mutasi lengkap dan sah menurut `labeling.import_mutant_sheet`, dengan masukan yang sama seperti CLI `mutants-import`."""
    lab = repo / "data" / "labels"

    def call(tmp: Path) -> None:
        cases = _jsonl(repo / "data" / "cases" / "questions_draft.jsonl")
        labeling.import_mutant_sheet(lab / "mutants_sheet.csv", lab / "labels.jsonl", cases, _jsonl(repo / "data" / "index" / "chunks.jsonl"),
                                     _protocol(repo), "pemeriksa", tmp / "mutants.jsonl", tmp / "mutants_log.json",
                                     anchor_texts=labeling._load_mutation_anchor_texts(cases, repo / "data" / "reducto" / "raw"))

    return _import_problems(repo, "data/labels/mutants_sheet.csv", call)


def g_relabel_sheet_complete(repo: Path) -> list[str]:
    """S26: lembar relabel lengkap dan sah menurut `labeling.import_relabel_sheet`."""
    lab = repo / "data" / "labels"
    # accept_short_gap=True: penjaga ini hanya memeriksa lembar lengkap dan sah; jeda 24 jam dijaga `not_before` S26 dan `relabel_gap` S27
    return _import_problems(repo, "data/labels/relabel_sheet.csv", lambda tmp: labeling.import_relabel_sheet(
        lab / "relabel_sheet.csv", lab / "relabel_sample.json", lab / "labels_all.jsonl", _protocol(repo),
        tmp / "relabel.jsonl", tmp / "relabel_result.json", accept_short_gap=True))


REGISTRY = {
    "pdfs_real": g_pdfs_real, "reducto_provenance": g_reducto_provenance, "parse_human_qa": g_parse_human_qa,
    "questions_verified": g_questions_verified, "protocol_locked": g_protocol_locked, "generator_frozen": g_generator_frozen,
    "captures_real": g_captures_real, "labels_valid": g_labels_valid_all_runs, "labels_all_valid": g_labels_all_valid, "relabel_gap": g_relabel_gap, "no_synthetic": g_no_synthetic,
    "label_sheets_complete": g_label_sheets_complete, "mutants_sheet_complete": g_mutants_sheet_complete, "relabel_sheet_complete": g_relabel_sheet_complete,
}


def run_guards(names: list[str], repo: Path) -> dict[str, list[str]]:
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise KeyError(f"penjaga tak dikenal: {unknown}")
    return {n: REGISTRY[n](repo) for n in names}
