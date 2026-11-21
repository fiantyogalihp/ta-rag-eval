# Kasus format Tabel 14 (konfigurasi B; aturan D16: kasus pertama menurut answer_id) — tambahan, tidak dipra-registrasi (aturan D16 yang sama dipakai pada konfigurasi ini)

Parameter B: bobot S:L 100:0, threshold ACCEPT 0.85, hard-fail False

## Jawaban layak yang diterima (ACCEPT)

- Sumber kasus: test; answer_id `run1:R02`; case_id `R02`; Track R
- Pertanyaan: Menurut Peraturan Presiden Nomor 59 Tahun 2024 Pasal 7 ayat (1), setelah jangka waktu berapa lama Peserta dapat mengganti FKTP tempat Peserta terdaftar?
- Sumber resmi: perpres_59_2024_perubahan_ketiga_jaminan_kesehatan hlm. 8; kutipan: "Peserta dapat mengganti FKTP tempat Peserta terdaftar setelah jangka waktu 3 (tiga) bulan"
- Retrieved chunk_ids: ['perpres_59_2024_perubahan_ketiga_jaminan_kesehatan::Pasal7::0008-0009::0', 'perpres_59_2024_perubahan_ketiga_jaminan_kesehatan::Pasal6A::0007-0008::0', 'perpres_59_2024_perubahan_ketiga_jaminan_kesehatan::Pasal42::0012-0014::0', 'perpres_59_2024_perubahan_ketiga_jaminan_kesehatan::Pembuka::0001-0003::0']
- Jawaban (original_llm): Menurut **Pasal 7 ayat (1)** Peraturan Presiden Nomor 59 Tahun 2024, Peserta dapat mengganti FKTP tempat Peserta terdaftar **setelah jangka waktu 3 (tiga) bulan**.
- Label manual: LAYAK; validator Fiantyo Galih Pramudya; dilabeli 2026-11-12T10:06:51+00:00
- Skor: L=0.686, S=0.909, H_B=0.90877; flags: -
- Keputusan: ACCEPT (cocok dengan label manual)

## Jawaban tidak layak yang ditahan (REVIEW/REJECT)

- Sumber kasus: validation (cadangan); answer_id `M:R03`; case_id `R03`; Track M
- Pertanyaan: Menurut Peraturan Presiden Nomor 59 Tahun 2024 (perubahan Pasal 15), dalam waktu berapa hari sejak pendaftaran BPJS Kesehatan harus melakukan verifikasi pendaftaran PBPU dan BP?
- Sumber resmi: perpres_59_2024_perubahan_ketiga_jaminan_kesehatan hlm. 9; kutipan: "verifikasi pendaftaran sebagaimana dimaksud pada ayat (1) dalam waktu 14 (empat belas) hari sejak pendaftaran"
- Retrieved chunk_ids: (mutasi: tidak melalui retrieval)
- Jawaban (mutasi_terkontrol): Berdasarkan **Pasal 15 ayat (2)** Peraturan Presiden Nomor 59 Tahun 2024, BPJS Kesehatan harus melakukan verifikasi pendaftaran PBPU dan BP dalam waktu **28 (dua puluh delapan) hari** sejak pendaftaran.
- Label manual: TIDAK_LAYAK; validator Fiantyo Galih Pramudya; dilabeli 2026-11-13T00:24:27+00:00
- Skor: L=0.333, S=0.817, H_B=0.817315; flags: -
- Keputusan: REVIEW (cocok dengan label manual)

## Jawaban tidak layak yang tetap diterima (ACCEPT)

- Sumber kasus: test; answer_id `M:R02`; case_id `R02`; Track M
- Pertanyaan: Menurut Peraturan Presiden Nomor 59 Tahun 2024 Pasal 7 ayat (1), setelah jangka waktu berapa lama Peserta dapat mengganti FKTP tempat Peserta terdaftar?
- Sumber resmi: perpres_59_2024_perubahan_ketiga_jaminan_kesehatan hlm. 8; kutipan: "Peserta dapat mengganti FKTP tempat Peserta terdaftar setelah jangka waktu 3 (tiga) bulan"
- Retrieved chunk_ids: (mutasi: tidak melalui retrieval)
- Jawaban (mutasi_terkontrol): Menurut **Pasal 7 ayat (1)** Peraturan Presiden Nomor 59 Tahun 2024, Peserta dapat mengganti FKTP tempat Peserta terdaftar **setelah jangka waktu 3 (tiga) hari**.
- Label manual: TIDAK_LAYAK; validator Fiantyo Galih Pramudya; dilabeli 2026-11-13T00:24:27+00:00
- Skor: L=0.629, S=0.896, H_B=0.896195; flags: -
- Keputusan: ACCEPT (tidak cocok dengan label manual)
