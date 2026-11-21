# Kasus format Tabel 14 (konfigurasi D; aturan D16: kasus pertama menurut answer_id)

Parameter D: bobot S:L 25:75, threshold ACCEPT 0.85, hard-fail True

## Jawaban layak yang diterima (ACCEPT)

- Sumber kasus: test; answer_id `run1:T17`; case_id `T17`; Track R
- Pertanyaan: Menurut Keputusan Menteri Kesehatan Nomor HK.01.07/MENKES/1511/2023, bagaimana pemeriksaan triple eliminasi dalam pemeriksaan kehamilan oleh FKTP selain Puskesmas dapat dilakukan?
- Sumber resmi: kepmenkes_1511_2023_layanan_kebidanan_neonatal_jkn hlm. 8; kutipan: "Pemeriksaan triple eliminasi dalam pemeriksaan kehamilan oleh FKTP selain Puskesmas dapat dilakukan dengan rujukan horizontal ke Puskesmas dengan pembiayaan program."
- Retrieved chunk_ids: ['kepmenkes_1511_2023_layanan_kebidanan_neonatal_jkn::Pembuka::0007-0008::3', 'permenkes_03_2023_standar_tarif_jkn::Pasal19::0013-0014::0', 'permenkes_03_2023_standar_tarif_jkn::Pasal20::0014-0015::0', 'kepmenkes_1511_2023_layanan_kebidanan_neonatal_jkn::Pembuka::0001-0003::0']
- Jawaban (original_llm): Menurut konteks yang tersedia, pemeriksaan triple eliminasi dalam pemeriksaan kehamilan oleh FKTP selain Puskesmas dapat dilakukan dengan **rujukan horizontal ke Puskesmas dengan pembiayaan program**.
- Label manual: LAYAK; validator Fiantyo Galih Pramudya; dilabeli 2026-11-16T14:40:21+00:00
- Skor: L=0.895, S=0.983, H_D=0.916823; flags: -
- Keputusan: ACCEPT (cocok dengan label manual)

## Jawaban tidak layak yang ditahan (REVIEW/REJECT)

- Sumber kasus: test; answer_id `M1:T01`; case_id `T01`; Track M
- Pertanyaan: Menurut Peraturan BPJS Kesehatan Nomor 3 Tahun 2024, apa yang dimaksud dengan Pelayanan Penapisan atau Skrining Kesehatan Tertentu?
- Sumber resmi: bpjs_03_2024_skrining_peserta_jkn hlm. 2; kutipan: "Pelayanan Penapisan atau Skrining Kesehatan Tertentu adalah deteksi risiko penyakit tertentu, melalui pemeriksaan atau prosedur spesifik secara cepat, serta pencegahan dampak lanjutan risiko penyakit."
- Retrieved chunk_ids: (mutasi: tidak melalui retrieval)
- Jawaban (mutasi_terkontrol): Menurut **Peraturan BPJS Kesehatan Nomor 3 Tahun 2024**, dalam Pasal 1 angka 1, yang dimaksud dengan **Pelayanan Penapisan atau Skrining Kesehatan Tertentu** tidak adalah:

> **Deteksi risiko penyakit tertentu, melalui pemeriksaan atau prosedur spesifik secara cepat, serta pencegahan dampak lanjutan risiko penyakit.**
- Label manual: TIDAK_LAYAK; validator Fiantyo Galih Pramudya; dilabeli 2026-11-18T13:11:00+00:00
- Skor: L=0.727, S=0.825, H_D=0.751763; flags: -
- Keputusan: REVIEW (cocok dengan label manual)

## Jawaban tidak layak yang tetap diterima (ACCEPT)

- Sumber kasus: test; answer_id `M2:T40`; case_id `T40`; Track M
- Pertanyaan: Menurut Peraturan Menteri Kesehatan Nomor 28 Tahun 2014, verifikasi dan validasi perubahan data Penerima Bantuan Iuran (PBI) oleh Menteri Sosial dilakukan setiap berapa bulan dalam tahun anggaran berjalan?
- Sumber resmi: permenkes_28_2014_pedoman_jkn hlm. 14; kutipan: "Perubahan data Penerima Bantuan Iuran (PBI) dilakukan oleh Menteri Sosial melalui verifikasi dan validasi setiap 6 (enam) bulan dalam tahun anggaran berjalan sesuai Peraturan Pemerintah Nomor 101 Tahun 2012 tentang Penerima Bantuan Iuran (PBI) Jaminan Kesehatan."
- Retrieved chunk_ids: (mutasi: tidak melalui retrieval)
- Jawaban (mutasi_terkontrol): Berdasarkan Peraturan Menteri Kesehatan Nomor 28 Tahun 2014 (Pasal 4), verifikasi dan validasi perubahan data Penerima Bantuan Iuran (PBI) oleh Menteri Sosial dilakukan setiap **6 (enam) hari** dalam tahun anggaran berjalan, sesuai dengan Peraturan Pemerintah Nomor 101 Tahun 2012 tentang Penerima Bantuan Iuran Jaminan Kesehatan.
- Label manual: TIDAK_LAYAK; validator Fiantyo Galih Pramudya; dilabeli 2026-11-18T13:11:00+00:00
- Skor: L=0.866, S=0.962, H_D=0.889661; flags: -
- Keputusan: ACCEPT (tidak cocok dengan label manual)
