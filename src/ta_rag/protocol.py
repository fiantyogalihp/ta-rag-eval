"""Fungsi murni untuk protokol pra-registrasi (config/protocol.json): seleksi Track M, sampel relabel,
kesepakatan intra-rater, verifikasi mutasi, pemilihan parameter, ringkasan pra-evaluator, dan kunci hash.

Tidak memanggil jaringan dan tidak membaca skor evaluator. Urutan acak memakai SHA256 (bukan `random`)
agar hasil tidak bergantung versi Python.

Berkas label (JSONL) yang dibaca CLI: satu baris per JAWABAN dengan kolom
  answer_id, case_id, kind (answerable|not_in_corpus), origin (natural|mutation), label (LAYAK|TIDAK_LAYAK),
  question_type, source_doc_id [, label2 (hasil relabel)].

    python -m ta_rag.protocol lock
    python -m ta_rag.protocol track-m --labels data/labels/labels.jsonl --cases data/cases/questions_draft.jsonl
    python -m ta_rag.protocol relabel --labels data/labels/labels.jsonl
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .numbers import extract_numbers

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = REPO / "config" / "protocol.json"
LAYAK, TIDAK = "LAYAK", "TIDAK_LAYAK"
FAMILIES = ("numeric_value", "unit", "date", "negation", "clause_deletion")


def load_protocol(path: Path = DEFAULT_PROTOCOL) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _key(seed: str, ident: str) -> str:
    return hashlib.sha256(f"{seed}:{ident}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- Track M

def track_m_order(candidates: list[dict], seed: str) -> list[str]:
    """Urutan kandidat Track M. `candidates` = pertanyaan berjawaban yang jawaban aslinya berlabel LAYAK
    ({case_id, source_doc_id}). Fase 1: per dokumen (urut doc_id) kandidat berkunci terkecil; fase 2: sisanya.
    Tidak bergantung pada urutan input, skor evaluator, atau kemudahan mutasi."""
    ids = [c["case_id"] for c in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("case_id kandidat ganda")
    by_doc: dict[str, list[dict]] = {}
    for c in candidates:
        by_doc.setdefault(c["source_doc_id"], []).append(c)
    first: list[str] = []
    for doc in sorted(by_doc):
        best = min(by_doc[doc], key=lambda c: (_key(seed, c["case_id"]), c["case_id"]))
        first.append(best["case_id"])
    rest = sorted((i for i in ids if i not in first), key=lambda i: (_key(seed, i), i))
    return first + rest


def assign_mutation_families(ordered: list[dict], fam_map: dict[str, list[str]]) -> dict[str, str]:
    """Family mutasi per kandidat, ditetapkan dari urutan Track M (D13), bukan dipilih peneliti. `ordered` = [{case_id, question_type}] dalam
    urutan lembar. numeric_duration bergantian family pertama/kedua (numeric_value, unit, numeric_value, ...); tipe lain: family pertama."""
    out, n_duration = {}, 0
    for c in ordered:
        fams = fam_map[c["question_type"]]
        if c["question_type"] == "numeric_duration":
            out[c["case_id"]] = fams[n_duration % len(fams)]
            n_duration += 1
        else:
            out[c["case_id"]] = fams[0]
    return out


def assign_mutation_slots(ordered: list[dict], fam_map: dict[str, list[str]], k: int) -> dict[str, list[str]]:
    """Studi 2 (D20): k mutasi per jawaban; family slot ke-i = family ke-i untuk jenis pertanyaan itu (peneliti tidak memilih).
    Jenis pertanyaan dengan kurang dari k family adalah galat protokol, bukan alasan melewati."""
    out = {}
    for c in ordered:
        fams = fam_map[c["question_type"]]
        if len(fams) < k:
            raise ValueError(f"{c['question_type']}: hanya {len(fams)} family untuk {k} mutasi per jawaban")
        out[c["case_id"]] = list(fams[:k])
    return out


# ---------------------------------------------------------------- verifikasi mutasi

_UNIT_RE = re.compile(r"\b(hari|minggu|bulan|tahun)\b", re.I)


_NUMBER_WORDS = frozenset({
    "nol", "kosong", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan",
    "sepuluh", "sebelas", "belas", "puluh", "ratus", "seratus", "ribu", "seribu", "juta", "miliar", "milyar",
    "triliun", "koma", "rupiah", "persen",
})
_TOKEN_EDGES = "*_`.,;:!?\"'"


def _mutation_tokens(text: str) -> list[str]:
    """Angka dan terbilang dalam kurung adalah satu unit perubahan menurut protokol."""
    words, result, i = text.split(), [], 0
    while i < len(words):
        end = i
        if extract_numbers(words[i]) and i + 1 < len(words) and words[i + 1].lstrip("*_`").startswith("("):
            for j in range(i + 1, len(words)):
                if ")" not in words[j]:
                    continue
                parenthetical = " ".join(words[i + 1:j + 1]).strip(_TOKEN_EDGES)
                if parenthetical.startswith("(") and parenthetical.endswith(")"):
                    spelled = parenthetical[1:-1].casefold().split()
                    if spelled and all(word in _NUMBER_WORDS for word in spelled):
                        end = j
                break
        result.append(" ".join(words[i:end + 1]))
        i = end + 1
    return result


def verify_mutation(original: str, mutated: str, family: str, anchor_text: str = "") -> list[str]:
    """Pemeriksaan MEKANIS atas satu mutasi. Lolos otomatis != benar-salah secara hukum: peneliti tetap harus
    membuka halaman jangkar yang membuktikan kebalikannya. Daftar kosong = lolos pemeriksaan mekanis."""
    if family not in FAMILIES:
        return [f"family tidak dikenal: {family}"]
    problems: list[str] = []
    if original.strip() == mutated.strip():
        return ["mutasi tidak mengubah apa pun"]
    a, b = _mutation_tokens(original), _mutation_tokens(mutated)
    blocks = [op for op in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op[0] != "equal"]
    if len(blocks) != 1:
        problems.append(f"harus tepat satu blok perubahan berdekatan, ditemukan {len(blocks)}")
    new_nums = extract_numbers(mutated) - extract_numbers(original)
    if family in ("numeric_value", "date"):
        if not new_nums:
            problems.append("tidak ada angka baru pada jawaban mutasi")
        on_page = new_nums & extract_numbers(anchor_text)
        if on_page:
            problems.append(f"angka baru {sorted(on_page)} muncul di halaman jangkar (mungkin kebetulan benar)")
    elif family == "unit":
        if extract_numbers(original) != extract_numbers(mutated):
            problems.append("family unit tidak boleh mengubah angka")
        if [u.lower() for u in _UNIT_RE.findall(original)] == [u.lower() for u in _UNIT_RE.findall(mutated)]:
            problems.append("satuan waktu tidak berubah")
    return problems


# ---------------------------------------------------------------- k run generator

def answer_key(text: str) -> str:
    """Kunci kesamaan jawaban antar-run: NFKC, casefold, spasi dirapatkan, tanda baca ujung dibuang."""
    import unicodedata
    t = " ".join(unicodedata.normalize("NFKC", text or "").split()).casefold()
    return t.strip(" .,;:!?\"'")


def distinct_answers(runs: dict[str, dict[str, str]]) -> dict:
    """runs = {run_id: {case_id: jawaban}}. Mengelompokkan jawaban identik per pertanyaan (menurut answer_key).
    Hanya kelompok yang BERBEDA dari run primer (urutan pertama pada `runs`) perlu label baru."""
    run_ids = list(runs)
    if not run_ids:
        raise ValueError("runs kosong")
    primary = run_ids[0]
    cases = set().union(*(set(v) for v in runs.values()))
    missing = {r: sorted(cases - set(runs[r])) for r in run_ids if cases - set(runs[r])}
    if missing:
        raise ValueError(f"run tidak lengkap: {missing}")
    need_label: list[dict] = []
    per_case: dict[str, int] = {}
    for c in sorted(cases):
        groups: dict[str, list[str]] = {}
        for r in run_ids:
            groups.setdefault(answer_key(runs[r][c]), []).append(r)
        per_case[c] = len(groups)
        prim_key = answer_key(runs[primary][c])
        for key, rs in groups.items():
            if key != prim_key:
                need_label.append({"case_id": c, "runs": rs, "answer": runs[rs[0]][c]})
    return {"n_cases": len(cases), "n_runs": len(run_ids), "distinct_per_case": per_case,
            "cases_with_variation": sorted(c for c, n in per_case.items() if n > 1), "need_label": need_label}


# ---------------------------------------------------------------- relabel

def _stratum(it: dict) -> str:
    if it.get("origin") == "mutation":
        return "mutation"
    if it.get("kind") == "not_in_corpus":
        return "probe"
    return "natural_tidak_layak" if it.get("label") == TIDAK else "natural_layak"


def relabel_sample(items: list[dict], n: int, seed: str, strata_min: dict[str, int]) -> dict:
    """Sampel relabel deterministik terstratifikasi. `items` = jawaban berlabel ({answer_id, origin, kind, label}).
    Stratum diisi sampai minimumnya (atau habis), sisanya dari natural_layak, lalu dari sisa mana pun."""
    ids = [it["answer_id"] for it in items]
    if len(ids) != len(set(ids)):
        raise ValueError("answer_id ganda")
    if n > len(items):
        raise ValueError(f"n={n} melebihi jumlah jawaban {len(items)}")
    ordered = sorted(items, key=lambda it: (_key(seed, it["answer_id"]), it["answer_id"]))
    chosen: list[dict] = []
    short: dict[str, int] = {}
    for stratum, need in strata_min.items():
        pool = [it for it in ordered if _stratum(it) == stratum and it not in chosen]
        take = pool[:need]
        chosen += take
        if len(take) < need:
            short[stratum] = need - len(take)
    for pool_name in ("natural_layak", None):
        for it in ordered:
            if len(chosen) >= n:
                break
            if it not in chosen and (pool_name is None or _stratum(it) == pool_name):
                chosen.append(it)
    chosen = chosen[:n]
    comp: dict[str, int] = {}
    for it in chosen:
        comp[_stratum(it)] = comp.get(_stratum(it), 0) + 1
    # urutan penyajian ke validator: acak deterministik, tidak dikelompokkan per stratum
    present = sorted((it["answer_id"] for it in chosen), key=lambda i: (_key(seed + ":urut", i), i))
    return {"answer_ids": present, "composition": comp, "strata_short": short}


def agreement(pairs: list[tuple[str, str, str]]) -> dict:
    """pairs = [(answer_id, label1, label2)]. Kesepakatan %, daftar selisih, kappa HANYA bila terdefinisi."""
    n = len(pairs)
    if n == 0:
        return {"n": 0, "agree": 0, "pct": None, "discrepancies": [], "kappa": None, "kappa_note": "n=0"}
    agree = sum(1 for _, a, b in pairs if a == b)
    po = agree / n
    labels = {x for _, a, b in pairs for x in (a, b)}
    pe = sum((sum(1 for _, a, _b in pairs if a == lab) / n) * (sum(1 for _, _a, b in pairs if b == lab) / n) for lab in labels)
    kappa, note = None, None
    if abs(1 - pe) < 1e-12:
        note = "tidak terdefinisi (kesepakatan harapan = 1: semua label sama)"
    else:
        kappa = round((po - pe) / (1 - pe), 4)
        note = "dilaporkan hanya sebagai pelengkap persentase kesepakatan; n kecil"
    return {"n": n, "agree": agree, "pct": round(100 * po, 1),
            "discrepancies": [{"answer_id": i, "label1": a, "label2": b} for i, a, b in pairs if a != b],
            "kappa": kappa, "kappa_note": note}


# ---------------------------------------------------------------- pemilihan parameter

def select_parameters(rows: list[dict], alpha: float = 0.05, latency_rel: float = 0.10) -> dict:
    """Aturan R1/R2 + rantai tie-break (protocol.json → selection). Hanya validation.
    rows = [{id, far (None bila tak terdefinisi), car, review_rate, p95_ms, w_s, accept}]."""
    eps = 1e-12
    defined = [r for r in rows if r["far"] is not None]
    if not defined:
        return {"status": "FAR_UNDEFINED_NO_SELECTION", "rule": None, "chosen": None}

    def chain(pool: list[dict]) -> dict:
        m = max(r["car"] for r in pool)
        pool = [r for r in pool if r["car"] >= m - eps]
        m = min(r["review_rate"] for r in pool)
        pool = [r for r in pool if r["review_rate"] <= m + eps]
        m = min(r["p95_ms"] for r in pool)
        pool = [r for r in pool if r["p95_ms"] <= m * (1 + latency_rel)]
        m = min(r["w_s"] for r in pool)
        pool = [r for r in pool if r["w_s"] <= m + eps]
        return max(pool, key=lambda r: (r["accept"], -rows.index(r)))

    eligible = [r for r in defined if r["far"] <= alpha + eps]
    if eligible:
        return {"status": "SELECTED", "rule": "R1", "chosen": chain(eligible)["id"]}
    m = min(r["far"] for r in defined)
    low = [r for r in defined if r["far"] <= m + eps]
    return {"status": "NO_ELIGIBLE_PARAMETER", "rule": "R2", "chosen": chain(low)["id"]}


# ---------------------------------------------------------------- ringkasan pra-evaluator

def pre_evaluator_summary(labels: list[dict], track_m: list[dict], skipped: list[dict], relabel: dict, second_validator_log: list[dict]) -> str:
    """Markdown ringkasan yang dijanjikan sebelum evaluator dijalankan. Tidak memuat skor."""
    nat = [r for r in labels if r.get("origin") == "natural"]
    types = sorted({r["question_type"] for r in nat})
    out = ["# Ringkasan pra-evaluator", "", "## 1. Distribusi label Track R (jawaban asli)", "",
           "| question_type | n LAYAK | n TIDAK_LAYAK |", "|---|---:|---:|"]
    for t in types:
        out.append(f"| {t} | {sum(1 for r in nat if r['question_type'] == t and r['label'] == LAYAK)} | "
                   f"{sum(1 for r in nat if r['question_type'] == t and r['label'] == TIDAK)} |")
    n_bad = sum(1 for r in nat if r["label"] == TIDAK)
    out += ["", f"Total jawaban asli: {len(nat)}; TIDAK_LAYAK alami: {n_bad}."]
    if n_bad == 0:
        out.append("**FAR Track R tidak terdefinisi (n=0 jawaban TIDAK_LAYAK alami)**; yang dicari: ≥1.")
    if len(runs := sorted({r["run_id"] for r in nat if r.get("run_id")})) > 1:  # Studi 2: tiga lari dilabel (catatan panduan 6a); satu lari = total di atas
        out += ["", "Per lari (catatan panduan 6a):", "", "| lari | n LAYAK | n TIDAK_LAYAK |", "|---|---:|---:|"]
        out += [f"| {k} | {sum(1 for r in nat if r.get('run_id') == k and r['label'] == LAYAK)} | {sum(1 for r in nat if r.get('run_id') == k and r['label'] == TIDAK)} |" for k in runs]
    out += ["", f"## 2. Track M: {len(track_m)} pasangan (semua kandidat LAYAK)", "",
            "| case_id | family | halaman jangkar yang membuktikan kebalikan |", "|---|---|---|"]
    for p in track_m:
        out.append(f"| {p['case_id']} | {p['family']} | {p['anchor_page_opposite']} |")
    if skipped:
        out += ["", "Kandidat dilewati (mutasi tak dapat diterapkan mekanis):"]
        out += [f"- {s['case_id']}: {s['reason']}" for s in skipped]
    out += ["", "## 3. Relabel intra-rater", ""]
    if relabel.get("n"):
        out.append(f"Kesepakatan {relabel['agree']}/{relabel['n']} = {relabel['pct']}%.")
        out.append(f"Kappa: {relabel['kappa'] if relabel['kappa'] is not None else 'tidak terdefinisi'} ({relabel['kappa_note']}).")
        out += [f"- selisih {d['answer_id']}: {d['label1']} → {d['label2']}" for d in relabel["discrepancies"]] or ["- tidak ada selisih"]
        nat, strata = relabel.get("natural_only") or {}, relabel.get("by_stratum") or {}  # hasil lama tanpa kunci ini: keluaran tetap
        extra = ([f"Tanpa mutasi (jawaban asli saja): {nat['agree']}/{nat['n']} = {nat['pct']}%."] if nat.get("n") else []) + [
            f"- {k}: {strata[k]['agree']}/{strata[k]['n']} = {strata[k]['pct']}%" for k in ("mutation", "probe", "natural_answerable") if k in strata]
        if extra:
            out += ["", *extra]
    else:
        out.append("Belum dilakukan.")
    out += ["", "## 4. Validator kedua", ""]
    out += [f"- {e}" for e in second_validator_log] or ["- belum ada upaya yang dicatat"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- kunci hash

def lock(path: Path = DEFAULT_PROTOCOL, now: datetime | None = None) -> dict:
    data = load_protocol(path)
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    rec = {"protocol_sha256": sha, "protocol_version": data["version"], "protocol_status_at_lock": data["status"],
           "locked_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    Path(path).with_name("protocol.lock.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return rec


def _read_jsonl(p: str) -> list[dict]:
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lock")
    t = sub.add_parser("track-m"); t.add_argument("--labels", required=True); t.add_argument("--cases", required=True)
    r = sub.add_parser("relabel"); r.add_argument("--labels", required=True)
    a = ap.parse_args(argv)
    proto = load_protocol()
    if a.cmd == "lock":
        print(json.dumps(lock(), indent=2))
        return 0
    labels = _read_jsonl(a.labels)
    if a.cmd == "track-m":
        cases = {c["case_id"]: c for c in _read_jsonl(a.cases)}
        cand = [{"case_id": x["case_id"], "source_doc_id": cases[x["case_id"]]["source_doc_id"]}
                for x in labels if x["origin"] == "natural" and x["kind"] == "answerable" and x["label"] == LAYAK]
        print(json.dumps(track_m_order(cand, proto["track_m"]["seed"]), indent=2))
        return 0
    rl = proto["relabel"]
    print(json.dumps(relabel_sample(labels, rl["n_sample"], rl["seed"], rl["strata_min"]), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
