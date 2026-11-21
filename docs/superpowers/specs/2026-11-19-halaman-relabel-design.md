# Halaman pelabelan lokal untuk S26 dan S28 (desain singkat, 19 Nov 2026)

Status: DISETUJUI pengguna 19 Nov ("ya, lakukan implementasi dengan sonnet 5.5 high"); dibangun dan ditinjau, lihat SPEC v4.2.23. Pembangun: subagent Sonnet 5.5, effort high.

## Maksud
Mempercepat relabel 60 butir oleh validator (S26) dan penilaian 60 butir yang sama oleh validator kedua (S28) tanpa AI ikut
menilai. Yang dipangkas hanya kerja mekanis: membuka PDF, mencari halaman jangkar, membaca sel CSV panjang, dan mencari angka,
rujukan Pasal, atau kata seperti "sebelum". Setiap label tetap diputuskan manusia.

## Tujuan
- Satu butir per layar: pertanyaan, jawaban dan kutipan jangkar berdampingan, teks rubrik terkunci (kolom `rubric` lembar), dan
  gambar halaman jangkar.
- Penanda seragam pada jawaban DAN kutipan, dengan aturan sama untuk semua butir (daftar di bawah). Tidak ada vonis.
- Tombol 1 = LAYAK, 2 = TIDAK_LAYAK, 3 = INSUFFICIENT_EVIDENCE (`data.LABELS`; rubrik `evidence_ambiguity`), kotak alasan opsional,
  ←/→ pindah butir.
- Simpan otomatis di browser. Ekspor CSV diterima `labeling.import_relabel_sheet` dan `import_second_rater` tanpa mengubah sel lain.
- Halaman S26 dan S28 dibangun dari lembar kosong yang identik, dan isinya sama kecuali nama unduhan dan penahan waktu S26.

## Bukan tujuan
- Saran label, skor, ringkasan, atau catatan per butir, baik dari model AI maupun kode evaluator. Catatan AI per butir baru boleh
  dibuat setelah S27 terkunci, untuk adjudikasi dan analisis galat.
- Daftar periksa tulisan agent di halaman. Halaman hanya memuat rubrik terkunci, supaya S28 tetap tanpa bantuan AI dari sisi isi.
- Mengubah `config/workflow.json`, `config/protocol.json`, importir, atau penjaga.
- Menyorot kutipan di dalam gambar, atau menampilkan halaman sebelum/sesudah halaman jangkar.
- Log waktu per butir (dapat ditambah bila diminta).
- Artifact claude.ai atau hosting. Berkasnya lokal, tanpa internet, jadi data penelitian tetap di mesin pengguna.

## Anti-tujuan (dianggap gagal walaupun berjalan)
- Halaman membuka label pertama, skor, atau asal jawaban (`answer_id`, `runK:`, `M1:`/`M2:`).
- Halaman validator kedua memuat label relabel validator pertama.
- Ekspor mengubah teks pertanyaan/jawaban, atau ditolak importir.
- Label S26 dapat diberikan sebelum jeda 24 jam terpenuhi.

## Batasan
- CLAUDE.md aturan 14, 22, 23; `protocol.json` → `relabel.blind_to` dan `second_validator.who` (terkunci).
- Masukan hanya lembar relabel kosong (`item_id`), `data/cases/questions_draft.jsonl`, dan PDF asli. Pembangun TIDAK membaca
  `relabel_sample.json` atau `labels_all.jsonl`.
- Ledger dan workflow tidak disentuh (aturan 24).
- Uji kering tidak boleh lewat CLI di worktree: tes memakai `tmp_path` (memori "uji kering menulis ke worktree asli").

## Pendekatan
- A. Daftar periksa rubrik saja, tanpa kode.
- **B. Daftar periksa + halaman pelabelan lokal (dipilih pengguna, 19 Nov).**
- Ditolak: catatan AI per butir sebelum S27 terkunci. Catatan semacam itu membuka asal 15 mutasi (`relabel.blind_to`) dan
  membuat S28 tidak sah sebagai inter-rater (`second_validator.if_ai_assisted`).

## Rancangan
- `src/ta_rag/relabel_page.py`:
  `build_page(sheet_csv, cases_jsonl, pdf_dir, out_html, download_name, not_before=None, dpi=100) -> dict`, ditambah CLI
  `python -m ta_rag.relabel_page` (`--sheet --cases --pdf-dir --out --download-name [--not-before] [--dpi]`).
  - Membaca lembar dengan `labeling._read_csv`. Urutan kolom dan baris dipertahankan (R01…R60 = urutan pra-registrasi).
  - Menolak (ValueError): lembar tanpa `item_id`; kolom pembuka asal/label (`answer_id`, `label`, `label_first`, `origin`, `route`,
    `H`); `label_baru` atau `alasan_bila_berbeda` yang sudah terisi; `case_id` yang tidak ada di kasus; `out_html` yang sudah ada
    (`labeling._guard_new`).
  - Halaman jangkar unik (`source_file`, `source_page`) dirender sekali dengan `ocr_check.render_page` (pdftoppm, PNG, 100 dpi)
    lalu disisipkan sebagai base64. Perkiraan dari 6 halaman nyata: 244 KB per halaman, sekitar 12 MB untuk 36 halaman (hasil nyata dpi 100: 10,3 MB).
    Butir probe (`source_page` null: T64, T70, T71) tidak punya halaman jangkar, jadi tidak diberi gambar; halaman menuliskannya
    (koreksi 19 Nov: angka awal "39" keliru karena ikut menghitung pasangan (berkas, None)).
  - Data disisipkan sebagai JSON: kolom, baris, gambar per halaman unik (`images`, kunci `<berkas>#<halaman>`) dengan peta `page_of` per `case_id`, sha256 lembar, nama unduhan, `not_before`.
  - Mengembalikan ringkasan: jumlah butir, jumlah gambar, ukuran berkas, sha256 lembar.
- `src/ta_rag/relabel_page.js` disisipkan ke HTML dan bisa di-`require` node untuk tes:
  - `mark(text)`: escape HTML dulu, lalu menandai pola.
  - `toCSV(columns, rows)`: BOM, baris CRLF, pengutipan RFC 4180, baris baru di dalam sel dipertahankan.
- Tampilan:
  - Teks ditampilkan mentah seperti di lembar, termasuk `**`, dengan baris baru dipertahankan.
  - `case_id` tidak ditampilkan, supaya butir tidak mudah dikelompokkan; kolom itu tetap ikut diekspor.
  - Ada satu baris instruksi tetap: "Nilai tiap jawaban dengan rubrik di bawah. Jangan memakai alat AI."
- Penahan waktu S26: `--not-before 2026-11-19T20:12:00+07:00`. Jeda 24 jam dari `labeled_at` terakhir di sampel (18 Nov 20.11.00
  WIB) jatuh pada 19 Nov 20.11.00 WIB. Tombol label nonaktif sampai jam lokal melewati batas itu, dan diperiksa ulang setiap kali
  tombol label dipakai. Halaman S28 tanpa penahan.
- Ekspor aktif hanya bila 60/60 berlabel. Nama unduhan: `relabel_sheet.csv` (S26) atau `second_rater_sheet.csv` (S28).
- Simpan otomatis: `localStorage` dengan kunci sha256 lembar + nama unduhan + `not_before` (draf tidak dipulihkan selama penahan aktif), dibungkus try/catch. Bila tidak tersedia, statusnya
  terlihat di layar.
- Keluaran disimpan di `data/relabel_page/` dan ditambahkan ke `.gitignore`, karena berisi turunan halaman PDF (aturan 16).

## Pola yang ditandai (keputusan agent; dapat diubah sebelum dibangun)
- Rujukan: `Pasal N`, `ayat (N)`, `huruf x`.
- Angka: digit dengan pemisah, awalan `Rp`, akhiran `%`. Hanya untuk tampilan; ekstraksi hard-fail tetap `ta_rag.numbers`.
- Kata (utuh, tanpa beda huruf besar/kecil): tidak, bukan, belum, tanpa, kecuali, selain, hanya, paling, lebih, kurang, sebelum,
  sesudah, setelah, sejak, sampai.

## Uji
1. Bangun dari lembar tiruan 3 baris di `tmp_path` + PDF kecil (reportlab): semua `item_id` ada, gambar tersisip, tidak ada string
   `answer_id`.
2. Kelima penolakan di atas.
3. node (skip bila tidak ada): `toCSV` → berkas → `labeling.import_relabel_sheet` dengan sampel dan `labels_all` tiruan di
   `tmp_path`. Lembar harus diterima, labelnya sesuai, dan semua sel lain identik, termasuk koma, tanda kutip, baris baru, dan Unicode.
4. node: `mark` meng-escape `<script>` dan menandai "Pasal 7 ayat (2)", "100", serta "sebelum".
5. Data asli (skip tanpa `TA_RAG_PDF_DIR`): 60 butir dan 36 gambar, dan tidak satu pun `answer_id` dari `relabel_sample.json` muncul
   di HTML.
- Satu uji mutasi (CLAUDE.md) memakai harness dengan pyc bersih (memori). Suite penuh harus hijau.

## Pengungkapan (SPEC v4.2.23 dan naskah)
"Relabel (S26) dan penilai kedua (S28) memakai halaman pelabelan lokal yang sama: satu butir per layar, gambar halaman jangkar, dan
penanda seragam untuk angka, rujukan pasal, serta kata negasi/pengecualian/waktu. Halaman dibuat oleh agent sebagai kode dan tidak
memuat keluaran model AI selain jawaban generator yang dinilai, saran label, label pertama, skor, atau asal jawaban. Label pertama (S19) memakai lembar CSV."

## Diserahkan ke pembangun
Tata letak CSS, gaya penanda, teks tombol dan pesan galat, serta perilaku zoom gambar.
