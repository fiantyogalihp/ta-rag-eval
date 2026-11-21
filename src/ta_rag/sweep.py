"""Sweep sensitivitas (spec §9) dan pemilihan parameter terkunci. Hanya VALIDATION yang boleh memilih; test sekali.

Input `scored`: [{answer_id, track (R|M), label, L, S, unsupported_numbers, neg_mismatch}] dari `evaluators.score_pair`.
Tahap A: bobot semantic 0..100% (101 titik), ACCEPT 0,78.  Tahap B: bobot 60:40, ACCEPT 0..1 (101 titik).
Tahap C: grid 6 x 5 = 30 untuk C dan 30 untuk D = 60 baris (satu baris per kombinasi).

Track R dan M TIDAK digabung (CLAUDE.md 5). Metrik per titik: CAR, false rejection, REVIEW/REJECT dari Track R; FAR dilaporkan
untuk R dan M, tetapi SELEKSI memakai FAR Track M (D10): Track R mungkin tak memuat TIDAK_LAYAK sama sekali.
Seleksi per konfigurasi (D11): A = baris w_s=0, B = baris w_s=1, C = hybrid murni (0<w_s<1), D = parameter C + hard-fail,
D* = R1/R2 atas 30 baris D (sekunder).
"""

from __future__ import annotations

import csv
import random
from collections import Counter
from pathlib import Path

from . import data
from . import evaluators as E
from . import metrics as M
from .protocol import select_parameters

W_GRID = (0.0, 0.25, 0.50, 0.60, 0.75, 1.0)
T_GRID = (0.70, 0.75, 0.78, 0.80, 0.85)
# kunci p95 (hasil `pipeline latency`) per nama konfigurasi seleksi; B memakai jalur yang sama dengan C (embedding + L)
LATENCY_KEY = {"A": "A", "B": "C", "C": "C", "D": "D", "E": "D", "F": "F", "D*": "D"}
CONFIGS = ("A", "B", "C", "D", "E", "F", "D*")  # urutan laporan; E dan F hanya muncul bila grid memuatnya
F_T_GRID = tuple(round(0.60 + 0.01 * i, 2) for i in range(36))  # ambang ACCEPT BERTScore F1 0,60-0,95
# konfigurasi grid -> (hard_fail, unit_fail). E = D + aturan satuan (Studi 2); bawaan Studi 1 hanya C dan D
GRID_FLAGS = {"C": (False, False), "D": (True, False), "E": (True, True)}


def evaluate_point(scored: list[dict], w_s: float, accept: float, hard_fail: bool, unit_fail: bool = False) -> dict:
    routed: dict[str, list[dict]] = {"R": [], "M": []}
    flags: dict[str, int] = {}
    for s in scored:
        r = E.route(s, w_s, accept, hard_fail, unit_fail=unit_fail)
        routed[s["track"]].append({"label": s["label"], "route": r["route"]})
        for f in r["flags"]:
            flags[f] = flags.get(f, 0) + 1
    return {"R": M.summarize(routed["R"]), "M": M.summarize(routed["M"]), "flags": flags}


def _cols(prefix: str, rate: dict) -> dict:
    return {prefix: rate["point"], f"{prefix}_k": rate["k"], f"{prefix}_n": rate["n"], f"{prefix}_lo95": rate["lo"], f"{prefix}_hi95": rate["hi"]}


def _flat(cfg_id: str, config: str, w_s: float, accept: float, ev: dict) -> dict:
    r, m = ev["R"], ev["M"]
    return {"id": cfg_id, "config": config, "w_s": w_s, "accept": accept, "n_R": r["n"], "n_M": m["n"],
            **_cols("car_R", r["CAR"]), **_cols("far_R", r["FAR"]), **_cols("far_M", m["FAR"]),
            "false_rejection_R": r["false_rejection"]["point"], "review_rate_R": r["review_rate"]["point"],
            "reject_rate_R": r["reject_rate"]["point"], "review_rate_M": m["review_rate"]["point"], "reject_rate_M": m["reject_rate"]["point"],
            "flags": ";".join(f"{k}={v}" for k, v in sorted(ev["flags"].items()))}


def stage_a(scored: list[dict]) -> list[dict]:
    return [_flat(f"A:{w}", "C", w / 100, 0.78, evaluate_point(scored, w / 100, 0.78, False)) for w in range(0, 101)]


def stage_b(scored: list[dict]) -> list[dict]:
    return [_flat(f"B:{t}", "C", 0.60, t / 100, evaluate_point(scored, 0.60, t / 100, False)) for t in range(0, 101)]


def stage_c(scored: list[dict], configs: tuple[str, ...] = ("C", "D")) -> list[dict]:
    out = []
    for config in configs:
        hard, unit = GRID_FLAGS[config]
        for w in W_GRID:
            for t in T_GRID:
                out.append(_flat(f"{config}:w{w}:t{t}", config, w, t, evaluate_point(scored, w, t, hard, unit)))
    return out


def stage_f(scored: list[dict], t_grid: tuple[float, ...] = F_T_GRID) -> list[dict]:
    """Grid konfigurasi F (BERTScore F1): satu baris per ambang ACCEPT. w_s = 0 hanya pengisi kolom (tidak dipakai)."""
    out = []
    for t in t_grid:
        routed: dict[str, list[dict]] = {"R": [], "M": []}
        for s in scored:
            routed[s["track"]].append({"label": s["label"], "route": E.route_bert(s["bert_f1"], t)["route"]})
        out.append(_flat(f"F:t{t}", "F", 0.0, t, {"R": M.summarize(routed["R"]), "M": M.summarize(routed["M"]), "flags": {}}))
    return out


def stage_grid(scored: list[dict], configs: tuple[str, ...] = ("C", "D")) -> list[dict]:
    """Grid validation lengkap menurut `selection.grid_configs` protokol: C/D/E (bobot x ambang) dan, bila diminta, F (BERTScore)."""
    return stage_c(scored, tuple(c for c in configs if c != "F")) + (stage_f(scored) if "F" in configs else [])


def select_on_validation(pool: list[dict], alpha: float, p95_ms: float | None = None, latency_rel: float = 0.10) -> dict:
    """R1/R2 terkunci atas satu pool baris grid. far = FAR Track M; car dan review_rate = Track R; p95_ms = p95 konfigurasi (None -> seri)."""
    rows = [{"id": r["id"], "far": r["far_M"], "car": r["car_R"] or 0.0, "review_rate": r["review_rate_R"] or 0.0,
             "p95_ms": p95_ms or 0.0, "w_s": r["w_s"], "accept": r["accept"]} for r in pool]
    pick = select_parameters(rows, alpha=alpha, latency_rel=latency_rel)
    _warn_if_degenerate(pick, next((r for r in pool if r["id"] == pick.get("chosen")), None))
    return pick


def _warn_if_degenerate(pick: dict, chosen: dict | None) -> None:
    if chosen is not None and not chosen["car_R"]:
        # FAR <= alpha terpenuhi secara sepele bila sistem tidak pernah ACCEPT: jangan dilaporkan sebagai keberhasilan
        pick["warning"] = "CAR_ZERO_DEGENERATE: parameter terpilih tidak pernah ACCEPT jawaban LAYAK"


def _params(name: str, row: dict | None) -> dict | None:
    if row is None:
        return None
    if row["config"] == "F":
        return {"label": name, "config": "F", "w_s": 0.0, "accept": row["accept"], "hard_fail": False}
    p = {"label": name, "config": row["config"], "w_s": row["w_s"], "accept": row["accept"], "hard_fail": GRID_FLAGS[row["config"]][0]}
    return p | {"unit_fail": True} if GRID_FLAGS[row["config"]][1] else p


def select_all(grid: list[dict], alpha: float, p95_ms_by_config: dict[str, float] | None = None, latency_rel: float = 0.10) -> dict:
    """Seleksi A, B, C, D, D* dari grid validation (60 baris). Mengembalikan {nama: {selection, params}}."""
    p95 = p95_ms_by_config or {}
    by_id = {r["id"]: r for r in grid}
    c_rows = [r for r in grid if r["config"] == "C"]
    pools = {"A": [r for r in c_rows if r["w_s"] == 0.0], "B": [r for r in c_rows if r["w_s"] == 1.0],
             "C": [r for r in c_rows if 0.0 < r["w_s"] < 1.0], "D*": [r for r in grid if r["config"] == "D"]}
    out = {}
    if any(r["config"] == "F" for r in grid):
        pools["F"] = [r for r in grid if r["config"] == "F"]
    for name, pool in pools.items():
        pick = select_on_validation(pool, alpha, p95.get(LATENCY_KEY[name]), latency_rel)
        out[name] = {"selection": pick, "params": _params(name, by_id.get(pick.get("chosen")))}
    # D = parameter C + hard-fail (Panduan Tabel 6), E = parameter C + hard-fail + satuan (bila grid memuat E): tidak dipilih ulang
    c_sel, c_par = out["C"]["selection"], out["C"]["params"]
    for name, rule in (("D", "D=C+hard-fail"), ("E", "E=C+hard-fail+satuan")):
        if name == "E" and not any(r["config"] == "E" for r in grid):
            continue
        row = by_id.get(f"{name}:w{c_par['w_s']}:t{c_par['accept']}") if c_par else None
        pick = {"status": c_sel["status"], "rule": rule, "chosen": row["id"] if row else None}
        _warn_if_degenerate(pick, row)
        out[name] = {"selection": pick, "params": _params(name, row)}
    return {k: out[k] for k in ("A", "B", "C", "D", "E", "F", "D*") if k in out}


def selection_stability(val: list[dict], alpha: float, n_boot: int = 1000, seed: int = 20261104,
                        p95_ms_by_config: dict[str, float] | None = None, latency_rel: float = 0.10, configs: tuple[str, ...] = ("C", "D")) -> dict:
    """Eksploratif PASCA-test: bootstrap komponen terhubung (group_id U evidence_group) pada VALIDATION dan ulangi seleksi
    tiap replikasi. Menunjukkan seberapa stabil parameter terpilih terhadap pengambilan sampel pertanyaan; tidak mengubah seleksi terkunci."""
    comps = data._components(val)
    rng = random.Random(seed)
    status: dict[str, Counter] = {}
    chosen: dict[str, Counter] = {}
    for _ in range(n_boot):
        grid = stage_grid([r for c in rng.choices(comps, k=len(comps)) for r in c], configs)
        for name, v in select_all(grid, alpha, p95_ms_by_config, latency_rel).items():
            status.setdefault(name, Counter())[v["selection"]["status"]] += 1
            if v["selection"]["chosen"]:
                chosen.setdefault(name, Counter())[v["selection"]["chosen"]] += 1
    share = lambda c: {k: round(n / n_boot, 4) for k, n in c.most_common()}
    return {"status": "EXPLORATORY_POST_TEST_BOOTSTRAP_OF_VALIDATION", "n_boot": n_boot, "seed": seed, "alpha": alpha, "n_units": len(comps),
            "configs": {k: {"status_share": share(status[k]), "chosen_share": share(chosen.get(k, Counter()))} for k in CONFIGS if k in status}}


def alpha_sensitivity(val: list[dict], alphas: tuple[float, ...] = (0.05, 0.10, 0.20),
                      p95_ms_by_config: dict[str, float] | None = None, latency_rel: float = 0.10, configs: tuple[str, ...] = ("C", "D")) -> dict:
    """Seleksi yang sama (R1/R2) pada validation dengan alpha berbeda: menunjukkan seberapa sensitif hasil terhadap batas FAR."""
    grid = stage_grid(val, configs)
    by_id = {r["id"]: r for r in grid}
    out = {}
    for a in alphas:
        out[str(a)] = {}
        for name, v in select_all(grid, a, p95_ms_by_config, latency_rel).items():
            row, entry = by_id.get(v["selection"]["chosen"]), {"status": v["selection"]["status"], "chosen": v["selection"]["chosen"]}
            if row:
                entry |= {"car_R": f"{row['car_R_k']}/{row['car_R_n']}", "far_M": f"{row['far_M_k']}/{row['far_M_n']}"}
            out[str(a)][name] = entry
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
