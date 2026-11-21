"""Metrik, interval, dan uji berpasangan. Python murni + stdlib (tanpa scipy).

Aturan (CLAUDE.md 7): setiap rasio = pembilang/penyebut + Clopper-Pearson; FAR tak terdefinisi bila tak ada TIDAK_LAYAK
(JANGAN 0%); REVIEW dan REJECT dilaporkan terpisah.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

LAYAK, TIDAK = "LAYAK", "TIDAK_LAYAK"


def _binom_cdf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(0, k + 1))


def _bisect(f, lo=0.0, hi=1.0, it=200):
    for _ in range(it):
        mid = (lo + hi) / 2
        if f(mid):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


@lru_cache(maxsize=None)  # murni; bootstrap/sweep mengulang pasangan (k, n) yang sama ribuan kali
def clopper_pearson(k: int, n: int, level: float = 0.95, two_sided: bool = True) -> tuple[float, float]:
    """Interval eksak. Dua sisi: alpha/2 di tiap ekor. Satu sisi: batas ATAS dengan alpha penuh (batas bawah = 0)
    untuk memudahkan pelaporan "batas atas FAR"; lihat `clopper_pearson_one_sided_upper`."""
    if n <= 0:
        raise ValueError("n harus > 0 (metrik tak terdefinisi)")
    if not 0 <= k <= n:
        raise ValueError("k di luar [0,n]")
    a = (1 - level) / (2 if two_sided else 1)
    lo = 0.0 if k == 0 else _bisect(lambda p: 1 - _binom_cdf(k - 1, n, p) >= a)
    hi = 1.0 if k == n else _bisect(lambda p: _binom_cdf(k, n, p) <= a)
    return (lo if two_sided else 0.0), hi


def rate(k: int, n: int, level: float = 0.95, two_sided: bool = True) -> dict:
    """{k, n, point, lo, hi, defined}. n=0 -> tak terdefinisi, TANPA angka 0."""
    if n == 0:
        return {"k": k, "n": 0, "point": None, "lo": None, "hi": None, "defined": False,
                "text": "tidak terdefinisi (n=0)"}
    lo, hi = clopper_pearson(k, n, level, two_sided)
    return {"k": k, "n": n, "point": k / n, "lo": lo, "hi": hi, "defined": True,
            "interval": f"Clopper-Pearson {'dua' if two_sided else 'satu'} sisi {int(level * 100)}%"}


def summarize(rows: list[dict]) -> dict:
    """rows: [{label, route}] -> CAR, FAR, false rejection, REVIEW rate, REJECT rate (semua dengan CI) + matriks."""
    cm = {l: {"ACCEPT": 0, "REVIEW": 0, "REJECT": 0} for l in (LAYAK, TIDAK)}
    for r in rows:
        if r["label"] in cm:
            cm[r["label"]][r["route"]] += 1
    nl, nt = sum(cm[LAYAK].values()), sum(cm[TIDAK].values())
    n = nl + nt
    tot = lambda route: cm[LAYAK][route] + cm[TIDAK][route]
    return {
        "n": n, "confusion": cm,
        "CAR": rate(cm[LAYAK]["ACCEPT"], nl),
        "FAR": rate(cm[TIDAK]["ACCEPT"], nt),
        "false_rejection": rate(cm[LAYAK]["REJECT"], nl),
        "review_rate": rate(tot("REVIEW"), n),
        "reject_rate": rate(tot("REJECT"), n),
    }


def cluster_bootstrap_ci(items: list[tuple[str, float]], n_boot: int = 2000, seed: int = 20261104, level: float = 0.95) -> dict:
    """Rata-rata nilai per record (0/1 untuk rasio; selisih berpasangan juga boleh) dengan CI bootstrap persentil yang me-resample
    KLASTER (pertanyaan), bukan record: lari berulang atas pertanyaan yang sama saling berkorelasi, sehingga Clopper-Pearson pada hitungan
    gabungan terlalu sempit. items = [(id_klaster, nilai)]. Titik = rata-rata gabungan seluruh record."""
    clusters: dict[str, list[float]] = {}
    for cid, v in items:
        clusters.setdefault(cid, []).append(v)
    keys = sorted(clusters)
    if len(keys) < 2:
        raise ValueError("bootstrap per klaster butuh >= 2 klaster")
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        picked = [clusters[k] for k in rng.choices(keys, k=len(keys))]
        means.append(sum(sum(c) for c in picked) / sum(len(c) for c in picked))
    means.sort()
    return {"point": sum(v for _, v in items) / len(items), "lo": means[int((1 - level) / 2 * n_boot)], "hi": means[int((1 + level) / 2 * n_boot) - 1],
            "n": len(items), "n_clusters": len(keys), "method": f"bootstrap persentil {int(level * 100)}%, {n_boot} resample klaster, seed {seed}"}


def cluster_rate(items: list[tuple[str, bool]], n_boot: int = 2000, seed: int = 20261104, level: float = 0.95) -> dict:
    """Seperti `rate`, tetapi CI = bootstrap klaster (pertanyaan). items = [(id_klaster, kena)]. n=0 -> tak terdefinisi (bukan 0);
    < 2 klaster -> titik tanpa CI, karena resample klaster tidak bermakna. Bootstrap persentil berlebar nol (semua klaster searah, mis. 12/12)
    bukan ukuran ketidakpastian: diganti Clopper-Pearson atas jumlah klaster dan ditandai `ci_fallback`."""
    n = len(items)
    if n == 0:
        return {"k": 0, "n": 0, "point": None, "lo": None, "hi": None, "defined": False, "text": "tidak terdefinisi (n=0)"}
    k, n_cl = sum(bool(h) for _, h in items), len({c for c, _ in items})
    out = {"k": k, "n": n, "point": k / n, "n_clusters": n_cl, "defined": True}
    if n_cl < 2:
        return out | {"lo": None, "hi": None, "interval": "tidak dihitung (klaster < 2)"}
    ci = cluster_bootstrap_ci([(c, float(h)) for c, h in items], n_boot, seed, level)
    if ci["lo"] == ci["hi"]:
        lo, hi = clopper_pearson(round(out["point"] * n_cl), n_cl, level)
        return out | {"lo": lo, "hi": hi, "ci_fallback": True, "interval": f"Clopper-Pearson {int(level * 100)}% atas {n_cl} klaster (bootstrap berlebar nol)"}
    return out | {"lo": ci["lo"], "hi": ci["hi"], "interval": ci["method"]}


def summarize_clustered(rows: list[dict], **kw) -> dict:
    """`summarize` dengan CI bootstrap klaster. rows = [{cluster, label, route}]; matriks dan hitungan sama dengan `summarize`, hanya interval lima rasionya diganti."""
    out = summarize(rows)
    lab = [r for r in rows if r["label"] in (LAYAK, TIDAK)]
    rate_of = lambda route, label=None: cluster_rate([(r["cluster"], r["route"] == route) for r in lab if label is None or r["label"] == label], **kw)
    out.update(CAR=rate_of("ACCEPT", LAYAK), FAR=rate_of("ACCEPT", TIDAK), false_rejection=rate_of("REJECT", LAYAK),
               review_rate=rate_of("REVIEW"), reject_rate=rate_of("REJECT"))
    return out


def run_spread(per_run: dict[str, dict]) -> dict:
    """Rata-rata (tak berbobot) dan rentang titik tiap rasio antar-lari (catatan panduan 6a). per_run = {lari: hasil `summarize`}.
    Lari dengan rasio tak terdefinisi dilewati; n_runs = jumlah lari yang terdefinisi."""
    out = {}
    for m in ("CAR", "FAR", "false_rejection", "review_rate", "reject_rate"):
        xs = [s[m]["point"] for s in per_run.values() if s[m]["defined"]]
        out[m] = {"defined": True, "mean": sum(xs) / len(xs), "min": min(xs), "max": max(xs), "n_runs": len(xs)} if xs else {"defined": False, "n_runs": 0}
    return out


def paired_cluster_diff(items: list[tuple[str, bool, bool]], level: float, min_diff: float, n_boot: int = 2000, seed: int = 20261104) -> dict:
    """Hipotesis berpasangan pra-registrasi (H1-H3): selisih P(a) - P(b) pada input identik, CI bootstrap klaster. items = [(klaster, a, b)].
    TERDUKUNG bila CI sepenuhnya > 0 DAN selisih >= min_diff; ARAH_BERLAWANAN bila CI sepenuhnya < 0 DAN selisih <= -min_diff; selain itu
    TIDAK_ADA_BUKTI_PERBEDAAN. McNemar eksak dilaporkan sebagai informasi (ia memperlakukan mutasi sebagai independen, jadi tidak menentukan putusan)."""
    n = len(items)
    if n == 0:
        return {"n": 0, "verdict": "TIDAK_TERDEFINISI", "text": "tidak terdefinisi (n=0)"}
    b, c = sum(1 for _, x, y in items if x and not y), sum(1 for _, x, y in items if y and not x)
    out = {"n": n, "n_clusters": len({k for k, _, _ in items}), "discordant": (b, c), "mcnemar_p": mcnemar_exact(b, c), "level": level, "min_diff": min_diff}
    if out["n_clusters"] < 2:
        return out | {"diff": (b - c) / n, "lo": None, "hi": None, "verdict": "CI_TIDAK_DAPAT_DIHITUNG"}
    ci = cluster_bootstrap_ci([(k, float(x) - float(y)) for k, x, y in items], n_boot, seed, level)
    verdict = ("TERDUKUNG" if ci["lo"] > 0 and ci["point"] >= min_diff else "ARAH_BERLAWANAN" if ci["hi"] < 0 and ci["point"] <= -min_diff
               else "TIDAK_ADA_BUKTI_PERBEDAAN")
    return out | {"diff": ci["point"], "lo": ci["lo"], "hi": ci["hi"], "degenerate": ci["lo"] == ci["hi"], "verdict": verdict, "interval": ci["method"]}


def percentile(samples: list[float], q: float) -> float:
    """Nearest-rank (q dalam [0,100])."""
    if not samples:
        raise ValueError("sampel kosong")
    s = sorted(samples)
    return s[max(0, math.ceil(q / 100 * len(s)) - 1)]


def latency_stats(samples_ms: list[float], n_boot: int = 1000, seed: int = 20261104) -> dict:
    """p50/p95 + CI bootstrap persentil 95%. Panggil setelah warm-up, >= 100 iterasi (spec §8)."""
    rng = random.Random(seed)
    out = {"n": len(samples_ms), "warning": "kurang dari 100 iterasi" if len(samples_ms) < 100 else None}
    for q in (50, 95):
        boots = sorted(percentile([rng.choice(samples_ms) for _ in samples_ms], q) for _ in range(n_boot))
        out[f"p{q}"] = percentile(samples_ms, q)
        out[f"p{q}_ci95"] = (boots[int(0.025 * n_boot)], boots[min(n_boot - 1, int(0.975 * n_boot))])
    return out


def mcnemar_exact(b: int, c: int) -> float:
    """p dua sisi uji McNemar eksak. b,c = jumlah pasangan diskordan (A benar & B salah; A salah & B benar)."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_diff(correct_a: list[bool], correct_b: list[bool], n_boot: int = 2000, seed: int = 20261104) -> dict:
    """Selisih proporsi benar (A - B) pada input identik: titik, CI bootstrap 95%, McNemar eksak."""
    if len(correct_a) != len(correct_b) or not correct_a:
        raise ValueError("panjang harus sama dan > 0")
    n = len(correct_a)
    d = [int(a) - int(b) for a, b in zip(correct_a, correct_b)]
    rng = random.Random(seed)
    boots = sorted(sum(rng.choice(d) for _ in range(n)) / n for _ in range(n_boot))
    b = sum(1 for a, c in zip(correct_a, correct_b) if a and not c)
    c = sum(1 for a, c_ in zip(correct_a, correct_b) if not a and c_)
    return {"n": n, "diff": sum(d) / n, "ci95": (boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]),
            "discordant": (b, c), "mcnemar_p": mcnemar_exact(b, c)}
