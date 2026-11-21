"""Evaluator A-D (kontribusi penelitian). Ditulis baru dari Panduan §6; tidak mengimpor kode proyek lama.

    L = F1 himpunan token (jawaban vs evidence)          S = (cos + 1) / 2   (embedding yang diinjeksikan)
    H = (1 - w_s) * L + w_s * S
    ACCEPT bila H >= accept; REVIEW bila H >= review (0,50); selain itu REJECT.
    Konfigurasi: A w_s=0 | B w_s=1 | C hybrid | D = C + hard-fail.
    Hard-fail (aturan handoff v1, BELUM diaudit lebih lanjut):
      * angka NILAI pada jawaban yang tidak ada pada evidence/pertanyaan -> REJECT (`ta_rag.numbers`; sitasi diabaikan, D12)
      * polaritas negasi jawaban != evidence dan L >= 0,70 -> ACCEPT diturunkan ke REVIEW
      * (konfigurasi E = D + `unit_fail`) angka sama dengan satuan waktu beda terhadap evidence -> REJECT

Embedding tidak dimuat di sini: `embed(list[str]) -> ndarray (n, d)` diinjeksikan (model nyata:
paraphrase-multilingual-MiniLM-L12-v2 via `sentence_transformer_embed`). Skor L, S, dan penanda dihitung SEKALI per record
(`score_pair`); sweep hanya memanggil `route` (murah).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Callable

from .numbers import unit_mismatches, unsupported_answer_numbers

REVIEW_THRESHOLD = 0.50
BERT_REVIEW_OFFSET = 0.10  # konfigurasi F: REVIEW bila F1 >= ambang ACCEPT - 0,10 (skala BERTScore sempit; dipra-registrasi)
NEG_F1_GATE = 0.70
NEG_WORDS = frozenset({"tidak", "bukan", "tanpa", "belum", "tak", "dilarang", "kecuali", "nihil"})
_TOKEN = re.compile(r"\w+", re.UNICODE)
_SENTENCE = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")  # titik pada "Rp3.600,00" tidak diikuti spasi, jadi tidak terpotong
ACCEPT, REVIEW, REJECT = "ACCEPT", "REVIEW", "REJECT"


def tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", text or "").casefold()
    return _TOKEN.findall(t)


def lexical_f1(answer: str, evidence: str) -> float:
    """F1 himpunan token. Kedua sisi kosong -> 0.0 (tidak ada dukungan yang dapat diukur)."""
    a, e = set(tokens(answer)), set(tokens(evidence))
    inter = len(a & e)
    if not a or not e or inter == 0:
        return 0.0
    p, r = inter / len(a), inter / len(e)
    return 2 * p * r / (p + r)


def negation_mismatch(answer: str, evidence: str) -> bool:
    """True bila salah satu sisi memuat kata negasi dan sisi lain tidak (polaritas biner, aturan kasar)."""
    return bool(NEG_WORDS & set(tokens(answer))) != bool(NEG_WORDS & set(tokens(evidence)))


def semantic_score(answer: str, evidence: str, embed: Callable) -> float:
    import numpy as np

    v = np.asarray(embed([answer, evidence]), dtype="float64")
    na, ne = np.linalg.norm(v[0]), np.linalg.norm(v[1])
    if na == 0 or ne == 0:
        return 0.5
    cos = float(np.clip(v[0] @ v[1] / (na * ne), -1.0, 1.0))
    return (cos + 1.0) / 2.0


def evidence_units(text: str | None) -> list[str]:
    """Baris (blok parser) dan kalimat dari teks konteks: satuan evidence Tahap II."""
    return [u.strip() for line in (text or "").split("\n") for u in _SENTENCE.split(line) if u.strip()]


def best_unit(answer: str, text: str | None) -> str:
    """Satuan konteks dengan F1 token tertinggi terhadap jawaban (seri: yang pertama); '' bila konteks kosong. Memilih memakai jawaban
    sedikit menaikkan skor dibanding kutipan oracle: dilaporkan sebagai keterbatasan, bukan disamarkan."""
    return max(evidence_units(text), key=lambda u: lexical_f1(answer, u), default="")


def score_pair(answer: str, evidence: str, embed: Callable | None, question: str = "", support: str | None = None) -> dict:
    """Skor dan penanda yang tidak bergantung parameter. `embed=None` -> S=None (hanya konfigurasi A yang sah).
    `support` (bawaan = evidence): teks tempat angka dan satuan boleh didukung; Tahap II memakai seluruh konteks terambil
    sehingga angka dari kalimat lain tetap didukung, sementara L, S, dan negasi diukur terhadap satuan terbaik."""
    support = evidence if support is None else support
    return {
        "L": lexical_f1(answer, evidence),
        "S": semantic_score(answer, evidence, embed) if embed is not None else None,
        "unsupported_numbers": sorted(unsupported_answer_numbers(answer, support, question)),
        "neg_mismatch": negation_mismatch(answer, evidence),
        "unit_mismatch": unit_mismatches(answer, support, question),
    }


def combine(L: float, S: float | None, w_s: float) -> float:
    if not 0.0 <= w_s <= 1.0:
        raise ValueError("w_s harus di [0,1]")
    if w_s > 0 and S is None:
        raise ValueError("S tidak tersedia tetapi w_s > 0")
    return (1.0 - w_s) * L + (w_s * S if w_s > 0 else 0.0)


def route(scores: dict, w_s: float, accept: float, hard_fail: bool, review: float = REVIEW_THRESHOLD, unit_fail: bool = False) -> dict:
    """Keputusan untuk satu record. Mengembalikan {route, H, flags}."""
    H = combine(scores["L"], scores["S"], w_s)
    flags = []
    if accept < review:
        flags.append("ACCEPT_BELOW_REVIEW")  # REVIEW terdistorsi (spec §9): tandai
    r = ACCEPT if H >= accept else REVIEW if H >= review else REJECT
    if hard_fail:
        if scores["unsupported_numbers"]:
            r = REJECT
            flags.append("UNSUPPORTED_NUMBER")
        elif unit_fail and scores.get("unit_mismatch"):
            r = REJECT
            flags.append("UNIT_MISMATCH")
        elif r == ACCEPT and scores["neg_mismatch"] and scores["L"] >= NEG_F1_GATE:
            r = REVIEW
            flags.append("NEGATION_MISMATCH")
    return {"route": r, "H": H, "flags": flags}


def route_bert(f1: float, accept: float, review_offset: float = BERT_REVIEW_OFFSET) -> dict:
    """Konfigurasi F: keputusan dari BERTScore F1 saja (tanpa L, S, atau hard-fail). Mengembalikan {route, H, flags} seperti `route`."""
    eps = 1e-12  # 0,85 - 0,10 tidak persis 0,75 pada float
    r = ACCEPT if f1 >= accept - eps else REVIEW if f1 >= accept - review_offset - eps else REJECT
    return {"route": r, "H": f1, "flags": []}


def route_params(scores: dict, p: dict) -> dict:
    """`route` dengan parameter beku seperti tersimpan di selection.json: {w_s, accept, hard_fail, [unit_fail]}; config F memakai `bert_f1`."""
    if p.get("config") == "F":
        return route_bert(scores["bert_f1"], p["accept"])
    return route(scores, p["w_s"], p["accept"], p["hard_fail"], unit_fail=p.get("unit_fail", False))


def sentence_transformer_embed(model_name: str = "paraphrase-multilingual-MiniLM-L12-v2") -> Callable:
    """Embedder nyata (butuh `pip install sentence-transformers` dan unduhan model). Tidak dipakai oleh tes."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, device="cpu")
    return lambda texts: model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
