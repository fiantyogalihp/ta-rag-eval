# GOAL — definisi selesai (direvisi Sab 7 Nov 2026, malam; menggantikan versi 19.40)

**Tujuan tunggal:** naskah jurnal SINTA (Bahasa Indonesia) terkirim paling lambat **Senin 9 Nov 2026** dan memuat hasil nyata dari alur `ta_rag.agent`, bukan angka dummy.
Framing: **pilot/preliminary**. Kontribusi yang dapat dipertahankan: protokol evaluasi yang dapat diaudit (pra-registrasi, label buta, dua track),
perbandingan A–D dengan interval, analisis galat, hard-fail sadar-sitasi untuk angka format Indonesia.

## Keputusan desain yang dikunci sebelum S11 (`config/protocol.json → pre_lock_revisions`, SPEC §2 D9–D16)
Seleksi parameter memakai **FAR Track M**; CAR/REVIEW/REJECT dari Track R; R dan M tidak pernah digabung · seleksi per konfigurasi A/B/C/D + D* sekunder ·
hard-fail mengabaikan angka sitasi dan angka pertanyaan · Track M = semua jawaban LAYAK (≤16), family ditetapkan · tahap II deskriptif ·
generator k=1, jeda relabel 12 jam · tiga kasus Tabel 14 ditetapkan dengan aturan.

## G1 — WAJIB (tanpa ini tidak kirim)
| # | Hasil | Langkah | Bukti |
|---|---|---|---|
| 1 | 267 halaman ter-parse r-1, QA manusia PASS pada halaman jangkar | S00–S07 | `data/reducto/manifests/*.manifest.json` |
| 2 | 20 pertanyaan HUMAN_VERIFIED | S08–S10 | `data/cases/questions_draft.jsonl` |
| 3 | Protokol dikunci SEBELUM label | S11 | `config/protocol.lock.json` |
| 4 | Run 1 MiMo (20 jawaban, respons mentah) | S12–S15 | `data/runs/answers_run1.jsonl` |
| 5 | 20 label (+ kolom abstain) + mutasi Track M (≤16) + relabel 8 | S18–S27 | `data/labels/labels_all.jsonl`, `relabel_result.json` |
| 6 | Ringkasan pra-evaluator terkirim | S28–S30 | `data/agent/pre_evaluator_sent.txt` |
| 7 | Tahap I: skor → latency → sweep → test sekali; tahap II deskriptif | S31–S36 | `data/results/I/test_result.json`, `data/results/II/stage2_result.json` |
| 8 | Tabel 11, Tabel 12, 2 grafik, confusion, `per_case.csv`, 3 kasus Tabel 14 | `python -m ta_rag.report` | `data/results/report/*` |
| 9 | `agent verify` bersih | — | "LEDGER UTUH; tidak ada drift" |
| 10 | Naskah IMRaD: Abstrak ID/EN, Pendahuluan, Tinjauan Pustaka (matriks BERTScore/RAGAS/RAGChecker dari bacaan sendiri), Metode, Hasil & Pembahasan, Keterbatasan, Kesimpulan | — | `docs/naskah/` |

## Dilepas secara sadar (tulis di naskah sebagai keterbatasan)
- Run 2–3 (S38–S39): hanya run 1; non-determinisme generator tidak diukur; catatan panduan 6(a) (k≥3) tidak dipenuhi.
- Sweep dan test terpisah untuk tahap II: tahap II hanya deskriptif.
- Validator kedua: hanya log upaya (S28), kecuali ada rekan yang bersedia (inter-rater sungguhan, dilaporkan terpisah dari intra-rater).
- Baseline LLM-judge.

## Klaim yang boleh muncul di naskah
Hanya angka dari `data/results/I/test_result.json` dan `data/results/II/stage2_result.json`, dengan CI, diawali
"Di bawah pelabelan validator tunggal (intra-rater agreement X%, n=…)". `NO_ELIGIBLE_PARAMETER`, `CAR_ZERO_DEGENERATE`, `FAR_UNDEFINED_NO_SELECTION`
dan "FAR Track R tidak terdefinisi (n=0)" dilaporkan sebagai temuan. Tanpa "lebih aman/akurat/tervalidasi klinis".

## Batas waktu
| Kapan | Harus selesai |
|---|---|
| Sab 7 Nov malam | G1-1 (S05–S06 jalan), G1-2 (S08), revisi kode D10–D16 selesai dan ditinjau |
| Min 8 Nov pagi | S11 lock → S12 → S13 smoke → S14 freeze → S15 run 1 (kunci protokol SEBELUM melabeli) |
| Min 8 Nov siang | label 20 jawaban (S19–S20); mutasi (S21–S24); lembar relabel dibuat tetapi belum dibuka |
| Min 8 Nov malam | naskah bagian non-hasil; relabel ≥12 jam setelah S20 (S26–S27); ringkasan pra-evaluator dikirim (S30) |
| Sen 9 Nov pagi | S31–S36 + tahap II + `python -m ta_rag.report` |
| Sen 9 Nov siang–malam | Hasil, Pembahasan, Abstrak; format template; kirim sebelum 21.00 |
