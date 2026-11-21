"""Skema data dua jalur (Track R / Track M), penjaga kebocoran split, dan pembagian validation/test.

Satu record = satu JAWABAN. Aturan keras (CLAUDE.md): label manusia dikunci SEBELUM skor/route diisi; mutasi wajib
`answer_origin = mutasi_terkontrol`, `pair_id`, `mutation_family`, `anchor_page_opposite`; semua record satu `group_id`
dan satu `evidence_group` berada di split yang sama (komponen terhubung, bukan hanya kolom tunggal).
"""

from __future__ import annotations

import hashlib

TRACKS = ("R", "M")
ORIGINS = ("original_llm", "mutasi_terkontrol")
LABELS = ("LAYAK", "TIDAK_LAYAK", "INSUFFICIENT_EVIDENCE")
REQUIRED = ("answer_id", "case_id", "group_id", "evidence_group", "track", "answer_origin", "answer", "kind")


def check_record(r: dict) -> list[str]:
    rid, p = r.get("answer_id", "?"), []
    for k in REQUIRED:
        if r.get(k) in (None, ""):
            p.append(f"{rid}: field wajib kosong: {k}")
    if r.get("track") not in TRACKS:
        p.append(f"{rid}: track harus R atau M")
    if r.get("answer_origin") not in ORIGINS:
        p.append(f"{rid}: answer_origin tidak valid")
    if (r.get("track") == "M") != (r.get("answer_origin") == "mutasi_terkontrol"):
        p.append(f"{rid}: track M <-> mutasi_terkontrol harus berpasangan (satu record, satu track)")
    if r.get("answer_origin") == "mutasi_terkontrol":
        for k in ("pair_id", "mutation_family", "anchor_page_opposite", "mutated_from_answer_id"):
            if r.get(k) in (None, ""):
                p.append(f"{rid}: mutasi wajib {k}")
        if r.get("label") not in (None, "TIDAK_LAYAK"):
            p.append(f"{rid}: label mutasi harus TIDAK_LAYAK secara konstruksi")
    label = r.get("label")
    if label is not None and label not in LABELS:
        p.append(f"{rid}: label tidak valid: {label}")
    if r.get("route") is not None or r.get("H") is not None:
        if not r.get("manual_label_locked") or label is None:
            p.append(f"{rid}: route/skor terisi sebelum label manusia dikunci")
    if r.get("manual_label_locked") and label is None:
        p.append(f"{rid}: manual_label_locked tanpa label")
    return p


def validate_records(rows: list[dict]) -> list[str]:
    p = [x for r in rows for x in check_record(r)]
    ids = [r.get("answer_id") for r in rows]
    if len(ids) != len(set(ids)):
        p.append("answer_id ganda")
    by_id = {r.get("answer_id"): r for r in rows}
    for r in rows:
        if r.get("answer_origin") == "mutasi_terkontrol":
            src = by_id.get(r.get("mutated_from_answer_id"))
            if src is None:
                p.append(f"{r['answer_id']}: mutated_from_answer_id tidak ada")
            elif src.get("answer_origin") != "original_llm" or src.get("label") != "LAYAK":
                p.append(f"{r['answer_id']}: mutasi harus berasal dari jawaban asli berlabel LAYAK")
            elif src.get("group_id") != r.get("group_id"):
                p.append(f"{r['answer_id']}: mutasi harus satu group_id dengan jawaban asalnya")
    return p


def _components(rows: list[dict]) -> list[list[dict]]:
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for r in rows:
        union("g:" + r["group_id"], "e:" + r["evidence_group"])
    comps: dict[str, list[dict]] = {}
    for r in rows:
        comps.setdefault(find("g:" + r["group_id"]), []).append(r)
    return list(comps.values())


def assign_splits(rows: list[dict], seed: str, validation_fraction: float = 0.7) -> dict[str, str]:
    """{answer_id: 'validation'|'test'} deterministik. Komponen terhubung (group_id U evidence_group) tak pernah terbelah.
    Tidak terstratifikasi menurut label: periksa `split_report` — test tanpa TIDAK_LAYAK membuat FAR test tak terdefinisi."""
    comps = _components(rows)
    comps.sort(key=lambda c: hashlib.sha256(f"{seed}:{min(r['group_id'] for r in c)}".encode()).hexdigest())
    n_total, out, n_val = len(rows), {}, 0
    for c in comps:
        split = "validation" if n_val < validation_fraction * n_total else "test"
        for r in c:
            out[r["answer_id"]] = split
        if split == "validation":
            n_val += len(c)
    return out


def check_split_leak(rows: list[dict], splits: dict[str, str]) -> list[str]:
    p = []
    for key in ("group_id", "evidence_group"):
        seen: dict[str, set] = {}
        for r in rows:
            seen.setdefault(r[key], set()).add(splits[r["answer_id"]])
        p += [f"kebocoran {key}={k}: {sorted(v)}" for k, v in seen.items() if len(v) > 1]
    return p


def split_report(rows: list[dict], splits: dict[str, str]) -> dict:
    rep = {}
    for s in ("validation", "test"):
        sub = [r for r in rows if splits[r["answer_id"]] == s]
        rep[s] = {"n": len(sub), "LAYAK": sum(r.get("label") == "LAYAK" for r in sub),
                  "TIDAK_LAYAK": sum(r.get("label") == "TIDAK_LAYAK" for r in sub),
                  "warning": "tanpa TIDAK_LAYAK: FAR tak terdefinisi" if not any(r.get("label") == "TIDAK_LAYAK" for r in sub) else None}
    return rep
