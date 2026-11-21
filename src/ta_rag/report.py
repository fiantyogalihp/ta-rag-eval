"""Tabel dan grafik naskah dari HASIL yang sudah ada (selection.json, test_result.json, stage_*.csv, per_case.csv). Tidak menghitung ulang
seleksi atau metrik: hanya memformat, jadi tidak ada angka baru yang lahir di sini.

    python -m ta_rag.report --results data/results --cases data/cases/questions_draft.jsonl --labels data/labels/labels_all.jsonl \
        --latency data/results/latency.json --out data/results/report

Keluaran: table11 (Panduan Tabel 11, test, Track R dan M terpisah), table12 (60 baris grid validation), fig_stage_A/B.png,
confusion_test.md, kasus_tabel14.md (aturan D16: kasus pertama menurut answer_id per kategori).
Studi 2 (test_result.json memuat `clustered`): table11_klaster (gabungan lari, CI bootstrap klaster), per_lari (rata-rata dan rentang antar-lari),
hipotesis (H1-H3 pra-registrasi + H4 deskriptif).
Rincian deskriptif bila hasil memuatnya: table11_jenis (FAR Track R menurut jenis TIDAK_LAYAK, abstain vs jawaban_salah) dan bagian "Sensitivitas tingkat
kutipan" di stage2.md; hasil lama tanpa kunci itu menghasilkan berkas yang sama seperti sebelumnya.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import metrics as M
from .sweep import LATENCY_KEY

UNDEFINED = "tidak terdefinisi (n=0)"
CATEGORIES = {
    "benar_ACCEPT": ("LAYAK", ("ACCEPT",), "Jawaban layak yang diterima (ACCEPT)"),
    "salah_tertahan": ("TIDAK_LAYAK", ("REVIEW", "REJECT"), "Jawaban tidak layak yang ditahan (REVIEW/REJECT)"),
    "salah_tetap_ACCEPT": ("TIDAK_LAYAK", ("ACCEPT",), "Jawaban tidak layak yang tetap diterima (ACCEPT)"),
}


def fmt_rate(r: dict) -> str:
    if not r.get("defined", r.get("n", 0) > 0):
        return UNDEFINED
    ci = f"[{100 * r['lo']:.1f}–{100 * r['hi']:.1f}]" if r.get("lo") is not None else "[CI tidak dihitung: klaster < 2]"
    return f"{r['k']}/{r['n']} = {100 * r['point']:.1f}% {ci}" + ("†" if r.get("ci_fallback") else "")


def _csv_rate(row: dict, prefix: str) -> dict:
    n = int(row[f"{prefix}_n"] or 0)
    if n == 0:
        return {"defined": False, "n": 0}
    return {"defined": True, "k": int(row[f"{prefix}_k"]), "n": n, "point": float(row[prefix]), "lo": float(row[f"{prefix}_lo95"]), "hi": float(row[f"{prefix}_hi95"])}


def _read_csv(p) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(rows: list[dict], p) -> None:
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _md_table(rows: list[dict]) -> str:
    cols = list(rows[0])
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"] + ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]) + "\n"


def _jsonl(p) -> list[dict]:
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def claim_prefix(template: str, relabel: dict | None) -> str:
    if not relabel:
        return template.format(pct="X", n="\u2026")  # relabel belum ada: slot dibiarkan terlihat
    return template.format(pct=f"{relabel['pct']:g}".replace(".", ","), n=relabel["n"])


def _p95(p95: dict, name: str) -> str:
    if name in p95:
        return f"{p95[name]:.2f}"
    key = LATENCY_KEY[name]  # latency lama hanya mengukur A/C/D: tandai sebagai proksi, jangan disamarkan
    return f"{p95[key]:.2f} (proksi {key})" if key in p95 else "-"


def _point_rate(g: dict, col: str, n_col: str) -> dict:
    n = int(g[n_col] or 0)
    return M.rate(round(float(g[col]) * n), n) if n else {"defined": False, "n": 0}


def _weights(w: float) -> str:
    return f"{round(w * 100)}:{round((1 - w) * 100)}"  # semantic : lexical


def _bobot(config: str | None, w_s: float) -> str:
    return "BERTScore F1" if config == "F" else _weights(w_s)


def table11(test: dict, latency: dict | None) -> list[dict]:
    p95 = (latency or {}).get("p95_ms_by_config", {})
    rows = []
    for name, c in test["configs"].items():
        if c.get("params") is None:
            rows.append({"konfigurasi": name, "bobot_SL": "-", "threshold": "-", "car_R": c["status"], "far_R": "-", "far_M": "-", "review_R": "-", "reject_R": "-",
                         "false_rejection_R": "-", "p95_ms": "-", "status": c["status"]})
            continue
        prm, r, m = c["params"], c["R"], c["M"]
        rows.append({"konfigurasi": name, "bobot_SL": _bobot(prm.get("config"), prm["w_s"]), "threshold": prm["accept"], "car_R": fmt_rate(r["CAR"]), "far_R": fmt_rate(r["FAR"]),
                     "far_M": fmt_rate(m["FAR"]), "review_R": fmt_rate(r["review_rate"]), "reject_R": fmt_rate(r["reject_rate"]),
                     "false_rejection_R": fmt_rate(r["false_rejection"]), "p95_ms": _p95(p95, name),
                     "status": c["status"] + (f"; {c['selection_warning']}" if c.get("selection_warning") else "")})
    return rows


def table12(grid: list[dict], alpha: float) -> list[dict]:
    out = []
    for g in grid:
        far = _csv_rate(g, "far_M")
        lolos = UNDEFINED if not far["defined"] else ("ya" if far["point"] <= alpha else "tidak")
        out.append({"id": g["id"], "config": g["config"], "bobot_SL": _bobot(g["config"], float(g["w_s"])), "threshold": g["accept"], "car_R": fmt_rate(_csv_rate(g, "car_R")),
                    "far_M": fmt_rate(far), "far_R": fmt_rate(_csv_rate(g, "far_R")), "review_R": fmt_rate(_point_rate(g, "review_rate_R", "n_R")),
                    "reject_R": fmt_rate(_point_rate(g, "reject_rate_R", "n_R")), "lolos_batas_FAR": lolos})
    return out


MIN_CLUSTERS_WARN = 10  # shortcut: ambang heuristik; bootstrap persentil tak andal pada klaster sedikit, ganti bila ada rujukan yang lebih tegas
FEW_CLUSTERS = f"klaster < {MIN_CLUSTERS_WARN}: CI bootstrap tidak andal"


def _spread(sp: dict) -> str:
    return UNDEFINED if not sp["defined"] else f"{100 * sp['mean']:.1f}% [{100 * sp['min']:.1f}–{100 * sp['max']:.1f}] ({sp['n_runs']} lari)"


def table_klaster(test: dict) -> list[dict]:
    """Tabel 11 untuk A-F pada gabungan lari: analisis utama Studi 2 (CI bootstrap klaster pertanyaan). Track R dan M di kolom terpisah."""
    rows = []
    for name, c in test["clustered"]["configs"].items():
        prm, r, m = test["configs"][name]["params"], c["pooled"]["R"], c["pooled"]["M"]
        rows.append({"konfigurasi": name, "bobot_SL": _bobot(prm.get("config"), prm["w_s"]), "threshold": prm["accept"], "car_R": fmt_rate(r["CAR"]), "far_R": fmt_rate(r["FAR"]),
                     "review_R": fmt_rate(r["review_rate"]), "reject_R": fmt_rate(r["reject_rate"]), "false_rejection_R": fmt_rate(r["false_rejection"]),
                     "far_M": fmt_rate(m["FAR"]), "review_M": fmt_rate(m["review_rate"]), "reject_M": fmt_rate(m["reject_rate"])})
    return rows


def table_far_jenis(test: dict) -> list[dict]:
    """Track R pada Tabel 11 dirinci menurut jenis jawaban TIDAK_LAYAK: FAR abstain dan FAR jawaban_salah di samping FAR gabungan. Studi 2: gabungan lari dengan
    CI bootstrap klaster (seperti `table_klaster`), selain itu Clopper-Pearson. [] bila hasil tak memuat `R_far_by_type` (berkas lama)."""
    cl = (test.get("clustered") or {}).get("configs", {})
    rows, ada = [], False
    for name, c in test["configs"].items():
        if c.get("params") is None:  # tidak dievaluasi: tampilkan statusnya, jangan hilang diam-diam
            rows.append({"konfigurasi": name, "far_R": c["status"], "far_R_abstain": "-", "far_R_jawaban_salah": "-", "catatan": ""})
            continue
        src = cl[name]["pooled"] if name in cl else c
        if "R_far_by_type" not in src:
            continue
        ada, t = True, src["R_far_by_type"]
        rows.append({"konfigurasi": name, "far_R": fmt_rate(src["R"]["FAR"]), "far_R_abstain": fmt_rate(t["abstain"]), "far_R_jawaban_salah": fmt_rate(t["jawaban_salah"]),
                     "catatan": "; ".join(f"{k}: {FEW_CLUSTERS}" for k, r in t.items() if r.get("n_clusters", MIN_CLUSTERS_WARN) < MIN_CLUSTERS_WARN)})
    return rows if ada else []


def table_per_lari(test: dict) -> list[dict]:
    """Track R per lari (Clopper-Pearson, hitungan satu lari) lalu rata-rata [rentang] antar-lari (catatan panduan 6a). Track M tidak punya baris per lari."""
    cols = (("car_R", "CAR"), ("far_R", "FAR"), ("review_R", "review_rate"), ("reject_R", "reject_rate"))
    rows = []
    for name, c in test["clustered"]["configs"].items():
        rows += [{"konfigurasi": name, "lari": run, "n_R": s["n"], **{col: fmt_rate(s[m]) for col, m in cols}} for run, s in c["per_run"].items()]
        rows.append({"konfigurasi": name, "lari": "rata-rata [rentang]", "n_R": "-", **{col: _spread(c["spread"][m]) for col, m in cols}})
    return rows


def hypothesis_rows(hyp: dict) -> list[dict]:
    pp = lambda x: f"{100 * x:+.1f}"
    rows = []
    for h, v in hyp.items():
        row = {"hipotesis": h, "perbandingan": f"{v['outcome']}: {v['higher']} vs {v['lower']}; " + (", ".join(v["families"]) if v["families"] else "semua mutasi"),
               "n_mutasi": v.get("n", "-"), "n_klaster": "-", "selisih_poin": "-", "ci_bootstrap_klaster": "-", "diskordan_b_c": "-", "mcnemar_p_info": "-",
               "putusan": v["verdict"], "catatan": ""}
        if "diff" in v:
            bonf = 1 - v["level"]  # ambang Bonferroni yang sama dengan level CI
            notes = [FEW_CLUSTERS] * (v["n_clusters"] < MIN_CLUSTERS_WARN) + ["CI berlebar nol (semua klaster searah): bukan ukuran ketidakpastian"] * bool(v.get("degenerate"))
            if v["verdict"] == "TERDUKUNG" and v["mcnemar_p"] > bonf:
                notes.append(f"McNemar eksak p={v['mcnemar_p']:.4f} > {bonf:.4f}: aturan umum klaim 'lebih akurat/aman' belum terpenuhi")
            row |= {"n_klaster": v["n_clusters"], "selisih_poin": pp(v["diff"]), "diskordan_b_c": "/".join(map(str, v["discordant"])), "mcnemar_p_info": f"{v['mcnemar_p']:.4f}",
                    "ci_bootstrap_klaster": f"[{pp(v['lo'])}; {pp(v['hi'])}]" if v["lo"] is not None else "tidak dihitung", "catatan": "; ".join(notes)}
        rows.append(row)
    return rows


def hypotheses_md(cl: dict, prefix: str) -> str:
    hyp = cl["hypotheses"]
    ev = next((v for v in hyp.values() if "level" in v), None)
    rule = (f"Putusan pra-registrasi: TERDUKUNG hanya bila CI bootstrap klaster {str(round(100 * ev['level'], 1)).replace('.', ',')}% (koreksi Bonferroni) atas selisih berpasangan "
            f"tidak memuat 0 DAN selisih ≥ {round(100 * ev['min_diff'])} poin persentase; selain itu tidak ada bukti perbedaan. Arah berlawanan dilaporkan sebagai temuan.\n\n"
            if ev else "Tidak ada hipotesis yang dapat dievaluasi.\n\n")
    d = cl["configs"].get("D")
    h4 = ("D tidak dievaluasi (tanpa parameter beku)." if d is None else
          f"D, gabungan lari, CI bootstrap klaster: CAR Track R = {fmt_rate(d['pooled']['R']['CAR'])}; REVIEW rate Track R = {fmt_rate(d['pooled']['R']['review_rate'])}.")
    return (f"# Hipotesis pra-registrasi H1–H3 (split test, Track M, selisih berpasangan per mutasi, klaster = pertanyaan)\n\nSetiap klaim diawali: \"{prefix}\"\n\n{rule}"
            + _md_table(hypothesis_rows(hyp)) + f"\nMcNemar eksak hanya informasi: ia memperlakukan mutasi sebagai independen dan tidak menentukan putusan.\n\n**H4 (deskriptif, tanpa uji).** {h4}\n")


def _method(cl: dict) -> str:
    return next((r["interval"] for c in cl["configs"].values() for r in c["pooled"]["R"].values() if isinstance(r, dict) and r.get("interval", "").startswith("bootstrap")), "bootstrap persentil 95% atas klaster pertanyaan")


def family_rows(per_case: list[dict], labels: dict) -> list[dict]:
    """Track M per family mutasi dan split: jumlah ACCEPT/REVIEW/REJECT tiap konfigurasi (parameter beku). Deskriptif pasca-test."""
    cfgs = [c[len("route_"):] for c in (per_case[0] if per_case else {}) if c.startswith("route_")]
    groups: dict[tuple, list] = {}
    for r in per_case:
        if r["track"] == "M":
            groups.setdefault((labels.get(r["answer_id"], {}).get("mutation_family", "?"), r["split"]), []).append(r)
    out = []
    for (fam, split), rows in sorted(groups.items()):
        routes = {c: [x[f"route_{c}"] for x in rows] for c in cfgs}
        out.append({"family": fam, "split": split, "n": len(rows), **{c: "/".join(str(v.count(k)) for k in ("ACCEPT", "REVIEW", "REJECT")) for c, v in routes.items()}})
    return out


S2_GROUPS = ("all", "answerable", "probe")


def _s2_row(name: str, grp: str, s: dict, **extra) -> dict:
    return {"konfigurasi": name, **extra, "kelompok": grp, "n": s["n"], "car": fmt_rate(s["CAR"]), "far": fmt_rate(s["FAR"]),
            "review": fmt_rate(s["review_rate"]), "reject": fmt_rate(s["reject_rate"])}


def stage2_rows(stage2: dict) -> list[dict]:
    rows = []
    for name, c in stage2["configs"].items():
        if c.get("params") is None:  # tidak diterapkan: tampilkan statusnya, jangan hilang diam-diam
            rows.append({"konfigurasi": name, "kelompok": "-", "n": "-", "car": c["status"], "far": "-", "review": "-", "reject": "-"})
        else:
            rows += [_s2_row(name, grp, c[grp]) for grp in S2_GROUPS]
    return rows


def stage2_klaster_rows(stage2: dict) -> list[dict]:
    """Tahap II Studi 2, gabungan lari: CI bootstrap klaster pertanyaan (kolom sama dengan `stage2_rows`)."""
    return [_s2_row(name, grp, c["clustered"][grp]) for name, c in stage2["configs"].items() if "clustered" in c for grp in S2_GROUPS]


def stage2_per_lari_rows(stage2: dict) -> list[dict]:
    """Tahap II Studi 2 per lari (Clopper-Pearson atas hitungan satu lari)."""
    return [_s2_row(name, grp, s[grp], lari=run) for name, c in stage2["configs"].items() if "per_run" in c for run, s in c["per_run"].items() for grp in S2_GROUPS]


def stage2_sensitivity_rows(stage2: dict) -> list[dict]:
    """Tahap II, kelompok berjawab: label primer (tingkat halaman, `retrieval_ok`) berdampingan dengan label sensitivitas tingkat kutipan; kolom sama dengan
    `stage2_rows`. Studi 2: gabungan lari dengan CI bootstrap klaster. [] bila hasil tak memuat blok sensitivitas (berkas lama)."""
    sens = stage2.get("sensitivity_quote_level")
    pick = lambda c: c["clustered"]["answerable"] if "clustered" in c else c["answerable"]
    return [_s2_row(name, "answerable", pick(cfg), dasar_label=basis) for name, c in stage2["configs"].items() if sens and c.get("params") is not None
            for basis, cfg in (("halaman (primer)", c), ("kutipan (sensitivitas)", sens["configs"][name]))]


def score_means(scored: list[dict]) -> dict:
    """Rerata L dan S jawaban asli pertanyaan berjawab: membandingkan evidence oracle (Tahap I) dengan konteks retrieval (Tahap II)."""
    xs = [s for s in scored if s.get("track", "R") == "R" and s.get("kind") == "answerable"]
    return {"n": len(xs), "L": round(sum(s["L"] for s in xs) / len(xs), 3), "S": round(sum(s["S"] for s in xs) / len(xs), 3)} if xs else {"n": 0}


def confusion_md(test: dict) -> str:
    out = ["# Confusion matrix pada split test (label manusia x keputusan evaluator), Track R dan M terpisah\n"]
    for name, c in test["configs"].items():
        if c.get("params") is None:
            out.append(f"## {name}: {c['status']}\n")
            continue
        for tr in ("R", "M"):
            cm = c[tr]["confusion"]
            out.append(f"## {name} — Track {tr}\n")
            out.append(_md_table([{"label": lab, **cm[lab], "total": sum(cm[lab].values())} for lab in ("LAYAK", "TIDAK_LAYAK")]))
    return "\n".join(out)


def pick_cases(per_case: list[dict], cfg: str = "D") -> dict:
    """D16: kasus pertama menurut answer_id per kategori; split test dulu, lalu validation (ditandai), kalau tidak ada: jumlah yang dicari."""
    col, out = f"route_{cfg}", {}
    for key, (label, routes, _) in CATEGORIES.items():
        hits = sorted((r for r in per_case if r["label"] == label and r.get(col) in routes), key=lambda r: r["answer_id"])
        test = [r for r in hits if r["split"] == "test"]
        val = [r for r in hits if r["split"] != "test"]
        row, source = (test[0], "test") if test else ((val[0], "validation (cadangan)") if val else (None, None))
        out[key] = {"row": row, "source": source, "searched": sum(1 for r in per_case if r["label"] == label)}
    return out


def cases_md(picks: dict, test: dict, cases: dict, labels: dict, cfg: str = "D", extra: bool = False) -> str:
    prm = (test["configs"].get(cfg) or {}).get("params")
    note = " — tambahan, tidak dipra-registrasi (aturan D16 yang sama dipakai pada konfigurasi ini)" if extra else ""
    out = [f"# Kasus format Tabel 14 (konfigurasi {cfg}; aturan D16: kasus pertama menurut answer_id){note}\n",
           f"Parameter {cfg}: " + (f"bobot S:L {_weights(prm['w_s'])}, threshold ACCEPT {prm['accept']}, hard-fail {prm['hard_fail']}\n" if prm else "tidak dievaluasi\n")]
    for key, (label, routes, title) in CATEGORIES.items():
        p = picks[key]
        out.append(f"## {title}\n")
        if p["row"] is None:
            out.append(f"Tidak ditemukan. Jumlah jawaban berlabel {label} yang diperiksa: {p['searched']} (test + validation). Ini hasil pencarian, bukan klaim bebas kesalahan.\n")
            continue
        r = p["row"]
        c, lab = cases.get(r["case_id"], {}), labels.get(r["answer_id"], {})
        match = "cocok" if (r["label"] == "LAYAK") == (r[f"route_{cfg}"] == "ACCEPT") else "tidak cocok"
        out += [f"- Sumber kasus: {p['source']}; answer_id `{r['answer_id']}`; case_id `{r['case_id']}`; Track {r['track']}",
                f"- Pertanyaan: {c.get('question', '(tidak ada di berkas kasus)')}",
                f"- Sumber resmi: {c.get('source_doc_id')} hlm. {c.get('source_page')}; kutipan: \"{c.get('source_quote')}\"",
                f"- Retrieved chunk_ids: {lab.get('chunk_ids') or '(mutasi: tidak melalui retrieval)'}",
                f"- Jawaban ({'mutasi_terkontrol' if lab.get('answer_origin') == 'mutasi_terkontrol' else 'original_llm'}): {lab.get('answer')}",
                f"- Label manual: {r['label']}; validator {lab.get('validator')}; dilabeli {lab.get('labeled_at')}",
                f"- Skor: L={float(r['L']):.3f}, S={float(r['S']):.3f}, H_{cfg}={r.get(f'H_{cfg}')}; flags: {r.get(f'flags_{cfg}') or '-'}",
                f"- Keputusan: {r[f'route_{cfg}']} ({match} dengan label manual)\n"]
    return "\n".join(out)


def series_ci(rows: list[dict], xkey: str, scale: float) -> dict:
    """Deret CAR (Track R) dan FAR (Track M) dalam persen beserta batas CI 95%; NaN bila tak terdefinisi (bukan 0)."""
    pct = lambda col: [float(r[col]) * 100 if r[col] not in ("", None) else float("nan") for r in rows]
    return {"xs": [float(r[xkey]) * scale for r in rows], "car": pct("car_R"), "car_lo": pct("car_R_lo95"), "car_hi": pct("car_R_hi95"),
            "far": pct("far_M"), "far_lo": pct("far_M_lo95"), "far_hi": pct("far_M_hi95")}


def figures(stage_a: list[dict], stage_b: list[dict], out_dir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for rows, xkey, scale, xlabel, title, name in ((stage_a, "w_s", 100, "Bobot semantic (%)", "Tahap A: bobot semantic, ACCEPT 0,78 (validation)", "fig_stage_A.png"),
                                                   (stage_b, "accept", 100, "Threshold ACCEPT (%)", "Tahap B: threshold, bobot 60:40 (validation)", "fig_stage_B.png")):
        s = series_ci(rows, xkey, scale)
        fig, ax = plt.subplots(figsize=(6.2, 3.2))
        for key, label, color in (("car", "CAR (Track R)", "#1f77b4"), ("far", "FAR (Track M)", "#d62728")):
            ax.plot(s["xs"], s[key], label=f"{label}; pita = CI 95%", color=color)
            ax.fill_between(s["xs"], s[f"{key}_lo"], s[f"{key}_hi"], color=color, alpha=0.15, linewidth=0)
        ax.set_xlabel(xlabel); ax.set_ylabel("%"); ax.set_title(title, fontsize=9); ax.set_ylim(-3, 103); ax.legend(fontsize=8); ax.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(out_dir / name, dpi=200); plt.close(fig)


def build_report(results_dir, cases_path, labels_path, out_dir, latency_path=None, relabel_path=None) -> dict:
    res, out = Path(results_dir) / "I", Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    test = json.loads((res / "test_result.json").read_text(encoding="utf-8"))
    sel = json.loads((res / "selection.json").read_text(encoding="utf-8"))
    latency = json.loads(Path(latency_path).read_text(encoding="utf-8")) if latency_path else None
    prefix = claim_prefix(test["claim_prefix_required"], json.loads(Path(relabel_path).read_text(encoding="utf-8")) if relabel_path else None)
    t11 = table11(test, latency)
    _write_csv(t11, out / "table11.csv")
    cl = test.get("clustered")
    caution = "**Studi 2:** Clopper–Pearson pada hitungan gabungan lari menganggap jawaban independen, jadi terlalu sempit; analisis utama = `table11_klaster.md`.\n\n" if cl else ""
    (out / "table11.md").write_text(f"# Tabel 11 (split test, parameter beku; Track R dan M TIDAK digabung)\n\nSetiap klaim diawali: \"{prefix}\"\n\n"
                                    f"n test: {test['n_test_by_track']}. Interval: Clopper–Pearson dua sisi 95%.\n\n{caution}" + _md_table(t11), encoding="utf-8")
    if cl:
        tk, tl = table_klaster(test), table_per_lari(test)
        _write_csv(tk, out / "table11_klaster.csv")
        _write_csv(tl, out / "per_lari.csv")
        head = f"Setiap klaim diawali: \"{prefix}\"\n\nLari: {', '.join(cl['runs'])}. Track R dan M TIDAK digabung. "
        (out / "table11_klaster.md").write_text(f"# Tabel 11 gabungan lari (split test, parameter beku; analisis utama Studi 2)\n\n{head}Interval: {_method(cl)}; klaster = pertanyaan. † = bootstrap berlebar nol (semua klaster searah), diganti Clopper–Pearson atas jumlah klaster.\n\n" + _md_table(tk), encoding="utf-8")
        (out / "per_lari.md").write_text(f"# Track R per lari (split test, parameter beku)\n\n{head}Per lari: Clopper–Pearson dua sisi 95% atas hitungan satu lari; "
                                         "rata-rata tak berbobot dan rentang (min–maks) dari titik per lari. Track M tidak punya baris per lari: mutasi dibuat dari lari primer.\n\n" + _md_table(tl), encoding="utf-8")
        if cl.get("hypotheses"):
            (out / "hipotesis.md").write_text(hypotheses_md(cl, prefix), encoding="utf-8")
    if (tj := table_far_jenis(test)):
        _write_csv(tj, out / "table11_jenis.csv")
        method = (f"{_method(cl)}; klaster = pertanyaan; † = bootstrap berlebar nol (semua klaster searah), diganti Clopper–Pearson atas jumlah klaster" if cl
                  else "Clopper–Pearson dua sisi 95%")
        (out / "table11_jenis.md").write_text(
            f"# Tabel 11, Track R: FAR menurut jenis jawaban TIDAK_LAYAK (split test, parameter beku; rincian deskriptif)\n\nSetiap klaim diawali: \"{prefix}\"\n\n"
            "FAR = bagian jawaban TIDAK_LAYAK yang tetap diterima (ACCEPT). `abstain` = jawaban berjawab yang abstain (kolom `abstain` pada lembar label); `jawaban_salah` = TIDAK_LAYAK lainnya. "
            "Pembilang dan penyebut kedua jenis berjumlah sama dengan `far_R` (FAR Tabel 11); Track M tidak ikut. "
            f"Interval: {method}. Rincian ini tidak mengubah FAR Tabel 11 dan tidak dipakai memilih apa pun.\n\n" + _md_table(tj), encoding="utf-8")
    t12 = table12(_read_csv(res / "stage_C.csv"), sel["alpha"])
    _write_csv(t12, out / "table12.csv")
    (out / "table12.md").write_text(f"# Tabel 12 (validation, satu baris per kombinasi; batas FAR_M alpha={sel['alpha']})\n\n" + _md_table(t12), encoding="utf-8")
    figures(_read_csv(res / "stage_A.csv"), _read_csv(res / "stage_B.csv"), out)
    (out / "confusion_test.md").write_text(confusion_md(test), encoding="utf-8")
    cases = {c["case_id"]: c for c in _jsonl(cases_path)}
    labels = {r["answer_id"]: r for r in _jsonl(labels_path)}
    per_case = _read_csv(res / "per_case.csv")
    (out / "kasus_tabel14.md").write_text(cases_md(pick_cases(per_case, "D"), test, cases, labels, "D"), encoding="utf-8")
    (out / "kasus_tabel14_B.md").write_text(cases_md(pick_cases(per_case, "B"), test, cases, labels, "B", extra=True), encoding="utf-8")
    fam = family_rows(per_case, labels)
    if fam:
        _write_csv(fam, out / "family_mutasi.csv")
        (out / "family_mutasi.md").write_text("# Track M per family mutasi (ACCEPT/REVIEW/REJECT; parameter beku; deskriptif pasca-test)\n\n"
                                              "Validation dipakai memilih parameter, jadi baris validation optimistis; baris test adalah uji sekali.\n\n"
                                              + _md_table(fam), encoding="utf-8")
    s2 = Path(results_dir) / "II" / "stage2_result.json"
    if s2.exists():
        stage2 = json.loads(s2.read_text(encoding="utf-8"))
        rows = stage2_rows(stage2)
        means = {st: score_means(_jsonl(Path(results_dir) / f"scored_{st}.jsonl")) for st in ("I", "II") if (Path(results_dir) / f"scored_{st}.jsonl").exists()}
        text = ("# Tahap II (deskriptif; parameter beku tahap I; konteks hasil retrieval)\n\n" + _md_table(rows)
                + "\nRerata skor jawaban asli berjawab: " + "; ".join(f"Tahap {k}: n={v.get('n')}, L={v.get('L')}, S={v.get('S')}" for k, v in means.items()) + "\n")
        if (kl := stage2_klaster_rows(stage2)):
            text += ("\n**Studi 2:** tabel di atas memakai Clopper–Pearson pada hitungan gabungan lari, yang terlalu sempit. Gunakan tabel gabungan klaster dan tabel per lari berikut "
                     "(Tahap II tetap deskriptif: tanpa seleksi, tanpa test).\n\n## Gabungan lari (CI bootstrap klaster pertanyaan)\n\n" + _md_table(kl)
                     + "\n## Per lari (Clopper–Pearson per lari)\n\n" + _md_table(stage2_per_lari_rows(stage2)))
        if (sn := stage2_sensitivity_rows(stage2)):
            sq = stage2["sensitivity_quote_level"]
            text += (f"\n## Sensitivitas tingkat kutipan (deskriptif; kelompok berjawab)\n\n{sq['definition']}\n\n"
                     f"Label berbeda dari label primer: {len(sq['flipped_answer_ids'])} jawaban ({', '.join(sq['flipped_answer_ids']) or '-'}). "
                     "Baris `halaman (primer)` mengulang angka tabel primer (Studi 2: tabel gabungan klaster); Tahap II tetap deskriptif.\n\n" + _md_table(sn))
        (out / "stage2.md").write_text(text, encoding="utf-8")
    return {"table11_rows": len(t11), "table12_rows": len(t12), "out": str(out)}


def main(argv=None) -> int:  # pragma: no cover - perekat tipis
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="data/results"); ap.add_argument("--cases", required=True); ap.add_argument("--labels", required=True)
    ap.add_argument("--latency"); ap.add_argument("--relabel", help="relabel_result.json untuk mengisi awalan klaim"); ap.add_argument("--out", default="data/results/report")
    a = ap.parse_args(argv)
    print(json.dumps(build_report(a.results, a.cases, a.labels, a.out, a.latency, a.relabel), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
