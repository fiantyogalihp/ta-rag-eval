# Halaman Pelabelan Lokal S26/S28 — Rencana Implementasi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Satu perintah menghasilkan berkas HTML lokal (offline) untuk menilai 60 butir lembar relabel satu per layar, dengan gambar
halaman jangkar dan penanda seragam, lalu mengekspor CSV yang diterima importir asli. Tidak ada saran label.

**Architecture:** Fungsi murni JS (`relabel_page.js`) memegang semua logika keadaan dan format, dan diuji lewat node dari pytest.
Templat HTML (`relabel_page_template.html`) hanya menyambungkan DOM ke fungsi itu. `relabel_page.py` memvalidasi masukan,
merender halaman jangkar (`ocr_check.render_page`), lalu menyisipkan pustaka, templat, dan data ke satu berkas.

**Tech Stack:** Python 3.12 (stdlib, `ta_rag.labeling`, `ta_rag.ocr_check`, `ta_rag.corpus`), pdftoppm, JS tanpa dependensi, node v26 (hanya tes), pytest + reportlab.

**Spec:** `docs/superpowers/specs/2026-11-19-halaman-relabel-design.md`

## Global Constraints

- Direktori kerja: `/home/satoru/Documents/context-aware-deep-learning/tyo claude v1/ta-rag-eval-studi2` (worktree `studi2`; jangan `cd` ke repo utama).
- Suite: `PYTHONPATH=src TA_RAG_PDF_DIR=data/raw_pdf PYTHONDONTWRITEBYTECODE=1 ../ta-rag-eval/.venv/bin/python -m pytest -q -p no:cacheprovider`. Tanpa `PYTHONPATH=src`, `ta_rag` dimuat dari repo utama.
- Jangan sentuh `config/`, `src/ta_rag/labeling.py`, `guards.py`, `agent.py`, isi `data/`, atau ledger. Jangan commit.
- Jangan menjalankan CLI `python -m ta_rag.*` di worktree untuk uji kering. Modul menentukan akar repo dari `Path(__file__)`. Tes memakai `tmp_path`; pemeriksaan manual memanggil fungsi dengan path keluaran di scratchpad.
- Tidak ada dependensi baru. Tes node memakai `pytest.mark.skipif(shutil.which("node") is None, ...)`.
- `data.LABELS` = `("LAYAK", "TIDAK_LAYAK", "INSUFFICIENT_EVIDENCE")`. Kolom lembar S25 sesuai urutan: `item_id, case_id, question, answer, kind, source_quote, rubric, label_baru, alasan_bila_berbeda`. Nilai `kind`: `answerable` | `not_in_corpus`.
- Kolom terlarang di lembar masukan: `answer_id, label, label_first, origin, route, H`.
- Pola penanda dipakai persis. Satu regex gabungan berurutan ref → num → kw, diterapkan sekali pada teks yang sudah di-escape (hanya `&`, `<`, `>`):
  - ref: `Pasal N` (N boleh berakhiran huruf besar), `ayat (N)`, `huruf x`.
  - num: digit dengan pemisah `.`/`,`, boleh berawalan `Rp` dan berakhiran `%`.
  - kw: kata utuh, tidak peka huruf besar/kecil: tidak, bukan, belum, tanpa, kecuali, selain, hanya, paling, lebih, kurang, sebelum, sesudah, setelah, sejak, sampai.
  - Markup: `<mark class="ref">`, `<mark class="num">`, `<mark class="kw">`.
- Teks UI dalam bahasa Indonesia. Instruksi tetap, persis: "Nilai tiap jawaban dengan rubrik di bawah. Jangan memakai alat AI."
- `case_id` tidak ditampilkan di layar. Teks ditampilkan mentah, termasuk `**`, dan baris baru dipertahankan.
- Sebelum `not_before`, semua isian (label dan alasan) ditolak. Pemeriksaan terjadi saat aksi, bukan saat halaman dimuat.
- Berkas keluaran offline: tanpa URL eksternal di templat.

## Review Focus

1. Sel berisi `</script>`, `<!--`, atau tag HTML tidak boleh memecah halaman atau menjalankan skrip → Task 1 `test_mark_escapes_and_marks`, Task 2 `test_build_page_escapes_script`.
2. Sel dengan tanda kutip, koma, `\n`, `\r\n`, Unicode, atau spasi di akhir: hasil ekspor harus identik di luar dua kolom isian → Task 1 `test_tocsv_bytes_equal_python_writer`, `test_export_roundtrip_relabel_import`.
3. Halaman S26 dibuka sebelum batas waktu lalu dipakai sesudahnya: penahan dicek saat aksi → Task 1 `test_setfield_gate_and_validation`.
4. Draf `localStorage` basi atau rusak (item_id asing, label tidak sah, JSON rusak) diabaikan dan tidak ikut diekspor → Task 1 `test_restorestate_sanitizes`.
5. Mengetik 1/2/3 di kotak alasan tidak boleh memberi label → Task 1 `test_keyaction`.

## File Structure

- Create `src/ta_rag/relabel_page.js`: fungsi murni untuk browser dan node.
- Create `src/ta_rag/relabel_page_template.html`: tata letak dan kabel DOM; placeholder `__LIB__` dan `__DATA__`.
- Create `src/ta_rag/relabel_page.py`: `build_page` + CLI.
- Create `tests/test_relabel_page.py`: semua tes rencana ini.
- Modify `.gitignore`: tambah `data/relabel_page/`.
- Modify `docs/SPEC_v4_20261103.md`: entri `**Revisi v4.2.23 …**` tepat di atas baris `**Revisi v4.2.22` (v4.2.22 sudah dipakai commit ae9a96b).

---

### Task 1: Pustaka JS murni + tes node

**Files:** Create `src/ta_rag/relabel_page.js`, `tests/test_relabel_page.py`

**Interfaces:**
- Produces (JS; diakhiri `if (typeof module !== "undefined") module.exports = {LABELS, mark, toCSV, setField, restoreState, fillRows, missing, keyAction};`):
  - `LABELS: string[]` = `["LAYAK","TIDAK_LAYAK","INSUFFICIENT_EVIDENCE"]`
  - `mark(text: string) -> string`: HTML dengan penanda (Global Constraints).
  - `toCSV(columns: string[], rows: object[]) -> string`: `"\ufeff"` (BOM, U+FEFF) + header + baris. Setiap baris diakhiri `"\r\n"`. Sel dikutip bila memuat `"`, `,`, `\r`, atau `\n`; `"` digandakan. Hasilnya identik dengan `csv.DictWriter` (QUOTE_MINIMAL).
  - `setField(state, itemId, field, value, nowMs, notBeforeMs /* number|null */) -> state`: objek baru. Melempar `Error` (pesan Indonesia) bila `nowMs < notBeforeMs`, bila `field` ∉ {`label_baru`, `alasan_bila_berbeda`}, atau bila label ∉ `LABELS`.
  - `restoreState(raw: string|null, rows) -> state`: tidak pernah melempar. Hanya menyimpan item_id yang dikenal, kedua field, dan label sah.
  - `fillRows(rows, state) -> rows`: salinan; hanya dua kolom isian yang diganti, dan masukan tidak dimutasi.
  - `missing(rows, state) -> string[]`: item_id tanpa `label_baru`, sesuai urutan baris.
  - `keyAction(key: string, tagName: string) -> {label}|{move: -1|1}|null`: `"1"/"2"/"3"` → `LABELS[0..2]`, `ArrowLeft/ArrowRight` → move. Mengembalikan `null` bila `tagName` (tidak peka huruf besar/kecil) `TEXTAREA` atau `INPUT`, atau tombol lain.
  - Tanpa `</script` di berkas, karena isinya disisipkan ke `<script>`.

- [ ] **Step 1: Tulis tes yang gagal** di `tests/test_relabel_page.py`.

  Helper `_node(js: str, payload) -> object` menjalankan `node -e` dengan
  `const L = require(<path absolut relabel_page.js>); const p = JSON.parse(require("fs").readFileSync(0, "utf8"));`, lalu `js`
  menulis `JSON.stringify(...)` ke stdout. Data tiruan hanya dibuat di `tmp_path` (aturan 16/23).

  Fixture `blank_sheet(tmp_path)` ditulis dengan `labeling._write_csv`:
  - kolom: urutan S25;
  - R01 `answerable`;
  - R02 `answerable` dengan `question` = `'</script><script>alert(1)</script><!-- Pasal 7'` dan
    `answer` = `'Jawaban "kutip", koma\nbaris dua\r\nbaris tiga ≥ – é '`;
  - R03 `not_in_corpus`.

  Untuk impor, `labels_all.jsonl`:
  - `run1:T01` (natural, answerable), `M1:T02` (mutation, answerable), `run2:T03` (natural, not_in_corpus);
  - setiap rekaman: `case_id`, `label`, `labeled_at` `"2026-01-01T00:00:00+00:00"`, `validator` `"Validator Satu"`.

  `relabel_sample.json`: `{"answer_ids": [...], "items": {"R01": "run1:T01", "R02": "M1:T02", "R03": "run2:T03"}, "composition": {}, "strata_short": []}`.
  Protokol: `{"relabel": {"min_gap_hours": 24, "disclosure": "uji"}}`.

  ```python
  def test_js_labels_match_python(): assert _node("out(L.LABELS)", None) == list(data.LABELS)
  def test_js_has_no_script_close(): assert "</script" not in JS.read_text(encoding="utf-8").lower()
  def test_tocsv_bytes_equal_python_writer(blank_sheet):  # bytes dari stdout node == blank_sheet.read_bytes()
  def test_export_roundtrip_relabel_import(blank_sheet, tmp_path):
      # setField R01 LAYAK, R02 TIDAK_LAYAK + alasan 'beda, "kutip"\nbaris', R03 INSUFFICIENT_EVIDENCE (nowMs > notBeforeMs)
      # fillRows -> toCSV -> tulis -> labeling.import_relabel_sheet(...) tidak melempar
      # rekaman label_second == [LAYAK, TIDAK_LAYAK, INSUFFICIENT_EVIDENCE] menurut item; reason_if_different R02 benar
      # labeling._read_csv(ekspor): semua kolom selain label_baru/alasan_bila_berbeda == lembar kosong
  def test_export_roundtrip_second_rater(...):  # import_second_rater(..., rater="Penilai Uji", ai_assistance="none")["eligible_as_inter_rater"] is True
  def test_mark_escapes_and_marks():
      out = mark('<script>x</script> Pasal 7 ayat (2) lebih dari 100 Sebelum Rp8.000,00 30% huruf a')
      assert "<script>" not in out and "&lt;script&gt;" in out
      for s in ['<mark class="ref">Pasal 7</mark>', '<mark class="ref">ayat (2)</mark>', '<mark class="ref">huruf a</mark>',
                '<mark class="num">100</mark>', '<mark class="num">Rp8.000,00</mark>', '<mark class="num">30%</mark>',
                '<mark class="kw">lebih</mark>', '<mark class="kw">Sebelum</mark>']: assert s in out
      assert "<mark" not in mark("ketidakadilan sebelumnya")      # kata utuh saja
  def test_setfield_gate_and_validation():  # sebelum batas: label & alasan melempar; tepat di batas/sesudah: ok; notBefore null: ok;
                                             # label "OK" melempar; field "case_id" melempar; state asal tidak berubah
  def test_restorestate_sanitizes():  # '{"R01":{"label_baru":"LAYAK","x":1},"R99":{"label_baru":"LAYAK"},"R02":{"label_baru":"OK"}}'
                                       # -> {"R01":{"label_baru":"LAYAK"}}; "bukan json" -> {}; null -> {}
  def test_missing_and_fillrows():  # missing == ["R02","R03"] setelah R01 diisi; rows masukan tidak berubah
  def test_keyaction():  # ("1","BODY")->{"label":"LAYAK"}; ("3","DIV")->{"label":"INSUFFICIENT_EVIDENCE"};
                         # ("ArrowRight","BODY")->{"move":1}; ("ArrowLeft","BODY")->{"move":-1};
                         # ("1","TEXTAREA")->None; ("2","input")->None; ("x","BODY")->None
  ```

- [ ] **Step 2: Jalankan dan pastikan gagal.** Run: `<suite> tests/test_relabel_page.py`. Expected: FAIL/ERROR karena `relabel_page.js` belum ada.
- [ ] **Step 3: Implementasikan `src/ta_rag/relabel_page.js`** sesuai Interfaces. ES2020 biasa, tanpa dependensi.
- [ ] **Step 4: Jalankan lagi.** Expected: semua tes Task 1 PASS.

### Task 2: Pembangun halaman, templat, CLI

**Files:** Create `src/ta_rag/relabel_page.py`, `src/ta_rag/relabel_page_template.html`. Modify `.gitignore`, `tests/test_relabel_page.py`.

**Interfaces:**
- Consumes: `relabel_page.js` (Task 1) disisipkan apa adanya ke `__LIB__`, dan fungsinya dipanggil oleh kabel DOM.
- Produces:
  - `build_page(sheet_csv, cases_jsonl, pdf_dir, out_html, download_name: str, not_before: str | None = None, dpi: int = 100) -> dict`,
    yang mengembalikan `{"items": int, "images": int, "bytes": int, "sheet_sha256": str}`.
  - `main(argv=None) -> int` (argparse: `--sheet --cases --pdf-dir --out --download-name --not-before --dpi`). Galat (`ValueError`, `FileExistsError`) dicetak `GAGAL: …` ke stderr dengan return 2. Sukses mencetak ringkasan JSON dan satu baris "Halaman ini alat tampilan, bukan penilai: label tetap diputuskan manusia." dengan return 0. Penutup modul: `if __name__ == "__main__": sys.exit(main())`.

Urutan validasi `build_page`:
1. `labeling._guard_new(out_html)`.
2. `labeling._read_csv`. Lembar tanpa baris ditolak dengan ValueError.
3. Tidak ada kolom `item_id`, atau kolom isian tidak ada, ditolak dengan ValueError.
4. Kolom terlarang ditolak dengan ValueError.
5. `label_baru` atau `alasan_bila_berbeda` yang terisi ditolak dengan ValueError (sebutkan item_id).
6. `download_name` harus cocok `^[\w.-]+\.csv$`; selain itu ValueError.
7. `not_before`: `datetime.fromisoformat`, dan tanpa zona waktu ditolak dengan ValueError.
8. `case_id` tidak ada di kasus, PDF hilang, atau `corpus.sha256_file(pdf) != case["source_pdf_sha256"]` ditolak dengan ValueError.

Sesudah validasi:
- Render tiap (`source_file`, `source_page`) unik sekali ke direktori sementara.
- `DATA` = `{columns, rows, images: {"<source_file>#<source_page>": "data:image/png;base64,…"}, page_of: {case_id: "<source_file>#<source_page>"}, sheet_sha256, download_name, not_before_ms, not_before_text}`. Gambar dikunci per halaman, bukan per kasus, supaya halaman yang dipakai bersama hanya disisipkan sekali. Serialisasi dengan `json.dumps(..., ensure_ascii=False).replace("<", "\\u003c")`.
- Ganti `__LIB__` lalu `__DATA__` di templat, buat direktori induk, dan tulis UTF-8.
- Modul tidak membaca `relabel_sample.json` atau `labels_all.jsonl`, bahkan tidak menyebut kedua nama itu.

Templat (diserahkan ke pembangun kecuali yang dipatok):
- Header berisi "R07 · 7/60", jenis (berjawab/probe), "terisi n/60", status simpan otomatis, dan instruksi tetap.
- Banner sebelum batas waktu: "Relabel baru boleh dimulai {not_before_text} (jeda 24 jam, protocol.json relabel.min_gap_hours)."
- Pertanyaan, lalu Jawaban dan Kutipan jangkar berdampingan (bertumpuk bila lebar < 900px). Keduanya lewat `mark()` dengan `white-space: pre-wrap`.
- Rubrik dipecah pada `" | "`. Gambar bisa diklik untuk berpindah antara pas-lebar dan 100%.
- Tiga tombol label (pilihan aktif terlihat), kotak alasan, dan tombol ←/→. Keyboard lewat `keyAction(e.key, e.target.tagName)`.
- `localStorage`: kunci `"relabel:" + sheet_sha256 + ":" + download_name`, dalam try/catch. Saat dimuat lewat `restoreState`.
- Ekspor: bila `missing()` tidak kosong, tampilkan daftarnya. Bila kosong, `Blob([toCSV(columns, fillRows(rows, state))], {type: "text/csv;charset=utf-8"})` diunduh dengan nama `download_name`.
- Galat `setField` tampil di halaman.
- Token warna di `:root` + `prefers-color-scheme: dark`, dan `:focus-visible` terlihat.
- Tanpa URL eksternal.

- [ ] **Step 1: Tulis tes yang gagal.**

  Pakai `make_pdf` ala `tests/test_ocr_check.py` (reportlab, dua halaman) dan `cases.jsonl` tiruan yang memuat `case_id`,
  `source_file`, `source_page`, dan `source_pdf_sha256` (dari `corpus.sha256_file`).

  ```python
  def test_build_page_tmp(...):  # items==3; images==jumlah (file,halaman) unik; html.count("data:image/png;base64,")==images;
                                  # semua item_id ada; "Nilai tiap jawaban dengan rubrik di bawah. Jangan memakai alat AI." ada
  def test_build_page_escapes_script(...):  # html.count("</script>") == template.count("</script>"); "<!-- Pasal" tidak ada mentah
  @pytest.mark.parametrize("case", ["no_item_id", "forbidden_origin", "filled_label", "filled_alasan", "unknown_case",
                                    "bad_download_name", "naive_not_before", "sha_mismatch", "missing_pdf"])
  def test_build_page_refusals(case, ...):  # pytest.raises(ValueError)
  def test_build_page_refuses_existing_out(...):  # pytest.raises(FileExistsError); berkas lama tidak berubah
  def test_module_never_names_first_labels():  # "relabel_sample" dan "labels_all" tidak ada di relabel_page.py
  def test_template_offline():  # "http" tidak ada di templat
  def test_gitignore_has_relabel_page():  # "data/relabel_page/" ada di baris .gitignore
  def test_cli_exit_codes(...):  # main([...lembar terisi...]) == 2; main([...sah, out di tmp_path...]) == 0
  @needs_real  # skipif tanpa TA_RAG_PDF_DIR atau tanpa data/labels/relabel_sheet_kosong_validator2.csv
  def test_real_blank_sheet(tmp_path):  # build_page(..., dpi=30) -> items 60, images 36 (probe T64/T70/T71 tanpa halaman; Ruling 7);
                                        # tak satu pun answer_id dari data/labels/relabel_sample.json muncul di html
                                        # (bila node ada) toCSV(columns, rows) == bytes berkas lembar kosong
  ```

- [ ] **Step 2: Jalankan dan pastikan gagal.** Expected: tes Task 2 FAIL karena modul belum ada; tes Task 1 tetap PASS.
- [ ] **Step 3: Implementasikan `relabel_page.py` dan templat, lalu tambahkan `data/relabel_page/` ke `.gitignore`.**
- [ ] **Step 4: Jalankan `tests/test_relabel_page.py`.** Expected: semua PASS, kecuali `needs_real` bila tanpa PDF.

### Task 3: Verifikasi menyeluruh, uji mutasi, SPEC

**Files:** Modify `docs/SPEC_v4_20261103.md`.

- [ ] **Step 1: Jalankan suite penuh** dengan `TA_RAG_PDF_DIR=data/raw_pdf`. Expected: semua lulus, dan jumlahnya = baseline + tes baru.
- [ ] **Step 2: Uji mutasi** (memori: hapus `__pycache__` sebelum setiap run, `PYTHONDONTWRITEBYTECODE=1`, baseline hijau dulu, terbunuh hanya bila exit 1). Mutan JS: `toCSV` berhenti menggandakan `"`. Mutan Python: hapus penolakan lembar terisi. Setiap mutan harus membuat `tests/test_relabel_page.py` exit 1; pulihkan, lalu hijau lagi.
- [ ] **Step 3: Smoke nyata.**
  - Panggil `build_page` dari Python dengan keluaran di scratchpad `/tmp/claude-1000/-home-satoru-Documents-context-aware-deep-learning-tyo-claude-v1-ta-rag-eval-studi2/295f2b1d-0fd0-4e4f-a552-47a7cd74c773/scratchpad/smoke/`, memakai lembar `data/labels/relabel_sheet_kosong_validator2.csv`, dpi 100, dan `not_before="2026-11-19T20:12:00+07:00"`. Jangan lewat CLI.
  - Jalankan `google-chrome-stable --headless=new --dump-dom file://…`. Expected: DOM memuat teks pertanyaan R01 dan banner penahan bila sekarang < 20.12 WIB.
  - Laporkan ukuran berkas.
- [ ] **Step 4: Periksa `git status --porcelain --untracked-files=all`.** Expected: hanya berkas di File Structure (ditambah dua dokumen `docs/superpowers/` dan `M docs/SPEC_v4_20261103.md`). Tidak ada perubahan di `data/` dan `config/`.
- [ ] **Step 5: Tulis entri SPEC** `**Revisi v4.2.23 (19 Nov, malam; halaman pelabelan lokal S26/S28; …):**` dengan gaya entri v4.2.20, tepat di atas v4.2.22:
  - (a) Permintaan pengguna 19 Nov: "HITL", yaitu catatan AI per butir (pasal sesuai, kata "sebelum") untuk S26/S28. Agent menolaknya sebelum S27 terkunci (`relabel.blind_to` asal jawaban; `second_validator.if_ai_assisted`) dan menjanjikan catatan AI per butir untuk adjudikasi pasca-kunci. Agent juga memberi daftar periksa generik di chat: rubrik terkunci yang disusun ulang, sama untuk semua butir, tanpa isi butir. Daftar ini tidak dimuat di halaman.
  - (b) Pilihan pengguna B dan berkas desain/rencana. Keputusan agent: daftar kata, `case_id` disembunyikan, tombol `INSUFFICIENT_EVIDENCE`, penahan 20.12 WIB (labeled_at terakhir sampel 18 Nov 20.11.00 WIB), serta berkas lokal dan bukan Artifact.
  - (c) Berkas dan tes, dengan angka suite dan hasil uji mutasi yang sebenarnya.
  - (d) Kalimat pengungkapan untuk naskah (dari desain).
  - (e) Keadaan: S26/S28 PENDING; workflow, protokol, importir, dan ledger tidak berubah; belum di-commit.
