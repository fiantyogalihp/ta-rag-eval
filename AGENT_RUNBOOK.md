# AGENT RUNBOOK — dari nol sampai hasil, dengan persetujuan manusia di setiap langkah

> **Catatan 7 Nov 2026 (revisi pra-lock D9–D16):** alur kini 37 langkah. S35 menjadi `stage2` (tahap II deskriptif: parameter beku tahap I, tanpa sweep/test) dan S37 dihapus; S36 juga menulis `per_case.csv`; S19 menambah kolom `abstain`; S22 mengisi semua kandidat dengan family tetap. Rujukan: `docs/GOAL.md`, `config/protocol.json → pre_lock_revisions`.

Dibuat 4 Nov 2026. Menggantikan `docs/RUNBOOK.md` (versi manual, tetap ada sebagai rujukan perintah mentah).

## 0. Yang dijanjikan dan yang tidak

**Dijanjikan.** Satu perintah (`python -m ta_rag.agent drive`) memandu seluruh alur 38 langkah: parsing Reducto, verifikasi, kunci protokol,
chunking, pembekuan generator, run MiMo (run 1 wajib, run 2-3 opsional), pelabelan, mutasi, relabel, skor, sweep, test, latency. Tidak ada langkah berjalan tanpa
frasa persetujuan yang kamu ketik. Semua tercatat di `data/agent/ledger.jsonl` (berantai hash). Data tanpa provenans ditolak (§6).

**Tidak dijanjikan.**
- Agent tidak memberi label, tidak membuat mutasi, tidak memverifikasi halaman PDF, tidak mengirim email, dan tidak mencari validator kedua.
  Itu sengaja: kalau agent melakukannya, yang kamu laporkan bukan lagi "pelabelan validator tunggal manusia".
- Alur ini belum pernah dijalankan pada Reducto/MiMo sungguhan (kuncinya tidak ada di sesi pembangunan dan jaringan sandbox memblokirnya).
  Yang sudah dijalankan nyata: S02 (13 PDF, SHA256 cocok), S03 (manifest 267 dari 1346 halaman), S04 (dry-run). Selebihnya teruji dengan
  tiruan, jadi ekspektasikan bug pertama pada kontak pertama dengan respons API nyata.
- Tabel dan teks naskah belum otomatis (§8).

## 1. Persiapan sekali (mesinmu sendiri, bukan sandbox ini)

```bash
unzip ta-rag-eval.zip && cd ta-rag-eval
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,retrieval,eval]"          # sentence-transformers mengunduh model MiniLM saat pertama dipakai (CPU cukup)
export REDUCTO_API_KEY=...                        # hanya di terminal ini; jangan ditulis ke berkas
export MIMO_API_KEY=...                           # tipe kunci: sk- (base URL default) atau tp- (set MIMO_BASE_URL)
export TA_VALIDATOR="Nama Lengkapmu"              # satu orang validator; dipakai pada impor label
python -m ta_rag.agent envcheck
```

## 2. Cara memakai (di terminal interaktif milikmu)

| Perintah | Fungsi |
|---|---|
| `python -m ta_rag.agent drive` | Mode utama. Maju langkah demi langkah; berhenti saat menunggu kerja manusia, frasa salah, atau kegagalan. Jalankan lagi untuk melanjutkan. |
| `... status` | Tabel 38 langkah dan keadaannya (PENDING/APPROVED/AWAITING_REVIEW/DONE/FAILED/STALE/BLOCKED). |
| `... next` | Langkah berikutnya dan instruksinya. |
| `... plan S06` | Tampilkan rencana (perintah, hash masukan) dan frasa yang harus diketik. |
| `... approve S06` / `approve S06 --post` | Setujui rencana / terima hasil. |
| `... run S06` | Jalankan langkah yang sudah disetujui. |
| `... done S19` | Nyatakan langkah manusia selesai. |
| `... reject S06 --reason "..."` | Batalkan hasil/persetujuan; langkah menjadi PENDING lagi. Dicatat. |
| `... verify` | Periksa rantai ledger dan "drift" (hasil berubah di luar ledger). Jalankan sebelum menulis naskah. |

**Frasa.** Persetujuan = mengetik persis `SETUJU <langkah> <8 hex hash rencana>`; menerima hasil = `TERIMA <langkah> <8 hex>`; kerja manusia selesai =
`SELESAI <langkah> <8 hex>`; langkah tak-terulang menambah ` TIDAK-BISA-DIULANG`. Hash mengikat persetujuan pada perintah dan berkas masukan
saat itu: bila ada masukan yang berubah sebelum `run`, persetujuan gugur dan dicatat `INVALIDATED`.

**Bagaimana memakai Claude Code/agent LLM di atas ini.** Boleh untuk membaca `status`, `next`, `plan`, `verify` dan men-debug kegagalan. `approve`, `done`,
dan `reject` menolak berjalan tanpa TTY, jadi agent LLM tidak bisa menyetujui lewat CLI. Jangan menyalin frasa ke agent supaya ia "mengetikkan" untukmu.

## 3. Peta 38 langkah

| ID | Langkah | Siapa | Biaya | Gerbang |
|---|---|---|---|---|
| S00 | Cek lingkungan (paket, nama kunci; nilai kunci tidak ditampilkan) | agent |  | setuju + terima hasil |
| S01 | Jalankan seluruh tes (kode harus hijau sebelum menyentuh data) | agent |  | setuju + terima hasil |
| S02 | Sediakan 13 PDF asli di data/raw_pdf | MANUSIA |  | selesai |
| S03 | Manifest cakupan (tersedia vs terindeks vs jangkar vs pengecoh) | agent |  | setuju + terima hasil |
| S04 | Parsing Reducto: dry-run atas rencana yang sama dengan parsing penuh (tanpa API, tanpa biaya) | agent |  | setuju + terima hasil |
| S05 | Parsing Reducto: pilot 3 halaman (satu dokumen) | agent | API berbayar | setuju + terima hasil |
| S06 | Parsing Reducto: korpus pilot 267 halaman (model r-1) | agent | API berbayar | setuju + terima hasil |
| S07 | QA fidelitas parsing oleh manusia (halaman jangkar vs gambar PDF) | MANUSIA |  | selesai |
| S08 | Verifikasi manusia 20 pertanyaan (kutipan, nilai, negasi, halaman) | MANUSIA |  | selesai |
| S09 | Verifikasi otomatis kutipan terhadap PDF asli | agent |  | setuju + terima hasil |
| S10 | Audit absence R17-R20 (kontrol topik tetangga) | agent |  | setuju + terima hasil |
| S11 | KUNCI protokol (pra-registrasi) sebelum melabeli | agent | TAK-TERULANG | setuju + terima hasil |
| S12 | Chunking + penjaga cakupan indeks | agent |  | setuju + terima hasil |
| S13 | Smoke test generator: 1 pertanyaan (R02), periksa bentuk respons | agent | API berbayar | setuju + terima hasil |
| S14 | BEKUKAN generator (model, prompt, parameter) sebelum Track R | agent | TAK-TERULANG | setuju + terima hasil |
| S15 | Capture jawaban generator run 1 (primer) | agent | API berbayar | setuju + terima hasil |
| S18 | Lembar label buta-skor untuk jawaban run 1 | agent |  | setuju + terima hasil |
| S19 | PELABELAN oleh manusia (buta skor, rubrik terkunci) | MANUSIA |  | selesai |
| S20 | Impor label (validasi + kunci) | agent |  | setuju + terima hasil |
| S21 | Lembar mutasi Track M (urutan kandidat pra-registrasi) | agent |  | setuju + terima hasil |
| S22 | MUTASI jawaban oleh manusia (urut, tanpa memilih yang mudah) | MANUSIA |  | selesai |
| S23 | Impor mutasi (verifikasi mekanis) | agent |  | setuju + terima hasil |
| S24 | Gabungkan label Track R + Track M | agent |  | setuju + terima hasil |
| S25 | Lembar relabel (8 jawaban terstratifikasi, tanpa label pertama) | agent |  | setuju + terima hasil |
| S26 | RELABEL oleh manusia (jeda >= 12 jam, buta label pertama) | MANUSIA |  | selesai, tunggu 12 jam |
| S27 | Impor relabel + kesepakatan intra-rater | agent |  | setuju + terima hasil |
| S28 | Upaya validator kedua (dicatat) | MANUSIA |  | selesai |
| S29 | Ringkasan pra-evaluator (tanpa skor) | agent |  | setuju + terima hasil |
| S30 | Kirim ringkasan pra-evaluator sebelum skor dihitung | MANUSIA |  | selesai |
| S31 | Skor tahap I (evidence oracle: kutipan jangkar) | agent |  | setuju + terima hasil |
| S32 | Skor tahap II (konteks hasil retrieval; hanya jawaban asli) | agent |  | setuju + terima hasil |
| S33 | Ukur latency evaluator konfigurasi C dan D (>=100 iterasi, setelah warm-up) | agent |  | setuju + terima hasil |
| S34 | Sweep tahap I pada validation + pemilihan parameter (R1/R2) | agent |  | setuju + terima hasil |
| S35 | Sweep tahap II pada validation + pemilihan parameter | agent |  | setuju + terima hasil |
| S36 | TEST tahap I: sekali, parameter beku | agent | TAK-TERULANG | setuju + terima hasil |
| S37 | TEST tahap II: sekali, parameter beku | agent | TAK-TERULANG | setuju + terima hasil |
| S38 | OPSIONAL — capture run 2 (replikasi; analisis per-run belum otomatis) | agent | API berbayar | setuju + terima hasil |
| S39 | OPSIONAL — capture run 3 (replikasi; analisis per-run belum otomatis) | agent | API berbayar | setuju + terima hasil |

## 4. Jadwal yang realistis (hari ini Rabu 4 Nov, 17.00 WIB; batas kirim Senin 9 Nov)

| Kapan | Langkah | Perkiraan | Catatan |
|---|---|---|---|
| Rab sore–malam | S00–S06 | 1–2 jam (sebagian menunggu Reducto) | S05 pilot 3 halaman dulu; baru S06. Cek `corpus_summary.md` hasilnya. |
| Rab malam / Kam pagi | S07–S10 | 3–4 jam manusia | QA gambar halaman jangkar (S07) dan 20 pertanyaan (S08) tidak bisa dipercepat. Dua dokumen scan (Perpres 59/2024, 64/2020) wajib visual. |
| Kam siang | S11–S15 | 1 jam | S11 mengunci protokol. Setelah S11 dan S14 tidak ada jalan kembali tanpa amandemen. |
| Kam sore | S18–S20 | 1–2 jam manusia | Pelabelan 20 jawaban, buta skor. **Waktu impor S20 memulai jam 12 jam relabel.** |
| Kam malam / Jum | S21–S24 | 2 jam manusia | 10 mutasi berurutan; halaman jangkar kebalikan dibuka satu per satu. |
| Jum sore | S25–S29 | 1 jam | S26 baru boleh sekitar 12 jam setelah S20. Bila S20 selesai Kamis 18.00, relabel paling cepat Jumat 06.00. Cari validator kedua (S28) sejak Kamis. |
| Jum malam | S30 | 10 menit | Kirim ringkasan pra-evaluator. Skor belum boleh dihitung sebelum ini. |
| Sab | S31–S37 | 1–2 jam | Skor, latency, sweep, test sekali. Apa pun hasilnya dilaporkan. |
| Sab malam–Sen | naskah | sisa waktu | Awali setiap klaim dengan "Di bawah pelabelan validator tunggal (intra-rater agreement X%, n=...)". |

Jika jeda 12 jam tidak muat, set `TA_ACCEPT_SHORT_GAP=1` sebelum S26/S27: relabel jalan lebih cepat dan deviasi tercatat di hasil dan ringkasan; tulis di naskah.
Jadwal ini hanya muat bila tidak ada kejutan di S06 dan S13. Pelabelan Kamis sore adalah titik kritisnya.

## 5. Bila sesuatu gagal

- `FAILED` di tabel `status` menampilkan alasan pertama (kode keluar atau penjaga). Ledger menyimpan 4000 karakter terakhir stdout/stderr.
- **Penjaga pra-langkah gagal**: perbaiki sumbernya (mis. label belum terkunci), jangan mengakali penjaga.
- **S13 smoke: jawaban terpotong (`finish_reason=length`)**: `reject S13`, hapus `data/smoke/answers_smoke.jsonl`, naikkan `max_tokens` di `config/generator.json`, ulang S13. Sesudah S14 beku, tidak bisa.
- **Run capture gagal di tengah**: file run baru ditulis di akhir, jadi tidak ada run setengah jadi. Ulangi dengan `reject` lalu setujui lagi.
- **Reducto gagal sebagian**: skrip parsing memakai ulang raw yang sudah ada; ulang S06 aman, tidak membayar dokumen yang sudah ter-parse.
- **`STALE`**: langkah hulu diulang dengan hasil berbeda; hilir harus dijalankan ulang. Agent tidak melakukannya otomatis.
- **`DRIFT` pada `verify`**: berkas hasil/bukti berubah setelah dicatat. Pulihkan berkas atau `reject` langkahnya dengan alasan; jangan membiarkannya.

## 6. Aturan "data asli" (apa yang benar-benar dicegah)

| Penjaga | Menolak |
|---|---|
| `pdfs_real` | PDF yang SHA256/jumlah halamannya beda dari audit korpus |
| `reducto_provenance` | JSON Reducto tanpa manifest (mis. ekspor UI/fixture yang disalin), tanpa `job_id`, model bukan `r-1`, atau raw diubah setelah parsing |
| `parse_human_qa` | Dokumen sumber bukti tanpa QA fidelitas manusia berstatus PASS/PASS_WITH_NOTES + reviewer + tanggal |
| `questions_verified` | Pertanyaan yang belum HUMAN_VERIFIED, tanpa validator/tanggal, atau SHA256 sumbernya tak cocok |
| `protocol_locked`, `generator_frozen` | Protokol/generator yang berubah setelah dikunci/dibekukan |
| `captures_real` | Jawaban tanpa respons API mentah, tanpa `usage`, bukan model MiMo, `prompt_sha256` beda dari pembekuan, cap waktu sebelum pembekuan, atau semua cap waktu identik |
| `labels_valid`, `labels_all_valid` | Label dengan >1 validator/kosong, belum terkunci, memuat skor, dibuat sebelum protokol dikunci, atau teks jawaban berbeda dari hasil capture |
| `relabel_gap` | Relabel dengan jeda <12 jam yang deviasinya tidak diakui |
| `no_synthetic` | Berkas data berpenanda `synthetic/dummy/fake/fixture/stub` atau berjalur fixture |

Tes kode memang memakai berkas buatan tangan (tidak mungkin sebaliknya sebelum ada log nyata); fungsinya menguji penolakan di atas. Data penelitian tidak boleh dibuat dengan
cara itu, dan alur menolaknya. Mau mencoba alur dengan data tiruan? Lakukan di salinan repo terpisah dan jangan menyalin hasilnya ke repo ini.

## 7. Batas keamanan yang jujur

Pada mesin yang agent-nya punya shell, tidak ada gerbang perangkat lunak yang tak bisa dipalsukan. Yang dijamin: agent tanpa TTY tidak dapat menyetujui lewat CLI; mengubah ledger atau
hasil terdeteksi (`verify`); kecelakaan dan pintasan ditolak. Yang tidak dijamin: orang yang sengaja memalsukan ledger sekaligus semua penanda provenans. Gerbang ini melindungimu dari
dirimu yang terburu-buru pada Minggu malam, bukan dari penguji yang curiga. Penguji yang curiga akan meminta log mentah API (`data/runs/*.jsonl` memuat respons mentah utuh) dan ledger; keduanya ada.

## 8. Belum otomatis (jangan berpura-pura sudah)

1. **Tabel dan teks naskah.** Hasil ada di `data/results/{I,II}/` (stage_A/B/C.csv, selection.json, test_result.json) dan `data/labels/`. Tabel naskah belum digenerasi.
2. **Label tahap II untuk abstain pada pertanyaan berjawab.** Aturan rubrik: di tahap II abstain LAYAK hanya bila `retrieval_ok=false`. Impor label memakai satu label per jawaban (aturan tahap I); bila ada abstain pada pertanyaan berjawab,
   tinjau manual sebelum melaporkan tahap II.
3. **Latency.** `pipeline latency` mengukur evaluator C dan D pada w_s=0,6 dan accept=0,78 (latency tidak bergantung ambang; ia bergantung pada embedding dan hard-fail). Hasilnya dipakai untuk tie-break; ia bukan latency end-to-end.
5. **Replikasi run 2-3 (S38-S39, opsional).** Protokol mensyaratkan k=3 karena generator SaaS tidak dijamin deterministik, tetapi belum ada langkah yang melabeli jawaban run 2-3 yang berbeda dari run 1 (`protocol.distinct_answers`) dan menghitung metrik per run (rata-rata + rentang). Menjalankan S38-S39 sekarang hanya mengumpulkan bahan, dan membayar 40 panggilan API. Tanpa analisisnya, naskah harus menyatakan: hanya run 1 yang dianalisis; non-determinisme generator tidak diukur.
