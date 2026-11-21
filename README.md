# ta-rag-eval

Repo kerja TA: evaluasi lapisan verifikasi jawaban RAG pada 13 dokumen JKN (parsing via Reducto API, retrieval lokal eksak).
Urutan kerja: `docs/MILESTONES.md`. Naskah: `docs/naskah/naskah_draft.md`.

## Cabang
| Cabang | Isi |
|---|---|
| `main` | Studi 1: 20 pertanyaan Track R; audit akhir 13 Nov 2026 (status lengkap di README cabang itu) |
| `studi2` | Studi 2: 72 pertanyaan, jawaban 3 lari, 64 mutasi Track M; workflow selesai 21 Nov 2026 |

## Status Studi 2 (cabang ini, 21 Nov 2026)
Ke-36 langkah workflow (S00–S37) berstatus DONE dan `python -m ta_rag.agent verify` melaporkan LEDGER UTUH. Test tahap I dijalankan sekali (`rerun=false`). Hasil ada di `data/results/`: `I/` (sweep dan test), `II/` (tahap II), `report/` (tabel, gambar, hipotesis H1–H4), dan `exploratory/` (analisis tambahan yang bukan dasar pemilihan parameter). Setiap klaim CAR/FAR diawali "Di bawah pelabelan validator tunggal (intra-rater agreement 55%, n=60):". Naskah (`docs/naskah/naskah_draft.md`) belum memuat hasil Studi 2. Tidak bergantung pada proyek lama.

## Tidak ada di repo
PDF sumber, JSON mentah Reducto, indeks, halaman relabel yang dibangun (`data/relabel_page/`), kunci API (`.env`), dan bukti kirim S30 (`data/agent/pre_evaluator_sent*`, memuat data pribadi). Hash berkas-berkas itu tercatat di manifest dan ledger, sehingga `agent verify` penuh hanya bisa dijalankan di mesin yang menyimpannya.

```bash
pip install -e ".[dev]" && python -m pytest -q
```

## Mulai dari sini
`docs/AGENT_RUNBOOK.md` — satu perintah (`python -m ta_rag.agent drive`) memandu workflow dengan persetujuan manusia dan penjaga data asli; jumlah langkah aktual mengikuti `config/workflow.json` (36 pada cabang ini), bukan tabel historis runbook. `docs/RUNBOOK.md` = versi manual. Pada workspace yang sudah selesai ini, gunakan `python -m ta_rag.agent status` dan `verify` untuk memeriksa, bukan mengulang eksperimen. Hasil test yang sudah tersedia dipertahankan apa adanya; tidak dipakai memilih parameter ulang.

## Tentang salinan ini
Salinan GitHub ini memuat keadaan akhir cabang tanpa riwayat kerja. Dokumen kerja internal (aturan kerja agen, spec kerja, dan korespondensi) tidak disertakan; rujukan ke `CLAUDE.md` atau SPEC di kode dan dokumen merujuk dokumen itu. `config/protocol.json`, `config/workflow.json`, dan fixture protokol Studi 1 disalin tanpa catatan administrasi internal, sehingga hash-nya berbeda dari yang tercatat di ledger; pemeriksaan hash penuh memakai berkas asli peneliti.
