"""Uji perekat agent: gerbang persetujuan, ledger, plan-hash, drift, dan konsistensi workflow.json dengan CLI nyata.

Catatan kejujuran: tes ini memakai workflow KECIL buatan dan runner tiruan karena belum ada log nyata (tidak ada kunci/PDF/label di
sesi pembangunan). Itu hanya menguji MEKANISME gerbang. Data penelitian tidak pernah dibuat dengan cara ini: penjaga data asli
(tests/test_guards.py) menolaknya saat alur sungguhan berjalan.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ta_rag import agent, guards

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


def wf(*stages):
    return {"stages": list(stages)}


def A(sid, needs=(), **kw):
    return {"id": sid, "title": sid, "kind": "auto", "needs": list(needs), "cmd": ["{python}", "-c", "pass"], "outputs": kw.pop("outputs", []), **kw}


def H(sid, needs=(), evidence=("ev.txt",), **kw):
    return {"id": sid, "title": sid, "kind": "human", "needs": list(needs), "evidence": list(evidence), "instructions": "kerjakan", **kw}


class Script:
    """input() berskrip; gagal keras bila diminta lebih banyak dari yang disediakan."""

    def __init__(self, *answers):
        self.a, self.prompts = list(answers), []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        if not self.a:
            raise AssertionError(f"input tak terduga: {prompt!r}")
        return self.a.pop(0)


def make(tmp_path, workflow, *answers, tty=True, runner=None, env=None, clock=None):
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    out = []
    ag = agent.Agent(repo=tmp_path, wf=workflow, input_fn=Script(*answers), is_tty=lambda: tty, out=out.append, env=env or {},
                     clock=clock or Clock(), runner=runner or (lambda argv, t: {"returncode": 0, "stdout": "ok", "stderr": "", "duration_s": 0.0}))
    ag.printed = out
    return ag


def phrase(ag, sid):
    st = agent.stage_by_id(ag.wf, sid)
    return agent.phrase_pre(st, ag.plan(sid))


# ------------------------------------------------------------------ ledger

@pytest.mark.parametrize("change,expected_drift", [
    (None, []), ("source", ["A"]), ("later", ["B"]), ("untracked", ["A"])
])
def test_directory_hash_recognizes_later_owned_outputs_without_hiding_changes(tmp_path, change, expected_drift):
    first = A("A", outputs=["results/I"])
    later = A("B", needs=["A"], outputs=["results/I/test.json", "results/I/per_case.csv"])
    ag = make(tmp_path, wf(first, later))
    folder = tmp_path / "results/I"
    folder.mkdir(parents=True)
    source = folder / "selection.json"
    source.write_text("frozen selection")
    initial = agent.result_hash(first, tmp_path)
    ag.ledger.append("FINISHED", "A", ok=True, result_hash=initial, upstream={})
    (folder / "test.json").write_text("recorded test")
    (folder / "per_case.csv").write_text("recorded per-case")
    ag.ledger.append("FINISHED", "B", ok=True, result_hash=agent.result_hash(later, tmp_path), upstream={"A": initial})
    if change:
        changed = {"source": source, "later": folder / "test.json", "untracked": folder / "extra.txt"}[change]
        changed.write_text("changed")
    problems = ag.verify()
    assert [p.split(":", 1)[0].split(" ", 1)[1] for p in problems if p.startswith("DRIFT ")] == expected_drift
    assert ag.ledger.verify() == []


def test_ledger_chain_detects_edit_and_deletion(tmp_path):
    led = agent.Ledger(tmp_path / "l.jsonl", Clock())
    for i in range(3):
        led.append("E", f"S{i}", n=i)
    assert led.verify() == []
    lines = (tmp_path / "l.jsonl").read_text().splitlines()
    # ubah payload entri ke-2 tanpa menghitung ulang hash
    e = json.loads(lines[1]); e["payload"]["n"] = 99
    (tmp_path / "l.jsonl").write_text("\n".join([lines[0], json.dumps(e), lines[2]]) + "\n")
    assert any("hash entri tidak cocok" in p for p in led.verify())
    # hapus entri ke-2: rantai putus
    (tmp_path / "l.jsonl").write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert any("rantai putus" in p or "nomor urut" in p for p in led.verify())


def test_ledger_chain_survives_rehash_of_single_entry_only_if_chain_recomputed(tmp_path):
    """Penyerang yang menghitung ulang hash satu entri tetap memutus entri berikutnya (prev)."""
    led = agent.Ledger(tmp_path / "l.jsonl", Clock())
    for i in range(3):
        led.append("E", "S", n=i)
    lines = (tmp_path / "l.jsonl").read_text().splitlines()
    e = json.loads(lines[1]); e["payload"]["n"] = 99
    body = {k: v for k, v in e.items() if k != "hash"}
    e["hash"] = agent._h(agent.canonical(body))
    (tmp_path / "l.jsonl").write_text("\n".join([lines[0], json.dumps(e), lines[2]]) + "\n")
    probs = led.verify()
    assert probs and any("rantai putus" in p for p in probs)


# ------------------------------------------------------------------ workflow

def test_workflow_validation_rejects_bad_structure():
    with pytest.raises(ValueError, match="ganda"):
        agent.validate_workflow(wf(A("S1"), A("S1")))
    with pytest.raises(ValueError, match="mendahului"):
        agent.validate_workflow(wf(A("S1", needs=["S2"]), A("S2")))
    with pytest.raises(ValueError, match="kind"):
        agent.validate_workflow(wf({**A("S1"), "kind": "robot"}))
    with pytest.raises(ValueError, match="cmd"):
        agent.validate_workflow(wf({"id": "S1", "title": "x", "kind": "auto"}))
    with pytest.raises(ValueError, match="penjaga"):
        agent.validate_workflow(wf(A("S1", guards_post=["tidak_ada"])))
    with pytest.raises(ValueError, match="instructions"):
        agent.validate_workflow(wf({"id": "S1", "title": "x", "kind": "human"}))


def test_real_workflow_loads_and_is_acyclic():
    w = agent.load_workflow(REPO / "config" / "workflow.json")
    assert len(w["stages"]) >= 30
    assert [s["id"] for s in w["stages"]][0] == "S00_env"


def test_real_workflow_relabel_gate_matches_protocol():
    """Gerbang waktu S26 harus sama dengan protocol.json (D15); selisih membuat agent menahan relabel lebih lama dari yang dipra-registrasi."""
    w = agent.load_workflow(REPO / "config" / "workflow.json")
    gate = next(s for s in w["stages"] if s["id"] == "S26_relabel")["not_before"]["hours"]
    protocol = json.loads((REPO / "config" / "protocol.json").read_text(encoding="utf-8"))
    assert gate == protocol["relabel"]["min_gap_hours"]


def test_real_workflow_inputs_are_produced_upstream_or_static():
    """Tiap masukan harus berkas statis di repo atau keluaran/bukti langkah SEBELUMNYA (menangkap salah urutan)."""
    w = agent.load_workflow(REPO / "config" / "workflow.json")
    produced: list[str] = []
    static_ok = ("config/", "data/cases/")
    for s in w["stages"]:
        for p in s.get("inputs", []):
            ok = p.startswith(static_ok) and (REPO / p).exists() and p not in sum(([*x.get("outputs", []), *x.get("evidence", [])] for x in w["stages"]), []) \
                or any(p == q or p.startswith(q.rstrip("/") + "/") or q.startswith(p.rstrip("/") + "/") for q in produced) \
                or p == "data/raw_pdf" or p in ("config/protocol.json", "config/generator.json", "config/corpus.json", agent.WORKFLOW.name)
            assert ok, f"{s['id']}: masukan {p} tidak dihasilkan langkah hulu"
        produced += s.get("outputs", []) + s.get("evidence", [])


def test_real_workflow_every_dependency_chain_reaches_start():
    w = agent.load_workflow(REPO / "config" / "workflow.json")
    ids = {s["id"] for s in w["stages"]}
    for s in w["stages"][1:]:
        assert s.get("needs"), f"{s['id']} tidak punya needs (alur bisa dilompati)"
        assert set(s["needs"]) <= ids


def _help_text(module: str, sub: str | None) -> str | None:
    cmd = [sys.executable, "-m", module] + ([sub] if sub else []) + ["--help"]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"})
    return r.stdout if r.returncode == 0 else None


def test_real_workflow_commands_match_actual_cli_options():
    """Setiap opsi (--x) dan subcommand pada workflow.json harus benar-benar diterima CLI modulnya (bukan sekadar teks)."""
    w = agent.load_workflow(REPO / "config" / "workflow.json")
    checked = 0
    for s in w["stages"]:
        if s["kind"] != "auto" or not s.get("cmd"):
            continue
        cmd = s["cmd"]
        if cmd[1:3] == ["-m", "pytest"]:
            continue
        mod = cmd[2]
        assert (REPO / "src" / Path(*mod.split(".")).with_suffix(".py")).exists(), f"{s['id']}: modul {mod} tidak ada"
        rest = cmd[3:]
        sub = rest[0] if rest and not rest[0].startswith(("--", "{")) else None
        h = _help_text(mod, sub)
        if h is None:
            pytest.skip(f"--help {mod} {sub} tidak dapat dijalankan di lingkungan ini (dependensi opsional)")
        for tok in rest:
            if tok.startswith("--") and tok != "--help":
                assert tok in h, f"{s['id']}: opsi {tok} tidak ada pada `{mod} {sub or ''} --help`"
        checked += 1
    assert checked >= 20


# ------------------------------------------------------------------ gerbang persetujuan

def test_agent_without_tty_cannot_approve_or_finish(tmp_path):
    ag = make(tmp_path, wf(A("S1")), tty=False)
    with pytest.raises(PermissionError, match="TTY"):
        ag.approve("S1")
    assert ag.entries() == []
    with pytest.raises(PermissionError, match="TTY"):
        ag.reject("S1", "x")
    with pytest.raises(PermissionError, match="TTY"):
        ag.drive()


def test_wrong_phrase_records_nothing_and_blocks_run(tmp_path):
    ag = make(tmp_path, wf(A("S1")), "SETUJU S1 00000000")
    with pytest.raises(PermissionError, match="frasa"):
        ag.approve("S1")
    assert ag.entries() == []
    with pytest.raises(PermissionError, match="belum disetujui"):
        ag.run("S1")


def test_approved_plan_runs_once_then_requires_reapproval(tmp_path):
    calls = []
    ag = make(tmp_path, wf(A("S1")), runner=lambda argv, t: calls.append(argv) or {"returncode": 0, "stdout": "", "stderr": "", "duration_s": 0})
    ag.input.a.append(phrase(ag, "S1"))
    ag.approve("S1")
    assert ag.state("S1")["state"] == "APPROVED"
    rec = ag.run("S1")
    assert rec["payload"]["ok"] and ag.state("S1")["state"] == "DONE" and len(calls) == 1
    with pytest.raises(RuntimeError, match="sudah selesai"):
        ag.approve("S1")
    with pytest.raises(PermissionError):  # persetujuan sudah habis dipakai
        ag.run("S1")


def test_changing_an_input_after_approval_invalidates_it(tmp_path):
    (tmp_path / "in.txt").write_text("v1")
    ag = make(tmp_path, wf(A("S1", inputs=["in.txt"])))
    ag.input.a.append(phrase(ag, "S1"))
    ag.approve("S1")
    (tmp_path / "in.txt").write_text("v2")  # berkas masukan berubah setelah disetujui
    with pytest.raises(PermissionError, match="berubah"):
        ag.run("S1")
    assert ag.state("S1")["state"] == "PENDING"
    assert [e["event"] for e in ag.entries()][-1] == "INVALIDATED"


def test_blocked_stage_cannot_be_approved_or_run(tmp_path):
    ag = make(tmp_path, wf(A("S1"), A("S2", needs=["S1"])))
    assert ag.state("S2")["state"] == "BLOCKED"
    with pytest.raises(RuntimeError, match="terblokir"):
        ag.approve("S2")


def test_irreversible_stage_needs_extra_words(tmp_path):
    w = wf(A("S1", cost="irreversible"))
    ag = make(tmp_path, w)
    base = phrase(ag, "S1")
    assert base.endswith("TIDAK-BISA-DIULANG")
    ag.input.a.append(base.replace(" TIDAK-BISA-DIULANG", ""))
    with pytest.raises(PermissionError):
        ag.approve("S1")
    ag.input.a.append(base)
    ag.approve("S1")
    ag.run("S1")
    # sudah selesai -> tak bisa diulang tanpa reject bertanda alasan
    with pytest.raises(RuntimeError):
        ag.approve("S1")
    ag.reject("S1", "kesalahan dicatat")
    assert ag.state("S1")["state"] == "PENDING"


def test_review_gate_requires_result_hash_phrase(tmp_path):
    def runner(argv, t):
        (tmp_path / "out.txt").write_text("hasil")
        return {"returncode": 0, "stdout": "", "stderr": "", "duration_s": 0}

    ag = make(tmp_path, wf(A("S1", review_outputs=True, outputs=["out.txt"])), runner=runner)
    ag.input.a.append(phrase(ag, "S1")); ag.approve("S1"); ag.run("S1")
    assert ag.state("S1")["state"] == "AWAITING_REVIEW"
    ag.input.a.append("TERIMA S1 deadbeef")
    with pytest.raises(PermissionError):
        ag.approve("S1", "post")
    assert ag.state("S1")["state"] == "AWAITING_REVIEW"
    rh = ag.state("S1")["record"]["payload"]["result_hash"]
    ag.input.a.append(agent.phrase_post(agent.stage_by_id(ag.wf, "S1"), rh))
    ag.approve("S1", "post")
    assert ag.state("S1")["state"] == "DONE"


def test_nonzero_exit_or_missing_output_is_failed_not_done(tmp_path):
    ag = make(tmp_path, wf(A("S1")), runner=lambda a, t: {"returncode": 3, "stdout": "", "stderr": "boom", "duration_s": 0})
    ag.input.a.append(phrase(ag, "S1")); ag.approve("S1"); ag.run("S1")
    assert ag.state("S1")["state"] == "FAILED"
    ag2 = make(tmp_path / "b", wf(A("S1", outputs=["tidak_ada.txt"])))
    ag2.input.a.append(phrase(ag2, "S1")); ag2.approve("S1"); rec = ag2.run("S1")
    assert not rec["payload"]["ok"] and "keluaran hilang" in rec["payload"]["guard_problems"][0]
    assert ag2.state("S1")["state"] == "FAILED"


def test_missing_env_variable_blocks_run_without_leaking_values(tmp_path):
    ag = make(tmp_path, wf(A("S1", env_required=["MIMO_API_KEY"])), env={})
    ag.input.a.append(phrase(ag, "S1")); ag.approve("S1")
    with pytest.raises(RuntimeError, match="MIMO_API_KEY"):
        ag.run("S1")
    ag2 = make(tmp_path / "c", wf(A("S1", env_required=["MIMO_API_KEY"])), env={"MIMO_API_KEY": "sk-RAHASIA-123"})
    ag2.input.a.append(phrase(ag2, "S1")); ag2.approve("S1"); ag2.run("S1")
    assert "sk-RAHASIA-123" not in (tmp_path / "c" / "data" / "agent" / "ledger.jsonl").read_text()


# ------------------------------------------------------------------ penjaga di dalam alur

def test_guard_failure_before_run_blocks_and_is_logged(tmp_path, monkeypatch):
    monkeypatch.setitem(guards.REGISTRY, "selalu_gagal", lambda repo: ["data palsu terdeteksi"])
    ag = make(tmp_path, wf(A("S1", guards_pre=["selalu_gagal"])))
    with pytest.raises(RuntimeError, match="penjaga pra-langkah"):
        ag.approve("S1")
    assert ag.entries()[-1]["event"] == "GUARD_FAILED"
    assert ag.state("S1")["state"] == "PENDING"


def test_guard_failure_after_run_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setitem(guards.REGISTRY, "gagal_pasca", lambda repo: ["keluaran tanpa provenans"])
    ag = make(tmp_path, wf(A("S1", guards_post=["gagal_pasca"])))
    ag.input.a.append(phrase(ag, "S1")); ag.approve("S1")
    rec = ag.run("S1")
    assert rec["payload"]["ok"] is False and ag.state("S1")["state"] == "FAILED"
    assert "keluaran tanpa provenans" in rec["payload"]["guard_problems"][0]


def test_human_stage_requires_evidence_guard_and_exact_phrase(tmp_path, monkeypatch):
    monkeypatch.setitem(guards.REGISTRY, "bukti_buruk", lambda repo: ["bukti tidak sah"])
    ag = make(tmp_path, wf(H("S1", guards_post=["bukti_buruk"])))
    with pytest.raises(FileNotFoundError):
        ag.done("S1")
    (tmp_path / "ev.txt").write_text("kerja")
    with pytest.raises(RuntimeError, match="penjaga menolak"):
        ag.done("S1")
    monkeypatch.setitem(guards.REGISTRY, "bukti_buruk", lambda repo: [])
    ag.input.a.append("SELESAI S1 00000000")
    with pytest.raises(PermissionError):
        ag.done("S1")
    rh = agent.result_hash(agent.stage_by_id(ag.wf, "S1"), tmp_path)
    ag.input.a.append(agent.phrase_done(agent.stage_by_id(ag.wf, "S1"), rh))
    ag.done("S1")
    assert ag.state("S1")["state"] == "DONE"


def test_time_gate_blocks_relabel_until_gap_passes(tmp_path):
    clock = Clock()
    ag = make(tmp_path, wf(A("S1"), H("S2", needs=["S1"], not_before={"stage": "S1", "hours": 24, "override_env": "AKUI"})), clock=clock)
    ag.input.a.append(phrase(ag, "S1")); ag.approve("S1"); ag.run("S1")
    (tmp_path / "ev.txt").write_text("x")
    clock.advance(hours=23)
    with pytest.raises(RuntimeError, match="belum boleh sebelum"):
        ag.done("S2")
    clock.advance(hours=2)
    rh = agent.result_hash(agent.stage_by_id(ag.wf, "S2"), tmp_path)
    ag.input.a.append(agent.phrase_done(agent.stage_by_id(ag.wf, "S2"), rh))
    ag.done("S2")
    assert ag.state("S2")["state"] == "DONE"


def test_time_gate_override_is_explicit_env_only(tmp_path):
    clock = Clock()
    ag = make(tmp_path, wf(A("S1"), H("S2", needs=["S1"], not_before={"stage": "S1", "hours": 24, "override_env": "AKUI"})), clock=clock,
              env={"AKUI": "1"})
    ag.input.a.append(phrase(ag, "S1")); ag.approve("S1"); ag.run("S1")
    (tmp_path / "ev.txt").write_text("x")
    rh = agent.result_hash(agent.stage_by_id(ag.wf, "S2"), tmp_path)
    ag.input.a.append(agent.phrase_done(agent.stage_by_id(ag.wf, "S2"), rh))
    ag.done("S2")  # tidak ada penolakan: override disetel sadar


# ------------------------------------------------------------------ stale & drift

def test_upstream_rerun_with_changed_result_makes_downstream_stale(tmp_path):
    def runner(argv, t):
        (tmp_path / "a.txt").write_text(runner.val)
        return {"returncode": 0, "stdout": "", "stderr": "", "duration_s": 0}
    runner.val = "v1"
    ag = make(tmp_path, wf(A("S1", outputs=["a.txt"]), A("S2", needs=["S1"], inputs=["a.txt"])), runner=runner)
    for sid in ("S1", "S2"):
        ag.input.a.append(phrase(ag, sid)); ag.approve(sid); ag.run(sid)
    assert ag.state("S2")["state"] == "DONE"
    ag.reject("S1", "ulang"); runner.val = "v2"
    ag.input.a.append(phrase(ag, "S1")); ag.approve("S1"); ag.run("S1")
    assert ag.state("S1")["state"] == "DONE"
    assert ag.state("S2")["state"] == "STALE"


def test_verify_reports_drift_but_not_for_mutable_outputs(tmp_path):
    def runner(argv, t):
        (tmp_path / "o.txt").write_text("asli"); (tmp_path / "m.txt").write_text("asli")
        return {"returncode": 0, "stdout": "", "stderr": "", "duration_s": 0}
    ag = make(tmp_path, wf(A("S1", outputs=["o.txt"]), A("S2", outputs=["m.txt"], mutable_outputs=True)), runner=runner)
    for sid in ("S1", "S2"):
        ag.input.a.append(phrase(ag, sid)); ag.approve(sid); ag.run(sid)
    assert ag.verify() == []
    (tmp_path / "o.txt").write_text("disunting"); (tmp_path / "m.txt").write_text("diisi manusia")
    probs = ag.verify()
    assert any("DRIFT S1" in p for p in probs) and not any("DRIFT S2" in p for p in probs)


# ------------------------------------------------------------------ drive & placeholder

class Typist:
    """Manusia yang mengetik persis apa yang diminta prompt (jalur bahagia)."""

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        m = re.search(r":\s+(\S[^\n]*)\n>", prompt)
        assert m, f"prompt tak dikenal: {prompt!r}"
        return m.group(1).strip()


def test_drive_stops_at_human_work_then_resumes(tmp_path):
    w = wf(A("S1"), H("S2", needs=["S1"]), A("S3", needs=["S2"]))
    ag = make(tmp_path, w)
    ag.input = Typist()
    assert ag.drive() == "WAITING_HUMAN: S2"
    assert ag.state("S1")["state"] == "DONE" and ag.state("S3")["state"] == "BLOCKED"
    (tmp_path / "ev.txt").write_text("kerja manusia")
    assert ag.drive() == "ALL_DONE"
    assert [ag.state(x)["state"] for x in ("S1", "S2", "S3")] == ["DONE"] * 3
    assert ag.ledger.verify() == [] and ag.verify() == []


def test_drive_review_stage_needs_second_phrase(tmp_path):
    ag = make(tmp_path, wf(A("S1", review_outputs=True)))
    ag.input = Typist()
    assert ag.drive() == "ALL_DONE"
    assert any("TERIMA" in p for p in ag.input.prompts) and any("SETUJU" in p for p in ag.input.prompts)


def test_drive_stops_on_wrong_phrase_without_running(tmp_path):
    calls = []
    ag = make(tmp_path, wf(A("S1")), "ketik apa saja", runner=lambda a, t: calls.append(a))
    assert ag.drive().startswith("STOPPED")
    assert calls == []


def test_placeholders_env_opt_and_today():
    st = {"id": "S", "kind": "auto", "cmd": ["{python}", "-m", "x", "--v", "{env:TA_VALIDATOR}", "{opt:AKUI=--accept-short-gap}", "--date", "{today}"]}
    assert agent.resolve_cmds(st, REPO, {"TA_VALIDATOR": "Galih"}, "2026-11-05") == [["{python}", "-m", "x", "--v", "Galih", "--date", "2026-11-05"]]
    assert "--accept-short-gap" in agent.resolve_cmds(st, REPO, {"TA_VALIDATOR": "G", "AKUI": "1"}, "d")[0]
    with pytest.raises(KeyError, match="TA_VALIDATOR"):
        agent.resolve_cmds(st, REPO, {}, "d")


def test_plan_hash_is_independent_of_interpreter_path_but_depends_on_command(tmp_path):
    a = agent.build_plan(A("S1"), tmp_path, [], {}, "d")
    b = agent.build_plan({**A("S1"), "cmd": ["{python}", "-c", "print(1)"]}, tmp_path, [], {}, "d")
    assert a["plan_hash"] != b["plan_hash"]
    assert "python3" not in json.dumps(a) and "{python}" in json.dumps(a)


def test_hash_path_directory_changes_with_content_and_ignores_pycache(tmp_path):
    d = tmp_path / "d"; d.mkdir(); (d / "a").write_text("1")
    h1 = agent.hash_path(d)
    (d / "__pycache__").mkdir(); (d / "__pycache__" / "x.pyc").write_text("z")
    assert agent.hash_path(d) == h1
    (d / "a").write_text("2")
    assert agent.hash_path(d) != h1
    assert agent.hash_path(tmp_path / "tidak_ada") == "ABSENT"


def test_dry_run_previews_the_same_scoped_plan_as_the_full_parse():
    """Dry-run yang menampilkan 1346 halaman padahal pilot hanya 267 akan menyesatkan keputusan biaya."""
    full = agent.DYNAMIC["parse_full"](REPO)
    dry = agent.DYNAMIC["parse_full_dry"](REPO)
    assert len(full) == len(dry) >= 2
    for f, d in zip(full, dry):
        assert d[-1] == "--dry-run" and "--dry-run" not in f
        assert d[d.index("--out-dir") + 1] == "data/reducto_dryrun" and f[f.index("--out-dir") + 1] == "data/reducto"
        assert [t for t in d if t not in ("data/reducto_dryrun", "--dry-run")] == [t for t in f if t != "data/reducto"]
    assert any("--page-range" in d and "1-91" in d for d in dry)  # Permenkes 3/2023 hanya hlm. 1-91
    assert all("--only" in d for d in dry)  # tidak pernah memparse seluruh folder


def test_drive_shows_each_result_once(tmp_path):
    ag = make(tmp_path, wf(A("S1", review_outputs=True)))
    ag.input = Typist()
    ag.drive()
    assert sum("--- HASIL S1" in line for line in ag.printed) == 1


def test_check_cwd_flags_cwd_outside_repo_including_sibling_with_same_prefix(tmp_path):
    repo = tmp_path / "ta-rag-eval"
    (repo / "sub").mkdir(parents=True)
    sibling = tmp_path / "ta-rag-eval-studi2"  # worktree Studi 2: awalan sama, repo berbeda
    sibling.mkdir()
    assert agent.check_cwd(repo, repo) is None and agent.check_cwd(repo, repo / "sub") is None
    msg = agent.check_cwd(repo, sibling)
    assert msg and str(repo) in msg and str(sibling) in msg and "PYTHONPATH=src" in msg
    assert agent.check_cwd(repo, tmp_path) is not None
