# MILESTONES — urutan kerja Claude Code (Selasa 3 – Senin 9 Nov 2026)

> **4 Nov 13.25:** kode M2–M8 sudah ditulis dan lulus tes sintetis (lihat `docs/RUNBOOK.md` untuk urutan perintah dan pekerjaan manusia). "Kode SELESAI" ≠ dijalankan pada data nyata.

> **4 Nov 17.10:** agent orkestrator (`ta_rag.agent`, `guards`, `labeling`, `config/workflow.json`) selesai dan teruji; gladi resik nyata S02–S04 pada 13 PDF berhasil. Langkah berikutnya berada di tanganmu: kunci API, jalankan `drive` (docs/AGENT_RUNBOOK.md).

Format: **tujuan · masukan · keluaran · gerbang selesai · yang butuh manusia**. Jalur kritis = pekerjaan manusia (spec §11);
milestone teknis tidak boleh menjadi alasan menunda penulisan pertanyaan/label.

| M | Hari | Tujuan | Bergantung pada |
|---|---|---|---|
| M0 | Sel 3 | Repo hidup + korpus terverifikasi | zip PDF dari pengguna |
| M1 | Sel 3–Rab 4 | Pilot Reducto + parse 267 hlm + QA teknis | `REDUCTO_API_KEY`, M0 |
| M2 | Rab 4 (kode SELESAI) | Chunker Pasal-aware | M1 (manifest lolos QA teknis) |
| M3 | Rab 4 (kode SELESAI) | BM25 + dense (FAISS) + RRF | M2 |
| M4 | Kam 5 (kode SELESAI) | Capture: retrieval → MiMo → frozen cases | M3, `MIMO_API_KEY`, pertanyaan dari pengguna |
| M5 | Kam 5 (kode SELESAI) | Skema data dua jalur + penjaga split | spec §7 (ZIP `research_eval/` belum ada) |
| M6 | Jum 6 (kode SELESAI) | Evaluator A–D + ekstraksi angka Indonesia | M5 |
| M7 | Jum 6–Sab 7 (kode SELESAI) | Sweep A/B/C → pilih → beku → test sekali | label terkunci, `config/protocol.json` |
| M8 | Sab 7 (kode SELESAI) | Metrik + CI + latency + tabel | M7 |
| M9 | Min 8 | Confusion matrix, 3 kasus Tabel 14, galat | M8 |

## M0 — Repo hidup + korpus terverifikasi
- Keluaran: `python -m pytest -q` hijau (132 tes lulus dengan PDF asli; 125 lulus + 7 skip tanpa; 4 Nov); `python -m ta_rag.corpus verify` = **13/13 cocok**.
- Gerbang: bila ada SHA256/halaman berbeda → **berhenti dan laporkan**, jangan lanjut parse.
- Manusia: taruh zip di mesin; `unpack --zip … --dest data/raw_pdf`.

## M1 — Pilot Reducto → parse 267 halaman
1. `--dry-run` (tanpa API). Periksa daftar dan jumlah halaman.
2. Pilot: `--only perpres_59_2024_perubahan_ketiga_jaminan_kesehatan --page-range 1-3`. Periksa: kredit/halaman, `usage.num_pages == 3`, `models_observed == ["r-1"]`, bentuk `result.type`.
3. Bandingkan hasil pilot dengan `tests/fixtures/reducto_perpres_59_2024_r1_ui_export.json` (ekspor Studio, halaman yang sama) — selisih besar = periksa pin model/pengaturan.
4. Jalankan perintah dari `python -m ta_rag.corpus plan` (2 perintah: 9 dokumen utuh = 176 hlm; Permenkes 3/2023 `--page-range 1-91`).
5. Baca `data/reducto/corpus_summary.md`. Dokumen scan harus `UNRELIABLE_REFERENCE`; **dokumen digital-asli yang juga `UNRELIABLE_REFERENCE` berarti `r-1` mengubah banyak teks → buka D7 (coba `--model legacy`) dan laporkan ke pengguna**.
- Gerbang: 10 manifest (9 dokumen utuh + Permenkes 3/2023 hlm. 1–91) berstatus `TECH_QA_PASS` atau `TECH_QA_FLAGS`, tanpa `PARSE_FAILED`; tidak ada raw yang tertimpa.
- Bila timeout/`result.type="url"` bermasalah pada hlm. 1–91 Permenkes 3/2023: pecah per rentang (mis. 1-31, 32-83, 84-91) atau pakai `parse.run_job` asinkron — **tambahkan tes sebelum memakainya**.
- Manusia: QA gambar pada halaman evidence (spec §5.5); isi `human_fidelity_qa` di manifest.

## M2 — Chunker Pasal-aware (`src/ta_rag/chunking/`)
- Masukan: raw JSON. Keluaran: `data/index/chunks.jsonl` (`chunk_id, doc_id, source_pdf_sha256, source_page_start/end, heading_path, text, text_sha256, ocr_quality_flag, eval_role`).
- Aturan: spec §6 (regex `Pasal N/NA/I` pada **teks**, ayat tetap dalam Pasal, `Figure/Signature/Header/Footer/Page Number` dikeluarkan, tabel satu unit, chunk lintas halaman = dua referensi halaman).
- Tes: pakai fixture Perpres 59/2024 nyata — 24 batas "Pasal N" mandiri harus terdeteksi; Pasal 103B (sisipan huruf) ditangani; tidak ada chunk berisi teks `Figure`. 1 uji mutasi (matikan regex → tes gagal).
- Gerbang: setiap chunk punya halaman fisik yang benar (cocok dengan `bbox.original_page`) **dan `ta_rag.corpus.check_chunk_scope(chunks, cfg) == []`** (tidak ada chunk dari dokumen `deferred` atau Permenkes 3/2023 hlm. 92+, tidak ada chunk yang melintasi batas cakupan). Tulis `page_start/page_end` pada tiap chunk agar penjaga ini dapat berjalan.

## M3 — Retrieval lokal (`src/ta_rag/retrieval/`)
- **BM25 (`rank_bm25`) + dense + RRF (k=60)**; dense = `paraphrase-multilingual-MiniLM-L12-v2`, vektor ternormalisasi, FAISS `IndexFlatIP`. **Ditulis baru** (tidak ada kode lama di repo) di atas `chunks.jsonl`, dengan tes baru. **Tanpa Qdrant, tanpa `prune_context`.**
- `top-k` dari `config/protocol.json` (usulan 4, kunci sebelum jalan). Simpan versi model + hash indeks.
- Tes: deterministik; kueri berisi "Pasal 6" mengembalikan chunk Pasal itu pada data fixture (BM25 harus menolong token eksak); uji bahwa teks chunk yang dikembalikan == teks di `chunks.jsonl` (tidak dipangkas).
- Catatan: model embedding yang sama dengan evaluator B → tulis sebagai risiko korelasi.

## M4 — Capture kasus beku (`src/ta_rag/capture.py`)
- Masukan: `data/cases/questions_draft.jsonl` (20 pertanyaan; wajib `HUMAN_VERIFIED` oleh pengguna pada gambar halaman sebelum dibekukan; pertanyaan, `source_doc`, `source_page`, `source_quote` **dari PDF asli**). Keluaran: `data/cases/frozen_cases.jsonl` + respons mentah penuh per panggilan.
- Klien MiMo: **ditulis baru** memakai **`config/generator.json`** (`mimo-v2.6-flash`, prompt konteks-saja dengan instruksi abstain eksplisit, temperature 0, tanpa JSON paksaan). `answer` = `message.content` saja; `reasoning_content` hanya disimpan mentah; kosong → `ANSWER_EMPTY`. Tanpa persona/larangan klinis/`exact_quote`.
- **Langkah wajib:** (1) uji **1 pertanyaan** dan lihat bentuk respons mentah (apakah ada bidang penalaran yang harus dipisah dari `answer`; laporkan ke pengguna); (2) pengguna mengonfirmasi `model`; (3) ubah `status` → `FROZEN`, hitung SHA256 prompt, catat di `config/protocol.json`; (4) baru jalankan batch Track R.
- **Tiga run (k=3)** pada konteks beku yang sama (`protocol.json → determinism.generator_runs`): run 1 primer, run 2–3 replikasi; `ta_rag.protocol.distinct_answers` menentukan jawaban berbeda yang perlu label baru. Jawaban tersimpan, tidak dibangkitkan ulang dalam satu run. Tes: tanpa jaringan (klien tiruan); tidak menimpa kasus yang sudah beku; prompt yang terkirim == prompt di config (hash cocok).

## M5 — Skema data dua jalur (`src/ta_rag/data.py`)
- Implementasikan dari spec §7 (ditulis baru). ZIP `research_eval/` hanya pembanding gerbang (spec §17); proyek lama memakai `expected_route`, bukan label per jawaban, dan tidak dipakai.
- Validasi: `track ∈ {R,M}`; mutasi wajib `answer_origin = mutasi_terkontrol` + `pair_id`; `source_page` tak kosong; label terkunci sebelum skor; **penjaga kebocoran split** (group_id dan evidence_group); larangan menggabungkan Track R dan M di agregasi.
- Tes: tiap aturan punya satu kasus gagal.

## M6 — Evaluator A–D (`src/ta_rag/evaluators/`)
- L = F1 himpunan token; S = (cos+1)/2; H = (1−w_s)L + w_s·S. A: w_s=0; B: w_s=1; C: dari validasi; D = C + hard-fail.
- Hard-fail (Panduan; logikanya cocok dengan ZIP riset, spec §17): angka jawaban tak ada di evidence → REJECT; negasi beda dengan L ≥ 0,70 → REVIEW.
- **Ekstraksi angka: pakai `ta_rag.numbers` (sudah ada, 19 tes).** Regex ZIP riset salah pada `Rp8.000,00`. Tambahkan tes per format yang belum tercakup: `Rp 150.000,00`, `1 Juli 2025`, `Pasal 6A`, `ayat (2)`, `5%`/`5 persen`, `1.000.000` = `1000000`.
- Laporkan min/median/maks L dan S per kelas pada validation **sebelum** menggabungkan.

## M7 — Sweep → pilih → beku → test sekali
- Tahap A (bobot 0–100%, thr 0,78) · B (thr 0–1, bobot 60:40) · C (grid 6×5: semantic {0,.25,.50,.60,.75,1.0} × ACCEPT {.70,.75,.78,.80,.85}) untuk C dan D = **60 baris, satu baris per kombinasi**, hanya pada validation.
- `config/protocol.json` (sudah ada, `DRAFT_UNLOCKED`) berisi aturan R1/R2 + rantai tie-break, α, rubrik, seleksi Track M, relabel — **jalankan `python -m ta_rag.protocol lock` sebelum melabeli, dan commit sebelum sweep**; `protocol.select_parameters` sudah mengimplementasikan dan menguji rantai pemilihan. Hash commit dicatat di hasil.
- Bekukan → jalankan test **sekali** → simpan hasil + hash kode. Sensitivity di test = `DIAGNOSTIC_ONLY_NO_RESELECTION`.
- Tes: skrip menolak menjalankan test lebih dari sekali tanpa `--acknowledge-rerun` yang tercatat.

## M8 — Metrik, CI, latency, tabel
- CAR, FAR (undefined bila tak ada TIDAK_LAYAK), REVIEW rate, REJECT rate, false rejection; pembilang/penyebut; Clopper–Pearson (scipy). Track R dan M terpisah; oracle dan retrieved terpisah.
- Latency: evaluator saja, warm-up, ≥ 100 iterasi, p50/p95, catat CPU/GPU/RAM.
- Keluaran: CSV/JSONL per kasus + tabel 11/12 dari data nyata.

## M9 — Analisis
- Confusion 3×3 (bila ada label 3 kelas independen), ≥ 3 kasus format Tabel 14 (benar-ACCEPT; salah-tertahan; salah-tetap-ACCEPT **atau** jumlah yang dicari bila tak ada), analisis galat (termasuk REJECT palsu akibat angka parser), keterbatasan.

## Pekerjaan manusia (tidak dapat diwakili kode)
Pertanyaan + kutipan PDF asli + halaman fisik (Track R: 20 draf sudah ditulis — verifikasi pada gambar halaman; tambah pertanyaan negasi/multi-ayat bila waktu ada) · 10 mutasi Track M (ditulis sebelum evaluator jalan) · rubrik pelabelan (sebelum melabeli) · label blind + kunci · re-label intra-rater 8 dari 30 jawaban unik (min 6; ≥2 mutasi, ≥2 probe, ≥2 TIDAK_LAYAK alami; jeda ≥ 24 jam; laporkan kesepakatan %, selisih, κ hanya bila terdefinisi) · upaya validator kedua (5–10 record, atau log upaya) · kunci `config/protocol.json` sebelum melabeli · QA gambar halaman evidence · matriks literatur BERTScore/RAGAS/RAGChecker dari bacaan sendiri · pilih 10 pasangan Track M dengan aturan terkunci (spec §7) setelah label SUPPORTED terkunci.
