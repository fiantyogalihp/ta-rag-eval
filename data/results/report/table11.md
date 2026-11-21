# Tabel 11 (split test, parameter beku; Track R dan M TIDAK digabung)

Setiap klaim diawali: "Di bawah pelabelan validator tunggal (intra-rater agreement 55%, n=60): "

n test: {'R': 87, 'M': 34}. Interval: Clopper–Pearson dua sisi 95%.

**Studi 2:** Clopper–Pearson pada hitungan gabungan lari menganggap jawaban independen, jadi terlalu sempit; analisis utama = `table11_klaster.md`.

| konfigurasi | bobot_SL | threshold | car_R | far_R | far_M | review_R | reject_R | false_rejection_R | p95_ms | status |
|---|---|---|---|---|---|---|---|---|---|---|
| A | 0:100 | 0.85 | 4/57 = 7.0% [1.9–17.0] | 0/30 = 0.0% [0.0–11.6] | 2/34 = 5.9% [0.7–19.7] | 40/87 = 46.0% [35.2–57.0] | 43/87 = 49.4% [38.5–60.4] | 13/57 = 22.8% [12.7–35.8] | 0.69 | TEST_RUN_ONCE_R2_REFERENCE_NO_ELIGIBLE_PARAMETER |
| B | 100:0 | 0.85 | 47/57 = 82.5% [70.1–91.3] | 5/30 = 16.7% [5.6–34.7] | 25/34 = 73.5% [55.6–87.1] | 35/87 = 40.2% [29.9–51.3] | 0/87 = 0.0% [0.0–4.2] | 0/57 = 0.0% [0.0–6.3] | 246.51 (proksi C) | TEST_RUN_ONCE_R2_REFERENCE_NO_ELIGIBLE_PARAMETER |
| C | 25:75 | 0.85 | 6/57 = 10.5% [4.0–21.5] | 0/30 = 0.0% [0.0–11.6] | 3/34 = 8.8% [1.9–23.7] | 44/87 = 50.6% [39.6–61.5] | 37/87 = 42.5% [32.0–53.6] | 11/57 = 19.3% [10.0–31.9] | 246.51 | TEST_RUN_ONCE_R2_REFERENCE_NO_ELIGIBLE_PARAMETER |
| D | 25:75 | 0.85 | 5/57 = 8.8% [2.9–19.3] | 0/30 = 0.0% [0.0–11.6] | 1/34 = 2.9% [0.1–15.3] | 28/87 = 32.2% [22.6–43.1] | 54/87 = 62.1% [51.0–72.3] | 24/57 = 42.1% [29.1–55.9] | 260.34 | TEST_RUN_ONCE_R2_REFERENCE_NO_ELIGIBLE_PARAMETER |
| E | 25:75 | 0.85 | 5/57 = 8.8% [2.9–19.3] | 0/30 = 0.0% [0.0–11.6] | 0/34 = 0.0% [0.0–10.3] | 28/87 = 32.2% [22.6–43.1] | 54/87 = 62.1% [51.0–72.3] | 24/57 = 42.1% [29.1–55.9] | 369.67 | TEST_RUN_ONCE_R2_REFERENCE_NO_ELIGIBLE_PARAMETER |
| F | BERTScore F1 | 0.95 | 0/57 = 0.0% [0.0–6.3] | 0/30 = 0.0% [0.0–11.6] | 0/34 = 0.0% [0.0–10.3] | 16/87 = 18.4% [10.9–28.1] | 71/87 = 81.6% [71.9–89.1] | 41/57 = 71.9% [58.5–83.0] | 1295.35 | TEST_RUN_ONCE_FROZEN_PARAMS; CAR_ZERO_DEGENERATE: parameter terpilih tidak pernah ACCEPT jawaban LAYAK |
| D* | 25:75 | 0.78 | 17/57 = 29.8% [18.4–43.4] | 0/30 = 0.0% [0.0–11.6] | 4/34 = 11.8% [3.3–27.5] | 16/87 = 18.4% [10.9–28.1] | 54/87 = 62.1% [51.0–72.3] | 24/57 = 42.1% [29.1–55.9] | 260.34 (proksi D) | TEST_RUN_ONCE_FROZEN_PARAMS |
