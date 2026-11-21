# Kasus format Tabel 14 (konfigurasi D; aturan D16: kasus pertama menurut answer_id)

Parameter D: bobot S:L 25:75, threshold ACCEPT 0.8, hard-fail True

## Jawaban layak yang diterima (ACCEPT)

- Sumber kasus: validation (cadangan); answer_id `run1:R01`; case_id `R01`; Track R
- Pertanyaan: Menurut Peraturan Presiden Nomor 59 Tahun 2024, orang asing yang bekerja paling singkat berapa lama di Indonesia yang termasuk dalam pengertian Peserta?
- Sumber resmi: perpres_59_2024_perubahan_ketiga_jaminan_kesehatan hlm. 3; kutipan: "Peserta adalah setiap orang, termasuk orang asing yang bekerja paling singkat 6 (enam) bulan di Indonesia, yang telah membayar Iuran Jaminan Kesehatan."
- Retrieved chunk_ids: ['bpjs_03_2024_skrining_peserta_jkn::Pasal1::0003-0003::1', 'perpres_59_2024_perubahan_ketiga_jaminan_kesehatan::Pasal1::0003-0005::0', 'permenkes_71_2013_pelayanan_jkn::Pasal1::0003-0004::0', 'permenkes_28_2014_pedoman_jkn::Pasal4::0005-0007::0']
- Jawaban (original_llm): Menurut Peraturan Presiden Nomor 59 Tahun 2024 (Pasal 1 angka 2), **Peserta** adalah setiap orang, termasuk orang asing yang bekerja **paling singkat 6 (enam) bulan** di Indonesia, yang telah membayar Iuran Jaminan Kesehatan.
- Label manual: LAYAK; validator Fiantyo Galih Pramudya; dilabeli 2026-11-12T10:06:51+00:00
- Skor: L=0.784, S=0.917, H_D=0.817485; flags: -
- Keputusan: ACCEPT (cocok dengan label manual)

## Jawaban tidak layak yang ditahan (REVIEW/REJECT)

- Sumber kasus: test; answer_id `M:R02`; case_id `R02`; Track M
- Pertanyaan: Menurut Peraturan Presiden Nomor 59 Tahun 2024 Pasal 7 ayat (1), setelah jangka waktu berapa lama Peserta dapat mengganti FKTP tempat Peserta terdaftar?
- Sumber resmi: perpres_59_2024_perubahan_ketiga_jaminan_kesehatan hlm. 8; kutipan: "Peserta dapat mengganti FKTP tempat Peserta terdaftar setelah jangka waktu 3 (tiga) bulan"
- Retrieved chunk_ids: (mutasi: tidak melalui retrieval)
- Jawaban (mutasi_terkontrol): Menurut **Pasal 7 ayat (1)** Peraturan Presiden Nomor 59 Tahun 2024, Peserta dapat mengganti FKTP tempat Peserta terdaftar **setelah jangka waktu 3 (tiga) hari**.
- Label manual: TIDAK_LAYAK; validator Fiantyo Galih Pramudya; dilabeli 2026-11-13T00:24:27+00:00
- Skor: L=0.629, S=0.896, H_D=0.695477; flags: -
- Keputusan: REVIEW (cocok dengan label manual)

## Jawaban tidak layak yang tetap diterima (ACCEPT)

Tidak ditemukan. Jumlah jawaban berlabel TIDAK_LAYAK yang diperiksa: 15 (test + validation). Ini hasil pencarian, bukan klaim bebas kesalahan.
