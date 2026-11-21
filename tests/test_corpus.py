"""Uji KODE manajemen korpus (bukan data penelitian). PDF nyata dipakai bila tersedia di TA_RAG_PDF_DIR."""

from __future__ import annotations

import copy
import os
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ta_rag import corpus  # noqa: E402

REAL_PDF_DIR = Path(os.environ.get("TA_RAG_PDF_DIR", REPO / "data" / "raw_pdf"))


def tiny_pdf(path: Path, n_pages: int) -> None:
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    for i in range(n_pages):
        c.drawString(50, 800, f"halaman {i + 1}")
        c.showPage()
    c.save()


def cfg_for(path: Path, name: str, pages: int, **extra) -> dict:
    d = {"doc_id": "x", "file": name, "sha256": corpus.sha256_file(path), "pages": pages,
         "eval_role": "evidence_source", "index_page_scope": f"1-{pages}"}
    d.update(extra)
    return {"documents": [d]}


def test_config_is_consistent():
    cfg = corpus.load_config()
    docs = cfg["documents"]
    assert len(docs) == 13
    assert sum(d["pages"] for d in docs) == 1346
    assert sum(d["pilot_pages"] for d in docs) == 267
    assert {d["status_seleksi"] for d in docs} == {"UTAMA", "HISTORIS", "RIWAYAT"}
    for d in docs:
        assert len(d["sha256"]) == 64
        if d["index_page_scope"]:
            a, b = corpus._parse_scope(d["index_page_scope"])
            assert 1 <= a <= b <= d["pages"]
    # HISTORIS tidak masuk pilot; RIWAYAT hanya pengecoh
    assert all(d["eval_role"] == "deferred" for d in docs if d["status_seleksi"] == "HISTORIS")
    assert all(d["eval_role"] == "distractor_only" for d in docs if d["status_seleksi"] == "RIWAYAT")


def test_verify_ok_and_detects_problems(tmp_path):
    p = tmp_path / "a.pdf"
    tiny_pdf(p, 2)
    cfg = cfg_for(p, "a.pdf", 2)
    assert corpus.verify(tmp_path, cfg) == []

    bad = copy.deepcopy(cfg); bad["documents"][0]["sha256"] = "0" * 64
    assert any(s.startswith("SHA256_BEDA") for s in corpus.verify(tmp_path, bad))

    bad = copy.deepcopy(cfg); bad["documents"][0]["pages"] = 3
    assert any(s.startswith("HALAMAN_BEDA") for s in corpus.verify(tmp_path, bad))

    (tmp_path / "liar.pdf").write_bytes(b"<html>bukan pdf</html>")
    out = corpus.verify(tmp_path, cfg)
    assert any(s.startswith("TAK_DIKENAL") for s in out)

    bad = copy.deepcopy(cfg); bad["documents"][0]["file"] = "b.pdf"
    assert any(s.startswith("HILANG") for s in corpus.verify(tmp_path, bad))


def test_verify_rejects_html_with_pdf_extension(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"<html>login page</html>")
    cfg = {"documents": [{"doc_id": "x", "file": "a.pdf", "sha256": corpus.sha256_file(f), "pages": 1}]}
    assert any(s.startswith("BUKAN_PDF") for s in corpus.verify(tmp_path, cfg))


def test_unpack_flattens_only_pdfs_and_refuses_collisions(tmp_path):
    src = tmp_path / "s"; src.mkdir()
    tiny_pdf(src / "a.pdf", 1)
    z = tmp_path / "k.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(src / "a.pdf", "01_X/a.pdf")
        zf.writestr("01_X/readme.md", "bukan pdf")
        zf.writestr("../../evil.pdf", b"%PDF-1.4 jahat")  # nama dasar saja yang dipakai
    out = corpus.unpack(z, tmp_path / "dest")
    assert sorted(p.name for p in out) == ["a.pdf", "evil.pdf"]
    assert {p.parent for p in out} == {tmp_path / "dest"}
    assert not (tmp_path.parent / "evil.pdf").exists()

    z2 = tmp_path / "k2.zip"
    with zipfile.ZipFile(z2, "w") as zf:
        zf.write(src / "a.pdf", "A/a.pdf"); zf.write(src / "a.pdf", "B/a.pdf")
    with pytest.raises(ValueError, match="bentrok"):
        corpus.unpack(z2, tmp_path / "dest2")


def test_plan_batches_full_docs_and_splits_partial_scope():
    cfg = corpus.load_config()
    plans = corpus.plan_commands(cfg, "data/raw_pdf", "data/reducto")
    assert sum(p["pages"] for p in plans) == 267
    partial = [p for p in plans if "--page-range" in p["command"]]
    assert len(partial) == 1 and partial[0]["docs"] == ["permenkes_03_2023_standar_tarif_jkn"]
    assert "--page-range 1-91" in partial[0]["command"] and partial[0]["stem_suffix"] == "__p001-091"
    batch = [p for p in plans if "--page-range" not in p["command"]]
    assert len(batch) == 1 and len(batch[0]["docs"]) == 9  # 4 UTAMA dicakup penuh + 5 RIWAYAT
    assert batch[0]["pages"] == 176  # 21+16+48+33 + 58
    assert not any("statistik" in d or "laporan_tahunan" in d for p in plans for d in p["docs"])


@pytest.mark.skipif(not (REAL_PDF_DIR / "BPJS_03_2024_Skrining_Peserta_JKN.pdf").exists(),
                    reason="13 PDF asli tidak tersedia (tidak di-commit)")
def test_real_corpus_matches_audit():
    assert corpus.verify(REAL_PDF_DIR, corpus.load_config()) == []


# ------------------------------------------------------------------ cakupan indeks (v4.2.2)

def real_cfg():
    return corpus.load_config()


def test_real_scope_config_is_consistent_and_totals_267_of_1346():
    cfg = real_cfg()
    assert corpus.validate_scope_config(cfg) == []
    man = corpus.scope_manifest(cfg)
    assert man["totals"] == {"pdf_pages": 1346, "indexed_pages": 267}


def test_permenkes3_pages_32_83_are_indexed_as_in_document_distractors_not_anchors():
    cfg = real_cfg()
    d = next(x for x in cfg["documents"] if x["doc_id"] == "permenkes_03_2023_standar_tarif_jkn")
    roles = corpus.index_page_roles(d)
    assert (32, 83, corpus.ROLE_IN_DOC_DISTRACTOR) in roles
    man = {r["doc_id"]: r for r in corpus.scope_manifest(cfg)["documents"]}["permenkes_03_2023_standar_tarif_jkn"]
    assert man["anchor_pages"] == ["1-31", "84-91"] and man["in_document_distractor_pages"] == ["32-83"]
    assert man["not_indexed_pages"] == ["92-721"]


def chunk(doc, a, b, cid="c"):
    return {"chunk_id": cid, "doc_id": doc, "page_start": a, "page_end": b}


def test_chunk_guard_accepts_inside_scope_including_distractor_pages():
    cfg = real_cfg()
    ok = [chunk("permenkes_03_2023_standar_tarif_jkn", 1, 2, "a"), chunk("permenkes_03_2023_standar_tarif_jkn", 91, 91, "b"),
          chunk("permenkes_03_2023_standar_tarif_jkn", 40, 41, "c"), chunk("permenkes_71_2013_pelayanan_jkn", 28, 28, "d")]
    assert corpus.check_chunk_scope(ok, cfg) == []


@pytest.mark.parametrize("row,needle", [
    (chunk("permenkes_03_2023_standar_tarif_jkn", 92, 92), "di luar cakupan"),
    (chunk("permenkes_03_2023_standar_tarif_jkn", 91, 92), "di luar cakupan"),
    (chunk("permenkes_03_2023_standar_tarif_jkn", 721, 721), "di luar cakupan"),
    (chunk("laporan_tahunan_jkn_2023_djsn", 1, 1), "DITUNDA"),
    (chunk("statistik_jkn_2015_2019_djsn", 5, 6), "DITUNDA"),
    (chunk("statistik_jkn_2016_2021_djsn", 100, 100), "DITUNDA"),
    (chunk("permenkes_71_2013_pelayanan_jkn", 29, 29), "di luar cakupan"),
    (chunk("dok_gaib", 1, 1), "tak dikenal"),
    (chunk("perpres_59_2024_perubahan_ketiga_jaminan_kesehatan", 5, 4), "tidak valid"),
    ({"chunk_id": "z", "doc_id": "perpres_59_2024_perubahan_ketiga_jaminan_kesehatan"}, "tidak valid"),
])
def test_mutation_chunk_outside_scope_is_flagged(row, needle):
    probs = corpus.check_chunk_scope([row], real_cfg())
    assert probs and needle in probs[0]


def test_mutation_scope_config_breakage_is_detected():
    cfg = real_cfg()

    def doc(c, did):
        return next(x for x in c["documents"] if x["doc_id"] == did)

    c = copy.deepcopy(cfg); doc(c, "laporan_tahunan_jkn_2023_djsn")["index_page_scope"] = "1-33"
    assert any("deferred" in p for p in corpus.validate_scope_config(c))
    c = copy.deepcopy(cfg); doc(c, "permenkes_03_2023_standar_tarif_jkn")["index_page_roles"][1]["pages"] = [32, 80]
    assert any("menutup index_page_scope" in p for p in corpus.validate_scope_config(c))
    c = copy.deepcopy(cfg); doc(c, "permenkes_03_2023_standar_tarif_jkn")["question_page_ranges"] = [[1, 91]]
    assert any("question_page_ranges" in p for p in corpus.validate_scope_config(c))
    c = copy.deepcopy(cfg); doc(c, "permenkes_71_2013_pelayanan_jkn")["index_page_roles"] = [{"pages": [1, 28], "role": "evidence_and_anchor"}]
    assert any("pengecoh tidak boleh" in p for p in corpus.validate_scope_config(c))
    c = copy.deepcopy(cfg); doc(c, "perpres_59_2024_perubahan_ketiga_jaminan_kesehatan")["pilot_pages"] = 30
    assert any("pilot_pages" in p for p in corpus.validate_scope_config(c))


def test_manifest_cli_writes_file_and_fails_on_broken_config(tmp_path):
    out = tmp_path / "m.json"
    assert corpus.main(["manifest", "--out", str(out)]) == 0
    assert out.exists()
    bad = real_cfg()
    next(x for x in bad["documents"] if x["doc_id"] == "laporan_tahunan_jkn_2023_djsn")["index_page_scope"] = "1-5"
    import json as _j
    cfgp = tmp_path / "bad.json"; cfgp.write_text(_j.dumps(bad), encoding="utf-8")
    assert corpus.main(["manifest", "--config", str(cfgp), "--out", str(tmp_path / "x.json")]) == 1
