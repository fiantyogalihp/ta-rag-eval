# ta-rag-eval — Studi 1 (pilot)

> Cabang ini berisi Studi 1, pilot dengan 20 pertanyaan Track R (audit akhir 13 Nov 2026); status di bawah adalah keadaan akhir pilot itu. Penelitian utama adalah Studi 2 di cabang `main`: https://github.com/fiantyogalihp/ta-rag-eval

Repo kerja TA: evaluasi lapisan verifikasi jawaban RAG pada 13 dokumen JKN (parsing via Reducto API, retrieval lokal eksak).
Urutan kerja: `docs/MILESTONES.md`. Naskah: `docs/naskah/naskah_draft.md`.

Status audit 2026-11-13: seluruh 37 langkah workflow S00–S39 yang tersedia berstatus DONE. Korpus 13/13 cocok audit; QA manusia dan 20 pertanyaan tercatat, generator/protokol terkunci, label utama 20 jawaban serta 11 mutasi tersedia. Hasil evaluasi ada di `data/results/{I,II}/`; ledger mencatat satu test tahap I, `rerun=false`. Audit hitungan/split/seleksi/interval cocok dan 311 tes unit lulus. Run 2–3 tersimpan sebagai capture opsional, belum berlabel atau dianalisis; hasil utama tetap run 1 (k=1). Tabel/grafik pelaporan belum dibuat (`data/results/report/` belum ada), naskah masih draf dengan slot kosong. Keterbatasan aktual termasuk jeda relabel pendek dan penilaian tambahan berbantuan AI. Tidak bergantung pada proyek lama.

```bash
pip install -e ".[dev]" && python -m pytest -q
```

## Mulai dari sini
`docs/AGENT_RUNBOOK.md` — satu perintah (`python -m ta_rag.agent drive`) memandu workflow dengan persetujuan manusia dan penjaga data asli; jumlah langkah aktual mengikuti `config/workflow.json` (37), bukan tabel historis runbook. `docs/RUNBOOK.md` = versi manual. Pada workspace yang sudah selesai ini, gunakan `python -m ta_rag.agent status` dan `verify` untuk memeriksa, bukan mengulang eksperimen. Hasil test yang sudah tersedia dipertahankan apa adanya; tidak dipakai memilih parameter ulang.

## Tentang salinan ini
Salinan GitHub ini memuat keadaan akhir cabang tanpa riwayat kerja. Dokumen kerja internal (aturan kerja agen, spec kerja, dan korespondensi) tidak disertakan; rujukan ke `CLAUDE.md` atau SPEC di kode dan dokumen merujuk dokumen itu. `config/protocol.json`, `config/workflow.json`, dan fixture protokol Studi 1 disalin tanpa catatan administrasi internal, sehingga hash-nya berbeda dari yang tercatat di ledger; pemeriksaan hash penuh memakai berkas asli peneliti. Nama cabang di dokumen kerja mengikuti repo kerja (`main` = Studi 1, `studi2` = Studi 2); di GitHub, Studi 2 ada di `main` dan Studi 1 di `studi1-pilot`.
Nama penilai kedua Studi 1 disamarkan menjadi "Penilai B" di `data/labels/pre_evaluator_summary.md`, `data/labels/second_validator_log.json`, dan `data/agent/ledger.jsonl`; karena itu rantai hash ledger di salinan ini tidak utuh. Berkas asli tetap utuh di mesin peneliti.
