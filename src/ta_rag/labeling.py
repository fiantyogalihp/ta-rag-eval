"""Antarmuka pekerjaan manusia: lembar label buta-skor, impor label, mutasi Track M, relabel, ringkasan pra-evaluator.

Mengapa modul ini ada: pelabelan harus dilakukan manusia (validator tunggal, buta skor, rubrik terkunci), tetapi mengetik JSONL
dengan tangan memancing salah. Modul ini hanya memindahkan keputusan manusia dari CSV ke JSONL dengan pemeriksaan; ia TIDAK
memberi label, TIDAK menyarankan label, dan tidak pernah membaca skor evaluator.

Berkas (data/labels/): sheet_<run>.csv -> labels.jsonl -> mutants_sheet.csv -> mutants.jsonl (+mutants_log.json) -> labels_all.jsonl
-> relabel_sheet.csv + relabel_sample.json -> relabel.jsonl + relabel_result.json -> pre_evaluator_summary.md
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import chunking, data, protocol as P
from .parsing.reducto_json_to_md import iter_blocks

REPO = Path(__file__).resolve().parents[2]
LABEL_DIR = REPO / "data" / "labels"
LABEL_CHOICES = data.LABELS
ORDER_SEED = "TA-RAG-SHEETORDER-v1-20261104"
ABSTAIN_HINT = " | kolom abstain: isi 'ya' bila jawaban HANYA menyatakan informasi tidak ada dalam konteks, selain itu 'tidak'"


# ------------------------------------------------------------------ utilitas

def _jsonl(p) -> list[dict]:
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def _write_jsonl(rows: list[dict], p) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + "\n", encoding="utf-8")


def _read_csv(p) -> list[dict]:
    with open(p, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _write_csv(p, rows: list[dict], fields: list[str]) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _sha256_file(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _key(seed: str, ident: str) -> str:
    return hashlib.sha256(f"{seed}:{ident}".encode("utf-8")).hexdigest()


def _norm(s: str | None) -> str:
    return " ".join((s or "").split())


def _now(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def _guard_new(p) -> None:
    if Path(p).exists():
        raise FileExistsError(f"{p} sudah ada; tidak ditimpa (label manusia tidak boleh hilang). Pindahkan/ganti nama secara sadar.")


def _rubric(protocol: dict, kind: str) -> str:
    r = protocol["label_rubric"]
    if kind == "answerable":
        a = r["answerable"]
        return " | ".join(a["LAYAK_iff_all"]) + " | " + a["extra_facts_rule"] + " | " + a["false_abstention_rule"]
    pr = r["probe_not_in_corpus"]
    return f"LAYAK: {pr['LAYAK']} | TIDAK_LAYAK: {pr['TIDAK_LAYAK']}"


def _cases_by_id(cases: list[dict]) -> dict:
    return {c["case_id"]: c for c in cases}


def _check_label(value: str, where: str, problems: list[str]) -> str | None:
    v = (value or "").strip().upper()
    if v not in LABEL_CHOICES:
        problems.append(f"{where}: label {value!r} bukan salah satu dari {list(LABEL_CHOICES)}")
        return None
    return v


def _check_abstain(value: str | None, kind: str, label: str | None, where: str, problems: list[str]) -> bool | None:
    """Kolom `abstain` (keputusan manusia): jawaban hanya menyatakan informasi tidak ada dalam konteks. Wajib untuk pertanyaan berjawab
    (dipakai menurunkan label tahap II secara mekanis); probe: diabaikan (None). Abstain pada berjawab + LAYAK bertentangan dengan
    rubrik terkunci tahap I (false_abstention_rule)."""
    if kind != "answerable":
        return None
    v = (value or "").strip().lower()
    if v not in ("ya", "tidak"):
        problems.append(f"{where}: kolom abstain wajib 'ya' atau 'tidak' untuk pertanyaan berjawab")
        return None
    if v == "ya" and label == "LAYAK":
        problems.append(f"{where}: abstain=ya pada pertanyaan berjawab harus TIDAK_LAYAK pada tahap I (rubrik terkunci)")
    return v == "ya"


# ------------------------------------------------------------------ 1. label jawaban asli (Track R)

def export_label_sheet(answers_path, cases: list[dict], protocol: dict, out_csv) -> dict:
    """Lembar label buta-skor: pertanyaan, jawaban, kutipan jangkar, rubrik. Urutan diacak deterministik. Tanpa skor, tanpa
    rute. Jawaban berstatus bukan OK (ANSWER_EMPTY/MALFORMED) tidak dilabeli; dilaporkan sebagai dikecualikan."""
    _guard_new(out_csv)
    cb = _cases_by_id(cases)
    rows = _jsonl(answers_path)
    ok = [r for r in rows if r["answer_status"] == "OK"]
    excluded = [{"case_id": r["case_id"], "answer_status": r["answer_status"]} for r in rows if r["answer_status"] != "OK"]
    run_id = rows[0]["run_id"]
    out = []
    for r in sorted(ok, key=lambda r: _key(ORDER_SEED + run_id, r["case_id"])):
        c = cb[r["case_id"]]
        out.append({"answer_id": f"{run_id}:{r['case_id']}", "case_id": r["case_id"], "question": c["question"], "answer": r["answer"],
                    "kind": c["kind"], "source_doc_id": c.get("source_doc_id") or "", "source_page": c.get("source_page") or "",
                    "source_quote": c.get("source_quote") or "(probe: tidak ada kutipan; periksa pernyataan 'tidak tersedia')",
                    "rubric": _rubric(protocol, c["kind"]) + (ABSTAIN_HINT if c["kind"] == "answerable" else ""), "label": "", "abstain": "", "note": ""})
    _write_csv(out_csv, out, list(out[0].keys()))
    return {"rows": len(out), "excluded": excluded, "sha256": _sha256_file(out_csv), "run_id": run_id}


def import_label_sheet(sheet_csv, answers_path, cases: list[dict], validator: str, out_jsonl, now: datetime | None = None) -> dict:
    if not validator.strip():
        raise ValueError("validator wajib diisi (satu orang)")
    _guard_new(out_jsonl)
    cb = _cases_by_id(cases)
    caps = {r["case_id"]: r for r in _jsonl(answers_path)}
    run_id = next(iter(caps.values()))["run_id"]
    sheet, problems, seen = _read_csv(sheet_csv), [], set()
    stamp, sha = _now(now), _sha256_file(sheet_csv)
    recs = []
    for s in sheet:
        aid = s["answer_id"]
        cid = aid.split(":", 1)[1] if ":" in aid else aid
        cap = caps.get(cid)
        if cap is None or aid != f"{run_id}:{cid}":
            problems.append(f"{aid}: tidak ada di capture {run_id}")
            continue
        if aid in seen:
            problems.append(f"{aid}: baris ganda")
        seen.add(aid)
        if _norm(s["answer"]) != _norm(cap["answer"]):
            problems.append(f"{aid}: teks jawaban di lembar berbeda dari hasil capture (jangan menyunting jawaban)")
        label = _check_label(s["label"], aid, problems)
        c = cb[cid]
        abstain = _check_abstain(s.get("abstain"), c["kind"], label, aid, problems)
        recs.append({"answer_id": aid, "case_id": cid, "group_id": c["group_id"], "evidence_group": c["evidence_group"], "track": "R",
                     "answer_origin": "original_llm", "origin": "natural", "answer": cap["answer"], "kind": c["kind"],
                     "question_type": c["question_type"], "source_doc_id": c.get("source_doc_id"), "run_id": run_id,
                     "chunk_ids": cap.get("chunk_ids", []), "label": label, "abstain": abstain, "manual_label_locked": True, "validator": validator.strip(),
                     "labeled_at": stamp, "sheet_sha256": sha, "note": (s.get("note") or "").strip()})
    missing = [f"{run_id}:{cid}" for cid, r in caps.items() if r["answer_status"] == "OK" and f"{run_id}:{cid}" not in seen]
    problems += [f"{m}: belum ada di lembar" for m in missing]
    problems += data.validate_records(recs) if not problems else []
    if problems:
        raise ValueError("impor label ditolak:\n" + "\n".join(problems[:30]))
    _write_jsonl(recs, out_jsonl)
    dist: dict[str, int] = {}
    for r in recs:
        dist[r["label"]] = dist.get(r["label"], 0) + 1
    return {"n": len(recs), "distribution": dist, "sheet_sha256": sha, "labeled_at": stamp, "note": "labeled_at = waktu impor (batas atas waktu pelabelan)"}


# ------------------------------------------------------------------ 2. mutasi Track M

def label_file(run: str) -> Path:
    """Berkas label per lari: run1 tetap `labels.jsonl` (kompatibel Studi 1); lari tambahan `labels_<run>.jsonl`."""
    return LABEL_DIR / ("labels.jsonl" if run == "run1" else f"labels_{run}.jsonl")


def _anchor_text(case: dict, chunks: list[dict]) -> str:
    pg = case.get("source_page")
    selected = [c for c in chunks if c["doc_id"] == case.get("source_doc_id") and c["page_start"] <= pg <= c["page_end"]]
    if not selected:
        raise ValueError(f"{case.get('case_id')}: teks halaman jangkar tidak ditemukan")
    if any(c["page_start"] != c["page_end"] for c in selected):
        raise ValueError(f"{case.get('case_id')}: chunk lintas halaman tidak membuktikan angka pada satu halaman fisik; berikan teks halaman jangkar")
    return "\n".join(c["text"] for c in selected)


def _load_mutation_anchor_texts(cases: list[dict], raw_dir: Path) -> dict[str, str]:
    """Teks pemeriksa angka per halaman fisik; kutipan pembuktian manusia tetap dari PDF asli."""
    by_doc: dict[str, dict[int, list[str]]] = {}
    result = {}
    for case in cases:
        if case["kind"] != "answerable":
            continue
        doc_id, page = case["source_doc_id"], case["source_page"]
        if doc_id not in by_doc:
            files = sorted(p for p in Path(raw_dir).glob(f"{doc_id}__*.json") if "__superseded_" not in p.name)
            if not files:
                raise FileNotFoundError(f"raw Reducto untuk {doc_id} tidak ada di {raw_dir}")
            pages: dict[int, list[str]] = {}
            for path in files:
                for block in iter_blocks(json.loads(path.read_text(encoding="utf-8"))):
                    if block.get("type") in chunking.DROP_TYPES:
                        continue
                    text = chunking.clean(block.get("content", ""))
                    if not text:
                        continue
                    physical_page = (block.get("bbox") or {}).get("original_page")
                    if not isinstance(physical_page, int):
                        raise ValueError(f"{doc_id}: blok tanpa bbox.original_page")
                    pages.setdefault(physical_page, []).append(text)
            by_doc[doc_id] = pages
        texts = by_doc[doc_id].get(page)
        if not texts:
            raise ValueError(f"{case['case_id']}: teks halaman jangkar tidak ditemukan pada halaman fisik {page}")
        result[case["case_id"]] = "\n".join(texts)
    return result


def _mutation_candidates(labels: list[dict], protocol: dict, primary_run: str) -> list[dict]:
    cand = [r for r in labels if r["answer_origin"] == "original_llm" and r["kind"] == "answerable" and r["label"] == "LAYAK"
            and r.get("run_id") == primary_run]
    order = P.track_m_order([{"case_id": r["case_id"], "source_doc_id": r["source_doc_id"]} for r in cand], protocol["track_m"]["seed"])
    by = {r["case_id"]: r for r in cand}
    return [by[i] for i in order]


def _mutation_plan(labels: list[dict], cb: dict, protocol: dict, primary_run: str) -> list[tuple[dict, int | None, str]]:
    """[(jawaban asal, slot, family)] menurut urutan pra-registrasi. Satu mutasi per jawaban (Studi 1): slot None; k > 1 (Studi 2, D20):
    k baris berurutan per jawaban, slot 1..k, family slot ke-i ditetapkan protokol."""
    k = protocol["track_m"].get("mutations_per_answer", 1)
    cands = _mutation_candidates(labels, protocol, primary_run)
    ordered = [{"case_id": r["case_id"], "question_type": cb[r["case_id"]]["question_type"]} for r in cands]
    fam_map = protocol["track_m"]["mutation"]["families_by_question_type"]
    if k == 1:
        fams = P.assign_mutation_families(ordered, fam_map)
        return [(r, None, fams[r["case_id"]]) for r in cands]
    slots = P.assign_mutation_slots(ordered, fam_map, k)
    return [(r, i + 1, slots[r["case_id"]][i]) for r in cands for i in range(k)]


def export_mutant_sheet(labels_path, cases: list[dict], chunks: list[dict], protocol: dict, out_csv, primary_run: str = "run1") -> dict:
    _guard_new(out_csv)
    cb = _cases_by_id(cases)
    plan = _mutation_plan(_jsonl(labels_path), cb, protocol, primary_run)
    rows = []
    for i, (r, slot, fam) in enumerate(plan, 1):
        c = cb[r["case_id"]]
        row = {"order": i, "case_id": r["case_id"], **({"slot": slot} if slot else {}), "source_answer_id": r["answer_id"],
               "question_type": c["question_type"], "mutation_family": fam, "question": c["question"], "original_answer": r["answer"],
               "source_quote": c["source_quote"], "source_page": c["source_page"], "mutated_answer": "",
               "anchor_page_opposite": "", "skip_reason": ""}
        rows.append(row)
    if not rows:
        raise ValueError("tidak ada jawaban asli berlabel LAYAK pada pertanyaan berjawaban: Track M tidak dapat dibentuk")
    _write_csv(out_csv, rows, list(rows[0].keys()))
    k = protocol["track_m"].get("mutations_per_answer", 1)
    return {"candidates": len({r["case_id"] for r in rows}), **({"mutations_per_answer": k} if k > 1 else {}),
            "target_pairs": protocol["track_m"]["n_pairs"] or len(rows), "sha256": _sha256_file(out_csv)}


def import_mutant_sheet(sheet_csv, labels_path, cases: list[dict], chunks: list[dict], protocol: dict, validator: str, out_jsonl, log_json,
                        now: datetime | None = None, primary_run: str = "run1", anchor_texts: dict[str, str] | None = None) -> dict:
    _guard_new(out_jsonl)
    labels = _jsonl(labels_path)
    cb = _cases_by_id(cases)
    plan = _mutation_plan(labels, cb, protocol, primary_run)
    expected = [(r["case_id"], slot) for r, slot, _ in plan]
    fam_for = {(r["case_id"], slot): fam for r, slot, fam in plan}
    src = {r["case_id"]: r for r in labels if r.get("run_id") == primary_run}
    all_mode = protocol["track_m"]["n_pairs"] is None  # D13: setiap kandidat LAYAK dimutasi atau dilewati dengan alasan
    target, stamp = protocol["track_m"]["n_pairs"] or len(expected), _now(now)
    sheet = sorted(_read_csv(sheet_csv), key=lambda r: int(r["order"]))
    problems = []
    if [(s["case_id"], int(s["slot"]) if s.get("slot") else None) for s in sheet] != expected:
        problems.append("urutan/isi kandidat di lembar != urutan pra-registrasi (jangan menyusun ulang atau menghapus baris)")
        raise ValueError("impor mutasi ditolak:\n" + "\n".join(problems))
    accepted, skipped, recs, blank_before, blanks = [], [], [], None, []
    for s in sheet:
        cid = s["case_id"]
        slot = int(s["slot"]) if s.get("slot") else None
        tag = cid if slot is None else f"{cid}#{slot}"
        mut, skip = (s["mutated_answer"] or "").strip(), (s["skip_reason"] or "").strip()
        if mut and skip:
            problems.append(f"{tag}: mutated_answer dan skip_reason sama-sama terisi")
            continue
        if len(accepted) >= target:
            if mut or skip:
                problems.append(f"{tag}: melebihi {target} pasangan; sisa kandidat harus dikosongkan")
            continue
        if not mut and not skip:
            blank_before = blank_before or tag
            blanks.append(tag)
            continue
        if blank_before:
            problems.append(f"{tag}: terisi padahal {blank_before} sebelumnya dilewati tanpa alasan (urutan pra-registrasi tidak boleh dilompati)")
            continue
        if skip:
            skipped.append({"case_id": cid, **({"slot": slot} if slot else {}), "reason": skip})
            continue
        c, a = cb[cid], src[cid]
        fam = (s["mutation_family"] or "").strip()
        if fam != fam_for[(cid, slot)]:
            problems.append(f"{tag}: family {fam!r} tidak sesuai penetapan pra-registrasi ({fam_for[(cid, slot)]!r}); family tidak dipilih peneliti")
            continue
        opp = (s["anchor_page_opposite"] or "").strip()
        if not opp:
            problems.append(f"{tag}: anchor_page_opposite wajib (halaman yang membuktikan kebalikan)")
            continue
        if anchor_texts is not None:
            if not anchor_texts.get(cid):
                problems.append(f"{tag}: teks halaman jangkar tidak tersedia")
                continue
            anchor_text = anchor_texts[cid]
        else:
            anchor_text = _anchor_text(c, chunks)
        bad = P.verify_mutation(a["answer"], mut, fam, anchor_text)
        if bad:
            problems.append(f"{tag}: verifikasi mekanis gagal: {'; '.join(bad)} (perbaiki, atau isi skip_reason)")
            continue
        accepted.append({"case_id": cid, **({"slot": slot} if slot else {}), "family": fam, "anchor_page_opposite": opp})
        recs.append({"answer_id": f"M:{cid}" if slot is None else f"M{slot}:{cid}", "case_id": cid, "group_id": a["group_id"], "evidence_group": a["evidence_group"], "track": "M",
                     "answer_origin": "mutasi_terkontrol", "origin": "mutation", "answer": mut, "kind": "answerable",
                     "question_type": c["question_type"], "source_doc_id": c["source_doc_id"], "pair_id": f"P:{cid}" if slot is None else f"P{slot}:{cid}", "mutation_family": fam,
                     "anchor_page_opposite": opp, "mutated_from_answer_id": a["answer_id"], "label": "TIDAK_LAYAK",
                     "manual_label_locked": True, "validator": validator.strip(), "labeled_at": stamp, "run_id": primary_run})
    if all_mode and blanks:
        problems.append(f"baris belum diisi (isi mutasi atau skip_reason; setiap kandidat wajib): {', '.join(blanks)}")
    if problems:
        raise ValueError("impor mutasi ditolak:\n" + "\n".join(problems[:30]))
    _write_jsonl(recs, out_jsonl)
    Path(log_json).write_text(json.dumps({"accepted": accepted, "skipped": skipped, "n_pairs": len(accepted), "target": target,
                                          "shortfall": max(0, target - len(accepted))}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"n_pairs": len(accepted), "target": target, "skipped": len(skipped), "shortfall": max(0, target - len(accepted))}


def merge_labels(labels_path, mutants_path, out_jsonl, extra_label_paths=()) -> dict:
    _guard_new(out_jsonl)
    rows = _jsonl(labels_path) + [r for p in extra_label_paths for r in _jsonl(p)] + _jsonl(mutants_path)
    probs = data.validate_records(rows)
    if probs:
        raise ValueError("gabungan label tidak valid:\n" + "\n".join(probs[:20]))
    _write_jsonl(rows, out_jsonl)
    return {"n": len(rows), "natural": sum(r["origin"] == "natural" for r in rows), "mutation": sum(r["origin"] == "mutation" for r in rows)}


# ------------------------------------------------------------------ 3. relabel intra-rater

def export_relabel_sheet(labels_all_path, cases: list[dict], protocol: dict, out_csv, sample_json) -> dict:
    """Lembar relabel buta asal jawaban (relabel.blind_to): baris diberi `item_id` R01.., bukan `answer_id` (`M1:T56` / `run2:T19` membuka asalnya).
    Pemetaan item_id -> answer_id hanya ada di `sample["items"]` (relabel_sample.json), bukan di lembar."""
    _guard_new(out_csv)
    cb = _cases_by_id(cases)
    labels = _jsonl(labels_all_path)
    rl = protocol["relabel"]
    sample = P.relabel_sample([{"answer_id": r["answer_id"], "origin": r["origin"], "kind": r["kind"], "label": r["label"]} for r in labels],
                              rl["n_sample"], rl["seed"], rl["strata_min"])
    by = {r["answer_id"]: r for r in labels}
    order = sorted(sample["answer_ids"], key=lambda i: _key(rl["seed"] + ":order", i))
    sample["items"] = {f"R{n:02d}": aid for n, aid in enumerate(order, 1)}
    rows = []
    for item, aid in sample["items"].items():
        r, c = by[aid], cb[by[aid]["case_id"]]
        rows.append({"item_id": item, "case_id": r["case_id"], "question": c["question"], "answer": r["answer"], "kind": c["kind"],
                     "source_quote": c.get("source_quote") or "(probe: tidak ada kutipan; periksa pernyataan 'tidak tersedia')",
                     "rubric": _rubric(protocol, c["kind"]), "label_baru": "", "alasan_bila_berbeda": ""})
    _write_csv(out_csv, rows, list(rows[0].keys()))
    Path(sample_json).write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"n": len(rows), "composition": sample["composition"], "strata_short": sample["strata_short"]}


def _resolve_rows(sheet: list[dict], sample: dict, problems: list[str]) -> list[tuple[str | None, str, dict]]:
    """[(answer_id, nama baris, baris)]. Lembar baru memuat `item_id` (dipetakan lewat sample["items"]); lembar lama (Studi 1) memuat `answer_id`.
    Pesan masalah memakai nama baris (item_id bila ada) agar tidak membuka asal jawaban kepada penilai; answer_id None = item_id tak dikenal."""
    out = []
    for s in sheet:
        if "item_id" not in s:
            out.append((s["answer_id"], s["answer_id"], s))
            continue
        aid = (sample.get("items") or {}).get(s["item_id"])
        if aid is None:
            problems.append(f"{s['item_id']}: item_id tidak ada di sampel relabel")
        out.append((aid, s["item_id"], s))
    return out


def _strata(pairs: list[tuple[str, str, str]], first: dict) -> dict:
    """Kesepakatan per stratum dan tanpa mutasi (jawaban asli saja). Mutasi dibuat peneliti sendiri, jadi hampir pasti disepakati dan menggelembungkan
    persentase keseluruhan; angka keseluruhan tetap dilaporkan apa adanya (`P.agreement`)."""
    by: dict[str, dict] = {}
    for aid, a, b in pairs:
        f = first[aid]
        d = by.setdefault("mutation" if f["origin"] == "mutation" else "probe" if f["kind"] == "not_in_corpus" else "natural_answerable", {"n": 0, "agree": 0})
        d["n"] += 1
        d["agree"] += a == b
    for d in by.values():
        d["pct"] = round(100 * d["agree"] / d["n"], 1)
    natural = P.agreement([p for p in pairs if first[p[0]]["origin"] != "mutation"])
    return {"by_stratum": by, "natural_only": {k: v for k, v in natural.items() if k != "discrepancies"}}


def import_relabel_sheet(sheet_csv, sample_json, labels_all_path, protocol: dict, out_jsonl, result_json, now: datetime | None = None,
                         accept_short_gap: bool = False) -> dict:
    _guard_new(out_jsonl)
    sample = json.loads(Path(sample_json).read_text(encoding="utf-8"))
    first = {r["answer_id"]: r for r in _jsonl(labels_all_path)}
    problems: list[str] = []
    rows = _resolve_rows(_read_csv(sheet_csv), sample, problems)
    if sorted(a for a, _, _ in rows if a is not None) != sorted(sample["answer_ids"]):
        problems.append("baris lembar != sampel relabel yang ditetapkan")
    stamp_dt = now or datetime.now(timezone.utc)
    saved_dt = datetime.fromtimestamp(Path(sheet_csv).stat().st_mtime, timezone.utc)
    review_bound = min(stamp_dt, saved_dt)
    sheet_sha = _sha256_file(sheet_csv)
    min_gap, pairs, recs, gaps = protocol["relabel"]["min_gap_hours"], [], [], []
    for aid, tag, s in rows:
        l2 = _check_label(s["label_baru"], tag, problems)
        f = first.get(aid)
        if f is None or l2 is None:
            continue
        gap = (review_bound - datetime.fromisoformat(f["labeled_at"])).total_seconds() / 3600
        gaps.append(gap)
        pairs.append((aid, f["label"], l2))
        recs.append({"answer_id": aid, "label_first": f["label"], "label_second": l2, "labeled_at": f["labeled_at"], "relabeled_at": _now(stamp_dt),
                     "sheet_saved_at": _now(saved_dt), "sheet_sha256": sheet_sha, "gap_is_upper_bound": True,
                     "gap_hours": round(gap, 2), "gap_deviation_acknowledged": bool(accept_short_gap and gap < min_gap),
                     "reason_if_different": (s.get("alasan_bila_berbeda") or "").strip()})
    if gaps and min(gaps) < min_gap and not accept_short_gap:
        problems.append(f"jeda minimum terdokumentasi {min(gaps):.1f} jam < {min_gap} jam; impor membutuhkan --accept-short-gap (dicatat sebagai deviasi); menunda impor tidak mengubah waktu simpan lembar")
    if problems:
        raise ValueError("impor relabel ditolak:\n" + "\n".join(problems[:30]))
    _write_jsonl(recs, out_jsonl)
    res = {**P.agreement(pairs), **_strata(pairs, first), "min_gap_hours_observed": round(min(gaps), 2), "min_gap_hours_required": min_gap, "gap_deviation": bool(accept_short_gap and min(gaps) < min_gap),
           "sheet_saved_at": _now(saved_dt), "imported_at": _now(stamp_dt), "sheet_sha256": sheet_sha,
           "gap_is_upper_bound": True, "gap_time_basis": "earlier_of_import_and_sheet_save",
           "composition": sample["composition"], "strata_short": sample["strata_short"],
           "disclosure": protocol["relabel"]["disclosure"]}
    Path(result_json).write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return res


def import_second_rater(sheet_csv, sample_json, labels_all_path, out_jsonl, result_json, rater: str, ai_assistance: str,
                        now: datetime | None = None) -> dict:
    """Validator KEDUA (Studi 2, D24): lembar relabel kosong yang sama, diisi orang lain. Menghitung kesepakatan antar-penilai terhadap label
    pertama. `ai_assistance` = pernyataan penilai ("none" atau "disclosed"); tidak dapat diverifikasi mesin, jadi dicatat dan menentukan
    `eligible_as_inter_rater`. Tidak mengubah label utama (label peneliti tetap yang dipakai evaluasi)."""
    _guard_new(out_jsonl)
    if ai_assistance not in ("none", "disclosed"):
        raise ValueError("ai_assistance harus 'none' atau 'disclosed' (pernyataan penilai)")
    sample = json.loads(Path(sample_json).read_text(encoding="utf-8"))
    first = {r["answer_id"]: r for r in _jsonl(labels_all_path)}
    first_validator = next(iter({r["validator"] for r in first.values()}))
    problems = []
    if not (rater or "").strip():
        problems.append("rater wajib diisi")
    elif _norm(rater).casefold() == _norm(first_validator).casefold():
        problems.append(f"validator kedua = validator pertama ({first_validator}): harus orang yang berbeda, bukan orang yang sama")
    sheet = _read_csv(sheet_csv)
    if sheet and {"label_first", "label", "H", "route", "origin"} & set(sheet[0]):
        problems.append("lembar penilai kedua harus buta: memuat kolom label pertama/skor/asal jawaban")
    rows = _resolve_rows(sheet, sample, problems)
    if sorted(a for a, _, _ in rows if a is not None) != sorted(sample["answer_ids"]):
        problems.append("baris lembar != sampel relabel yang ditetapkan")
    pairs, recs, stamp = [], [], _now(now)
    for aid, tag, x in rows:
        l2 = _check_label(x["label_baru"], tag, problems)
        f = first.get(aid)
        if f is not None and l2 is not None:
            pairs.append((aid, f["label"], l2))
            recs.append({"answer_id": aid, "label_first": f["label"], "label_second": l2, "rater": rater.strip(), "ai_assistance": ai_assistance,
                         "imported_at": stamp, "sheet_sha256": _sha256_file(sheet_csv), "reason_if_different": (x.get("alasan_bila_berbeda") or "").strip()})
    if problems:
        raise ValueError("impor penilai kedua ditolak:\n" + "\n".join(problems[:30]))
    res = {**P.agreement(pairs), "rater": rater.strip(), "first_validator": first_validator, "ai_assistance": ai_assistance,
           "eligible_as_inter_rater": ai_assistance == "none", **_strata(pairs, first), "imported_at": stamp, "sheet_sha256": _sha256_file(sheet_csv),
           "disclosure": "kesepakatan antar-penilai atas sampel relabel; pernyataan ai_assistance berasal dari penilai dan tidak diverifikasi mesin; label utama tetap label peneliti"}
    _write_jsonl(recs, out_jsonl)
    Path(result_json).write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return res


# ------------------------------------------------------------------ 4. ringkasan pra-evaluator (tanpa skor)

def write_pre_evaluator_summary(labels_all_path, mutants_log_json, relabel_result_json, second_log_json, out_md) -> str:
    labels = _jsonl(labels_all_path)
    log = json.loads(Path(mutants_log_json).read_text(encoding="utf-8"))
    relabel = json.loads(Path(relabel_result_json).read_text(encoding="utf-8"))
    second = json.loads(Path(second_log_json).read_text(encoding="utf-8"))
    if not isinstance(second, list) or not second:
        raise ValueError("second_validator_log.json harus daftar berisi minimal satu catatan upaya")
    md = P.pre_evaluator_summary(labels, [{"case_id": a["case_id"], "family": a["family"], "anchor_page_opposite": a["anchor_page_opposite"]}
                                          for a in log["accepted"]],
                                 [{"case_id": s["case_id"], "reason": s["reason"]} for s in log["skipped"]], relabel,
                                 [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in second])
    if relabel.get("gap_deviation"):
        timing = "terdokumentasi paling lama" if relabel.get("gap_is_upper_bound") else "minimum"
        md += f"\n**Deviasi:** jeda relabel {timing} {relabel['min_gap_hours_observed']} jam < {relabel.get('min_gap_hours_required', 24)} jam; diakui saat impor.\n"
    if relabel.get("gap_is_upper_bound"):
        md += "\nCatatan waktu: jeda memakai waktu yang lebih awal antara simpan lembar dan impor sebagai batas atas waktu penyelesaian; bukan pengukuran waktu mulai inspeksi.\n"
    Path(out_md).write_text(md, encoding="utf-8")
    return md


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:  # pragma: no cover - perekat tipis; fungsi di atas yang diuji
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("sheet", "import"):
        s = sub.add_parser(name); s.add_argument("--run", nargs="+", default=["run1"], help="satu atau beberapa lari (Studi 2: run1 run2 run3)")
        if name == "import":
            s.add_argument("--validator", required=True)
    sub.add_parser("mutants-sheet")
    mi = sub.add_parser("mutants-import"); mi.add_argument("--validator", required=True)
    sub.add_parser("merge")
    sub.add_parser("relabel-sheet")
    ri = sub.add_parser("relabel-import"); ri.add_argument("--accept-short-gap", action="store_true")
    sr = sub.add_parser("second-rater-import"); sr.add_argument("--sheet", required=True); sr.add_argument("--rater", required=True)
    sr.add_argument("--ai-assistance", required=True, choices=["none", "disclosed"], help="pernyataan penilai: tanpa bantuan AI (none) atau dengan bantuan AI (disclosed)")
    sub.add_parser("summary")
    a = ap.parse_args(argv)
    proto = P.load_protocol()
    L = LABEL_DIR
    cases = _jsonl(REPO / "data" / "cases" / "questions_draft.jsonl")
    chunks_p = REPO / "data" / "index" / "chunks.jsonl"
    if a.cmd == "sheet":
        for run in a.run:
            print(json.dumps(export_label_sheet(REPO / "data" / "runs" / f"answers_{run}.jsonl", cases, proto, L / f"sheet_{run}.csv"), ensure_ascii=False, indent=2))
    elif a.cmd == "import":
        for run in a.run:
            print(json.dumps(import_label_sheet(L / f"sheet_{run}.csv", REPO / "data" / "runs" / f"answers_{run}.jsonl", cases, a.validator, label_file(run)), ensure_ascii=False, indent=2))
    elif a.cmd == "mutants-sheet":
        print(json.dumps(export_mutant_sheet(L / "labels.jsonl", cases, _jsonl(chunks_p), proto, L / "mutants_sheet.csv"), indent=2))
    elif a.cmd == "mutants-import":
        anchors = _load_mutation_anchor_texts(cases, REPO / "data/reducto/raw")
        print(json.dumps(import_mutant_sheet(L / "mutants_sheet.csv", L / "labels.jsonl", cases, _jsonl(chunks_p), proto, a.validator, L / "mutants.jsonl", L / "mutants_log.json", anchor_texts=anchors), indent=2))
    elif a.cmd == "merge":
        print(json.dumps(merge_labels(L / "labels.jsonl", L / "mutants.jsonl", L / "labels_all.jsonl", sorted(L.glob("labels_run*.jsonl"))), indent=2))
    elif a.cmd == "relabel-sheet":
        print(json.dumps(export_relabel_sheet(L / "labels_all.jsonl", cases, proto, L / "relabel_sheet.csv", L / "relabel_sample.json"), ensure_ascii=False, indent=2))
    elif a.cmd == "second-rater-import":
        print(json.dumps(import_second_rater(a.sheet, L / "relabel_sample.json", L / "labels_all.jsonl", L / "second_rater.jsonl", L / "second_rater_result.json",
                                             a.rater, a.ai_assistance), ensure_ascii=False, indent=2))
    elif a.cmd == "relabel-import":
        print(json.dumps(import_relabel_sheet(L / "relabel_sheet.csv", L / "relabel_sample.json", L / "labels_all.jsonl", proto, L / "relabel.jsonl", L / "relabel_result.json", accept_short_gap=a.accept_short_gap), ensure_ascii=False, indent=2))
    else:
        write_pre_evaluator_summary(L / "labels_all.jsonl", L / "mutants_log.json", L / "relabel_result.json", L / "second_validator_log.json", L / "pre_evaluator_summary.md")
        print((L / "pre_evaluator_summary.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
