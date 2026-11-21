# Kasus format Tabel 14 (konfigurasi B; aturan D16: kasus pertama menurut answer_id) — tambahan, tidak dipra-registrasi (aturan D16 yang sama dipakai pada konfigurasi ini)

Parameter B: bobot S:L 100:0, threshold ACCEPT 0.85, hard-fail False

## Jawaban layak yang diterima (ACCEPT)

- Sumber kasus: test; answer_id `run1:T10`; case_id `T10`; Track R
- Pertanyaan: Menurut Peraturan BPJS Kesehatan Nomor 3 Tahun 2024, jika Peserta JKN mendapatkan skrining Diabetes Mellitus atau IVA pada Upaya Kesehatan Bersumber Daya Masyarakat, pembiayaan skrining tersebut masuk dalam mekanisme penjaminan program apa?
- Sumber resmi: bpjs_03_2024_skrining_peserta_jkn hlm. 18; kutipan: "Jika pasien adalah Peserta JKN, mendapatkan Pelayanan Penapisan atau Skrining Kesehatan Tertentu (skrining Diabetes Mellitus atau IVA) pada Upaya Kesehatan Bersumber Daya Masyarakat maka pembiayaan skrining tersebut masuk dalam mekanisme penjaminan Program Pemerintah selain Program JKN."
- Retrieved chunk_ids: ['bpjs_03_2024_skrining_peserta_jkn::Pasal32::0018-0020::1', 'permenkes_28_2014_pedoman_jkn::Pasal4::0044-0046::18', 'kepmenkes_1511_2023_layanan_kebidanan_neonatal_jkn::Pembuka::0007-0008::3', 'permenkes_28_2014_pedoman_jkn::Pasal4::0047-0048::20']
- Jawaban (original_llm): Menurut Penjelasan Matriks Pasal 32 Lampiran II Peraturan BPJS Kesehatan Nomor 3 Tahun 2024 (hlm. 18–20):

Jika pasien adalah Peserta JKN dan mendapatkan Pelayanan Penapisan atau Skrining Kesehatan Tertentu (skrining Diabetes Mellitus atau IVA) **pada Upaya Kesehatan Bersumber Daya Masyarakat**, maka pembiayaan skrining tersebut masuk dalam **mekanisme penjaminan Program Pemerintah selain Program JKN**.
- Label manual: LAYAK; validator Fiantyo Galih Pramudya; dilabeli 2026-11-16T14:40:21+00:00
- Skor: L=0.779, S=0.924, H_B=0.924188; flags: -
- Keputusan: ACCEPT (cocok dengan label manual)

## Jawaban tidak layak yang ditahan (REVIEW/REJECT)

- Sumber kasus: test; answer_id `M1:T01`; case_id `T01`; Track M
- Pertanyaan: Menurut Peraturan BPJS Kesehatan Nomor 3 Tahun 2024, apa yang dimaksud dengan Pelayanan Penapisan atau Skrining Kesehatan Tertentu?
- Sumber resmi: bpjs_03_2024_skrining_peserta_jkn hlm. 2; kutipan: "Pelayanan Penapisan atau Skrining Kesehatan Tertentu adalah deteksi risiko penyakit tertentu, melalui pemeriksaan atau prosedur spesifik secara cepat, serta pencegahan dampak lanjutan risiko penyakit."
- Retrieved chunk_ids: (mutasi: tidak melalui retrieval)
- Jawaban (mutasi_terkontrol): Menurut **Peraturan BPJS Kesehatan Nomor 3 Tahun 2024**, dalam Pasal 1 angka 1, yang dimaksud dengan **Pelayanan Penapisan atau Skrining Kesehatan Tertentu** tidak adalah:

> **Deteksi risiko penyakit tertentu, melalui pemeriksaan atau prosedur spesifik secara cepat, serta pencegahan dampak lanjutan risiko penyakit.**
- Label manual: TIDAK_LAYAK; validator Fiantyo Galih Pramudya; dilabeli 2026-11-18T13:11:00+00:00
- Skor: L=0.727, S=0.825, H_B=0.825233; flags: -
- Keputusan: REVIEW (cocok dengan label manual)

## Jawaban tidak layak yang tetap diterima (ACCEPT)

- Sumber kasus: test; answer_id `M1:T10`; case_id `T10`; Track M
- Pertanyaan: Menurut Peraturan BPJS Kesehatan Nomor 3 Tahun 2024, jika Peserta JKN mendapatkan skrining Diabetes Mellitus atau IVA pada Upaya Kesehatan Bersumber Daya Masyarakat, pembiayaan skrining tersebut masuk dalam mekanisme penjaminan program apa?
- Sumber resmi: bpjs_03_2024_skrining_peserta_jkn hlm. 18; kutipan: "Jika pasien adalah Peserta JKN, mendapatkan Pelayanan Penapisan atau Skrining Kesehatan Tertentu (skrining Diabetes Mellitus atau IVA) pada Upaya Kesehatan Bersumber Daya Masyarakat maka pembiayaan skrining tersebut masuk dalam mekanisme penjaminan Program Pemerintah selain Program JKN."
- Retrieved chunk_ids: (mutasi: tidak melalui retrieval)
- Jawaban (mutasi_terkontrol): Menurut Penjelasan Matriks Pasal 32 Lampiran II Peraturan BPJS Kesehatan Nomor 3 Tahun 2024 (hlm. 18–20):

Jika pasien adalah Peserta JKN dan mendapatkan Pelayanan Penapisan atau Skrining Kesehatan Tertentu (skrining Diabetes Mellitus atau IVA) **pada Upaya Kesehatan Bersumber Daya Masyarakat**, maka pembiayaan skrining tersebut tidak masuk dalam **mekanisme penjaminan Program Pemerintah selain Program JKN**.
- Label manual: TIDAK_LAYAK; validator Fiantyo Galih Pramudya; dilabeli 2026-11-18T13:11:00+00:00
- Skor: L=0.769, S=0.920, H_B=0.919831; flags: -
- Keputusan: ACCEPT (tidak cocok dengan label manual)
