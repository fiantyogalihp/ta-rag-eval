# Hipotesis pra-registrasi H1–H3 (split test, Track M, selisih berpasangan per mutasi, klaster = pertanyaan)

Setiap klaim diawali: "Di bawah pelabelan validator tunggal (intra-rater agreement 55%, n=60): "

Putusan pra-registrasi: TERDUKUNG hanya bila CI bootstrap klaster 98,3% (koreksi Bonferroni) atas selisih berpasangan tidak memuat 0 DAN selisih ≥ 10 poin persentase; selain itu tidak ada bukti perbedaan. Arah berlawanan dilaporkan sebagai temuan.

| hipotesis | perbandingan | n_mutasi | n_klaster | selisih_poin | ci_bootstrap_klaster | diskordan_b_c | mcnemar_p_info | putusan | catatan |
|---|---|---|---|---|---|---|---|---|---|
| H1 | ACCEPT: B vs D; semua mutasi | 34 | 19 | +70.6 | [+45.5; +91.7] | 24/0 | 0.0000 | TERDUKUNG |  |
| H2 | REJECT: E vs D; unit | 5 | 5 | +100.0 | [+100.0; +100.0] | 5/0 | 0.0625 | TERDUKUNG | klaster < 10: CI bootstrap tidak andal; CI berlebar nol (semua klaster searah): bukan ukuran ketidakpastian; McNemar eksak p=0.0625 > 0.0167: aturan umum klaim 'lebih akurat/aman' belum terpenuhi |
| H3 | ACCEPT: F vs D; numeric_value, date | 11 | 11 | +0.0 | [+0.0; +0.0] | 0/0 | 1.0000 | TIDAK_ADA_BUKTI_PERBEDAAN | CI berlebar nol (semua klaster searah): bukan ukuran ketidakpastian |

McNemar eksak hanya informasi: ia memperlakukan mutasi sebagai independen dan tidak menentukan putusan.

**H4 (deskriptif, tanpa uji).** D, gabungan lari, CI bootstrap klaster: CAR Track R = 5/57 = 8.8% [0.0–21.1]; REVIEW rate Track R = 28/87 = 32.2% [18.4–47.1].
