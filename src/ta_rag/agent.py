"""Agent orkestrator: menjalankan alur TA dari PDF mentah sampai hasil, dengan persetujuan manusia di setiap langkah.

Prinsip rancangan
 1. Alur DETERMINISTIK (config/workflow.json), bukan LLM yang berimprovisasi. LLM boleh membantu menjelaskan atau men-debug; ia tidak
    memutuskan langkah, tidak memberi label, tidak menyetujui.
 2. Persetujuan diketik manusia di TTY dan terikat pada hash RENCANA (perintah yang sudah diurai + hash berkas masukan + hash hasil
    langkah hulu). Berkas masukan berubah -> persetujuan tidak berlaku lagi. Langkah tak-terulang menuntut kata tambahan.
 3. Ledger append-only berantai hash (data/agent/ledger.jsonl): setiap rencana, persetujuan, penolakan, eksekusi, hasil, dan kegagalan
    penjaga tercatat dengan cap waktu. `verify` mendeteksi ledger yang diubah dan hasil yang berubah di luar ledger.
 4. Penjaga data asli (guards.py) dijalankan sebelum/sesudah langkah. Data tanpa provenans ditolak.
 5. Langkah manusia (verifikasi visual, pelabelan, mutasi, relabel, kirim ringkasan) hanya digerbangi dan dibuktikan dengan berkas; tidak
    pernah diotomatisasi.

Batas yang jujur: pada mesin yang agent-nya punya akses shell, tidak ada gerbang perangkat lunak yang tak bisa dipalsukan. Yang
dijamin di sini: (a) agent tanpa TTY tidak dapat menyetujui lewat CLI; (b) mengubah ledger atau hasil terdeteksi; (c) kecelakaan
dan pintasan (fixture tersalin, label disunting, run ditimpa, urutan terbalik) ditolak. Jalankan `drive` di terminal milikmu sendiri.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import corpus, guards

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / "config" / "workflow.json"
LEDGER_REL = Path("data") / "agent" / "ledger.jsonl"
ZERO = "0" * 64
KINDS = ("auto", "human")


# ------------------------------------------------------------------ hash & ledger

def canonical(o) -> str:
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hash_path(p: Path, excluded: tuple[Path, ...] = ()) -> str:
    """SHA256 berkas; untuk folder: hash dari (jalur relatif, hash isi) terurut. Tidak ada -> 'ABSENT'."""
    p = Path(p)
    if p.is_file():
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
        return h.hexdigest()
    if p.is_dir():
        items = [(str(f.relative_to(p)), hash_path(f)) for f in sorted(p.rglob("*"))
                 if f.is_file() and "__pycache__" not in f.parts
                 and not any(f == x or x in f.parents for x in excluded)]
        return _h(canonical(items))
    return "ABSENT"


class Ledger:
    def __init__(self, path: Path, clock: Callable[[], datetime] | None = None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def append(self, event: str, stage: str | None = None, actor: str = "agent", **payload) -> dict:
        es = self.entries()
        e = {"seq": len(es) + 1, "ts": self.clock().isoformat(timespec="seconds"), "event": event, "stage": stage, "actor": actor,
             "payload": payload, "prev": es[-1]["hash"] if es else ZERO}
        e["hash"] = _h(canonical(e))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return e

    def verify(self) -> list[str]:
        prev, problems = ZERO, []
        for i, e in enumerate(self.entries(), 1):
            body = {k: v for k, v in e.items() if k != "hash"}
            if e.get("seq") != i:
                problems.append(f"seq {i}: nomor urut {e.get('seq')}")
            if e.get("prev") != prev:
                problems.append(f"seq {i}: rantai putus (prev tidak cocok)")
            if _h(canonical(body)) != e.get("hash"):
                problems.append(f"seq {i}: hash entri tidak cocok (entri diubah)")
            prev = e.get("hash", prev)
        return problems


# ------------------------------------------------------------------ workflow

def load_workflow(path: Path = WORKFLOW) -> dict:
    wf = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_workflow(wf)
    return wf


def validate_workflow(wf: dict) -> None:
    ids = [s["id"] for s in wf["stages"]]
    if len(ids) != len(set(ids)):
        raise ValueError("id langkah ganda")
    seen: set[str] = set()
    for s in wf["stages"]:
        if s["kind"] not in KINDS:
            raise ValueError(f"{s['id']}: kind harus salah satu dari {KINDS}")
        for d in s.get("needs", []):
            if d not in seen:
                raise ValueError(f"{s['id']}: needs {d} harus mendahului (urutan topologis, tanpa siklus)")
        if s["kind"] == "auto" and not (s.get("cmd") or s.get("cmd_dynamic")):
            raise ValueError(f"{s['id']}: langkah auto butuh cmd atau cmd_dynamic")
        if s["kind"] == "human" and not (s.get("instructions") and s.get("evidence")):
            raise ValueError(f"{s['id']}: langkah human butuh instructions dan evidence")
        for g in s.get("guards_pre", []) + s.get("guards_post", []):
            if g not in guards.REGISTRY:
                raise ValueError(f"{s['id']}: penjaga tak dikenal {g}")
        seen.add(s["id"])


def stage_by_id(wf: dict, sid: str) -> dict:
    for s in wf["stages"]:
        if s["id"] == sid or s["id"].split("_")[0] == sid:
            return s
    raise KeyError(f"langkah tidak ada: {sid}")


def _dynamic_parse_full(repo: Path) -> list[list[str]]:
    cfg = corpus.load_config(repo / "config" / "corpus.json")
    return [["{python}"] + shlex.split(p["command"])[1:] for p in corpus.plan_commands(cfg, "data/raw_pdf", "data/reducto")]


def _dynamic_parse_full_dry(repo: Path) -> list[list[str]]:
    """Dry-run atas RENCANA YANG SAMA dengan parsing penuh (--only/--page-range ikut), bukan atas seluruh 1346 halaman."""
    out = []
    for argv in _dynamic_parse_full(repo):
        i = argv.index("--out-dir")
        out.append(argv[:i + 1] + ["data/reducto_dryrun"] + argv[i + 2:] + ["--dry-run"])
    return out


DYNAMIC = {"parse_full": _dynamic_parse_full, "parse_full_dry": _dynamic_parse_full_dry}


def resolve_cmds(stage: dict, repo: Path, env: dict, today: str) -> list[list[str]]:
    """Perintah dengan placeholder {python} dibiarkan (hash tidak bergantung jalur interpreter)."""
    raw = DYNAMIC[stage["cmd_dynamic"]](repo) if stage.get("cmd_dynamic") else [stage["cmd"]]
    out = []
    for argv in raw:
        r = []
        for t in argv:
            if t.startswith("{env:") and t.endswith("}"):
                name = t[5:-1]
                if not env.get(name):
                    raise KeyError(f"variabel lingkungan {name} wajib diisi untuk langkah {stage['id']}")
                t = env[name]
            elif t.startswith("{opt:") and t.endswith("}"):
                name, flag = t[5:-1].split("=", 1)
                if env.get(name) != "1":
                    continue
                t = flag
            t = t.replace("{today}", today)
            r.append(t)
        out.append(r)
    return out


def result_hash(stage: dict, repo: Path, excluded: tuple[Path, ...] = ()) -> str:
    paths = stage.get("outputs") if stage["kind"] == "auto" else stage["evidence"]
    return _h(canonical({p: hash_path(repo / p, excluded) for p in paths}))


def build_plan(stage: dict, repo: Path, entries: list[dict], env: dict | None = None, today: str | None = None) -> dict:
    env = os.environ if env is None else env
    today = today or datetime.now(timezone(timedelta(hours=7))).date().isoformat()
    body = {"stage": stage["id"], "kind": stage["kind"], "cost": stage.get("cost", "none"),
            "cmds": resolve_cmds(stage, repo, env, today) if stage["kind"] == "auto" else [],
            "inputs": {p: hash_path(repo / p) for p in stage.get("inputs", [])},
            "upstream": {d: recorded_result(entries, d) for d in stage.get("needs", [])},
            "env_required": sorted(stage.get("env_required", []))}
    return {**body, "plan_hash": _h(canonical(body))}


def recorded_result(entries: list[dict], sid: str) -> str | None:
    cur = None
    for e in entries:
        if e["stage"] != sid:
            continue
        if e["event"] in ("REJECTED", "INVALIDATED"):
            cur = None
        elif e["event"] in ("FINISHED", "HUMAN_DONE") and e["payload"].get("ok", True):
            cur = e["payload"].get("result_hash")
    return cur


def derive(entries: list[dict], stage: dict) -> dict:
    approved = finished = reviewed = done = None
    for e in entries:
        if e["stage"] != stage["id"]:
            continue
        ev, pl = e["event"], e["payload"]
        if ev == "APPROVED" and pl.get("phase") == "pre":
            approved, finished, reviewed = e, None, None
        elif ev == "FINISHED":
            finished, reviewed, approved = e, None, None
        elif ev == "APPROVED" and pl.get("phase") == "post" and finished and pl.get("result_hash") == finished["payload"].get("result_hash"):
            reviewed = e
        elif ev == "HUMAN_DONE":
            done = e
        elif ev in ("REJECTED", "INVALIDATED"):
            approved = finished = reviewed = done = None
    if stage["kind"] == "human":
        return {"state": "DONE" if done and done["payload"].get("ok", True) else "PENDING", "record": done}
    if finished:
        if not finished["payload"].get("ok"):
            return {"state": "FAILED", "record": finished}
        if stage.get("review_outputs") and not reviewed:
            return {"state": "AWAITING_REVIEW", "record": finished}
        return {"state": "DONE", "record": finished}
    return {"state": "APPROVED" if approved else "PENDING", "record": approved}


def state_of(wf: dict, entries: list[dict], sid: str, repo: Path) -> dict:
    """PENDING | APPROVED | AWAITING_REVIEW | DONE | FAILED | STALE | BLOCKED."""
    st = stage_by_id(wf, sid)
    d = derive(entries, st)
    blockers = [n for n in st.get("needs", []) if state_of(wf, entries, n, repo)["state"] != "DONE"]
    if blockers and d["state"] != "DONE":
        return {"state": "BLOCKED", "blockers": blockers, "record": d["record"]}
    if d["state"] == "DONE":
        up_now = {n: recorded_result(entries, n) for n in st.get("needs", [])}
        if d["record"]["payload"].get("upstream", up_now) != up_now:
            return {"state": "STALE", "record": d["record"]}
    return d


# ------------------------------------------------------------------ pendekatan manusia: fase persetujuan

def phrase_pre(stage: dict, plan: dict) -> str:
    base = f"SETUJU {stage['id']} {plan['plan_hash'][:8]}"
    return base + (" TIDAK-BISA-DIULANG" if stage.get("cost") == "irreversible" else "")


def phrase_post(stage: dict, rh: str) -> str:
    return f"TERIMA {stage['id']} {rh[:8]}"


def phrase_done(stage: dict, rh: str) -> str:
    return f"SELESAI {stage['id']} {rh[:8]}"


class Agent:
    def __init__(self, repo: Path = REPO, wf: dict | None = None, input_fn: Callable[[str], str] = input,
                 is_tty: Callable[[], bool] = lambda: sys.stdin.isatty(), out: Callable[[str], None] = print,
                 env: dict | None = None, clock: Callable[[], datetime] | None = None, runner: Callable | None = None):
        self.repo = Path(repo)
        self.wf = wf or load_workflow(self.repo / "config" / "workflow.json")
        self.ledger = Ledger(self.repo / LEDGER_REL, clock)
        self.input, self.is_tty, self.out = input_fn, is_tty, out
        self.env = os.environ if env is None else env
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.runner = runner or self._run_subprocess

    # ---- util
    def entries(self) -> list[dict]:
        return self.ledger.entries()

    def state(self, sid: str) -> dict:
        return state_of(self.wf, self.entries(), sid, self.repo)

    def today(self) -> str:
        return self.clock().astimezone(timezone(timedelta(hours=7))).date().isoformat()

    def plan(self, sid: str) -> dict:
        return build_plan(stage_by_id(self.wf, sid), self.repo, self.entries(), self.env, self.today())

    def _need_human(self) -> None:
        if not self.is_tty():
            raise PermissionError("persetujuan harus diketik manusia di terminal interaktif (TTY). Agent/skrip tanpa TTY tidak dapat menyetujui.")

    def _time_gate(self, st: dict) -> str | None:
        g = st.get("not_before")
        if not g:
            return None
        for e in self.entries():
            if e["stage"] == g["stage"] and e["event"] in ("FINISHED", "HUMAN_DONE") and e["payload"].get("ok", True):
                t0 = datetime.fromisoformat(e["ts"])
                ready = t0 + timedelta(hours=g["hours"])
                if self.clock() < ready and self.env.get(g.get("override_env", "")) != "1":
                    return f"belum boleh sebelum {ready.astimezone(timezone(timedelta(hours=7))).isoformat(timespec='minutes')} WIB ({g['hours']} jam setelah {g['stage']})"
        return None

    def _guards(self, names: list[str]) -> list[str]:
        res = guards.run_guards(names, self.repo)
        return [f"[{n}] {p}" for n, ps in res.items() for p in ps]

    # ---- persetujuan
    def approve(self, sid: str, phase: str = "pre") -> dict:
        self._need_human()
        st, s = stage_by_id(self.wf, sid), self.state(sid)
        if phase == "pre":
            if s["state"] == "BLOCKED":
                raise RuntimeError(f"{st['id']} terblokir oleh {s['blockers']}")
            if s["state"] == "DONE":
                raise RuntimeError(f"{st['id']} sudah selesai; untuk mengulang, catat `reject` dengan alasan terlebih dahulu")
            if st.get("cost") == "irreversible" and any(e["stage"] == st["id"] and e["event"] == "FINISHED" and e["payload"].get("ok")
                                                        for e in self.entries()) and s["state"] != "PENDING":
                raise RuntimeError(f"{st['id']} tak-terulang dan sudah pernah selesai; amandemen harus manual (`reject` + alasan) dan dicantumkan di naskah")
            gate = self._time_gate(st)
            if gate:
                raise RuntimeError(f"{st['id']} {gate}")
            bad = self._guards(st.get("guards_pre", []))
            if bad:
                self.ledger.append("GUARD_FAILED", st["id"], phase="pre", problems=bad[:20])
                raise RuntimeError("penjaga pra-langkah gagal:\n" + "\n".join(bad[:15]))
            plan = build_plan(st, self.repo, self.entries(), self.env, self.today())
            self._show_plan(st, plan)
            want = phrase_pre(st, plan)
            typed = self.input(f"\nKetik persis untuk menyetujui:  {want}\n> ").strip()
            if typed != want:
                raise PermissionError("frasa tidak cocok; tidak ada persetujuan dicatat")
            return self.ledger.append("APPROVED", st["id"], actor="human", phase="pre", plan_hash=plan["plan_hash"], plan=plan)
        if s["state"] != "AWAITING_REVIEW":
            raise RuntimeError(f"{st['id']} tidak menunggu tinjauan (state {s['state']})")
        rh = s["record"]["payload"]["result_hash"]
        want = phrase_post(st, rh)
        typed = self.input(f"\nSetelah memeriksa hasil di atas, ketik:  {want}\n> ").strip()
        if typed != want:
            raise PermissionError("frasa tidak cocok; hasil belum diterima")
        return self.ledger.append("APPROVED", st["id"], actor="human", phase="post", result_hash=rh)

    def reject(self, sid: str, reason: str) -> dict:
        self._need_human()
        return self.ledger.append("REJECTED", stage_by_id(self.wf, sid)["id"], actor="human", reason=reason)

    def _show_plan(self, st: dict, plan: dict) -> None:
        o = self.out
        o(f"\n=== RENCANA {st['id']} — {st['title']} ===")
        o(f"biaya/risiko : {st.get('cost', 'none')}" + ("  (!!! TIDAK BISA DIULANG)" if st.get("cost") == "irreversible" else ""))
        if st.get("cost_note"):
            o(f"catatan      : {st['cost_note']}")
        for c in plan["cmds"]:
            o("perintah     : " + " ".join(t if t == "{python}" else shlex.quote(t) for t in c))
        for p, h in plan["inputs"].items():
            o(f"masukan       : {p}  sha256={h[:12]}")
        for d, h in plan["upstream"].items():
            o(f"hasil hulu    : {d}  {str(h)[:12]}")
        o(f"env dibutuhkan: {plan['env_required'] or '-'} (hanya nama; nilai tidak dicatat)")
        o(f"plan_hash    : {plan['plan_hash'][:16]}")

    # ---- eksekusi
    def _run_subprocess(self, argv: list[str], timeout: float | None) -> dict:
        exe = [sys.executable if t == "{python}" else t for t in argv]
        env = {**os.environ, **{k: v for k, v in self.env.items() if isinstance(v, str)}}
        env["PYTHONPATH"] = str(self.repo / "src") + os.pathsep + env.get("PYTHONPATH", "")
        t0 = time.time()
        r = subprocess.run(exe, cwd=self.repo, env=env, capture_output=True, text=True, timeout=timeout)
        return {"returncode": r.returncode, "stdout": r.stdout[-4000:], "stderr": r.stderr[-4000:], "duration_s": round(time.time() - t0, 2)}

    def run(self, sid: str) -> dict:
        st, s = stage_by_id(self.wf, sid), self.state(sid)
        if st["kind"] != "auto":
            raise RuntimeError(f"{st['id']} adalah langkah manusia; gunakan `done`")
        if s["state"] != "APPROVED":
            raise PermissionError(f"{st['id']} belum disetujui untuk rencana saat ini (state {s['state']})")
        plan = build_plan(st, self.repo, self.entries(), self.env, self.today())
        if s["record"]["payload"]["plan_hash"] != plan["plan_hash"]:
            self.ledger.append("INVALIDATED", st["id"], reason="rencana berubah sejak disetujui (masukan/hulu/perintah)")
            raise PermissionError("rencana berubah sejak disetujui; setujui ulang")
        missing = [n for n in st.get("env_required", []) if not self.env.get(n)]
        if missing:
            raise RuntimeError(f"variabel lingkungan belum diisi: {missing}")
        bad = self._guards(st.get("guards_pre", []))
        if bad:
            self.ledger.append("GUARD_FAILED", st["id"], phase="pre", problems=bad[:20])
            raise RuntimeError("penjaga pra-langkah gagal:\n" + "\n".join(bad[:15]))
        self.ledger.append("STARTED", st["id"], plan_hash=plan["plan_hash"])
        results = []
        for argv in plan["cmds"]:
            r = self.runner(argv, st.get("timeout_s"))
            results.append({"argv": argv, **r})
            if r["returncode"] != 0:
                break
        rc = max((r["returncode"] for r in results), default=0)
        problems: list[str] = []
        if rc == 0:
            problems += [f"keluaran hilang: {p}" for p in st.get("outputs", []) if hash_path(self.repo / p) == "ABSENT"]
            problems += self._guards(st.get("guards_post", []))
        rh = result_hash(st, self.repo)
        return self.ledger.append("FINISHED", st["id"], ok=(rc == 0 and not problems), returncode=rc, plan_hash=plan["plan_hash"],
                                  upstream=plan["upstream"], result_hash=rh, guard_problems=problems[:30],
                                  runs=[{k: (v if k != "argv" else v) for k, v in r.items()} for r in results])

    def done(self, sid: str) -> dict:
        self._need_human()
        st, s = stage_by_id(self.wf, sid), self.state(sid)
        if st["kind"] != "human":
            raise RuntimeError(f"{st['id']} bukan langkah manusia")
        if s["state"] == "BLOCKED":
            raise RuntimeError(f"{st['id']} terblokir oleh {s['blockers']}")
        gate = self._time_gate(st)
        if gate:
            raise RuntimeError(f"{st['id']} {gate}")
        absent = [p for p in st["evidence"] if hash_path(self.repo / p) == "ABSENT"]
        if absent:
            raise FileNotFoundError(f"bukti belum ada: {absent}")
        bad = self._guards(st.get("guards_post", []))
        if bad:
            self.ledger.append("GUARD_FAILED", st["id"], phase="done", problems=bad[:20])
            raise RuntimeError("penjaga menolak bukti:\n" + "\n".join(bad[:15]))
        rh = result_hash(st, self.repo)
        want = phrase_done(st, rh)
        typed = self.input(f"\nDengan ini saya menyatakan pekerjaan manusia ini benar-benar selesai. Ketik:  {want}\n> ").strip()
        if typed != want:
            raise PermissionError("frasa tidak cocok; tidak dicatat")
        up = {n: recorded_result(self.entries(), n) for n in st.get("needs", [])}
        return self.ledger.append("HUMAN_DONE", st["id"], actor="human", ok=True, result_hash=rh, upstream=up)

    # ---- tampilan
    def status_table(self) -> list[tuple[str, str, str, str]]:
        rows = []
        for st in self.wf["stages"]:
            s = self.state(st["id"])
            extra = ""
            if s["state"] == "BLOCKED":
                extra = "menunggu " + ",".join(b.split("_")[0] for b in s["blockers"])
            elif s["state"] == "FAILED":
                extra = ((s["record"]["payload"].get("guard_problems") or [""])[0] or f"rc={s['record']['payload'].get('returncode')}")[:70]
            rows.append((st["id"], st["kind"], s["state"], extra))
        return rows

    def next_stage(self) -> str | None:
        for st in self.wf["stages"]:
            if self.state(st["id"])["state"] != "DONE":
                return st["id"]
        return None

    def verify(self) -> list[str]:
        problems = self.ledger.verify()
        es = self.entries()
        for st in self.wf["stages"]:
            s = state_of(self.wf, es, st["id"], self.repo)
            if s["state"] in ("DONE", "STALE") and s["record"] and not st.get("mutable_outputs"):
                now, was = result_hash(st, self.repo), s["record"]["payload"].get("result_hash")
                if was and now != was:
                    roots = [self.repo / p for p in (st.get("outputs", []) if st["kind"] == "auto" else st["evidence"])
                             if (self.repo / p).is_dir()]
                    later_paths = []
                    for other in self.wf["stages"]:
                        if other["id"] == st["id"]:
                            continue
                        later = state_of(self.wf, es, other["id"], self.repo)
                        if later["state"] != "DONE" or not later["record"] or later["record"]["seq"] <= s["record"]["seq"]:
                            continue
                        paths = other.get("outputs", []) if other["kind"] == "auto" else other["evidence"]
                        later_paths.extend(self.repo / p for p in paths if any(root in (self.repo / p).parents for root in roots))
                    # Keluaran tahap lanjut tetap diperiksa sendiri; isi folder semula harus cocok persis.
                    if later_paths and result_hash(st, self.repo, tuple(later_paths)) == was:
                        continue
                    problems.append(f"DRIFT {st['id']}: hasil/bukti berubah di luar ledger setelah dicatat selesai")
        return problems

    def drive(self, until: str | None = None) -> str:
        """Satu putaran interaktif: berhenti saat menunggu pekerjaan manusia di luar terminal, saat frasa salah, atau gagal."""
        self._need_human()
        for st in self.wf["stages"]:
            s = self.state(st["id"])
            if s["state"] == "DONE":
                if until and st["id"].startswith(until):
                    return "UNTIL"
                continue
            self.out(f"\n>>> {st['id']} [{s['state']}] {st['title']}")
            if s["state"] == "BLOCKED":
                return f"BLOCKED: {s['blockers']}"
            if st["kind"] == "human":
                self.out("\nPEKERJAAN MANUSIA:\n" + st["instructions"])
                try:
                    self.done(st["id"])
                except (FileNotFoundError, RuntimeError, PermissionError) as ex:
                    self.out(f"\n[menunggu] {ex}")
                    return f"WAITING_HUMAN: {st['id']}"
                continue
            if s["state"] in ("PENDING", "FAILED", "STALE"):
                if s["state"] == "FAILED":
                    self.out("langkah ini gagal sebelumnya: " + "; ".join(s["record"]["payload"].get("guard_problems") or [f"rc={s['record']['payload'].get('returncode')}"])[:400])
                try:
                    self.approve(st["id"], "pre")
                except (RuntimeError, PermissionError) as ex:
                    self.out(f"\n[berhenti] {ex}")
                    return f"STOPPED: {st['id']}"
                s = self.state(st["id"])
            shown = False
            if s["state"] == "APPROVED":
                try:
                    rec = self.run(st["id"])
                except (RuntimeError, PermissionError) as ex:
                    self.out(f"\n[gagal] {ex}")
                    return f"ERROR: {st['id']}"
                self._show_result(st, rec)
                shown = True
                if not rec["payload"]["ok"]:
                    return f"FAILED: {st['id']}"
                s = self.state(st["id"])
            if s["state"] == "AWAITING_REVIEW":
                if not shown:
                    self._show_result(st, s["record"])
                try:
                    self.approve(st["id"], "post")
                except PermissionError as ex:
                    self.out(f"\n[berhenti] {ex}")
                    return f"STOPPED_REVIEW: {st['id']}"
            if until and st["id"].startswith(until):
                return "UNTIL"
        return "ALL_DONE"

    def _show_result(self, st: dict, rec: dict) -> None:
        p = rec["payload"]
        self.out(f"\n--- HASIL {st['id']}: {'OK' if p['ok'] else 'GAGAL'} (rc={p['returncode']}) ---")
        for r in p.get("runs", []):
            tail = (r.get("stdout") or "").strip()[-1500:]
            if tail:
                self.out(tail)
            if r.get("returncode"):
                self.out((r.get("stderr") or "").strip()[-1500:])
        for g in p.get("guard_problems", [])[:10]:
            self.out("PENJAGA: " + g)
        for o in st.get("outputs", []):
            f = self.repo / o
            if f.is_file():
                n = sum(1 for _ in open(f, encoding="utf-8", errors="ignore")) if f.suffix in (".jsonl", ".csv", ".md") else None
                self.out(f"keluaran: {o}  {f.stat().st_size} B" + (f"  {n} baris" if n is not None else ""))
            elif f.is_dir():
                self.out(f"keluaran: {o}/  {sum(1 for _ in f.rglob('*') if _.is_file())} berkas")


# ------------------------------------------------------------------ envcheck & CLI

def envcheck(env: dict | None = None) -> int:
    import importlib

    env = os.environ if env is None else env
    bad = 0
    print(f"python {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print("GAGAL: butuh Python >= 3.10")
        bad += 1
    for mod in ("numpy", "pypdf", "httpx", "reducto", "sentence_transformers"):
        try:
            importlib.import_module(mod)
            print(f"ok     {mod}")
        except Exception as ex:  # noqa: BLE001
            print(f"HILANG {mod}  ({type(ex).__name__})")
            bad += 1
    for k in ("REDUCTO_API_KEY", "MIMO_API_KEY", "TA_VALIDATOR"):
        print(f"{'ada   ' if env.get(k) else 'BELUM '} {k}  (nilai tidak ditampilkan)")
    return 1 if bad else 0


def check_cwd(repo: Path = REPO, cwd: Path | None = None) -> str | None:
    """Pesan galat bila direktori kerja di luar repo tempat `ta_rag` dimuat. Kasus nyata: worktree Studi 2 yang menjalankan
    `python -m ta_rag.agent` dengan instalasi editable milik main akan memakai config/ dan data/ MAIN tanpa pemberitahuan."""
    cwd = Path(cwd or Path.cwd()).resolve()
    if cwd == repo or repo in cwd.parents:
        return None
    return (f"ta_rag dimuat dari {repo}, tetapi direktori kerja {cwd} berada di luar repo itu: agent akan memakai config/ dan data/ milik {repo}. "
            f"Jalankan dari repo yang sama, atau set PYTHONPATH=src di repo tempat Anda berada.")


def main(argv=None) -> int:  # pragma: no cover - perekat tipis; kelas Agent yang diuji
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status"); sub.add_parser("next"); sub.add_parser("verify"); sub.add_parser("envcheck")
    for n in ("plan", "run", "done"):
        sub.add_parser(n).add_argument("stage")
    ap_ = sub.add_parser("approve"); ap_.add_argument("stage"); ap_.add_argument("--post", action="store_true")
    rj = sub.add_parser("reject"); rj.add_argument("stage"); rj.add_argument("--reason", required=True)
    dr = sub.add_parser("drive"); dr.add_argument("--until")
    a = ap.parse_args(argv)
    if msg := check_cwd():
        print(msg, file=sys.stderr)
        return 2
    if a.cmd == "envcheck":
        return envcheck()
    ag = Agent()
    try:
        if a.cmd == "status":
            for sid, kind, state, extra in ag.status_table():
                print(f"{sid:<26} {kind:<6} {state:<16} {extra}")
        elif a.cmd == "next":
            n = ag.next_stage()
            print(n or "SEMUA SELESAI")
            if n:
                st = stage_by_id(ag.wf, n)
                print(st["title"]); print(st.get("instructions", "") or "")
        elif a.cmd == "plan":
            st = stage_by_id(ag.wf, a.stage); ag._show_plan(st, ag.plan(a.stage)); print("frasa:", phrase_pre(st, ag.plan(a.stage)))
        elif a.cmd == "approve":
            ag.approve(a.stage, "post" if a.post else "pre"); print("tercatat")
        elif a.cmd == "run":
            rec = ag.run(a.stage); ag._show_result(stage_by_id(ag.wf, a.stage), rec); return 0 if rec["payload"]["ok"] else 1
        elif a.cmd == "done":
            ag.done(a.stage); print("tercatat")
        elif a.cmd == "reject":
            ag.reject(a.stage, a.reason); print("penolakan tercatat")
        elif a.cmd == "verify":
            pr = ag.verify()
            print("\n".join(pr) if pr else "LEDGER UTUH; tidak ada drift")
            return 1 if pr else 0
        else:
            print(ag.drive(a.until))
    except (PermissionError, RuntimeError, FileNotFoundError, KeyError) as ex:
        print(f"DITOLAK: {ex}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
