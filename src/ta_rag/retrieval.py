"""Retrieval lokal: BM25 + dense + RRF (k=60), top-k dikunci di protocol. Deterministik.

* BM25 Okapi ditulis di sini (k1=1,5, b=0,75) agar tidak bergantung paket; tokenisasi = `evaluators.tokens`.
* Dense: produk dalam EKSAK (numpy) atas vektor ternormalisasi == `faiss.IndexFlatIP` (flat, bukan aproksimasi); embedder diinjeksikan.
* Seri skor diputus: skor menurun, lalu chunk_id naik. Tidak ada pengacakan. Tidak ada `prune_context`.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Callable

from .evaluators import tokens

RRF_K = 60


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b, self.docs = k1, b, docs
        self.n = len(docs)
        self.avgdl = sum(len(d) for d in docs) / self.n if self.n else 0.0
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for i, d in enumerate(self.docs):
            s, dl = 0.0, len(d)
            for t in query:
                f = self.tf[i].get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
            out.append(s)
        return out


def _rank(scores: list[float], ids: list[str]) -> list[int]:
    """Indeks terurut: skor menurun, chunk_id naik (tie-break tetap)."""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], ids[i]))


class Index:
    def __init__(self, chunks: list[dict], embed: Callable):
        import numpy as np

        if not chunks:
            raise ValueError("chunks kosong")
        ids = [c["chunk_id"] for c in chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("chunk_id ganda")
        self.chunks, self.ids, self.embed = chunks, ids, embed
        self.bm25 = BM25([tokens(c["text"]) for c in chunks])
        v = np.asarray(embed([c["text"] for c in chunks]), dtype="float64")
        norms = np.linalg.norm(v, axis=1, keepdims=True)
        self.vecs = v / np.where(norms == 0, 1.0, norms)

    def search(self, query: str, k: int = 4) -> list[dict]:
        import numpy as np

        sparse = self.bm25.scores(tokens(query))
        q = np.asarray(self.embed([query]), dtype="float64")[0]
        qn = np.linalg.norm(q)
        dense = (self.vecs @ (q / qn if qn else q)).tolist()
        fused: dict[int, float] = {}
        for ranking, scores in ((_rank(sparse, self.ids), sparse), (_rank(dense, self.ids), dense)):
            for pos, i in enumerate(ranking):
                if scores is sparse and sparse[i] == 0.0:
                    continue  # BM25 tanpa kecocokan token tidak menyumbang peringkat
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + pos + 1)
        order = sorted(fused, key=lambda i: (-fused[i], self.ids[i]))[:k]
        return [{**self.chunks[i], "rrf_score": fused[i], "bm25": sparse[i], "dense": dense[i]} for i in order]
