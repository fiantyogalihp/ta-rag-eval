# RUNBOOK — dari repo ini sampai angka di naskah (Rabu 4 – Senin 9 Nov 2026)

Semua perintah dijalankan dari akar repo. **Kode sudah ada dan teruji dengan data sintetis dan fixture nyata; belum pernah dijalankan pada
data nyata** (belum ada kunci Reducto/MiMo, raw parsing, label). Setiap langkah di bawah punya gerbang: bila gagal, berhenti.
Pekerjaan yang hanya bisa dilakukan manusia ditandai **[KAMU]**.

## 0. Siapkan (Rabu, ±30 mnt)
```bash
pip install -e ".[dev,retrieval,eval]"          # sentence-transformers akan mengunduh model MiniLM saat pertama dipakai
export TA_RAG_PDF_DIR=data/raw_pdf REDUCTO_API_KEY=... MIMO_API_KEY=...   # kunci hanya dari lingkungan
python -m ta_rag.corpus unpack --zip <zip 13 PDF> --dest data/raw_pdf
python -m ta_rag.corpus verify --pdf-dir data/raw_pdf      # gerbang: 13/13 cocok audit
python -m ta_rag.corpus manifest                            # 1346 tersedia -> 267 terindeks
python -m pytest -q                                         # gerbang: hijau
```

## 1. Parsing Reducto (Rabu, ±1–2 jam termasuk menunggu)
```bash
python src/ta_rag/parsing/reducto_parse_corpus.py --pdf-dir data/raw_pdf --out-dir data/reducto --dry-run
python src/ta_rag/parsing/reducto_parse_corpus.py --pdf-dir data/raw_pdf --out-dir data/reducto --only perpres_59_2024_perubahan_ketiga_jaminan_kesehatan --page-range 1-3
python -m ta_rag.corpus plan --pdf-dir data/raw_pdf --out-dir data/reducto     # lalu jalankan 2 perintah yang dicetak
```
Gerbang: `models_observed == ["r-1"]`; tidak ada `PARSE_FAILED`; baca `data/reducto/corpus_summary.md`.
**[KAMU]** QA gambar halaman pada halaman jangkar (spec §5.5), terutama Perpres 59/2024 (scan).

## 2. Verifikasi 20 pertanyaan (Rabu malam, ±2–3 jam) **[KAMU]**
Buka `verification_pack_R01-R20.pdf` (lembar cek + halaman PDF asli). Untuk tiap pertanyaan: kutipan benar, nilai/negasi benar, halaman fisik benar.
Ubah `status` ke `HUMAN_VERIFIED` + `validator` + `validated_at` di `data/cases/questions_draft.jsonl` hanya bila semuanya cocok; perbaiki lalu jalankan:
```bash
python -m ta_rag.questions verify --cases data/cases/questions_draft.jsonl --pdf-dir data/raw_pdf
python -m ta_rag.questions absence-audit --cases data/cases/questions_draft.jsonl --pdf-dir data/raw_pdf --out data/cases/absence_audit.json --date 2026-11-05
```
Cek visual khusus "mamografi / 2026 / masa tunggu" pada dua dokumen scan (`manual_check_required_docs`).

## 3. Kunci protokol, bangun indeks, bekukan generator (Kamis pagi)
```bash
python -m ta_rag.protocol lock                  # SEBELUM melabeli satu jawaban pun; commit protocol.json + protocol.lock.json
python -m ta_rag.pipeline chunk                 # gerbang: check_chunk_scope lolos (tidak ada deferred / hlm. 92+)
python -m ta_rag.capture freeze                 # generator.json -> FROZEN + generator.lock.json (hash prompt)
```
Smoke test MiMo dengan 1 pertanyaan (R02): periksa `message.content`, `reasoning_content`, `finish_reason`, `usage`, `response.model`; bila jawaban terpotong,
naikkan `max_tokens` SEBELUM freeze. Jenis kunci: `sk-` (base URL default) vs `tp-` (Token Plan, base URL lain) — set `MIMO_BASE_URL` bila perlu.

## 4. Capture 3 run (Kamis)
```bash
for r in run1 run2 run3; do python -m ta_rag.pipeline capture --cases data/cases/questions_draft.jsonl --chunks data/index/chunks.jsonl --run $r --out data/runs; done
```
Run tidak bisa ditimpa. Periksa `answer_status` (ANSWER_EMPTY?), `chunk_ids`, dan `retrieval_ok` (`pipeline.retrieval_ok`).
Jawaban run 2–3 yang berbeda dari run 1: `protocol.distinct_answers`.

## 5. Pelabelan (Kamis–Jumat) **[KAMU]**
1. Labeli 20 jawaban run 1 **buta skor**, per jawaban, dengan rubrik `protocol.json → label_rubric`. Tulis `data/labels/labels.jsonl` (skema `ta_rag.data`): `manual_label_locked=true` hanya setelah selesai. Jangan membuka skor.
2. `python -m ta_rag.protocol track-m --labels data/labels/labels.jsonl --cases data/cases/questions_draft.jsonl` → urutan kandidat. Buat mutasi berurutan sampai 10 lolos `protocol.verify_mutation` + catat `anchor_page_opposite`.
3. Labeli jawaban run 2–3 yang berbeda (bila ada). Mutasi berlabel TIDAK_LAYAK secara konstruksi.
4. `python -m ta_rag.protocol relabel --labels ...` → 8 jawaban; relabel setelah **≥24 jam**; hitung `protocol.agreement`.
5. Upayakan validator kedua (5–10 record) atau isi `second_validator.attempt_log`.
6. Susun ringkasan pra-evaluator (`protocol.pre_evaluator_summary`) — wajib ada sebelum evaluator dijalankan.

## 6. Skor, sweep, test sekali (Sabtu)
```bash
python -m ta_rag.pipeline score --stage I  --labels data/labels/labels.jsonl --cases data/cases/questions_draft.jsonl --out data/results/scored_I.jsonl
python -m ta_rag.pipeline score --stage II --labels data/labels/labels.jsonl --cases data/cases/questions_draft.jsonl --chunks data/index/chunks.jsonl --out data/results/scored_II.jsonl
python -m ta_rag.pipeline sweep --scored data/results/scored_I.jsonl --out data/results/I      # validation saja: stage_A/B/C.csv + selection.json
python -m ta_rag.pipeline test  --scored data/results/scored_I.jsonl --selection data/results/I/selection.json --out data/results/I/test_result.json
```
Ulangi untuk tahap II. Tahap I dan II **tidak digabung**. Baca `selection.json`: `NO_ELIGIBLE_PARAMETER`, `FAR_UNDEFINED_NO_SELECTION`, dan `CAR_ZERO_DEGENERATE`
adalah **temuan**, bukan kegagalan; laporkan apa adanya. `split_report`: test tanpa TIDAK_LAYAK berarti FAR test tak terdefinisi.
Latency: `pipeline.measure_latency` (≥100 iterasi, setelah warm-up) untuk konfigurasi terpilih; catat perangkat keras.

## 7. Naskah (Sabtu malam – Senin)
Awali tiap klaim FAR/CAR dengan "di bawah pelabelan validator tunggal (intra-rater agreement X%, n=…)". Tulis keterbatasan: validator tunggal, bias penulis-pertanyaan,
prompt memuat instruksi abstain, generator tidak deterministik (3 run), cakupan 267 dari 1.346 halaman, keragaman mutasi sempit, FAR Track R bisa tak terdefinisi.
Jangan menempel angka Bagian 9 dokumen panduan (DUMMY). Matriks literatur (BERTScore/RAGAS/RAGChecker) dari bacaanmu sendiri.

## Yang belum teruji (jangan berpura-pura sudah)
Reducto sungguhan; bentuk respons MiMo nyata dan jenis kunci; embedding MiniLM nyata di sini (tes memakai embedder tiruan); chunker pada dokumen selain fixture Perpres 59/2024;
regex Pasal pada tabel Permenkes 3/2023 hlm. 32–83; aturan hard-fail negasi (kasar, polaritas biner).
