"""Perekat alur: chunk -> capture -> score -> sweep (validation) -> test (SEKALI). Fungsi murni + CLI tipis.

    python -m ta_rag.pipeline chunk   --raw-dir data/reducto/raw --out data/index/chunks.jsonl
    python -m ta_rag.pipeline capture --cases data/cases/questions_draft.jsonl --chunks data/index/chunks.jsonl --run run1 --out data/runs
    python -m ta_rag.pipeline score   --stage I  --labels data/labels/labels.jsonl --cases data/cases/questions_draft.jsonl --out data/results/scored_I.jsonl
    python -m ta_rag.pipeline sweep   --scored data/results/scored_I.jsonl --out data/results/I
    python -m ta_rag.pipeline test    --scored data/results/scored_I.jsonl --selection data/results/I/selection.json --out data/results/I/test_result.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

from . import bertscore, chunking, corpus, data, metrics, sweep
from . import evaluators as E
from .protocol import load_protocol


def read_jsonl(p) -> list[dict]:
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def write_jsonl(rows: list[dict], p) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ chunk

def raw_files_for(doc_id: str, raw_dir: Path) -> list[Path]:
    return sorted(p for p in Path(raw_dir).glob(f"{doc_id}__*.json") if "superseded" not in p.name)


def build_chunks(raw_dir: Path, cfg: dict) -> list[dict]:
    chunks: list[dict] = []
    for d in cfg["documents"]:
        if d.get("eval_role") == "deferred":
            continue
        files = raw_files_for(d["doc_id"], raw_dir)
        if not files:
            raise FileNotFoundError(f"raw Reducto untuk {d['doc_id']} tidak ada di {raw_dir}")
        for f in files:
            chunks += chunking.chunk_document(json.loads(f.read_text(encoding="utf-8")), d)
    problems = corpus.check_chunk_scope(chunks, cfg)
    if problems:
        raise ValueError("chunk di luar cakupan indeks:\n" + "\n".join(problems[:10]))
    return chunks


# ------------------------------------------------------------------ retrieval_ok

def retrieval_ok(case: dict, retrieved: list[dict]) -> bool | None:
    """True bila salah satu chunk terambil memuat halaman jangkar dokumen sumber. Probe: tak terdefinisi (None)."""
    if case.get("kind") != "answerable":
        return None
    pg, doc = case["source_page"], case["source_doc_id"]
    return any(c["doc_id"] == doc and c["page_start"] <= pg <= c["page_end"] for c in retrieved)


def _norm_quote(text: str) -> str:
    """NFKC, casefold, penanda markdown `*` dan `_` dibuang, spasi dirapatkan."""
    return " ".join(unicodedata.normalize("NFKC", text or "").casefold().replace("*", "").replace("_", "").split())


def quote_in_context(case: dict, retrieved: list[dict]) -> bool | None:
    """True bila kutipan oracle (ternormalisasi) termuat dalam teks chunk terambil yang digabung dengan spasi (kutipan boleh melintasi dua chunk).
    Pembanding tingkat kutipan untuk sensitivitas deskriptif tahap II; TIDAK memengaruhi label maupun `retrieval_ok`. Probe atau tanpa kutipan: None."""
    if case.get("kind") != "answerable" or not case.get("source_quote"):
        return None
    return _norm_quote(case["source_quote"]) in _norm_quote(" ".join(c["text"] for c in retrieved))


# ------------------------------------------------------------------ score

def evidence_for(stage: str, row: dict, cases: dict, chunks: dict, ) -> str | None:
    case = cases[row["case_id"]]
    if stage == "I":
        return case.get("source_quote") if case["kind"] == "answerable" else None  # probe tak punya evidence oracle
    if row.get("answer_origin") == "mutasi_terkontrol" or not row.get("chunk_ids"):
        return None  # mutan tidak melalui retrieval; tahap II hanya jawaban asli dengan konteks terambil
    return "\n".join(chunks[c]["text"] for c in row["chunk_ids"])


def score_rows(stage: str, labels: list[dict], cases: dict, chunks: dict, embed, stage_ii_evidence: str = "concat", bert_scorer=None) -> list[dict]:
    """stage_ii_evidence: "concat" = gabungan chunk terambil (Studi 1); "best_unit" = satuan konteks terbaik untuk L, S, negasi (Studi 2).
    bert_scorer (konfigurasi F): bila diberikan, `bert_f1` = BERTScore F1 jawaban terhadap evidence yang sama dengan L dan S."""
    if stage not in ("I", "II"):
        raise ValueError("stage harus I atau II")
    if stage_ii_evidence not in ("concat", "best_unit"):
        raise ValueError("stage_ii_evidence harus concat atau best_unit")
    probs = data.validate_records(labels)
    if probs:
        raise ValueError("labels tidak valid:\n" + "\n".join(probs[:10]))
    out, pairs = [], []
    for r in labels:
        if not r.get("manual_label_locked"):
            raise ValueError(f"{r['answer_id']}: label belum dikunci; skor tidak boleh dihitung")
        if r["label"] not in ("LAYAK", "TIDAK_LAYAK"):
            continue  # INSUFFICIENT_EVIDENCE keluar dari analisis utama (dilaporkan terpisah)
        ev = evidence_for(stage, r, cases, chunks)
        if ev is None:
            continue
        span = E.best_unit(r["answer"], ev) if stage == "II" and stage_ii_evidence == "best_unit" else ev
        s = E.score_pair(r["answer"], span, embed, cases[r["case_id"]].get("question", ""), support=ev)
        pairs.append((r["answer"], span))
        label, rok, qic = r["label"], None, None
        if stage == "II":
            ctx = [chunks[c] for c in r["chunk_ids"]]
            rok, qic = retrieval_ok(cases[r["case_id"]], ctx), quote_in_context(cases[r["case_id"]], ctx)
            if r["kind"] == "answerable" and r.get("abstain") and rok is False:
                label = "LAYAK"  # rubrik terkunci: abstain pada pertanyaan berjawab LAYAK di tahap II hanya bila retrieval meleset
        out.append({"answer_id": r["answer_id"], "case_id": r["case_id"], "group_id": r["group_id"], "evidence_group": r["evidence_group"],
                    "track": r["track"], "kind": r["kind"], "label": label, "label_stage_I": r["label"], "abstain": r.get("abstain"),
                    "retrieval_ok": rok, **({"quote_in_context": qic} if stage == "II" else {}),
                    "stage": stage, "evidence_mode": stage_ii_evidence if stage == "II" else "oracle_quote",
                    **{k: r[k] for k in ("run_id", "mutation_family") if r.get(k)}, **s})
    if bert_scorer is not None and out:
        for row, f1 in zip(out, bertscore.score_pairs(pairs, bert_scorer)["F1"]):
            row["bert_f1"] = f1
    return out


# ------------------------------------------------------------------ sweep + test

def run_sweep(scored: list[dict], out_dir: Path, protocol: dict, p95_ms_by_config: dict | None = None) -> dict:
    sp = protocol["split"]
    splits = data.assign_splits(scored, sp["seed"], sp["validation_fraction"])
    leaks = data.check_split_leak(scored, splits)
    if leaks:
        raise ValueError("kebocoran split: " + "; ".join(leaks))
    val = [s for s in scored if splits[s["answer_id"]] == "validation"]
    out_dir = Path(out_dir)
    sweep.write_csv(sweep.stage_a(val), out_dir / "stage_A.csv")
    sweep.write_csv(sweep.stage_b(val), out_dir / "stage_B.csv")
    grid = sweep.stage_grid(val, tuple(protocol["selection"].get("grid_configs", ("C", "D"))))
    sweep.write_csv(grid, out_dir / "stage_C.csv")
    sel = {"configs": sweep.select_all(grid, protocol["selection"]["alpha"], p95_ms_by_config, 0.10),
           "alpha": protocol["selection"]["alpha"], "selection_far": "FAR Track M pada validation (D10)",
           "split_report": data.split_report(scored, splits),
           "splits_sha256": hashlib.sha256(json.dumps(sorted(splits.items())).encode()).hexdigest(),
           "note": "dipilih HANYA dari validation; test belum disentuh"}
    (out_dir / "selection.json").write_text(json.dumps(sel, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "splits.json").write_text(json.dumps(splits, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return sel


def r_far_items(test: list[dict], route: dict) -> dict[str, list[tuple[str, bool]]]:
    """Baris Track R berlabel TIDAK_LAYAK menurut jenisnya, sebagai [(group_id, diterima)]: `abstain` (abstain is True) vs `jawaban_salah` (selain itu).
    Hanya memecah FAR Track R (pembilang dan penyebut kedua jenis berjumlah sama dengan FAR gabungan); tidak memilih apa pun. route = {answer_id: rute}."""
    bad = [s for s in test if s["track"] == "R" and s["label"] == "TIDAK_LAYAK"]
    return {t: [(s["group_id"], route[s["answer_id"]] == "ACCEPT") for s in bad if (s.get("abstain") is True) == (t == "abstain")] for t in ("abstain", "jawaban_salah")}


def run_test(scored: list[dict], selection: dict, protocol: dict, out_path: Path, acknowledge_rerun: bool = False) -> dict:
    """Test SEKALI: menilai semua konfigurasi terpilih (A, B, C, D, D*) pada split test, per track. Track R dan M tidak digabung.
    `R_far_by_type` (rincian deskriptif, tidak memengaruhi apa pun): FAR Track R menurut jenis TIDAK_LAYAK, abstain vs jawaban_salah (`r_far_items`)."""
    out_path = Path(out_path)
    if out_path.exists() and not acknowledge_rerun:
        raise FileExistsError(f"{out_path} sudah ada: test hanya SEKALI. Ulang hanya dengan --acknowledge-rerun (dicatat sebagai deviasi).")
    cfgs = selection["configs"]
    if all(c["params"] is None for c in cfgs.values()):
        raise ValueError("tidak ada parameter terpilih pada konfigurasi mana pun (" + ", ".join(f"{k}: {c['selection']['status']}" for k, c in cfgs.items()) + "); test tidak dijalankan")
    sp = protocol["split"]
    splits = data.assign_splits(scored, sp["seed"], sp["validation_fraction"])
    if hashlib.sha256(json.dumps(sorted(splits.items())).encode()).hexdigest() != selection["splits_sha256"]:
        raise ValueError("pembagian split berbeda dari saat pemilihan (data/seed berubah); jangan lanjut")
    test = [s for s in scored if splits[s["answer_id"]] == "test"]
    out_cfgs, rerun = {}, out_path.exists()
    for name, c in cfgs.items():
        prm = c["params"]
        if prm is None:
            out_cfgs[name] = {"params": None, "status": f"NOT_EVALUATED_{c['selection']['status']}"}
            continue
        route = {s["answer_id"]: E.route_params(s, prm)["route"] for s in test}
        by_track = {t: [{"label": s["label"], "route": route[s["answer_id"]]} for s in test if s["track"] == t] for t in ("R", "M")}
        out_cfgs[name] = {"params": prm, "R": metrics.summarize(by_track["R"]), "M": metrics.summarize(by_track["M"]),
                          "R_far_by_type": {t: metrics.rate(sum(a for _, a in it), len(it)) for t, it in r_far_items(test, route).items()},
                          "selection_warning": c["selection"].get("warning"),
                          "status": ("TEST_RUN_ONCE_FROZEN_PARAMS" if c["selection"]["status"] == "SELECTED"
                                     else "TEST_RUN_ONCE_R2_REFERENCE_NO_ELIGIBLE_PARAMETER")}
    res = {"n_test": len(test), "n_test_by_track": {t: sum(1 for s in test if s["track"] == t) for t in ("R", "M")}, "configs": out_cfgs,
           "claim_prefix_required": protocol["claim_prefix"], "rerun": rerun, "status": "TEST_RUN_ONCE"}
    if clustered := clustered_analysis(test, cfgs, protocol):
        res["clustered"] = clustered
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sweep.write_csv(per_case_rows(scored, splits, cfgs), out_path.parent / "per_case.csv")
    return res


def clustered_analysis(test: list[dict], cfgs: dict, protocol: dict) -> dict | None:
    """Studi 2, dari baris test yang SAMA dengan `run_test` (bukan analisis kedua; parameter tetap beku). Per konfigurasi: gabungan lari dengan CI
    bootstrap klaster pertanyaan (Track R dan M terpisah), per lari (Clopper-Pearson, Track R) dengan rata-rata dan rentang, dan hipotesis
    berpasangan H1-H3 bila protokol mengoperasionalkannya (`significance_claims.operationalization`). None bila baris tak memuat run_id (Studi 1).
    `pooled.R_far_by_type`: FAR Track R gabungan lari menurut jenis TIDAK_LAYAK (abstain vs jawaban_salah), CI bootstrap klaster seperti `pooled.R`."""
    if not any(s.get("run_id") for s in test):
        return None
    routes = {n: {s["answer_id"]: E.route_params(s, c["params"])["route"] for s in test} for n, c in cfgs.items() if c["params"]}
    runs = sorted({s["run_id"] for s in test if s.get("run_id")})
    out = {"runs": runs, "cluster_unit": "group_id (pertanyaan)", "configs": {}}
    for n, rt in routes.items():
        rows = {t: [{"cluster": s["group_id"], "run": s.get("run_id"), "label": s["label"], "route": rt[s["answer_id"]]} for s in test if s["track"] == t] for t in ("R", "M")}
        per_run = {k: metrics.summarize([r for r in rows["R"] if r["run"] == k]) for k in runs}
        pooled = {t: metrics.summarize_clustered(rows[t]) for t in ("R", "M")} | {"R_far_by_type": {t: metrics.cluster_rate(it) for t, it in r_far_items(test, rt).items()}}
        out["configs"][n] = {"pooled": pooled, "per_run": per_run, "spread": metrics.run_spread(per_run)}
    op = protocol.get("significance_claims", {}).get("operationalization")
    if op:
        level, out["hypotheses"] = 1 - op["alpha_family"] / op["n_hypotheses"], {}
        for h in ("H1", "H2", "H3"):
            spec = op[h]
            if spec["higher"] not in routes or spec["lower"] not in routes:
                out["hypotheses"][h] = {**spec, "verdict": "NOT_EVALUATED_NO_FROZEN_PARAMS"}
                continue
            muts = [s for s in test if s["track"] == "M" and (spec["families"] is None or s.get("mutation_family") in spec["families"])]
            hit = lambda cfg, s: routes[cfg][s["answer_id"]] == spec["outcome"]
            out["hypotheses"][h] = {**spec, **metrics.paired_cluster_diff([(s["group_id"], hit(spec["higher"], s), hit(spec["lower"], s)) for s in muts], level, op["min_diff"])}
    return out


def per_case_rows(scored: list[dict], splits: dict, cfgs: dict) -> list[dict]:
    """Satu baris per jawaban (validation + test): skor mentah dan rute tiap konfigurasi terpilih. Dipanggil SETELAH test."""
    rows = []
    for s in scored:
        row = {"answer_id": s["answer_id"], "case_id": s["case_id"], "track": s["track"], "label": s["label"], "split": splits[s["answer_id"]],
               "L": s["L"], "S": s["S"], "unsupported_numbers": ";".join(s["unsupported_numbers"]), "neg_mismatch": s["neg_mismatch"],
               **{k: s[k] for k in ("kind", "retrieval_ok", "label_stage_I", "bert_f1") if k in s}}
        for name, c in cfgs.items():
            if c["params"] is None:
                continue
            r = E.route_params(s, c["params"])
            row[f"H_{name}"], row[f"route_{name}"], row[f"flags_{name}"] = round(r["H"], 6), r["route"], ";".join(r["flags"])
        rows.append(row)
    return rows


def stage2_configs(scored: list[dict], selection: dict) -> dict:
    """Ringkasan tahap II per konfigurasi dengan parameter beku, menurut kolom `label` baris `scored`: label primer, atau label sensitivitas tingkat kutipan."""
    kinds = {"all": lambda s: True, "answerable": lambda s: s["kind"] == "answerable", "probe": lambda s: s["kind"] == "not_in_corpus"}
    runs = sorted({s["run_id"] for s in scored if s.get("run_id")})
    cfgs_out = {}
    for name, c in selection["configs"].items():
        prm = c["params"]
        if prm is None:
            cfgs_out[name] = {"params": None, "status": "NOT_APPLIED_NO_FROZEN_PARAMS"}
            continue
        routed = [(s, E.route_params(s, prm)["route"]) for s in scored]
        rows = lambda f: [{"cluster": s["group_id"], "run": s.get("run_id"), "label": s["label"], "route": r} for s, r in routed if f(s)]
        cfgs_out[name] = {"params": prm, **{g: metrics.summarize(rows(f)) for g, f in kinds.items()}}
        if runs:  # Studi 2: tiga lari atas pertanyaan yang sama -> CI bootstrap klaster untuk gabungan, Clopper-Pearson per lari
            cfgs_out[name] |= {"clustered": {g: metrics.summarize_clustered(rows(f)) for g, f in kinds.items()},
                               "per_run": {k: {g: metrics.summarize([r for r in rows(f) if r["run"] == k]) for g, f in kinds.items()} for k in runs}}
    return cfgs_out


def run_stage2(scored: list[dict], selection: dict, protocol: dict, out_dir: Path) -> dict:
    """Tahap II DESKRIPTIF (D14): parameter beku dari seleksi tahap I diterapkan pada semua jawaban asli (konteks hasil retrieval).
    Bukan sweep, bukan test: tidak ada pemilihan dan tidak ada pembagian split.
    `sensitivity_quote_level` (tambahan deskriptif, hanya bila baris memuat `quote_in_context`): ringkasan yang sama dengan label diturunkan pada tingkat kutipan;
    blok primer tidak berubah."""
    rok = [s["retrieval_ok"] for s in scored]
    res = {"stage": "II", "status": "DESCRIPTIVE_NO_SELECTION_NO_TEST", "n_by_kind": {k: sum(1 for s in scored if s["kind"] == k) for k in ("answerable", "not_in_corpus")},
           "retrieval_ok": {"true": rok.count(True), "false": rok.count(False), "n/a": rok.count(None)}, "configs": stage2_configs(scored, selection),
           "claim_prefix_required": protocol["claim_prefix"],
           "note": "parameter dipilih pada tahap I (validation); di sini diterapkan pada seluruh jawaban asli, jadi bukan evaluasi independen"}
    if any("quote_in_context" in s for s in scored):  # skor dari kode lama tak memuatnya: tanpa blok, keluaran lama tidak berubah
        sens = [{**s, "label": "LAYAK" if s["kind"] == "answerable" and s.get("abstain") is True and s.get("quote_in_context") is False else s["label_stage_I"]} for s in scored]
        res["sensitivity_quote_level"] = {
            "definition": "Label tahap II diturunkan ulang pada tingkat kutipan: jawaban berjawab yang abstain dan kalimat kutipannya tidak termuat dalam konteks terambil "
                          "(`quote_in_context` salah) berlabel LAYAK, semua baris lain memakai label tahap I; analisis deskriptif, definisi `retrieval_ok` tingkat halaman dan hasil primer tidak berubah.",
            "flipped_answer_ids": sorted(a["answer_id"] for a, b in zip(scored, sens) if a["label"] != b["label"]),
            "configs": stage2_configs(sens, selection)}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stage2_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sweep.write_csv(per_case_rows(scored, {s["answer_id"]: "descriptive" for s in scored}, selection["configs"]), out_dir / "per_case_II.csv")
    return res


# ------------------------------------------------------------------ latency

def hardware_info() -> dict:
    import os
    import platform

    mem = None
    try:
        mem = int(next(l for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemTotal")).split()[1]) // 1024
    except Exception:  # pragma: no cover - bukan Linux
        pass
    return {"platform": platform.platform(), "processor": platform.processor() or None, "cpu_count": os.cpu_count(),
            "ram_mb": mem, "gpu": "tidak dicatat (embedding dijalankan di CPU)", "python": platform.python_version()}


def measure_latency(pairs: list[tuple[str, str]], embed, w_s: float, accept: float, hard_fail: bool, unit_fail: bool = False,
                    iters: int = 100, warmup: int = 10, timer=None) -> dict:
    """Latency EVALUATOR saja (skor + keputusan, termasuk embedding) per pasangan jawaban-evidence, setelah warm-up.
    Minimal 100 iterasi (spec §8); pasangan diputar berurutan agar deterministik."""
    import time

    timer = timer or time.perf_counter
    if not pairs:
        raise ValueError("pairs kosong")
    for i in range(warmup):
        a, e = pairs[i % len(pairs)]
        E.route(E.score_pair(a, e, embed if w_s > 0 else None), w_s, accept, hard_fail, unit_fail=unit_fail)
    samples = []
    for i in range(iters):
        a, e = pairs[i % len(pairs)]
        t0 = timer()
        E.route(E.score_pair(a, e, embed if w_s > 0 else None), w_s, accept, hard_fail, unit_fail=unit_fail)
        samples.append((timer() - t0) * 1000.0)
    return {**metrics.latency_stats(samples), "unit": "ms", "w_s": w_s, "hard_fail": hard_fail, "hardware": hardware_info(),
            "scope": "evaluator saja (skor + keputusan); tanpa retrieval dan generator"}


def sweep_stability(scored: list[dict], protocol: dict, selection: dict | None = None, n_boot: int = 1000,
                    alphas: tuple[float, ...] = (0.05, 0.10, 0.20), p95_ms_by_config: dict | None = None) -> dict:
    """Eksploratif pasca-test, hanya dari split VALIDATION: stabilitas seleksi (bootstrap komponen), sensitivitas terhadap alpha,
    dan (bila `selection` diberikan) apakah seleksi terkunci dapat direproduksi dari data yang sama."""
    sp, alpha = protocol["split"], protocol["selection"]["alpha"]
    configs = tuple(protocol["selection"].get("grid_configs", ("C", "D")))
    splits = data.assign_splits(scored, sp["seed"], sp["validation_fraction"])
    val = [s for s in scored if splits[s["answer_id"]] == "validation"]
    res = {"stability": sweep.selection_stability(val, alpha, n_boot, p95_ms_by_config=p95_ms_by_config, configs=configs),
           "alpha_sensitivity": sweep.alpha_sensitivity(val, alphas, p95_ms_by_config, configs=configs)}
    if selection:
        again = sweep.select_all(sweep.stage_grid(val, configs), alpha, p95_ms_by_config)
        res["locked_selection_reproduced"] = {k: again[k]["selection"]["chosen"] == selection["configs"][k]["selection"]["chosen"] for k in again}
    return res


# ------------------------------------------------------------------ stabilitas antar-run (eksploratif)

def route_stability(runs: dict[str, list[dict]], cases: dict, configs: dict, embed) -> dict:
    """Eksploratif pasca-test, TANPA label: keputusan parameter beku tiap konfigurasi untuk jawaban asli pertanyaan berjawab
    di setiap run, terhadap evidence oracle Tahap I. Mengukur seberapa sering keputusan berubah karena variasi generator;
    bukan CAR/FAR (run 2-3 tidak dilabel) dan tidak dipakai memilih apa pun."""
    params = {k: v["params"] for k, v in configs.items() if v.get("params")}
    per_case: dict[str, dict] = {}
    for run_id, rows in sorted(runs.items()):
        for r in rows:
            c = cases[r["case_id"]]
            if c["kind"] != "answerable":
                continue
            sc = E.score_pair(r["answer"], c["source_quote"], embed, c.get("question", ""))
            per_case.setdefault(r["case_id"], {})[run_id] = {k: E.route_params(sc, p)["route"] for k, p in params.items()}
    missing = sorted(cid for cid, d in per_case.items() if len(d) != len(runs))
    if missing:
        raise ValueError(f"kasus tidak ada di semua run: {missing}")
    same = {k: sum(len({routes[k] for routes in d.values()}) == 1 for d in per_case.values()) for k in params}
    return {"status": "EXPLORATORY_POST_TEST_UNLABELED", "runs": sorted(runs), "n_cases": len(per_case),
            "same_route_all_runs": same, "per_case": per_case}


def measure_latency_bert(pairs: list[tuple[str, str]], scorer, iters: int = 100, warmup: int = 10, timer=None) -> dict:
    """Latency evaluator F: satu pasangan (jawaban, evidence) per panggilan BERTScore beserta keputusannya, setelah warm-up."""
    import time

    timer = timer or time.perf_counter
    if not pairs:
        raise ValueError("pairs kosong")
    for i in range(warmup):
        a, e = pairs[i % len(pairs)]
        scorer.score([a], [e])
    samples = []
    for i in range(iters):
        a, e = pairs[i % len(pairs)]
        t0 = timer()
        E.route_bert(float(scorer.score([a], [e])[2][0]), 0.78)
        samples.append((timer() - t0) * 1000.0)
    return {**metrics.latency_stats(samples), "unit": "ms", "config": "F", "hardware": hardware_info(),
            "scope": "evaluator F saja (BERTScore F1 + keputusan); tanpa retrieval dan generator"}


def latency_default(pairs: list[tuple[str, str]], embed, grid: tuple[str, ...], bert_scorer=None, iters: int = 100, timer=None) -> dict:
    """Latency PRA-seleksi (S33), sebelum parameter terpilih ada: A (w_s 0), C dan D (w_s 0,6, ambang 0,78), E = D + aturan satuan dan F = BERTScore
    hanya bila `selection.grid_configs` memuatnya. Dipakai kolom p95 Tabel 11 dan tie-break seleksi; B memakai jalur C (sweep.LATENCY_KEY)."""
    cfgs = {"A": (0.0, False, False), "C": (0.6, False, False), "D": (0.6, True, False)} | ({"E": (0.6, True, True)} if "E" in grid else {})
    res = {c: measure_latency(pairs, embed, w_s=w, accept=0.78, hard_fail=h, unit_fail=u, iters=iters, timer=timer) for c, (w, h, u) in cfgs.items()}
    if "F" in grid:
        res["F"] = measure_latency_bert(pairs, bert_scorer or bertscore.default_scorer(), iters=iters, timer=timer)
    res["p95_ms_by_config"] = {c: v["p95"] for c, v in res.items()}
    return res


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:  # pragma: no cover - perekat tipis; fungsi di atas yang diuji
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chunk"); c.add_argument("--raw-dir", default="data/reducto/raw"); c.add_argument("--out", default="data/index/chunks.jsonl")
    k = sub.add_parser("capture"); k.add_argument("--cases", required=True); k.add_argument("--chunks", required=True); k.add_argument("--run", required=True); k.add_argument("--out", default="data/runs"); k.add_argument("--only", help="id kasus dipisah koma (smoke test)"); k.add_argument("--smoke", action="store_true", help="boleh sebelum generator FROZEN; wajib dengan --only dan keluaran di luar data/runs")
    s = sub.add_parser("score"); s.add_argument("--stage", required=True, choices=["I", "II"]); s.add_argument("--labels", required=True); s.add_argument("--cases", required=True); s.add_argument("--chunks", default="data/index/chunks.jsonl"); s.add_argument("--out", required=True)
    w = sub.add_parser("sweep"); w.add_argument("--scored", required=True); w.add_argument("--out", required=True); w.add_argument("--latency", help="latency.json dari `pipeline latency` (p95 per konfigurasi untuk tie-break)")
    st = sub.add_parser("stability"); st.add_argument("--runs", nargs="+", required=True); st.add_argument("--cases", required=True); st.add_argument("--selection", required=True); st.add_argument("--out", required=True)
    ss = sub.add_parser("sweep-stability"); ss.add_argument("--scored", required=True); ss.add_argument("--selection", required=True); ss.add_argument("--out", required=True); ss.add_argument("--latency"); ss.add_argument("--n-boot", type=int, default=1000)
    lt = sub.add_parser("latency"); lt.add_argument("--labels", required=True); lt.add_argument("--cases", required=True); lt.add_argument("--out", required=True); lt.add_argument("--iters", type=int, default=100)
    lt.add_argument("--selection", help="ukur ulang tiap konfigurasi terpilih dengan parameternya sendiri (pelaporan pasca-test; tidak dipakai seleksi)")
    g2 = sub.add_parser("stage2"); g2.add_argument("--scored", required=True); g2.add_argument("--selection", required=True); g2.add_argument("--out", required=True)
    t = sub.add_parser("test"); t.add_argument("--scored", required=True); t.add_argument("--selection", required=True); t.add_argument("--out", required=True); t.add_argument("--acknowledge-rerun", action="store_true")
    a = ap.parse_args(argv)
    proto = load_protocol()
    if a.cmd == "chunk":
        ch = build_chunks(Path(a.raw_dir), corpus.load_config())
        write_jsonl(ch, a.out)
        print(f"{len(ch)} chunk -> {a.out} (penjaga cakupan lolos)")
    elif a.cmd == "capture":
        from . import capture, retrieval

        cfg = capture.load_generator_config()
        ch = read_jsonl(a.chunks)
        idx = retrieval.Index(ch, E.sentence_transformer_embed(proto["retrieval"]["embedding_model"]))
        cases = [x for x in read_jsonl(a.cases)]
        if a.only:
            keep = set(a.only.split(","))
            cases = [x for x in cases if x["case_id"] in keep]
            if len(cases) != len(keep):
                raise SystemExit(f"kasus tidak ditemukan: {sorted(keep - {c['case_id'] for c in cases})}")
        if a.smoke and (not a.only or Path(a.out).name == "runs"):
            raise SystemExit("--smoke butuh --only dan --out selain data/runs (smoke bukan data penelitian)")
        print(capture.capture_run(cases, lambda q: idx.search(q, proto["retrieval"]["top_k"]), cfg, Path(a.out), a.run, top_k=proto["retrieval"]["top_k"], allow_unfrozen=a.smoke))
    elif a.cmd == "score":
        cases = {x["case_id"]: x for x in read_jsonl(a.cases)}
        chunks = {x["chunk_id"]: x for x in read_jsonl(a.chunks)} if a.stage == "II" else {}
        bert = bertscore.default_scorer() if "F" in proto["selection"].get("grid_configs", ()) else None  # konfigurasi F dipra-registrasi di protokol
        write_jsonl(score_rows(a.stage, read_jsonl(a.labels), cases, chunks, E.sentence_transformer_embed(proto["retrieval"]["embedding_model"]),
                               proto["split"].get("stage_II_evidence", "concat"), bert), a.out)
    elif a.cmd == "sweep":
        p95 = json.loads(Path(a.latency).read_text(encoding="utf-8"))["p95_ms_by_config"] if a.latency else None
        print(json.dumps(run_sweep(read_jsonl(a.scored), Path(a.out), proto, p95), ensure_ascii=False, indent=2))
    elif a.cmd == "stage2":
        print(json.dumps(run_stage2(read_jsonl(a.scored), json.loads(Path(a.selection).read_text(encoding="utf-8")), proto, Path(a.out)), ensure_ascii=False, indent=2))
    elif a.cmd == "latency":
        cases = {x["case_id"]: x for x in read_jsonl(a.cases)}
        pairs = [(r["answer"], cases[r["case_id"]]["source_quote"]) for r in read_jsonl(a.labels)
                 if cases[r["case_id"]]["kind"] == "answerable" and cases[r["case_id"]].get("source_quote")]
        embed = E.sentence_transformer_embed(proto["retrieval"]["embedding_model"])
        if a.selection:
            cfgs = json.loads(Path(a.selection).read_text(encoding="utf-8"))["configs"]
            res = {k: (measure_latency_bert(pairs, bertscore.default_scorer(), iters=a.iters) if v["params"]["config"] == "F" else
                       measure_latency(pairs, embed, w_s=v["params"]["w_s"], accept=v["params"]["accept"], hard_fail=v["params"]["hard_fail"],
                                       unit_fail=v["params"].get("unit_fail", False), iters=a.iters))
                   for k, v in cfgs.items() if v.get("params")}
            res["p95_ms_by_config"] = {cfg: v["p95"] for cfg, v in res.items()}
        else:
            res = latency_default(pairs, embed, tuple(proto["selection"].get("grid_configs", ("C", "D"))), iters=a.iters)  # A tanpa embedding; B memakai jalur C
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(res["p95_ms_by_config"]))
    elif a.cmd == "sweep-stability":
        p95 = json.loads(Path(a.latency).read_text(encoding="utf-8"))["p95_ms_by_config"] if a.latency else None
        res = sweep_stability(read_jsonl(a.scored), proto, json.loads(Path(a.selection).read_text(encoding="utf-8")), a.n_boot, p95_ms_by_config=p95)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(res["locked_selection_reproduced"]))
    elif a.cmd == "stability":
        runs = {}
        for path in a.runs:
            rows = read_jsonl(path)
            ids = {r["run_id"] for r in rows}
            if len(ids) != 1:
                raise ValueError(f"{path}: harus tepat satu run_id, ada {sorted(ids)}")
            runs[ids.pop()] = rows
        res = route_stability(runs, {x["case_id"]: x for x in read_jsonl(a.cases)}, json.loads(Path(a.selection).read_text(encoding="utf-8"))["configs"],
                              E.sentence_transformer_embed(proto["retrieval"]["embedding_model"]))
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: res[k] for k in ("runs", "n_cases", "same_route_all_runs")}))
    else:
        print(json.dumps(run_test(read_jsonl(a.scored), json.loads(Path(a.selection).read_text()), proto, Path(a.out), a.acknowledge_rerun), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
