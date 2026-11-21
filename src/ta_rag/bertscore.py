"""BERTScore (Zhang dkk., 2020) sebagai pembanding DESKRIPTIF, memakai implementasi resmi `bert-score` (extra `eval`).

Kandidat = jawaban, rujukan = evidence (kutipan oracle). Model `bert-base-multilingual-cased` (lapisan 9 = bawaan implementasi),
tanpa idf dan tanpa baseline rescaling; konfigurasi tercatat pada `hash`. Tidak ada seleksi atau test di sini.

    python -m ta_rag.bertscore pilot --labels data/labels/labels_all.jsonl --cases data/cases/questions_draft.jsonl \
        --scored data/results/scored_I.jsonl --out data/results/exploratory/bertscore_pilot.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

MODEL = "bert-base-multilingual-cased"


def default_scorer():
    """BERTScorer resmi (CPU) dengan konfigurasi yang dipra-registrasi; menolak bila hash konfigurasi tidak sesuai."""
    from bert_score import BERTScorer

    scorer = BERTScorer(model_type=MODEL, rescale_with_baseline=False, idf=False, device="cpu")
    if not scorer.hash.startswith(f"{MODEL}_L9_no-idf"):
        raise RuntimeError(f"konfigurasi BERTScore berbeda dari protokol (lapisan 9, tanpa idf/rescaling): {scorer.hash}")
    return scorer


def score_pairs(pairs: list[tuple[str, str]], scorer=None) -> dict:
    """pairs = [(jawaban, evidence)] -> {P, R, F1 (daftar float), hash}. `scorer` diinjeksikan (tes); bawaan = `default_scorer()`."""
    if scorer is None:
        scorer = default_scorer()
    cands, refs = [a for a, _ in pairs], [e for _, e in pairs]
    p, r, f = scorer.score(cands, refs)
    return {"P": p.tolist(), "R": r.tolist(), "F1": f.tolist(), "hash": scorer.hash}


def auc(pos: list[float], neg: list[float]) -> float:
    """P(skor pos > skor neg) + 0,5 P(seri). 0,5 = tak terbedakan; pos = jawaban LAYAK, neg = mutasi."""
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def pilot_analysis(rows: list[dict], scorer=None) -> dict:
    """rows: jawaban Tahap I {answer_id, track, label, answer, evidence, L, S, mutated_from_answer_id, mutation_family, unsupported_numbers}.
    Menjawab Panduan Tabel 3: apakah perubahan satu fakta menghasilkan skor tinggi? Selisih berpasangan (mutasi - aslinya) per metrik."""
    bs = score_pairs([(r["answer"], r["evidence"]) for r in rows], scorer)
    scored = [{**r, "BERT_P": p, "BERT_R": rc, "BERT_F1": f} for r, p, rc, f in zip(rows, bs["P"], bs["R"], bs["F1"])]
    by_id = {r["answer_id"]: r for r in scored}
    muts = [r for r in scored if r["track"] == "M"]
    missing = [m["answer_id"] for m in muts if m["mutated_from_answer_id"] not in by_id]
    if missing:
        raise ValueError(f"jawaban asal mutasi tidak ada: {missing}")
    layak = [r for r in scored if r["track"] == "R" and r["label"] == "LAYAK"]
    summary = {}
    for key in ("BERT_F1", "S", "L"):
        d = [m[key] - by_id[m["mutated_from_answer_id"]][key] for m in muts]
        summary[key] = {"n_pairs": len(d), "n_lower": sum(x < 0 for x in d), "median_delta": round(statistics.median(d), 4), "mean_delta": round(statistics.mean(d), 4),
                        "auc_layak_vs_mutasi": round(auc([r[key] for r in layak], [m[key] for m in muts]), 3)}
    pairs = [{"case_pair": [m["mutated_from_answer_id"], m["answer_id"]], "family": m["mutation_family"], "unsupported_numbers": m["unsupported_numbers"],
              **{f"{k}_{w}": round(src[k], 4) for w, src in (("asli", by_id[m["mutated_from_answer_id"]]), ("mutasi", m)) for k in ("BERT_F1", "S", "L")}} for m in muts]
    return {"status": "EXPLORATORY_POST_TEST_DESCRIPTIVE", "hash": bs["hash"], "n_layak_asli": len(layak), "summary": summary, "pairs": pairs,
            "records": [{k: round(r[k], 4) if isinstance(r[k], float) else r[k] for k in ("answer_id", "track", "label", "BERT_P", "BERT_R", "BERT_F1", "S", "L")} for r in scored]}


def main(argv=None) -> int:  # pragma: no cover - perekat tipis
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["pilot"]); ap.add_argument("--labels", required=True); ap.add_argument("--cases", required=True)
    ap.add_argument("--scored", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    jl = lambda p: [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]
    cases, labels, scored = {c["case_id"]: c for c in jl(a.cases)}, {r["answer_id"]: r for r in jl(a.labels)}, jl(a.scored)
    rows = [{"answer_id": s["answer_id"], "track": s["track"], "label": s["label"], "answer": labels[s["answer_id"]]["answer"],
             "evidence": cases[s["case_id"]]["source_quote"], "L": s["L"], "S": s["S"], "unsupported_numbers": s["unsupported_numbers"],
             "mutated_from_answer_id": labels[s["answer_id"]].get("mutated_from_answer_id"), "mutation_family": labels[s["answer_id"]].get("mutation_family")} for s in scored]
    res = pilot_analysis(rows)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"hash": res["hash"], "summary": res["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
