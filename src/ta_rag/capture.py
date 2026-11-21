"""Capture jawaban generator (MiMo) dari konteks retrieval. Klien ditulis baru; transport diinjeksikan (tes tanpa jaringan).

Aturan (config/generator.json, CLAUDE.md 15): `answer` = choices[0].message.content SAJA; kosong -> ANSWER_EMPTY (tidak diganti
reasoning_content); respons mentah disimpan utuh; satu panggilan per pertanyaan per run; run yang sudah ada TIDAK ditimpa;
kunci hanya dari lingkungan (MIMO_API_KEY), tidak pernah dicatat.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO / "config" / "generator.json"
SYSTEM_PROMPT_KEY = "system_prompt"
CONTEXT_PLACEHOLDER = "{context}"


def load_generator_config(path: Path = DEFAULT_CONFIG) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def format_context(chunks: list[dict], cfg: dict) -> str:
    fmt, sep = cfg["context_chunk_format"], cfg["context_chunk_separator"]
    return sep.join(fmt.format(doc_id=c["doc_id"], page_start=c["page_start"], page_end=c["page_end"],
                               heading_path=c.get("heading_path", ""), text=c["text"]) for c in chunks)


def build_messages(question: str, chunks: list[dict], cfg: dict) -> list[dict]:
    template = cfg[SYSTEM_PROMPT_KEY]
    if CONTEXT_PLACEHOLDER not in template:
        raise ValueError(f"{SYSTEM_PROMPT_KEY} harus memuat {CONTEXT_PLACEHOLDER}")
    system = template.replace(CONTEXT_PLACEHOLDER, format_context(chunks, cfg))
    return [{"role": "system", "content": system}, {"role": "user", "content": cfg["user_prompt"].format(question=question)}]


def prompt_sha256(cfg: dict) -> str:
    """Hash teks prompt tetap + parameter (bukan konteks per pertanyaan): bukti prompt beku."""
    keep = {k: cfg.get(k) for k in (SYSTEM_PROMPT_KEY, "user_prompt", "context_chunk_format", "context_chunk_separator",
                                    "temperature", "max_tokens", "response_format", "model")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def request_json(question: str, chunks: list[dict], cfg: dict) -> dict:
    body = {"model": os.environ.get(cfg["model_env"], cfg["model"]), "messages": build_messages(question, chunks, cfg),
            "temperature": cfg["temperature"], "max_tokens": cfg["max_tokens"]}
    if cfg.get("response_format"):
        body["response_format"] = cfg["response_format"]
    return body


def extract_answer(resp: dict) -> tuple[str | None, str]:
    """(answer, status). status ∈ {OK, ANSWER_EMPTY, MALFORMED_RESPONSE}. reasoning_content TIDAK dipakai."""
    try:
        content = resp["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None, "MALFORMED_RESPONSE"
    if content is None or not str(content).strip():
        return None, "ANSWER_EMPTY"
    return str(content), "OK"


def http_transport(url: str, headers: dict, body: dict, timeout: float = 120.0, retries: int = 3, post=None, sleep=None) -> dict:
    """POST sekali per panggilan logis; ulang hanya pada 429/5xx/timeout (backoff 1, 2, 4 dtk). 4xx lain langsung gagal."""
    import time

    import httpx

    post, sleep = post or httpx.post, sleep or time.sleep
    for attempt in range(retries + 1):
        try:
            r = post(url, headers=headers, json=body, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            retryable = isinstance(exc, httpx.TimeoutException) or exc.response.status_code == 429 or exc.response.status_code >= 500
            if not retryable or attempt == retries:
                raise
            sleep(float(2**attempt))


def headers_from_env(cfg: dict) -> dict:
    key = os.environ.get(cfg["api_key_env"])
    if not key:
        raise RuntimeError(f"{cfg['api_key_env']} belum diset di lingkungan")
    return {cfg["auth_header"]: key, "Content-Type": "application/json"}


def capture_run(cases: list[dict], retrieve: Callable[[str], list[dict]], cfg: dict, out_dir: Path, run_id: str,
                transport: Callable = http_transport, headers: dict | None = None, now: Callable[[], datetime] | None = None,
                top_k: int = 4, allow_unfrozen: bool = False) -> Path:
    """Satu run: untuk tiap kasus, retrieve -> satu panggilan -> simpan baris JSONL (mentah utuh).
    Menolak menimpa run yang sudah ada dan menolak cfg yang belum beku."""
    if cfg.get("status") not in ("FROZEN",) and not allow_unfrozen:
        raise RuntimeError("generator.json belum FROZEN: bekukan (status=FROZEN + hash di protocol.json) sebelum capture")
    out = Path(out_dir) / f"answers_{run_id}.jsonl"
    if out.exists():
        raise FileExistsError(f"{out} sudah ada; run tidak boleh ditimpa (buat run_id baru)")
    out.parent.mkdir(parents=True, exist_ok=True)
    hdr = headers if headers is not None else headers_from_env(cfg)
    url = os.environ.get(cfg["base_url_env"], cfg["base_url"]).rstrip("/") + cfg["endpoint"]
    clock = now or (lambda: datetime.now(timezone.utc))
    psha = prompt_sha256(cfg)
    lines = []
    for c in cases:
        chunks = retrieve(c["question"])[:top_k]
        body = request_json(c["question"], chunks, cfg)
        resp = transport(url, hdr, body)
        answer, status = extract_answer(resp)
        lines.append(json.dumps({
            "run_id": run_id, "case_id": c["case_id"], "question": c["question"], "answer": answer, "answer_status": status,
            "request_json": body, "response_json_raw": resp, "response_model": resp.get("model") if isinstance(resp, dict) else None,
            "usage": resp.get("usage") if isinstance(resp, dict) else None, "timestamp_utc": clock().isoformat(timespec="seconds"),
            "prompt_sha256": psha, "top_k": top_k, "chunk_ids": [x["chunk_id"] for x in chunks],
        }, ensure_ascii=False, sort_keys=True))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def freeze(path: Path = DEFAULT_CONFIG, now: datetime | None = None) -> dict:
    """Bekukan generator: status=FROZEN + berkas kunci berisi SHA256 prompt/parameter dan isi berkas. Jalankan SEBELUM Track R."""
    cfg = load_generator_config(path)
    if cfg.get("status") == "FROZEN":
        raise RuntimeError("sudah FROZEN; perubahan = run baru dengan konfigurasi baru, bukan membekukan ulang")
    cfg["status"] = "FROZEN"
    path = Path(path)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rec = {"prompt_sha256": prompt_sha256(cfg), "generator_json_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
           "model": cfg["model"], "frozen_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    path.with_name("generator.lock.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return rec


def main(argv=None) -> int:  # pragma: no cover - CLI tipis
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="freeze | smoke | run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("freeze")
    a = ap.parse_args(argv)
    print(json.dumps(freeze(), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
