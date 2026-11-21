"""Pustaka JS halaman relabel (src/ta_rag/relabel_page.js), diuji lewat node. Data tiruan hanya di tmp_path."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ta_rag import corpus, data, labeling
from ta_rag import relabel_page as RP

JS = Path(__file__).resolve().parents[1] / "src" / "ta_rag" / "relabel_page.js"
COLS = ["item_id", "case_id", "question", "answer", "kind", "source_quote", "rubric", "label_baru", "alasan_bila_berbeda"]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node tidak terpasang")


def _run(js: str, payload) -> bytes:
    prelude = (f"const L = require({json.dumps(str(JS))}); const p = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
               "const out = v => process.stdout.write(JSON.stringify(v));")
    r = subprocess.run(["node", "-e", prelude + js], input=json.dumps(payload).encode("utf-8"), capture_output=True, check=False)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return r.stdout


def _node(js: str, payload=None):
    return json.loads(_run(js, payload).decode("utf-8"))


TRICKY_Q = "</script><script>alert(1)</script><!-- Pasal 7"
TRICKY_A = 'Jawaban "kutip", koma\nbaris dua\r\nbaris tiga ≥ – é '


@pytest.fixture
def blank_sheet(tmp_path):
    def row(i, kind, q, a):
        return {"item_id": f"R0{i}", "case_id": f"C{i}", "question": q, "answer": a, "kind": kind,
                "source_quote": "kutipan", "rubric": "rubrik", "label_baru": "", "alasan_bila_berbeda": ""}
    rows = [row(1, "answerable", "Pertanyaan satu?", "Jawaban satu."), row(2, "answerable", TRICKY_Q, TRICKY_A),
            row(3, "not_in_corpus", "Pertanyaan tiga?", "Tidak ada.")]
    p = tmp_path / "blank.csv"
    labeling._write_csv(p, rows, COLS)
    return p


@pytest.fixture
def import_env(tmp_path):
    ids = {"R01": "run1:T01", "R02": "M1:T02", "R03": "run2:T03"}
    meta = {"run1:T01": ("T01", "natural", "answerable", "LAYAK"), "M1:T02": ("T02", "mutation", "answerable", "TIDAK_LAYAK"),
            "run2:T03": ("T03", "natural", "not_in_corpus", "INSUFFICIENT_EVIDENCE")}
    allp = tmp_path / "labels_all.jsonl"
    allp.write_text("\n".join(json.dumps({"answer_id": a, "case_id": c, "label": lab, "labeled_at": "2026-01-01T00:00:00+00:00", "origin": o,
                                          "kind": k, "validator": "Validator Satu"}) for a, (c, o, k, lab) in meta.items()) + "\n", encoding="utf-8")
    sp = tmp_path / "relabel_sample.json"
    sp.write_text(json.dumps({"answer_ids": list(ids.values()), "items": ids, "composition": {}, "strata_short": []}), encoding="utf-8")
    return allp, sp, {"relabel": {"min_gap_hours": 24, "disclosure": "uji"}}


def _filled_csv(blank, tmp_path):
    rows = labeling._read_csv(blank)
    js = ("let s = {}; const nb = 1000, now = 2000;"
          "s = L.setField(s, 'R01', 'label_baru', 'LAYAK', now, nb);"
          "s = L.setField(s, 'R02', 'label_baru', 'TIDAK_LAYAK', now, nb);"
          "s = L.setField(s, 'R02', 'alasan_bila_berbeda', 'beda, \"kutip\"\\nbaris', now, nb);"
          "s = L.setField(s, 'R03', 'label_baru', 'INSUFFICIENT_EVIDENCE', now, nb);"
          "process.stdout.write(L.toCSV(p.columns, L.fillRows(p.rows, s)));")
    out = tmp_path / "ekspor.csv"
    out.write_bytes(_run(js, {"columns": COLS, "rows": rows}))
    return out


@needs_node
def test_js_labels_match_python():
    assert _node("out(L.LABELS)") == list(data.LABELS)


def test_js_has_no_script_close():
    src = JS.read_text(encoding="utf-8")
    low = src.lower()
    assert "</script" not in low and "<script" not in low and "<!--" not in src
    assert chr(0xFEFF) not in src  # BOM ditulis lewat String.fromCharCode, bukan karakter literal
    assert "(?<" not in src  # tanpa lookbehind: Safari < 16.4 gagal mengurai seluruh skrip


@needs_node
def test_tocsv_bytes_equal_python_writer(blank_sheet):
    got = _run("process.stdout.write(L.toCSV(p.columns, p.rows));", {"columns": COLS, "rows": labeling._read_csv(blank_sheet)})
    assert got == blank_sheet.read_bytes()


@needs_node
def test_tocsv_bare_cr_and_empty_match_python_writer(tmp_path):
    rows = [{"a": "x\ry", "b": "", "c": 'q"q'}, {"a": "plain", "b": "1,2", "c": " "}]
    ref = tmp_path / "ref.csv"
    labeling._write_csv(ref, rows, ["a", "b", "c"])
    assert _run("process.stdout.write(L.toCSV(p.columns, p.rows));", {"columns": ["a", "b", "c"], "rows": rows}) == ref.read_bytes()


@needs_node
def test_export_roundtrip_relabel_import(blank_sheet, import_env, tmp_path):
    allp, sp, proto = import_env
    exported = _filled_csv(blank_sheet, tmp_path)
    res = labeling.import_relabel_sheet(exported, sp, allp, proto, tmp_path / "out.jsonl", tmp_path / "res.json")
    assert res["n"] == 3
    recs = {r["answer_id"]: r for r in labeling._jsonl(tmp_path / "out.jsonl")}
    assert [recs[a]["label_second"] for a in ("run1:T01", "M1:T02", "run2:T03")] == ["LAYAK", "TIDAK_LAYAK", "INSUFFICIENT_EVIDENCE"]
    assert recs["M1:T02"]["reason_if_different"] == 'beda, "kutip"\nbaris'
    blank, back = labeling._read_csv(blank_sheet), labeling._read_csv(exported)
    keep = [c for c in COLS if c not in ("label_baru", "alasan_bila_berbeda")]
    assert [{c: r[c] for c in keep} for r in back] == [{c: r[c] for c in keep} for r in blank]
    assert back[1]["answer"] == TRICKY_A and back[1]["question"] == TRICKY_Q


@needs_node
def test_export_roundtrip_second_rater(blank_sheet, import_env, tmp_path):
    allp, sp, _ = import_env
    exported = _filled_csv(blank_sheet, tmp_path)
    res = labeling.import_second_rater(exported, sp, allp, tmp_path / "o2.jsonl", tmp_path / "r2.json", rater="Penilai Uji", ai_assistance="none")
    assert res["eligible_as_inter_rater"] is True


@needs_node
def test_mark_escapes_and_marks():
    hostile = _node("out(L.mark(p))", "<img src=x onerror=alert(1)> </script><!-- " + TRICKY_Q + " Pasal 7 lebih 100")
    assert "<" not in re.sub(r'<mark class="(?:ref|num|kw)">|</mark>', "", hostile) and "&lt;img" in hostile
    out = _node("out(L.mark(p))", '<script>x</script> Pasal 7 ayat (2) lebih dari 100 Sebelum Rp8.000,00 30% huruf a')
    assert "<script>" not in out and "&lt;script&gt;" in out
    for s in ['<mark class="ref">Pasal 7</mark>', '<mark class="ref">ayat (2)</mark>', '<mark class="ref">huruf a</mark>',
              '<mark class="num">100</mark>', '<mark class="num">Rp8.000,00</mark>', '<mark class="num">30%</mark>',
              '<mark class="kw">lebih</mark>', '<mark class="kw">Sebelum</mark>']:
        assert s in out
    assert "<mark" not in _node("out(L.mark(p))", "ketidakadilan sebelumnya")  # kata utuh saja
    assert _node("out(L.mark(p))", "a & b") == "a &amp; b"


@needs_node
def test_setfield_gate_and_validation():
    js = """
    const r = {};
    const t = f => { try { f(); return null; } catch (e) { return e instanceof Error ? e.message : "bukan Error"; } };
    const s0 = {};
    r.early_label = t(() => L.setField(s0, 'R01', 'label_baru', 'LAYAK', 99, 100));
    r.early_reason = t(() => L.setField(s0, 'R01', 'alasan_bila_berbeda', 'x', 99, 100));
    r.edge = L.setField(s0, 'R01', 'label_baru', 'LAYAK', 100, 100);
    r.after = L.setField(s0, 'R01', 'alasan_bila_berbeda', 'x', 101, 100);
    r.nogate = L.setField(s0, 'R01', 'label_baru', 'LAYAK', 1, null);
    r.bad_label = t(() => L.setField(s0, 'R01', 'label_baru', 'OK', 1, null));
    r.bad_field = t(() => L.setField(s0, 'R01', 'case_id', 'LAYAK', 1, null));
    const bad = {};
    for (const [k, now, nb] of [["nb_nan", 100, NaN], ["now_nan", NaN, 100], ["now_undef", undefined, 100], ["nb_string", 100, "2026-11-20"],
                                ["nb_inf", 100, Infinity], ["now_inf", Infinity, 100]]) {
      bad[k] = t(() => L.setField(s0, 'R01', 'label_baru', 'LAYAK', now, nb));
      bad[k + "_alasan"] = t(() => L.setField(s0, 'R01', 'alasan_bila_berbeda', 'x', now, nb));
    }
    r.bad = bad;
    r.undef_gate = L.setField(s0, 'R01', 'label_baru', 'LAYAK', 1, undefined);
    r.s0 = s0;
    out(r);
    """
    r = _node(js)
    assert r["early_label"] and r["early_reason"] and r["early_label"] != "bukan Error"
    assert r["edge"] == {"R01": {"label_baru": "LAYAK"}} and r["after"] == {"R01": {"alasan_bila_berbeda": "x"}}
    assert r["nogate"] == {"R01": {"label_baru": "LAYAK"}}
    assert r["bad_label"] and r["bad_field"]
    assert len(r["bad"]) == 12 and all(m and m != "bukan Error" for m in r["bad"].values())  # gerbang waktu rusak = ditolak (fail closed)
    assert r["undef_gate"] == {"R01": {"label_baru": "LAYAK"}}
    assert r["s0"] == {}


@needs_node
def test_restorestate_sanitizes():
    rows = [{"item_id": i} for i in ("R01", "R02", "R03")]
    js = "out(L.restoreState(p.raw, p.rows));"
    raw = '{"R01":{"label_baru":"LAYAK","x":1},"R99":{"label_baru":"LAYAK"},"R02":{"label_baru":"OK"}}'
    assert _node(js, {"raw": raw, "rows": rows}) == {"R01": {"label_baru": "LAYAK"}}
    assert _node(js, {"raw": "bukan json", "rows": rows}) == {}
    assert _node(js, {"raw": None, "rows": rows}) == {}
    assert _node(js, {"raw": "[1,2]", "rows": rows}) == {}
    assert _node(js, {"raw": '{"R03":{"alasan_bila_berbeda":"a","label_baru":"TIDAK_LAYAK"}}', "rows": rows}) == \
        {"R03": {"label_baru": "TIDAK_LAYAK", "alasan_bila_berbeda": "a"}}


@needs_node
def test_missing_and_fillrows():
    rows = [{"item_id": i, "case_id": "c", "label_baru": "", "alasan_bila_berbeda": ""} for i in ("R01", "R02", "R03")]
    r = _node("const s = {R01: {label_baru: 'LAYAK', alasan_bila_berbeda: 'a'}}; const before = JSON.stringify(p);"
              "const f = L.fillRows(p, s); out({m: L.missing(p, s), f, same: before === JSON.stringify(p), m0: L.missing(p, {})});", rows)
    assert r["m"] == ["R02", "R03"] and r["m0"] == ["R01", "R02", "R03"] and r["same"] is True
    assert r["f"][0] == {"item_id": "R01", "case_id": "c", "label_baru": "LAYAK", "alasan_bila_berbeda": "a"}
    assert r["f"][1] == rows[1]


@needs_node
def test_keyaction():
    cases = [("1", "BODY", {"label": "LAYAK"}), ("3", "DIV", {"label": "INSUFFICIENT_EVIDENCE"}), ("2", "BODY", {"label": "TIDAK_LAYAK"}),
             ("ArrowRight", "BODY", {"move": 1}), ("ArrowLeft", "BODY", {"move": -1}),
             ("1", "TEXTAREA", None), ("2", "input", None), ("ArrowLeft", "textarea", None), ("x", "BODY", None)]
    assert _node("out(p.map(([k, t]) => L.keyAction(k, t)))", [[k, t] for k, t, _ in cases]) == [e for _, _, e in cases]


# ------------------------------------------------------------------ Task 2: pembangun halaman

REPO = Path(__file__).resolve().parents[1]
REAL = os.environ.get("TA_RAG_PDF_DIR")
REAL_SHEET = REPO / "data" / "labels" / "relabel_sheet_kosong_validator2.csv"
needs_real = pytest.mark.skipif(not REAL or not REAL_SHEET.exists(), reason="set TA_RAG_PDF_DIR dan sediakan lembar kosong asli")
INSTR = "Nilai tiap jawaban dengan rubrik di bawah. Jangan memakai alat AI."


def _make_pdf(path, pages):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    for lines in pages:
        for i, ln in enumerate(lines):
            c.drawString(60, 780 - 20 * i, ln)
        c.showPage()
    c.save()


@pytest.fixture
def env(tmp_path):
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    _make_pdf(pdfs / "A.pdf", [["Pasal 1", "Halaman satu dokumen A"], ["Pasal 2", "Halaman dua dokumen A"]])
    _make_pdf(pdfs / "B.pdf", [["BBBB BBBB BBBB", "BBBB BBBB BBBB BBBB", "BBBB", "BBBB BBBB"], ["Halaman dua dokumen B"]])

    def case(cid, f, page):
        return {"case_id": cid, "source_file": f, "source_page": page, "source_pdf_sha256": corpus.sha256_file(pdfs / f)}
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(json.dumps(c) for c in [case("C1", "A.pdf", 1), case("C2", "A.pdf", 1), case("C3", "B.pdf", 1)]) + "\n", encoding="utf-8")
    return pdfs, cases


def _data_of(html: str) -> dict:
    return json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))


def _build(blank_sheet, env, tmp_path, **kw):
    pdfs, cases = env
    args = dict(sheet_csv=blank_sheet, cases_jsonl=cases, pdf_dir=pdfs, out_html=tmp_path / "out" / "p.html",
                download_name="relabel_x.csv", dpi=30)
    args.update(kw)
    return RP.build_page(**args), args["out_html"]


def test_build_page_tmp(blank_sheet, env, tmp_path):
    info, out = _build(blank_sheet, env, tmp_path)
    html = out.read_text(encoding="utf-8")
    assert info["items"] == 3 and info["images"] == 2  # C1 dan C2 berbagi A#1; B#1 punya nomor halaman sama tetapi berkas lain
    assert info["bytes"] == out.stat().st_size and info["sheet_sha256"] == corpus.sha256_file(blank_sheet)
    assert html.count("data:image/png;base64,") == info["images"]
    d = _data_of(html)
    assert d["page_of"] == {"C1": "A.pdf#1", "C2": "A.pdf#1", "C3": "B.pdf#1"} and set(d["images"]) == {"A.pdf#1", "B.pdf#1"}
    assert d["images"]["A.pdf#1"] != d["images"]["B.pdf#1"]
    assert [r["item_id"] for r in d["rows"]] == ["R01", "R02", "R03"] and d["columns"] == COLS
    assert d["not_before_ms"] is None and d["download_name"] == "relabel_x.csv"
    assert INSTR in html and "http" not in html


def test_build_page_probe_has_no_image(blank_sheet, env, tmp_path):
    pdfs, cases = env
    rows = [json.loads(x) for x in cases.read_text(encoding="utf-8").splitlines()]
    rows[2]["source_page"] = None
    cases.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    info, out = _build(blank_sheet, env, tmp_path)
    d = _data_of(out.read_text(encoding="utf-8"))
    assert info["images"] == 1 and "C3" not in d["page_of"]


def test_build_page_not_before(blank_sheet, env, tmp_path):
    _, out = _build(blank_sheet, env, tmp_path, not_before="2026-11-19T20:12:00+07:00")
    d = _data_of(out.read_text(encoding="utf-8"))
    assert d["not_before_ms"] == 1795093920000 and isinstance(d["not_before_ms"], int)
    assert "2026-11-19 20:12" in d["not_before_text"] and "+07:00" in d["not_before_text"]


def test_build_page_escapes_script(blank_sheet, env, tmp_path):
    _, out = _build(blank_sheet, env, tmp_path)
    html = out.read_text(encoding="utf-8")
    tpl = (REPO / "src" / "ta_rag" / "relabel_page_template.html").read_text(encoding="utf-8")
    assert html.count("</script>") == tpl.count("</script>")
    assert "<!-- Pasal" not in html and "<script>alert(1)" not in html
    assert TRICKY_Q in [r["question"] for r in _data_of(html)["rows"]]  # tetap utuh setelah JSON.parse


@needs_node
def test_embedded_rows_export_unchanged(blank_sheet, env, tmp_path):
    _, out = _build(blank_sheet, env, tmp_path)
    d = _data_of(out.read_text(encoding="utf-8"))
    got = _run("process.stdout.write(L.toCSV(p.columns, p.rows));", {"columns": d["columns"], "rows": d["rows"]})
    assert got == blank_sheet.read_bytes()


def _sheet_variant(src, dst, edit):
    rows = labeling._read_csv(src)
    cols = list(rows[0].keys())
    cols, rows = edit(cols, rows)
    labeling._write_csv(dst, rows, cols)


def _mut(f):
    def edit(cols, rows):
        return f(list(cols), [dict(r) for r in rows])
    return edit


def _rename(cols, rows):
    return ["id" if c == "item_id" else c for c in cols], [{("id" if k == "item_id" else k): v for k, v in r.items()} for r in rows]


def _add_origin(cols, rows):
    for r in rows:
        r["origin"] = "natural"
    return cols + ["origin"], rows


def _fill(col):
    def f(cols, rows):
        rows[1][col] = "LAYAK" if col == "label_baru" else "x"
        return cols, rows
    return f


def _drop_rubric(cols, rows):
    return [c for c in cols if c != "rubric"], [{k: v for k, v in r.items() if k != "rubric"} for r in rows]


def _add_asal(cols, rows):
    for r in rows:
        r["asal"] = "x"
    return cols + ["asal"], rows


def _empty_id(cols, rows):
    rows[1]["item_id"] = "  "
    return cols, rows


def _unknown_case(cols, rows):
    rows[0]["case_id"] = "ZZ"
    return cols, rows


def _dup_id(cols, rows):
    rows[1]["item_id"] = rows[0]["item_id"]
    return cols, rows


@pytest.mark.parametrize("case", ["no_item_id", "forbidden_origin", "filled_label", "filled_alasan", "unknown_case", "dup_item_id", "answerable_without_page",
                                  "bad_download_name", "naive_not_before", "sha_mismatch", "missing_pdf", "empty_sheet", "missing_column",
                                  "extra_column", "empty_item_id", "case_missing_sha"])
def test_build_page_refusals(case, blank_sheet, env, tmp_path):
    pdfs, cases = env
    kw, sheet = {}, blank_sheet
    edits = {"no_item_id": _rename, "forbidden_origin": _add_origin, "filled_label": _fill("label_baru"), "filled_alasan": _fill("alasan_bila_berbeda"),
             "unknown_case": _unknown_case, "dup_item_id": _dup_id, "missing_column": _drop_rubric,
             "extra_column": _add_asal, "empty_item_id": _empty_id}
    why = {"no_item_id": "tidak memiliki kolom item_id", "forbidden_origin": "kolom terlarang.*origin", "filled_label": "label_baru sudah terisi.*R02",
           "filled_alasan": "alasan_bila_berbeda sudah terisi.*R02", "unknown_case": "case_id tidak ada.*ZZ", "dup_item_id": "item_id ganda",
           "answerable_without_page": "R01.*tanpa source_page", "bad_download_name": "download_name tidak sah", "naive_not_before": "zona waktu",
           "sha_mismatch": "SHA256 PDF tidak cocok", "missing_pdf": "PDF tidak ada", "empty_sheet": "tidak memuat baris",
           "missing_column": "kolom lembar tidak ada.*rubric", "extra_column": "kolom tidak dikenal.*asal", "empty_item_id": "item_id kosong",
           "case_missing_sha": "tidak memiliki source_pdf_sha256"}
    if case in edits:
        sheet = tmp_path / "v.csv"
        _sheet_variant(blank_sheet, sheet, _mut(edits[case]))
    elif case == "empty_sheet":
        sheet = tmp_path / "v.csv"
        labeling._write_csv(sheet, [], COLS)
    elif case == "bad_download_name":
        kw["download_name"] = "../x.txt"
    elif case == "naive_not_before":
        kw["not_before"] = "2026-11-19T20:12:00"
    elif case == "sha_mismatch":
        rows = [json.loads(x) for x in cases.read_text(encoding="utf-8").splitlines()]
        rows[0]["source_pdf_sha256"] = "0" * 64
        cases.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    elif case == "answerable_without_page":  # R01 berjenis answerable, kasusnya kehilangan source_page
        rows = [json.loads(x) for x in cases.read_text(encoding="utf-8").splitlines()]
        rows[0]["source_page"] = None
        cases.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    elif case == "case_missing_sha":
        rows = [json.loads(x) for x in cases.read_text(encoding="utf-8").splitlines()]
        del rows[0]["source_pdf_sha256"]
        cases.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    elif case == "missing_pdf":
        (pdfs / "B.pdf").unlink()
    with pytest.raises(ValueError, match=why[case]):
        _build(sheet, env, tmp_path, **kw)
    assert not (tmp_path / "out" / "p.html").exists()


def test_build_page_missing_pdftoppm_is_value_error(blank_sheet, env, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("pdftoppm")
    monkeypatch.setattr(RP.ocr_check, "render_page", boom)
    with pytest.raises(ValueError, match="pdftoppm"):
        _build(blank_sheet, env, tmp_path)
    assert not (tmp_path / "out" / "p.html").exists()


def test_template_rerender_does_not_reset_image_or_banner():
    tpl = (REPO / "src" / "ta_rag" / "relabel_page_template.html").read_text(encoding="utf-8")
    assert "if (key !== shownKey)" in tpl and "shownKey = key" in tpl
    assert re.search(r'\$\("banner"\)\.textContent !== txt', tpl)


def test_build_page_refuses_existing_out(blank_sheet, env, tmp_path):
    out = tmp_path / "ada.html"
    out.write_text("lama", encoding="utf-8")
    with pytest.raises(FileExistsError):
        _build(blank_sheet, env, tmp_path, out_html=out)
    assert out.read_text(encoding="utf-8") == "lama"


def test_module_never_names_first_labels():
    src = (REPO / "src" / "ta_rag" / "relabel_page.py").read_text(encoding="utf-8")
    assert "relabel_sample" not in src and "labels_all" not in src


def test_template_offline():
    tpl = (REPO / "src" / "ta_rag" / "relabel_page_template.html").read_text(encoding="utf-8")
    assert "http" not in tpl and "__LIB__" in tpl and "__DATA__" in tpl


def test_template_wiring_guards():
    tpl = (REPO / "src" / "ta_rag" / "relabel_page_template.html").read_text(encoding="utf-8")
    for needle in ("ctrlKey", "altKey", "metaKey", "keyAction(", "setField(", "Date.now()", "DATA.not_before_ms", "restoreState(", "fillRows(", "missing("):
        assert needle in tpl, needle


def test_template_gate_covers_storage_and_export():
    tpl = (REPO / "src" / "ta_rag" / "relabel_page_template.html").read_text(encoding="utf-8")
    key = re.search(r"const STORE = [^;]*;", tpl).group(0)
    assert "DATA.not_before_ms" in key and '"none"' in key  # kunci simpan memuat batas waktu
    assert re.search(r"if \(!gated\(\)\) \{ try \{ state = restoreState\(", tpl)  # pemulihan dilewati sebelum batas waktu
    assert '$("export").disabled = on;' in tpl and re.search(r'if \(gated\(\)\) \{[^}]*return;', tpl)  # tombol ekspor mati + penjaga di handler
    assert "Date.now() < DATA.not_before_ms" in tpl


def test_gitignore_has_relabel_page():
    assert "data/relabel_page/" in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_cli_exit_codes(blank_sheet, env, tmp_path, capsys):
    pdfs, cases = env
    filled = tmp_path / "filled.csv"
    _sheet_variant(blank_sheet, filled, _mut(_fill("label_baru")))
    base = ["--cases", str(cases), "--pdf-dir", str(pdfs), "--download-name", "r.csv", "--dpi", "30"]
    assert RP.main(["--sheet", str(filled), "--out", str(tmp_path / "bad.html")] + base) == 2
    assert "GAGAL:" in capsys.readouterr().err and not (tmp_path / "bad.html").exists()
    out = tmp_path / "good.html"
    assert RP.main(["--sheet", str(blank_sheet), "--out", str(out)] + base) == 0
    so = capsys.readouterr().out
    assert json.loads(so[: so.rindex("}") + 1])["items"] == 3 and "label tetap diputuskan manusia." in so
    assert RP.main(["--sheet", str(blank_sheet), "--out", str(out)] + base) == 2  # tidak menimpa


@needs_real
def test_real_blank_sheet(tmp_path):
    cases = REPO / "data" / "cases" / "questions_draft.jsonl"
    by = {c["case_id"]: c for c in (json.loads(x) for x in cases.read_text(encoding="utf-8").splitlines())}
    rows = labeling._read_csv(REAL_SHEET)
    pages = {(by[r["case_id"]]["source_file"], by[r["case_id"]]["source_page"]) for r in rows if by[r["case_id"]]["source_page"] is not None}
    out = tmp_path / "real.html"
    info = RP.build_page(REAL_SHEET, cases, Path(REAL), out, "relabel_validator2.csv", dpi=30)
    print("REAL", info)
    assert info["items"] == 60 and info["images"] == len(pages) == 36  # probe T64, T70, T71 tanpa halaman
    html = out.read_text(encoding="utf-8")
    sample = json.loads((REPO / "data" / "labels" / "relabel_sample.json").read_text(encoding="utf-8"))
    for aid in sample["answer_ids"]:
        assert aid not in html
    if shutil.which("node"):
        d = _data_of(html)
        got = _run("process.stdout.write(L.toCSV(p.columns, p.rows));", {"columns": d["columns"], "rows": d["rows"]})
        assert got == REAL_SHEET.read_bytes()
