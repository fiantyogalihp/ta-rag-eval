# Studi 2 (konfirmatori): status persiapan dan langkah berikutnya

Rencana lengkap: keputusan D17–D32 di `docs/SPEC_v4_20261103.md` §2 (status **RENCANA**, belum dikunci). Dokumen ini hanya mencatat apa yang sudah ada di kode, apa yang belum, dan apa yang harus dilakukan manusia. Tidak ada data Studi 2 yang dibuat atau diisi oleh Claude.

## 0. Status 14 Nov (cabang `studi2`, worktree `../ta-rag-eval-studi2`)

**Sudah ada di cabang `studi2`:** artefak Studi 1 direset (arsip ada di `main`); `config/generator.json` (DRAFT_UNFROZEN, k = 3, `max_tokens` 1600 = usulan D28); `config/protocol.json` v2.0 (DRAFT_UNLOCKED; D17–D31); `config/workflow.json` v2.0 (36 langkah); manifest QA parse direset ke NOT_DONE (QA Studi 1 diarsipkan di manifest); **72 draf pertanyaan** `data/cases/questions_draft.jsonl` (T01–T60 berjawab, T61–T72 probe; `DRAFT_UNVERIFIED_BY_HUMAN`; kutipan diambil langsung dari teks halaman PDF asli, bukan diketik ulang); `data/cases/absence_audit.json` (12 probe: istilah absen, istilah kontrol ada); penjaga `tests/test_study2_questions.py` (kuota protokol, halaman unik, jenis dikenal rencana mutasi).

**Cara menjalankan agent di cabang itu** (instalasi editable `ta_rag` menunjuk ke `main/src`, jadi `PYTHONPATH=src` wajib; tanpa itu agent menolak jalan, exit 2):

```bash
cd "../ta-rag-eval-studi2"
export PYTHONPATH=src
"<repo main>/.venv/bin/python" -m ta_rag.agent status     # 36 langkah, ledger baru
"<repo main>/.venv/bin/python" -m ta_rag.agent drive      # TTY, persetujuan manusia
```

**Variabel lingkungan** (diset di terminal yang menjalankan `agent drive`; nilainya tidak dicatat): `MIMO_API_KEY` (S13–S17; tambahkan `MIMO_BASE_URL` bila kunci berawalan `tp-`), `TA_VALIDATOR` (S20 dan S23: nama Anda), `TA_SECOND_RATER` dan `TA_SECOND_RATER_AI` (S37: nama validator kedua dan pernyataan **dia sendiri**, `none` atau `disclosed`; jangan mengisi `none` kecuali ia benar-benar tidak memakai AI), dan `TA_ACCEPT_SHORT_GAP=1` (S27, opsional: menerima jeda relabel < 24 jam sebagai deviasi tercatat). `agent envcheck` (S00) hanya memeriksa `REDUCTO_API_KEY`, `MIMO_API_KEY`, dan `TA_VALIDATOR`; sisanya baru ketahuan saat langkahnya tiba (galat "variabel lingkungan … wajib diisi").

**Yang harus Anda kerjakan berikutnya (S07–S08, aturan 17 dan 22):** periksa 72 pertanyaan pada gambar halaman memakai `verification_pack_studi2.pdf` (dibangun dari draf + audit; tidak di-commit). Prioritas: 9 pertanyaan Perpres 59/2024 (T52–T60; dokumen pindai, teks bawaan tidak dapat dipercaya), T30 dan T34 (tabel Permenkes 3/2023), dan probe T71–T72 (ketiadaan pada dokumen pindai harus dikonfirmasi pada gambar). Claude tidak menandai apa pun `HUMAN_VERIFIED`.

**Alat bantu untuk dokumen pindai (opsional; bukan verifikasi):** `python -m ta_rag.ocr_check --cases data/cases/questions_draft.jsonl --pdf-dir data/raw_pdf --audit data/cases/absence_audit.json --out-dir data/qa/ocr_crosscheck` (butuh `pip install -e ".[ocr]"`, Python < 3.13; sekitar 20 detik per halaman pada 4 inti). Ia membaca ulang halaman dokumen `manual_check_required_docs` (Perpres 59/2024 dan 64/2020) sebagai gambar dengan OCR lain lalu membandingkannya dengan teks bawaan: kesepakatan per halaman, istilah probe yang harus nihil beserta kontrol positif dari audit, dan kutipan T52–T60. Keluaran: `crosscheck_report.json` (boleh di-commit) dan teks OCR per dokumen untuk grep (cache, tidak di-commit). Kode keluar 1 = ada temuan, 2 = galat (mis. SHA256 PDF tidak cocok). Nihil KATA bukan nihil TOPIK, dan dua pembacaan OCR dapat salah di tempat yang sama: gambar halaman tetap Anda periksa sendiri, dan alat ini tidak menyentuh JSONL, workflow, atau ledger.

**Kuota D18 direvisi menjadi D31** (durasi 12, tanggal 7, uang/jumlah/rentang/persen 15, definisi/ketentuan 26): korpus tidak memuat lebih banyak fakta bersih yang belum dipakai Studi 1. Dampak: butir unit-mutasi hanya 12 pertanyaan, jadi daya H2 terbatas.

## 1. Sudah ada dan teruji (cabang `main`; Studi 1 tidak berubah)

| Kebutuhan | Kode | Cara memakai |
|---|---|---|
| Kandidat kutipan untuk pertanyaan baru | `questions.extract_candidates` | `python -m ta_rag.questions candidates --pdf-dir data/raw_pdf --exclude data/cases/questions_draft.jsonl --out data/cases/studi2_draft/candidates.jsonl` (166 kandidat; hanya bahan) |
| Aturan satuan (konfigurasi E = D + satuan) | `numbers.unit_mismatches`, `evaluators.route(unit_fail=)`, `sweep.stage_c(configs=("C","D","E"))` | protokol v2: `selection.grid_configs = ["C","D","E"]` |
| Konfigurasi F (BERTScore F1 sebagai evaluator terpilih; commit `5417adc`) | `evaluators.route_bert`, `sweep.stage_f`/`stage_grid`, `pipeline.score_rows(bert_scorer=)`, `measure_latency_bert`, `bertscore.default_scorer` | protokol v2: `selection.grid_configs = ["C","D","E","F"]`; ambang 0,60–0,95; REVIEW = ambang − 0,10 |
| Evidence Tahap II = satuan konteks terbaik | `evaluators.best_unit`, `pipeline.score_rows(stage_ii_evidence=)` | protokol v2: `split.stage_II_evidence = "best_unit"` |
| Dua mutasi per jawaban | `protocol.assign_mutation_slots`, `labeling` (kolom `slot`, id `M1:`/`M2:`) | protokol v2: `track_m.mutations_per_answer = 2` dan `families_by_question_type` dengan ≥ 2 family per jenis |
| Label lari 2–3 | `labeling.label_file`, `merge_labels(extra_label_paths)` | `labeling sheet/import --run run2`; `merge` menyertakan `labels_run*.jsonl` |
| CI untuk 3 lari atas pertanyaan yang sama | `metrics.cluster_bootstrap_ci` | analisis utama gabungan lari; per lari: rata-rata dan rentang |
| Stabilitas seleksi dan sensitivitas α | `pipeline sweep-stability` | sudah dijalankan pada Studi 1 |
| Verifier himpunan pertanyaan | `questions verify --expect-total 72 --expect-answerable 60` | opsi sudah ada |
| Fixture tes Studi 1 | `tests/fixtures/studi1/` | cabang Studi 2 boleh mengganti `config/` dan `data/cases/` tanpa merusak suite |

## 2. Belum ada (pekerjaan Claude setelah Anda memberi tanda mulai)

1. ~~Konfigurasi F~~ **SELESAI** (commit `5417adc`; lihat tabel di atas).
2. ~~**Cabang dan worktree `studi2`**~~ **SELESAI (14 Nov)**: `git worktree add ../ta-rag-eval-studi2 -b studi2`, hapus artefak Studi 1 dari `data/` dan berkas lock di `config/` pada commit pertama cabang itu, salin `data/raw_pdf` dan `data/reducto/raw` (parse dipakai ulang, tanpa biaya Reducto).
3. ~~**`config/protocol.json` v2**~~ **DRAFT SELESAI (14 Nov; dikunci setelah S11)** (D17–D24: seed baru, k = 3, dua mutasi, E dan F, `best_unit`, relabel ≥ 20% dengan jeda ≥ 24 jam) dan **`config/workflow.json` v2**: S04–S06 diganti langkah pengesahan manusia atas parse yang dipakai ulang; S07 untuk halaman jangkar yang baru; label per lari; mutasi k = 2; S38/S39 menjadi wajib.
4. ~~**`report` untuk A–F**, CI per klaster, dan tabel per lari~~ **KODE SELESAI (14 Nov), menunggu data:** `run_test` menulis bagian `clustered` pada `test_result.json` (gabungan 3 lari dengan CI bootstrap klaster, per lari dengan Clopper–Pearson plus rata-rata dan rentang, H1–H3 bila protokol memuat `operationalization`), dan `python -m ta_rag.report --results data/results --cases data/cases/questions_draft.jsonl --labels data/labels/labels_all.jsonl --out data/results/report` menulis `table11_klaster`, `per_lari`, `hipotesis` (md dan csv) di samping tabel lama. Tahap II (deskriptif) juga memuat gabungan klaster dan tabel per lari bila baris memuat `run_id` (`stage2.md`). S33 (`pipeline latency` tanpa `--selection`) kini mengukur A, C, D, dan E/F bila `selection.grid_configs` memuatnya, sehingga kolom p95 Tabel 11 terisi untuk E dan F; judul langkah di `workflow.json` masih menyebut 'C dan D' dan sengaja tidak diubah (aturan 24: hash rencana). Belum dijalankan pada data nyata; hanya diuji dengan data sintetis di `tmp_path`. Belum ada: pita CI klaster pada grafik validation (pita itu masih Clopper–Pearson per record, jadi terlalu sempit untuk 3 lari; sebut di keterangan gambar).
5. **Naskah dua studi** setelah hasil ada.

## 3. Pekerjaan manusia (tidak dapat diwakili Claude)

| Langkah | Perkiraan |
|---|---|
| Pilih 60 pertanyaan berjawab + 12 probe dari kandidat atau halaman sendiri; tulis pertanyaan dan kutipan utuh; periksa pada **gambar halaman** | 6–7 jam |
| Tinjau protokol v2 sebelum dikunci (S11) | 0,5 jam |
| Label ± 216 jawaban (3 lari) + kolom abstain, buta skor. 'Jawaban identik dilabel sekali' (rencana awal) **tidak dibangun**: di Studi 1 hanya 1 dari 40 jawaban lari 2–3 identik dengan lari 1 (59 teks unik dari 60), jadi penghematan ≈ 2% dan tidak sebanding dengan perubahan prosedur pelabelan | 6–8 jam |
| Verifikasi atau buat ± 90 mutasi | 1,5–3 jam |
| Relabel ≥ 20% dengan jeda ≥ 24 jam | 1,5 jam |
| **Validator kedua manusia tanpa bantuan AI**, buta label pertama, ≥ 25% sampel | waktu orang kedua |

**Peringatan dari kandidat:** daftar mentah memuat fragmen patah (tabel Permenkes 3/2023 hlm. 24, OCR scan Perpres 59/2024) dan beberapa fakta yang sama dengan Studi 1 (ganti FKTP setelah 3 bulan). Pemilihan harus manual; kutipan harus kalimat/ayat utuh, bukan fragmen.

## 4. Keputusan yang masih terbuka (SPEC D25–D32 dan validator kedua)

- **D25** mutasi dibuat skrip lalu diverifikasi manusia (menghemat sekitar 1,5 jam; mengubah praktik S22). Bawaan: dibuat manusia seperti Studi 1.
- **D26** baseline LLM-as-judge dengan API MiMo (ada biaya dan non-determinisme). Bawaan: tidak dijalankan.
- **D27** rubrik probe; **D28** `max_tokens` 800 → 1600; **D29** relabel 60 record dengan jeda ≥ 24 jam; **D30** jenis `numeric_day` (T48); **D31** revisi kuota D18; **D32** operasionalisasi H1–H3 (rute yang dihitung, ambang 10 poin, CI 98,3%). Semuanya USULAN sampai Anda menyetujuinya pada tinjau-kunci protokol (S11).
- **Validator kedua manusia tanpa bantuan AI** (D24): tanpa orang ini hanya intra-rater dan target realistis turun ke SINTA 3.

## 5. Syarat kelayakan (dari perhitungan CI, `metrics.clopper_pearson`)

| Target | Dasar |
|---|---|
| ≥ 30 mutasi di test | bila 0 lolos, batas atas 95% = 11,6% |
| ≥ 40 jawaban LAYAK di test | lebar CI CAR ≈ 29 poin |
| ≥ 40 mutasi di validation | agar α = 5% dapat dicapai tanpa mensyaratkan "nol lolos" |

Jumlah aktual dilaporkan apa adanya; data tidak ditambah setelah test dibuka.

## 6. Catatan desain (riwayat 13 Nov, malam; protokol/workflow v2 kini ada di cabang `studi2`, lihat §0)

**Cabang.** `git worktree add ../ta-rag-eval-studi2 -b studi2` dari `main`. Jalankan dengan `PYTHONPATH=src` dan venv `main`: instalasi editable `ta_rag` menunjuk ke `main/src`, jadi tanpa `PYTHONPATH=src` agent akan memakai data `main`. Rencana: penjaga di `agent.main` yang menolak bila direktori kerja di luar `REPO`.

**Commit pertama cabang.** `git rm -r` untuk `data/agent`, `data/labels`, `data/results`, `data/runs`, `data/cases` (kecuali kandidat), `data/reducto_pilot`, `config/protocol.lock.json`, `config/generator.lock.json`; salin `data/raw_pdf` dan `data/reducto/raw|markdown` (diabaikan git). Pada manifest, pindahkan `human_fidelity_qa` Studi 1 ke `studi1_human_fidelity_qa` dan setel `human_fidelity_qa` = NOT_DONE, supaya S07 v2 mewajibkan QA manusia pada halaman jangkar baru. Catat di SPEC.

**`generator.json` v2.** `status` kembali DRAFT_UNFROZEN dan `runs` = 3. Usulan `max_tokens` 800 → 1600 karena respons R10 Studi 1 terpotong (643 dari 800 token terpakai untuk penalaran); prompt tidak diubah. Keputusan pengguna sebelum S14 (usulan D28).

**Protokol v2 (turunan v1.1).** version 2.0; seed baru (`TA-RAG-SPLIT-v2-…`, `TA-RAG-TRACKM-v2-…`, `TA-RAG-RELABEL-v2-…`); `split.validation_fraction` 0,5; `split.stage_II_evidence = "best_unit"`; `track_m.mutations_per_answer = 2` dengan family D20; `selection.grid_configs = ["C","D","E","F"]`; `determinism.generator_runs.k = 3`; `relabel.n_sample` 60, `min_gap_hours` 24, strata (mutasi 15, probe 6, TIDAK_LAYAK alami 10); `second_validator.target_records` 60 (sampel relabel yang sama), tanpa alat AI; `baselines` E dan F; `intervals` memuat bootstrap klaster 2.000×; hipotesis H1–H3 dengan CI 98,3% (Bonferroni, tiga hipotesis) dan selisih ≥ 10 poin persentase, H4 deskriptif.

**Masalah yang ditemukan dan perlu keputusan di protokol.**
1. **Family `date`** (geser tahun +1) tidak berlaku untuk fakta seperti "tanggal 15 bulan berikutnya" yang tidak memuat tahun. Usulan: jenis baru `numeric_day` dengan family [numeric_value, negation]. Verifier pertanyaan tidak membatasi nilai `question_type`, tetapi `families_by_question_type` harus memuatnya (`labeling` memakai `fam_map[question_type]`).
2. **Rubrik probe.** Kedua selisih relabel Studi 1 (R18, R20) terjadi pada probe: abstain benar disertai klaim tambahan. Usulan garis tegas, yang perlu persetujuan validator (usulan D27): menyebut isi atau bagian spesifik yang tidak ada di konteks = TIDAK_LAYAK; saran umum merujuk sumber resmi tanpa menyebut ketentuan = LAYAK.
3. **Alur kerja.** Ganti S04–S06 (Reducto berbayar) dengan satu tahap otomatis `S06_reuse_parse` (cmd `corpus verify`, guard `reducto_provenance`). Tambahkan S16/S17 (capture run 2 dan 3, wajib). S18 mengekspor tiga lembar, S19 melabel tiga lembar, S20 mengimpor tiga lembar, S21 membuat lembar mutasi k = 2. S33 mengukur latency A, C, D, E, F. Tes `test_real_workflow_*` memvalidasi struktur workflow v2 secara otomatis di cabang.
4. ~~**Draf 72 pertanyaan belum dibuat.**~~ **Sudah dibuat 14 Nov (lihat §0).** Bahan: `data/cases/studi2_draft/candidates.jsonl` (166 kandidat). Pertanyaan harus berawalan "Menurut …", kutipan kalimat/ayat utuh, tanpa mengulang fakta Studi 1.

**Keputusan pengguna yang masih terbuka:** D25 (mutasi oleh skrip; bawaan: manusia), D26 (LLM-judge; bawaan: tidak), D27 (rubrik probe), D28 (`max_tokens`), jumlah relabel dan jeda 24 jam (usulan D29).

## 7. Setelah S36 (perintah manual; semuanya pasca-test dan eksploratif kecuali `report`)

Workflow v2 berhenti di S37; tidak ada langkah agent untuk perintah ini. Jalankan dari worktree `studi2` dengan `PYTHONPATH=src`. Keluaran eksploratif hanya ke `data/results/exploratory/` dan `data/results/report/`; tidak ada yang boleh mengubah label, split, parameter terpilih, atau `test_result.json`.

```bash
# 1. stabilitas seleksi (bootstrap komponen validation) dan sensitivitas alpha 0,05/0,10/0,20
python -m ta_rag.pipeline sweep-stability --scored data/results/scored_I.jsonl --selection data/results/I/selection.json \
    --latency data/results/latency.json --out data/results/exploratory/sweep_stability.json
# 2. latency pada parameter terpilih (S33 mengukur parameter acuan sebelum seleksi)
python -m ta_rag.pipeline latency --labels data/labels/labels_all.jsonl --cases data/cases/questions_draft.jsonl \
    --selection data/results/I/selection.json --out data/results/exploratory/latency_selected.json
# 3. BERTScore deskriptif: apakah mutasi satu fakta menurunkan skor? (Panduan Tabel 3)
python -m ta_rag.bertscore pilot --labels data/labels/labels_all.jsonl --cases data/cases/questions_draft.jsonl \
    --scored data/results/scored_I.jsonl --out data/results/exploratory/bertscore_studi2.json
# 4. tabel dan grafik naskah (Tabel 11/12 A-F, gabungan lari dengan CI klaster, per lari, hipotesis H1-H3, Tahap II)
python -m ta_rag.report --results data/results --cases data/cases/questions_draft.jsonl --labels data/labels/labels_all.jsonl \
    --latency data/results/latency.json --relabel data/labels/relabel_result.json --out data/results/report
```

Cara membaca `hipotesis.md`: putusan TERDUKUNG mengikuti `decision_rule` (CI klaster 98,3% > 0 dan selisih ≥ 10 poin). Klaim 'lebih akurat/aman' juga mensyaratkan McNemar eksak lolos ambang Bonferroni (0,0167); itu membutuhkan ≥ 7 mutasi diskordan searah. Kolom `catatan` memberi tanda bila syarat itu, jumlah klaster (≥ 10), atau lebar CI tidak terpenuhi.
