# HASIL VERIFIKASI PDF JKN/BPJS KESEHATAN

Tanggal: 2026-11-01. Sumber: ZIP yang diunggah pengguna `Archive(1).zip`.

## Keputusan (23 PDF, 23 hash SHA-256 unik)

- UTAMA: 5 PDF; konten khusus JKN, siap diproses sebagai korpus regulasi/pedoman terbatas.
- HISTORIS: 3 PDF; hanya statistik/laporan JKN menurut periode dokumen.
- RIWAYAT: 5 PDF; regulasi dasar/amandemen. **Jangan indeks sebagai aturan sekarang tanpa konsolidasi pasal.**
- TAHAN: 5 PDF; relevan tapi terdapat ketidakpastian edisi/provenance, perubahan regulasi, atau cakupan administratif yang tidak sesuai chatbot umum. **Tidak disertakan dalam ZIP siap parsing.**
- TOLAK: 5 PDF; topik terlalu umum atau sudah dicabut. **Tidak disertakan dalam ZIP siap parsing.**

## Validasi yang berhasil

Seluruh 23 berkas: header PDF valid; dapat dibuka dengan PyMuPDF; seluruh objek halaman dapat diakses; empat halaman sampel di setiap PDF mengandung teks; tidak ada duplikasi SHA-256 identik. Sampel sampul 23 PDF juga ditinjau secara visual.

### Batas verifikasi untuk publikasi ilmiah

**Verifikasi struktur PDF dan identitas dokumen ≠ autentikasi kriptografis penerbit.** SHA-256 berkas pengguna sudah dihitung, tetapi **tidak dapat dicocokkan dengan berkas yang diunduh langsung dari server pemerintah** karena akses unduh dalam lingkungan audit terblokir. URL resmi/indeks JDIH digunakan untuk memeriksa identitas/judul dan beberapa status regulasi. Status hukum harus dicek ulang pada tanggal publikasi. PDF dengan halaman tabel kompleks (khususnya Permenkes 3/2023 721 halaman dan buku statistik) wajib diverifikasi manual setelah parsing Markdown.

## Aturan RAG agar tidak terjadi citation pollution

1. Parse hanya PDF di paket ini, pertahankan `doc_id`, `nama_pdf_bersih`, `sha256`, `halaman`, `status_seleksi`, dan `periode`.
2. `UTAMA`: boleh dipakai untuk QA JKN dengan caveat aturan khusus yang lebih baru dan aturan induk yang belum lengkap.
3. `HISTORIS`: hanya untuk kueri berperiode (2015–2019, 2016–2021, 2023); jangan infer statistik terkini.
4. `RIWAYAT`: belum boleh menjadi sumber jawaban ketentuan sekarang sebelum dokumen induk dan amandemen diterapkan ke satu versi konsolidasi per-pasal.
5. `TAHAN` dan `TOLAK` tidak termasuk input parsing dari ZIP ini. Detail dan langkah perbaikan ada di CSV audit.
6. Pertahankan teks halaman dan tabel dengan identitas halaman sumber; evaluasi chunk berbasis halaman/pasal.

## Dokumen yang penting tetapi BELUM ADA di unggahan

- Perpres 82/2018 (aturan induk JKN).
- Perpres 75/2019 (perubahan pertama Perpres 82/2018).
- Permenkes 99/2015 (perubahan pertama Permenkes 71/2013).
- Kepmenkes 34/2025 (perubahan Kepmenkes 2090/2023).

Sebelum paper final, lengkapi chain-of-amendment dan publikasikan prosedur seleksi, waktu audit, tautan resmi, SHA-256, serta peninjauan manual dokumen parsed.
