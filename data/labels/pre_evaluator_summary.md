# Ringkasan pra-evaluator

## 1. Distribusi label Track R (jawaban asli)

| question_type | n LAYAK | n TIDAK_LAYAK |
|---|---:|---:|
| definition | 0 | 1 |
| not_in_corpus | 2 | 2 |
| numeric_count | 1 | 0 |
| numeric_date | 1 | 2 |
| numeric_duration | 6 | 1 |
| numeric_money | 2 | 0 |
| numeric_percent | 1 | 0 |
| numeric_range | 1 | 0 |

Total jawaban asli: 20; TIDAK_LAYAK alami: 6.

## 2. Track M: 11 pasangan (semua kandidat LAYAK)

| case_id | family | halaman jangkar yang membuktikan kebalikan |
|---|---|---|
| R06 | numeric_value | BPJS_03_2024_Skrining_Peserta_JKN.pdf, hlm. fisik 13, Pasal 19 ayat (6):
"Jumlah Peserta Prolanis yang mengikuti aktivitas fisik dan/atau edukasi kesehatan sebagaimana dimaksud pada ayat (1) paling sedikit 15 (lima belas) orang dan paling banyak 30 (tiga puluh) orang per klub." |
| R10 | date | Kepmenkes_1511_2023_Layanan_Kebidanan_Neonatal_JKN.pdf, hlm. fisik 12, bagian 3.b Pembiayaan SHK, butir 4):
"Persalinan di fasilitas pelayanan kesehatan yang dilakukan setelah tanggal 1 September 2023 hanya dapat dibayarkan oleh BPJS Kesehatan jika disertai bukti pengambilan sampel SHK" |
| R15 | numeric_value | Permenkes_03_2023_Standar_Tarif_JKN.pdf, hlm. fisik 5, Pasal 4 huruf a:
"Standar Tarif Kapitasi ditetapkan sebagai berikut: a. Puskesmas sebesar Rp3.600,00 (tiga ribu enam ratus rupiah) sampai dengan Rp9.000,00 (sembilan ribu rupiah) per peserta per bulan;" |
| R13 | numeric_value | Permenkes_28_2014_Pedoman_JKN.pdf, hlm. fisik 38, bagian D. Pengelolaan dan Pemanfaatan Dana, butir c.3) FKTP lainnya milik Pemerintah:
"Dana kapitasi yang digunakan untuk Jasa Pelayanan dialokasikan antara 40% - 60% dari total pengembalian dana Penerimaan Negara Bukan Pajak (PNBP) dan sisanya dimanfaatkan untuk dukungan biaya operasional pelayanan kesehatan" |
| R01 | numeric_value | Perpres_59_2024_Perubahan_Ketiga_Jaminan_Kesehatan.pdf, hlm. fisik 3, Pasal 1 angka 2:
"Peserta adalah setiap orang, termasuk orang asing yang bekerja paling singkat 6 (enam) bulan di Indonesia, yang telah membayar Iuran Jaminan Kesehatan." |
| R02 | unit | Perpres_59_2024_Perubahan_Ketiga_Jaminan_Kesehatan.pdf, hlm. fisik 8, Pasal 7 ayat (1):
"Peserta dapat mengganti FKTP tempat Peserta terdaftar setelah jangka waktu 3 (tiga) bulan." |
| R03 | numeric_value | Perpres_59_2024_Perubahan_Ketiga_Jaminan_Kesehatan.pdf, hlm. fisik 9, Pasal 15 ayat (2):
"BPJS Kesehatan harus melakukan verifikasi pendaftaran sebagaimana dimaksud pada ayat (1) dalam waktu 14 (empat belas) hari sejak pendaftaran." |
| R07 | unit | BPJS_03_2024_Skrining_Peserta_JKN.pdf, hlm. fisik 14, Pasal 24 ayat (2):
"Pengajuan klaim penggantian biaya sebagaimana dimaksud pada ayat (1) diberikan jangka waktu paling lambat 3 (tiga) bulan sejak kegiatan kelompok dilaksanakan." |
| R16 | numeric_value | Permenkes_03_2023_Standar_Tarif_JKN.pdf, hlm. fisik 8, Pasal 10 ayat (3):
"Besaran tarif kapitasi khusus sebagaimana dimaksud pada ayat (1) bagi FKTP yang hanya memiliki bidan/perawat ditetapkan sebesar Rp8.000,00 (delapan ribu rupiah) per peserta per bulan." |
| R09 | numeric_value | Kepmenkes_1511_2023_Layanan_Kebidanan_Neonatal_JKN.pdf, hlm. fisik 10, poin 2.e.2):
"Pelayanan persalinan dengan tindakan emergensi dasar di FKTP PONED dilaksanakan minimal 2 (dua) hari, tarif pelayanan dibayarkan sesuai dengan tarif pelayanan persalinan PONED." |
| R12 | unit | Permenkes_28_2014_Pedoman_JKN.pdf, hlm. fisik 35, bagian 5. Mekanisme Pembayaran INA CBGs:
"Klaim FKRTL dibayarkan oleh BPJS Kesehatan paling lambat 15 hari setelah berkas klaim diterima lengkap." |

Kandidat dilewati (mutasi tak dapat diterapkan mekanis):
- R05: Angka kunci jawaban adalah 1 (frekuensi pemeriksaan), sehingga kandidat nilai baru dari urutan faktor 2, 3, 5 adalah 2, 3, dan 5; ketiganya muncul sebagai angka pada halaman jangkar BPJS_03_2024_Skrining_Peserta_JKN.pdf hlm. fisik 8 (nomor butir 2., 3., dan 5. pada Pasal 11 ayat (1) huruf a, nomor ayat (2), serta rujukan "angka 3, angka 4, angka 5, angka 6" pada ayat (2)). Tidak ada faktor dari urutan 2, 3, 5 yang menghasilkan nilai baru yang tidak muncul pada halaman jangkar, sehingga mutasi numeric_value tidak dapat diterapkan.

## 3. Relabel intra-rater

Kesepakatan 6/8 = 75.0%.
Kappa: 0.5 (dilaporkan hanya sebagai pelengkap persentase kesepakatan; n kecil).
- selisih run1:R18: TIDAK_LAYAK → LAYAK
- selisih run1:R20: TIDAK_LAYAK → LAYAK

## 4. Validator kedua

- 2026-11-13 sekitar 15:28 WIB; peran: validator manusia kedua, Penilai B (latar/profesi tidak disebutkan); saluran: WhatsApp menurut keterangan peneliti; hasil: bersedia, meninjau 8 record dengan bantuan AI dan menetapkan keputusan akhir; alasan menolak: tidak berlaku. Peneliti mengonfirmasi pilihan B pada percakapan: Penilai B manusia nyata yang memeriksa serta menetapkan keputusan setelah dibantu AI. Bagian persona/simulasi pada keterangan sebelumnya dijelaskan peneliti sebagai template agent; asal bantuan AI tetap diungkapkan. Berkas hasil: data/labels/second_validator_answer.csv, SHA256 8fdf1ea87fd5cacb740c41cecd28dbe2b8d70e04762763de2369b24f87d4c060, 8 baris lengkap. Ini penilaian manusia berbantuan AI, bukan pemeriksaan tanpa bantuan AI; independensi proses dan kebutaan terhadap label terdahulu tidak diverifikasi secara independen oleh agent. Keputusan tambahan ini tidak mengganti label utama atau relabel intra-rater yang terkunci. Kontak WhatsApp dan kepengarangan akhir dicatat berdasarkan pernyataan peneliti, bukan hasil pemeriksaan isi chat oleh agent.

**Deviasi:** jeda relabel terdokumentasi paling lama 7.18 jam < 12 jam; diakui saat impor.

Catatan waktu: jeda memakai waktu yang lebih awal antara simpan lembar dan impor sebagai batas atas waktu penyelesaian; bukan pengukuran waktu mulai inspeksi.
