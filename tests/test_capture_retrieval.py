"""Uji KODE capture (klien MiMo tiruan), chunker, dan retrieval. Tanpa jaringan, tanpa kunci nyata."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ta_rag import capture as C  # noqa: E402
from ta_rag import chunking as K  # noqa: E402
from ta_rag import corpus  # noqa: E402
from ta_rag import retrieval as R  # noqa: E402

np = pytest.importorskip("numpy")
FIXTURE = REPO / "tests" / "fixtures" / "reducto_perpres_59_2024_r1_ui_export.json"


# ------------------------------------------------------------------ capture

def frozen_cfg():
    cfg = C.load_generator_config()
    cfg["status"] = "FROZEN"
    return cfg


CHUNKS = [{"chunk_id": "d::1", "doc_id": "d", "page_start": 3, "page_end": 3, "heading_path": "Pasal 7", "text": "Peserta dapat mengganti FKTP setelah 3 (tiga) bulan."}]
CASES = [{"case_id": "R02", "question": "Menurut Perpres, setelah berapa lama?"}]


def good_resp(content="3 (tiga) bulan.", **extra):
    return {"model": "mimo-v2.6-flash", "choices": [{"message": {"content": content, **extra}, "finish_reason": "stop"}], "usage": {"total_tokens": 9}}


def run(tmp_path, resp, run_id="run1", cfg=None):
    calls = []

    def transport(url, headers, body):
        calls.append((url, headers, body))
        return resp

    out = C.capture_run(CASES, lambda q: CHUNKS, cfg or frozen_cfg(), tmp_path, run_id, transport=transport,
                        headers={"api-key": "sk-RAHASIA"}, now=lambda: datetime(2026, 11, 5, tzinfo=timezone.utc))
    return out, calls


def test_build_messages_has_instruction_context_and_question():
    msgs = C.build_messages("Pertanyaan?", CHUNKS, C.load_generator_config())
    assert msgs[0]["role"] == "system" and "hanya berdasarkan konteks" in msgs[0]["content"]
    assert "[d · hlm. 3-3 · Pasal 7]" in msgs[0]["content"] and "Peserta dapat mengganti" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "Pertanyaan?"}


def test_capture_stores_raw_response_one_call_and_never_logs_key(tmp_path):
    out, calls = run(tmp_path, good_resp(reasoning_content="berpikir..."))
    assert len(calls) == 1 and calls[0][0].endswith("/chat/completions")
    row = json.loads(out.read_text().splitlines()[0])
    assert row["answer"] == "3 (tiga) bulan." and row["answer_status"] == "OK" and row["chunk_ids"] == ["d::1"]
    assert row["response_json_raw"]["choices"][0]["message"]["reasoning_content"] == "berpikir..."  # mentah utuh
    assert "sk-RAHASIA" not in out.read_text()
    assert row["prompt_sha256"] == C.prompt_sha256(frozen_cfg()) and row["response_model"] == "mimo-v2.6-flash"


def test_answer_never_falls_back_to_reasoning_content():
    assert C.extract_answer(good_resp(content="", reasoning_content="jawaban bocor")) == (None, "ANSWER_EMPTY")
    assert C.extract_answer({"choices": [{"message": {"content": None, "reasoning_content": "x"}}]}) == (None, "ANSWER_EMPTY")
    assert C.extract_answer({"choices": []}) == (None, "MALFORMED_RESPONSE")
    assert C.extract_answer({}) == (None, "MALFORMED_RESPONSE")


def test_capture_refuses_unfrozen_config_and_overwrite(tmp_path):
    cfg = {**C.load_generator_config(), "status": "DRAFT_UNFROZEN"}
    with pytest.raises(RuntimeError, match="FROZEN"):
        run(tmp_path, good_resp(), cfg=cfg)
    run(tmp_path, good_resp(), "runA")
    with pytest.raises(FileExistsError):
        run(tmp_path, good_resp(), "runA")
    run(tmp_path, good_resp(), "runB")  # run baru boleh


def test_capture_without_api_key_env_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MIMO_API_KEY"):
        C.capture_run(CASES, lambda q: CHUNKS, frozen_cfg(), tmp_path, "r", transport=lambda *a: good_resp())


def test_prompt_hash_changes_when_prompt_or_parameter_changes():
    base = C.prompt_sha256(frozen_cfg())
    for key, val in (("system_prompt", "lain"), ("temperature", 0.7), ("max_tokens", 801), ("model", "mimo-lain")):
        cfg = frozen_cfg(); cfg[key] = val
        assert C.prompt_sha256(cfg) != base, key
    cfg = frozen_cfg(); cfg["provenance"] = "ubah catatan"
    assert C.prompt_sha256(cfg) == base  # metadata non-prompt tidak mengubah hash


def test_generator_config_keeps_explicit_abstention_instruction():
    assert "tidak ada dalam konteks" in C.load_generator_config()["system_prompt"]


# ------------------------------------------------------------------ chunker

DOC = {"doc_id": "d", "sha256": "ab", "eval_role": "evidence_source", "provenance": {"class": "digital_asli"}, "pages": 5,
       "index_page_scope": "1-5", "pilot_pages": 5}


def blk(t, text, page):
    return {"type": t, "content": text, "bbox": {"original_page": page}}


def raw_of(blocks):
    return {"result": {"chunks": [{"blocks": blocks}]}}


def test_chunker_splits_at_pasal_keeps_ayat_and_drops_boilerplate():
    raw = raw_of([blk("Header", "- 4 -", 1), blk("Title", "<b>Pasal 6</b>", 1), blk("List Item", "(1) ayat satu", 1), blk("List Item", "(2) ayat dua", 2),
                  blk("Figure", "Logo", 2), blk("Footer", "SK No", 2), blk("Section Header", "Pasal 6A", 2), blk("Text", "isi 6A", 3),
                  blk("Signature", "tanda tangan", 3)])
    ch = K.chunk_document(raw, DOC)
    assert [c["heading_path"] for c in ch] == ["Pasal 6", "Pasal 6A"]
    assert "(1) ayat satu" in ch[0]["text"] and "(2) ayat dua" in ch[0]["text"]
    assert (ch[0]["page_start"], ch[0]["page_end"]) == (1, 2) and (ch[1]["page_start"], ch[1]["page_end"]) == (2, 3)
    joined = " ".join(c["text"] for c in ch)
    assert "Logo" not in joined and "SK No" not in joined and "tanda tangan" not in joined and "<b>" not in joined


def test_chunker_missing_physical_page_raises_instead_of_guessing():
    with pytest.raises(ValueError, match="original_page"):
        K.chunk_document(raw_of([{"type": "Text", "content": "x", "bbox": {}}]), DOC)


def test_chunker_splits_long_pasal_on_block_boundary_with_unique_ids():
    raw = raw_of([blk("Title", "Pasal 1", 1)] + [blk("List Item", f"{i}. " + "kata " * 200, 1 + i // 3) for i in range(1, 7)])
    ch = K.chunk_document(raw, DOC, max_chars=1500)
    assert len(ch) >= 3 and len({c["chunk_id"] for c in ch}) == len(ch)
    assert all(len(c["text"]) <= 1500 + 1010 for c in ch)
    assert all(c["text"].startswith(("Pasal 1", "1.", "2.", "3.", "4.", "5.", "6.")) for c in ch)


def test_chunker_real_fixture_perpres_59_has_pasal_chunks_and_passes_scope_guard():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cfg = corpus.load_config()
    doc = next(d for d in cfg["documents"] if d["doc_id"].startswith("perpres_59_2024"))
    ch = K.chunk_document(raw, doc)
    assert sum(c["heading_path"].startswith("Pasal") for c in ch) >= 20
    assert corpus.check_chunk_scope(ch, cfg) == []
    assert all(1 <= c["page_start"] <= c["page_end"] <= doc["pages"] for c in ch)
    assert not any("Logo Republik" in c["text"] for c in ch)
    tampered = copy.deepcopy(ch); tampered[0]["page_end"] = 99
    assert corpus.check_chunk_scope(tampered, cfg), "penjaga cakupan harus menolak halaman di luar dokumen"


# ------------------------------------------------------------------ retrieval

def stub_embed(texts):
    out = np.zeros((len(texts), 64))
    for r, t in enumerate(texts):
        for tok in K.clean(t).casefold().split():
            out[r, int(hashlib.sha256(tok.encode()).hexdigest(), 16) % 64] += 1.0
    return out


def mk(cid, text):
    return {"chunk_id": cid, "doc_id": "d", "page_start": 1, "page_end": 1, "heading_path": "x", "text": text}


CORPUS = [mk("c1", "Peserta dapat mengganti FKTP setelah jangka waktu 3 bulan"), mk("c2", "iuran bulanan Peserta PBPU Kelas 3 dibayar tiap bulan"),
          mk("c3", "tarif kapitasi Puskesmas per peserta per bulan Rp3.600"), mk("c4", "klaim FKRTL dibayarkan paling lambat 15 hari")]


def test_retrieval_returns_relevant_chunk_first_and_respects_k():
    idx = R.Index(CORPUS, stub_embed)
    hits = idx.search("mengganti FKTP jangka waktu", k=2)
    assert hits[0]["chunk_id"] == "c1" and len(hits) <= 2


def test_retrieval_is_deterministic_and_order_of_input_independent_for_ties():
    a = R.Index(CORPUS, stub_embed).search("peserta bulan", k=4)
    b = R.Index(list(reversed(CORPUS)), stub_embed).search("peserta bulan", k=4)
    assert [h["chunk_id"] for h in a] == [h["chunk_id"] for h in b]


def test_retrieval_exact_token_query_is_found_via_bm25_even_with_weak_dense():
    weak = lambda texts: np.ones((len(texts), 4)) + np.arange(len(texts))[:, None] * 1e-9  # dense hampir tak informatif
    hits = R.Index(CORPUS, weak).search("FKRTL", k=1)
    assert hits[0]["chunk_id"] == "c4"


def test_retrieval_rejects_duplicate_ids_and_empty_corpus():
    with pytest.raises(ValueError):
        R.Index([mk("c1", "a"), mk("c1", "b")], stub_embed)
    with pytest.raises(ValueError):
        R.Index([], stub_embed)


def test_bm25_idf_rare_term_outweighs_common_term():
    bm = R.BM25([["a", "x"], ["a", "b"], ["a", "c"]])
    assert bm.idf["x"] > bm.idf["a"] and bm.scores(["x"])[0] > bm.scores(["a"])[0]


def test_freeze_marks_frozen_writes_lock_and_refuses_second_freeze(tmp_path):
    cfg_path = tmp_path / "generator.json"
    cfg_path.write_text(json.dumps({**C.load_generator_config(), "status": "DRAFT_UNFROZEN"}), encoding="utf-8")
    rec = C.freeze(cfg_path, now=datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert json.loads(cfg_path.read_text())["status"] == "FROZEN"
    lock = json.loads((tmp_path / "generator.lock.json").read_text())
    assert lock["prompt_sha256"] == rec["prompt_sha256"] == C.prompt_sha256(json.loads(cfg_path.read_text()))
    assert lock["generator_json_sha256"] == hashlib.sha256(cfg_path.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError, match="FROZEN"):
        C.freeze(cfg_path)


def test_build_messages_substitutes_context_placeholder_once_and_never_leaks_it():
    sys_msg = C.build_messages("Pertanyaan?", CHUNKS, C.load_generator_config())[0]["content"]
    assert "{context}" not in sys_msg and sys_msg.count("Peserta dapat mengganti") == 1
    assert sys_msg.index("Konteks:") < sys_msg.index("[d · hlm. 3-3 · Pasal 7]")  # konteks berada setelah label "Konteks:"


def test_build_messages_rejects_config_without_context_placeholder():
    cfg = {**C.load_generator_config(), "system_prompt": "Jawab dari konteks."}
    with pytest.raises(ValueError, match=r"\{context\}"):
        C.build_messages("Pertanyaan?", CHUNKS, cfg)


def _resp(status, **kw):
    import httpx

    return httpx.Response(status, request=httpx.Request("POST", "http://x"), **kw)


def test_http_transport_retries_429_and_5xx_then_succeeds_and_sleeps_with_backoff():
    seq, slept = [_resp(429), _resp(503), _resp(200, json={"ok": 1})], []
    out = C.http_transport("http://x", {}, {}, post=lambda *a, **k: seq.pop(0), sleep=slept.append)
    assert out == {"ok": 1} and not seq and slept == [1.0, 2.0]


def test_http_transport_gives_up_after_retries_and_does_not_retry_4xx():
    import httpx

    always_500 = [_resp(500) for _ in range(4)]
    with pytest.raises(httpx.HTTPStatusError):
        C.http_transport("http://x", {}, {}, retries=3, post=lambda *a, **k: always_500.pop(0), sleep=lambda s: None)
    assert not always_500  # 1 percobaan + 3 ulang = 4 panggilan
    calls = []

    def bad_request(*a, **k):
        calls.append(1)
        return _resp(400)

    with pytest.raises(httpx.HTTPStatusError):
        C.http_transport("http://x", {}, {}, post=bad_request, sleep=lambda s: None)
    assert len(calls) == 1
