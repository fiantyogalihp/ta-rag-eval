# Evaluasi Keandalan Jawaban Retrieval-Augmented Generation pada Dokumen Layanan Kesehatan Publik Menggunakan Hybrid Semantic–Lexical Scoring dan Rule-Based Verification

> **CATATAN PENULIS — hapus blok ini dan Lampiran B sebelum submit.**
>
> - **Status berkas (Sen 9 Nov 2026):** kerangka + draf Metode. Angka di §3 diambil dari `config/*.json` dan kode; komentar `<!-- sumber: ... -->` menunjuk berkas dan kuncinya. `config/protocol.json` masih `DRAFT_UNLOCKED` dan `data/cases/questions_draft.jsonl` belum `HUMAN_VERIFIED`: periksa ulang angka bertanda *(draf)* setelah S08 dan S11.
> - **Hasil (§4) tidak memuat angka.** Isi hanya dengan menyalin dari `data/results/**` setelah S36; jangan mengetik ulang. Tiap klaim CAR/FAR diawali `claim_prefix`.
> - **Slot `[ISI: …]`** adalah bagian yang hanya dapat diisi dari langkah manusia atau hasil yang belum ada. Saat submit, `grep -n "\[ISI" docs/naskah/naskah_draft.md` harus kosong.
> - **Pendahuluan dan Tinjauan Pustaka** ditulis Claude (13 Nov) dari abstrak/teks lengkap makalah yang dibaca saat itu dan dari kode llm-eval-layer (lihat komentar di Daftar Pustaka). SPEC §10 mensyaratkan literatur dari bacaan Anda: baca keempat makalah utama dan periksa setiap kalimat §2 sebelum submit; ubah ke suara Anda.
> - **Frasa terlarang** (aturan 13): lihat Lampiran B.
> - **Judul** di atas adalah opsi dari Panduan. Templat, panjang, dan gaya sitasi mengikuti jurnal target (belum dipilih).
> - **Pernyataan penggunaan alat AI:** banyak jurnal mewajibkannya (naskah ini dibantu alat AI untuk kode dan draf). Periksa pedoman jurnal dan nyatakan sesuai fakta.
> - **Istilah:** "langkah sensitivitas 1–3" di naskah = "Tahap A–C" di Panduan §8 (diganti agar tidak bentrok dengan evaluator A–D). "Tahap I/II" = evaluasi dengan evidence oracle / dengan konteks hasil retrieval.
> - **Gambar 1** (`docs/ARCHITECTURE_v4_main_20261103.png`) dibuat 3 Nov, sebelum revisi D9–D16: periksa kesesuaiannya sebelum dipakai.

## Abstrak

**Latar belakang.** Sistem RAG dapat menghasilkan jawaban yang fasih tetapi salah pada satu fakta, misalnya angka, satuan, atau tanggal, sehingga diperlukan lapisan verifikasi sebelum jawaban dilepas ke pengguna.
**Tujuan.** Menguji pengaruh penggabungan skor leksikal–semantik dan aturan hard-fail terhadap penerimaan jawaban benar dan salah pada dokumen layanan JKN.
**Metode.** Studi pilot dengan protokol pra-registrasi pada korpus 267 halaman (10 dokumen). Track R berisi 20 jawaban generator yang dilabel manusia secara buta skor. Track M berisi 11 mutasi terkontrol. Empat konfigurasi (leksikal, semantik, hybrid, hybrid + hard-fail) dipilih parameternya pada validation dengan batas FAR 5% dan diuji sekali pada test.
**Hasil.** Di bawah pelabelan validator tunggal (intra-rater agreement 75%, n=8), evaluator semantik saja menerima 4/4 mutasi test (CI 95% 39,8–100%). Konfigurasi yang lolos batas FAR menahan 4/4 mutasi, tetapi juga menahan hampir semua jawaban benar (CAR 0–1/4). Hard-fail menolak semua mutasi angka dan tanggal (8/8), tidak menangkap mutasi satuan (0/3), dan menolak satu jawaban benar. BERTScore F1 turun hanya median 0,003 akibat mutasi (10 dari 11 pasangan), sekitar 2% dari sebaran skor antar jawaban benar. Tidak ada perbedaan yang signifikan secara statistik (McNemar p = 0,125).
**Simpulan.** Pada data pilot ini, kemiripan semantik saja tidak peka terhadap perubahan satu fakta. Aturan berbasis angka menutup sebagian celah itu dengan biaya penolakan yang bergantung pada granularitas evidence. Hasil ini perlu diuji pada sampel yang lebih besar dengan validator independen.

**Kata kunci:** retrieval-augmented generation; verifikasi jawaban; semantic similarity; hard-fail; false acceptance; JKN.

## Abstract

**Background.** Retrieval-augmented generation (RAG) systems can produce fluent answers that are wrong in a single fact, such as a number, a time unit, or a date, so a verification layer is needed before an answer reaches the user.
**Objective.** To test how combining lexical–semantic scores with hard-fail rules affects the acceptance of correct and incorrect answers on Indonesian National Health Insurance (JKN) service documents.
**Methods.** A pilot study with a pre-registered protocol on a 267-page corpus (10 documents). Track R contains 20 generator answers labelled by a human blind to evaluator scores; Track M contains 11 controlled mutations. Parameters of four configurations (lexical, semantic, hybrid, hybrid with hard-fail) were selected on a validation split under a 5% false-acceptance limit and evaluated once on a held-out test split.
**Results.** Under single-validator labelling (intra-rater agreement 75%, n=8), the semantic-only evaluator accepted 4/4 test mutations (95% CI 39.8–100%). Configurations that met the false-acceptance limit held back 4/4 mutations but also held back almost all correct answers (correct acceptance 0–1/4). The hard-fail rule rejected all numeric and date mutations (8/8), caught none of the unit mutations (0/3), and rejected one correct answer. BERTScore F1 fell by a median of only 0.003 after a mutation (10 of 11 pairs), about 2% of the spread among correct answers. No difference was statistically significant (McNemar p = 0.125).
**Conclusion.** In this pilot, semantic similarity alone was insensitive to single-fact changes. Number-based rules closed part of that gap, at a rejection cost that depends on the granularity of the evidence. These results need to be tested on a larger sample with an independent validator.

**Keywords:** retrieval-augmented generation; answer verification; semantic similarity; hard-fail rules; false acceptance; Indonesian national health insurance.

## 1. Pendahuluan

*Retrieval-augmented generation* (RAG) menggabungkan model bahasa yang menyimpan pengetahuan dalam parameternya dengan memori non-parametrik berupa indeks dokumen. Tujuannya adalah membuat akses pengetahuan lebih tepat dan memberi jejak sumber atas jawaban (Lewis dkk., 2020). Pendekatan ini menarik untuk layanan informasi Jaminan Kesehatan Nasional (JKN). Ketentuannya tersebar di banyak peraturan dan perubahannya, misalnya Peraturan Presiden Nomor 82 Tahun 2018 yang telah diubah tiga kali hingga Peraturan Presiden Nomor 59 Tahun 2024, serta standar tarif dalam Peraturan Menteri Kesehatan Nomor 3 Tahun 2023. Banyak pertanyaan peserta dan fasilitas kesehatan bergantung pada satu nilai yang tepat: lama masa tunggu, batas waktu pengajuan klaim, atau besaran tarif kapitasi.

Namun, model pembangkit teks rentan menghasilkan teks yang tidak dimaksudkan dan tidak didukung sumbernya (Ji dkk., 2023). Pada dokumen administratif, kesalahan yang paling sulit dikenali adalah jawaban yang fasih dan hampir sama dengan sumbernya, tetapi mengubah satu fakta: angka, satuan waktu, tahun, atau polaritas kalimat. Karena itu, di antara keluaran model dan pengguna diperlukan lapisan verifikasi yang memutuskan apakah sebuah jawaban dilepas (ACCEPT), ditahan untuk diperiksa manusia (REVIEW), atau ditolak (REJECT).

Metode evaluasi yang ada menjawab pertanyaan yang berbeda. BERTScore mengukur kemiripan token kontekstual terhadap kalimat rujukan (Zhang dkk., 2020). RAGAS dan RAGChecker menilai kesetiaan jawaban terhadap konteks dengan bantuan model bahasa sebagai pengekstrak dan pemeriksa pernyataan (Es dkk., 2024; Ru dkk., 2024). Pendekatan berbasis LLM membawa biaya per panggilan dan ketergantungan pada model penilai. Alternatif lokal yang deterministik, yaitu gabungan skor semantik dan leksikal yang menghasilkan keputusan tri-state, telah diusulkan dalam bentuk perangkat lunak (Alexander, 2026). Namun, efektivitasnya belum diuji dengan label manusia, data uji terpisah, dan kesalahan satu fakta yang terkontrol. Panduan penelitian ini merumuskan celah tersebut sebagai hipotesis yang harus diuji, bukan diasumsikan: apakah kombinasi skor semantik–leksikal dan aturan deterministik mengurangi penerimaan jawaban salah dibanding komponen tunggal, dengan beban komputasi yang masih praktis.

Penelitian ini menanyakan bagaimana pengaruh penggabungan skor leksikal–semantik dan aturan hard-fail terhadap *false acceptance*, *correct acceptance*, beban REVIEW/REJECT, dan latency, dibandingkan komponen tunggal, pada jawaban RAG atas dokumen layanan JKN. Untuk menjawabnya, empat konfigurasi evaluator dibandingkan pada input identik: leksikal saja, semantik saja, hybrid, dan hybrid dengan aturan hard-fail. Jawaban berasal dari generator yang dibekukan, label ditetapkan manusia tanpa melihat skor, dan kesalahan terkontrol dibuat dengan prosedur yang ditetapkan sebelumnya.

Penelitian ini adalah studi pilot dengan empat kontribusi: (a) protokol evaluasi yang dapat diaudit, meliputi pra-registrasi aturan seleksi, label buta skor, pemisahan jawaban asli dan mutasi terkontrol, serta test yang dijalankan sekali; (b) perbandingan empat konfigurasi pada input identik dengan interval kepercayaan; (c) analisis galat per kasus dan per jenis mutasi; dan (d) ekstraksi angka format Indonesia untuk aturan hard-fail yang mengabaikan angka sitasi. Bagian 2 meninjau metode terdekat. Bagian 3 menjelaskan korpus, protokol, dan evaluator. Bagian 4 menyajikan hasil dan pembahasan, Bagian 5 keterbatasan, dan Bagian 6 kesimpulan.

## 2. Tinjauan Pustaka

### 2.1 RAG dan kesalahan yang tidak didukung sumber

Lewis dkk. (2020) memperkenalkan RAG sebagai model yang menggabungkan memori parametrik (model seq2seq terlatih) dan memori non-parametrik (indeks vektor dense). Model ini menghasilkan teks yang lebih spesifik dan faktual daripada model parametrik saja pada tugas tanya-jawab domain terbuka. Menambahkan retrieval tidak menjamin jawaban setia pada dokumen yang diambil. Ji dkk. (2023) menyurvei masalah halusinasi pada pembangkitan bahasa alami, yaitu kecenderungan model menghasilkan teks yang tidak dimaksudkan, berikut metrik dan metode mitigasinya. Penelitian ini membatasi diri pada satu bentuk kesalahan yang dapat diuji secara mekanis: jawaban yang tidak didukung kutipan sumber, terutama pada nilai angka, satuan, dan tanggal.

### 2.2 Metrik berbasis kemiripan

BERTScore (Zhang dkk., 2020) menghitung kemiripan antara kalimat kandidat dan kalimat rujukan pada tingkat token dengan embedding kontekstual. Setiap token dicocokkan secara *greedy* dengan token paling mirip di kalimat lain. Recall dihitung dari token rujukan, presisi dari token kandidat, dan keduanya digabung menjadi F1. Bobot idf bersifat opsional, dan skor dapat diskalakan ulang terhadap garis dasar empiris. Metrik ini divalidasi dengan korelasinya terhadap penilaian manusia pada keluaran 363 sistem penerjemahan mesin dan pembuatan keterangan gambar. Dengan demikian BERTScore mengukur kemiripan terhadap rujukan, bukan memeriksa kontradiksi fakta secara khusus. Satu token angka yang berubah hanya mengubah satu dari banyak pasangan token yang dicocokkan.

Embedding kalimat seperti Sentence-BERT (Reimers & Gurevych, 2019) memungkinkan kemiripan semantik dihitung sebagai kosinus antarvektor kalimat. Model multibahasa dapat diturunkan dari model satu bahasa melalui distilasi pengetahuan, dengan melatih model murid agar kalimat terjemahan dipetakan ke lokasi vektor yang sama dengan kalimat aslinya (Reimers & Gurevych, 2020). Model multibahasa jenis ini dipakai sebagai komponen semantik pada penelitian ini.

### 2.3 Kerangka evaluasi RAG berbasis LLM

RAGAS (Es dkk., 2024) menilai sistem RAG tanpa anotasi rujukan manusia, pada tiga dimensi. *Faithfulness* dihitung dengan meminta LLM memecah jawaban menjadi pernyataan pendek, lalu memeriksa apakah tiap pernyataan dapat disimpulkan dari konteks; skornya adalah proporsi pernyataan yang didukung. *Answer relevance* dihitung dari kemiripan embedding antara pertanyaan asli dan pertanyaan yang dibangkitkan LLM dari jawaban. *Context relevance* menilai bagian konteks yang benar-benar diperlukan. Dalam eksperimennya, seluruh prompt dievaluasi dengan gpt-3.5-turbo-16k. Pada dataset WikiEval (50 halaman Wikipedia), kesepakatan RAGAS dengan pilihan anotator manusia dalam perbandingan berpasangan adalah 0,95 (faithfulness), 0,78 (answer relevance), dan 0,70 (context relevance). Penulisnya mengakui bahwa kerangka ini sangat bergantung pada kinerja LLM yang dipakai.

RAGChecker (Ru dkk., 2024) mendiagnosis modul retrieval dan generation secara terpisah, melalui operasi *entailment* pada tingkat klaim. LLM bertindak sebagai pengekstrak klaim sekaligus pemeriksa klaim. Masukannya mencakup pertanyaan, jawaban sistem, konteks yang diambil, dan jawaban rujukan (*ground truth*). Metriknya meliputi presisi, recall, dan F1 keseluruhan; *claim recall* dan *context precision* untuk retriever; serta *context utilization*, *noise sensitivity*, *hallucination*, *self-knowledge*, dan *faithfulness* untuk generator. Meta-evaluasinya melaporkan korelasi dengan penilaian manusia yang lebih baik dibanding metrik lain.

### 2.4 Lapisan keputusan lokal

Lapisan keputusan yang berjalan lokal tanpa panggilan API ditawarkan oleh llm-eval-layer (Alexander, 2026), sebuah repositori perangkat lunak dan artikel populer, bukan publikasi ilmiah. Skor *attribution*-nya adalah 0,60 × kemiripan semantik ditambah 0,40 × overlap leksikal antara konteks dan jawaban. Overlap dihitung dengan Jaccard atas token huruf saja, sehingga angka tidak ikut dihitung. Skor tersebut digabung dengan skor *specificity*, lalu dipetakan ke ACCEPT/REVIEW/REJECT dengan ambang 0,45 dan 0,65. Repositori ini tidak memuat pemeriksaan angka atau negasi, dan contoh RAG-nya hanya lima kasus. Evaluator pada penelitian ini adalah implementasi independen yang mengambil ide lapisan keputusan dan bobot 60:40 sebagai salah satu titik grid, bukan replikasi.

### 2.5 Matriks metode terdekat

**Tabel 1.** Matriks metode terdekat.

| Metode | Input | Jenis skor/keputusan | Perlu rujukan atau LLM? | Keterbatasan yang relevan untuk domain ini | Perbedaan dengan metode usulan |
|---|---|---|---|---|---|
| BERTScore (Zhang dkk., 2020) | kandidat + kalimat rujukan | skor kontinu P/R/F1 kemiripan token | rujukan: ya; LLM: tidak (encoder) | dirancang untuk kemiripan, bukan pemeriksaan kontradiksi fakta | usulan menambah keputusan tri-state dan aturan angka |
| RAGAS (Es dkk., 2024) | pertanyaan + konteks + jawaban | skor faithfulness, answer relevance, context relevance | rujukan: tidak; LLM: ya | biaya dan non-determinisme LLM; validasi pada WikiEval berbahasa Inggris | usulan lokal, deterministik, tanpa LLM penilai |
| RAGChecker (Ru dkk., 2024) | pertanyaan + konteks + jawaban + jawaban rujukan | metrik tingkat klaim untuk retriever dan generator | rujukan: ya; LLM: ya | butuh LLM pengekstrak dan pemeriksa klaim | usulan tidak mendiagnosis retriever; menilai jawaban terhadap evidence |
| llm-eval-layer (Alexander, 2026) | konteks + jawaban | skor gabungan → ACCEPT/REVIEW/REJECT | rujukan: tidak; LLM: opsional | angka dibuang dari overlap; embedding berbahasa Inggris; contoh lima kasus | usulan memeriksa angka format Indonesia dan negasi; diuji dengan label manusia |
| Usulan (A–D) | jawaban + evidence (+ pertanyaan untuk hard-fail) | skor H → ACCEPT/REVIEW/REJECT | rujukan: evidence kutipan; LLM: tidak | lihat §5 | — |

### 2.6 Posisi penelitian

Penelitian ini tidak membandingkan diri secara langsung dengan RAGAS atau RAGChecker, yang tidak dijalankan. BERTScore dijalankan hanya secara deskriptif pada data pilot setelah test (§4.8), tidak sebagai konfigurasi yang dipilih dan diuji. Yang diuji adalah komponen tunggal terhadap gabungannya pada input yang sama: kemiripan leksikal, kemiripan semantik, gabungan keduanya, dan gabungan dengan aturan hard-fail. Pengujian memakai jawaban generator nyata yang dilabel manusia dan mutasi satu fakta yang terkontrol, dalam bahasa Indonesia, dengan parameter yang dipilih pada validation dan diuji sekali. Matriks di atas menempatkan pilihan desain itu: keputusan tri-state yang deterministik tanpa LLM penilai, dengan biaya bahwa evaluator membutuhkan evidence kutipan dan hanya memeriksa jenis kesalahan yang dapat dirumuskan sebagai aturan.

## 3. Metode

### 3.1 Rancangan penelitian

Penelitian ini adalah studi pilot (*preliminary*) eksperimental yang menguji lapisan verifikasi jawaban pada sistem RAG, bukan membangun sistem RAG baru. Parsing dokumen, pemotongan teks, retrieval, dan generator diperlakukan sebagai lingkungan tetap yang dibekukan sebelum pelabelan dan tidak dioptimasi demi hasil. Alurnya: dokumen sumber → parsing → pemotongan teks dan indeks → retrieval tetap → jawaban LLM yang disimpan → evaluator A–D → keputusan ACCEPT/REVIEW/REJECT (Gambar 1). Evaluasi dilakukan dalam dua tahap. Tahap I menilai jawaban terhadap *evidence oracle*, yaitu kutipan verbatim dari halaman PDF asli yang memuat jawabannya, sehingga kinerja evaluator terpisah dari kegagalan retrieval. Tahap II menerapkan parameter yang dibekukan pada Tahap I terhadap konteks hasil retrieval yang sesungguhnya, secara deskriptif. Domain dibatasi pada dokumen layanan administratif JKN (keandalan jawaban dokumen); pertanyaan tidak memuat dosis atau keputusan klinis, sehingga penelitian ini tidak menguji keamanan klinis.
<!-- sumber: config/protocol.json → split.stage_I, split.stage_II; CLAUDE.md aturan 12-13 -->

### 3.2 Korpus dan cakupan

Korpus terdiri atas 13 PDF peraturan dan laporan JKN dengan total 1.346 halaman; SHA256 dan jumlah halaman setiap berkas cocok dengan audit penulis (13 dari 13). Sebanyak 267 halaman dari 10 dokumen diindeks. Dokumen dibagi menurut peran: lima dokumen sumber evidence (Peraturan BPJS Kesehatan 3/2024, Kepmenkes 1511/2023, Permenkes 3/2023, Permenkes 28/2014, dan Perpres 59/2024); lima dokumen pengecoh (Permenkes 71/2013 beserta tiga perubahannya yang tersedia, yaitu 23/2017, 5/2018, dan 7/2021, serta Perpres 64/2020); dan tiga dokumen statistik/laporan historis yang ditunda dan tidak diindeks (Laporan Tahunan JKN 2023 serta Statistik JKN 2015–2019 dan 2016–2021). Dari Permenkes 3/2023 (721 halaman) hanya hlm. 1–91 yang diindeks: hlm. 1–31 dan 84–91 (prosa) menjadi jangkar pertanyaan, hlm. 32–83 (tabel kelompok khusus, kode ICD, dan kode grup INA-CBG) hanya berperan sebagai pengecoh dalam dokumen, dan hlm. 92–721 (tabel tarif INA-CBG) dikeluarkan. Dokumen induk (Perpres 82/2018, Perpres 75/2019, Permenkes 99/2015, dan Kepmenkes 34/2025) tidak ada dalam korpus; karena itu tidak ada pertanyaan yang menuntut "aturan yang berlaku saat ini" hasil konsolidasi induk dan perubahan.
<!-- sumber: config/corpus.json → documents[].eval_role, index_page_scope, pages; permenkes_03_2023_page_map; missing_parent_documents; data/manifest/scope_manifest.json (267 dari 1346). Penjumlahan: 21+16+91+48+33+7+7+4+28+12 = 267; di luar cakupan 449 (3 dokumen ditunda) + 630 (Permenkes 3/2023 hlm. 92-721) = 1.079. -->

### 3.3 Parsing dan kontrol mutu

Halaman terindeks diurai dengan Reducto (Reducto, 2026; model `r-1`, dikirim eksplisit pada setiap permintaan; SDK `reductoai` 0.26.0). JSON mentah keluaran parser disimpan sebagai sumber kebenaran, sedangkan Markdown hanya bahan baca. Seluruh 267 halaman menghasilkan blok teks. Kontrol mutu berlapis dua. Pertama, pemeriksaan teknis otomatis membandingkan angka dan kata per halaman antara teks-bawaan PDF (pypdf) dan keluaran parser; halaman dengan selisih angka atau kemiripan Dice kata < 0,85 ditandai. Pemeriksaan ini hanya pendeteksi dan bukan bukti kebenaran: bila separuh atau lebih halaman yang diperiksa ditandai, pembanding dinyatakan tidak andal (`UNRELIABLE_REFERENCE`) dan tidak dipakai sebagai bukti. Status itu muncul pada Perpres 59/2024 dan Perpres 64/2020 (dokumen hasil pindai yang membawa teks OCR bawaan dengan kesalahan sistematis, misalnya ayat "(2)" terbaca "21") dan pada Permenkes 3/2023 (pada dua halaman tabel yang diperiksa, hlm. 40 dan 85, pypdf mengekstrak setiap string 16 kali, sedangkan pdftotext dan Reducto 1 kali). Kedua, pemeriksaan manusia terhadap gambar halaman PDF asli pada 16 halaman jangkar pertanyaan (angka, negasi, tabel) dengan status per dokumen. Kelima dokumen sumber evidence dinyatakan PASS, kecuali Permenkes 28/2014 yang PASS_WITH_NOTES; pada halaman yang ditandai pendeteksi tetapi bukan jangkar (misalnya Permenkes 28/2014 hlm. 6), gambar halaman mengonfirmasi teks Reducto. Evidence yang dinilai evaluator tidak diambil dari keluaran parser, melainkan dikutip dari halaman fisik PDF asli (§3.6); kualitas parsing memengaruhi retrieval pada Tahap II, bukan penilaian Tahap I.
<!-- sumber: data/reducto/manifests/*.manifest.json → request.model="r-1", sdk_version="0.26.0", technical_qa.pages_without_blocks=[], text_layer_check.thresholds (low_sim_dice 0.85; unreliable_flag_ratio 0.5, kondisi ratio >= 0.5 di src/ta_rag/parsing/reducto_parse_corpus.py:274), text_layer_check.reference_reliability. 16 halaman jangkar (draf): Perpres 59/2024 hlm. 3,8,9,16; BPJS 3/2024 hlm. 8,13,14; Kepmenkes 1511/2023 hlm. 5,10,12; Permenkes 28/2014 hlm. 31,35,38; Permenkes 3/2023 hlm. 3,5,8. Duplikasi 16x pypdf: dihitung 9 Nov pada hlm. 40 ("15.673.000" 576 vs 36) dan hlm. 85 ("RR-02-II" 16 vs 1). Inferensi [Likely], tidak dinyatakan di teks: Dice seragam ~0,12 pada hlm. 38-91 sesuai dengan 16x (2/17 = 0,118). -->

### 3.4 Pemotongan teks dan retrieval

Teks dipotong oleh *chunker* yang mengenali struktur peraturan: batas chunk adalah awal "Pasal N" pada teks blok, ayat tetap berada dalam Pasalnya, tabel diperlakukan sebagai satu unit, dan blok bertipe Figure, Signature, Header, Footer, dan Page Number tidak dimasukkan. Setiap chunk membawa rentang halaman fisiknya. Sebelum indeks dibangun, pemeriksa cakupan memastikan tidak ada chunk dari dokumen yang ditunda atau dari Permenkes 3/2023 hlm. 92–721. Retrieval menggabungkan BM25 Okapi (k1 = 1,5; b = 0,75), pencarian dense berupa produk dalam eksak atas embedding *paraphrase-multilingual-MiniLM-L12-v2* (384 dimensi, CPU), dan *Reciprocal Rank Fusion* (k = 60). Indeks berisi 312 chunk. Empat chunk teratas (top-k = 4) dikirim ke generator. Seri skor diputus menurut skor menurun lalu chunk_id naik, sehingga retrieval deterministik.
<!-- sumber: src/ta_rag/chunking.py (docstring; DROP_TYPES); src/ta_rag/retrieval.py (docstring: k1=1,5 b=0,75; RRF_K=60); config/protocol.json → retrieval.top_k=4, rrf_k=60, embedding_model, dense_index; CLAUDE.md aturan 21 (check_chunk_scope). Dimensi 384: terukur 7 Nov saat unduh model. -->

### 3.5 Generator

Jawaban dibangkitkan oleh MiMo `mimo-v2.6-flash` (Xiaomi, 2026) melalui API *chat completions* dengan temperature 0,0 dan max_tokens 800, satu panggilan per pertanyaan. Prompt sistem memuat konteks hasil retrieval dan instruksi eksplisit untuk menyatakan bahwa informasi tidak ada dalam konteks bila konteks tidak memuat jawabannya ("Jawab pertanyaan hanya berdasarkan konteks yang diberikan di bawah. Jika konteks tidak memuat jawabannya, katakan bahwa informasinya tidak ada dalam konteks."). Dengan demikian abstain pada pertanyaan di luar korpus mencerminkan kepatuhan terhadap instruksi, bukan perilaku emergen. Jawaban yang dinilai adalah isi `choices[0].message.content` saja (bukan `reasoning_content`). Respons mentah, `response.model`, penggunaan token, stempel waktu, SHA256 prompt, dan chunk_id disimpan untuk setiap panggilan, dan konfigurasi generator dibekukan beserta hash-nya sebelum pembangkitan. Layanan generator tidak menjamin determinisme walaupun temperature = 0; jawaban yang dilabel berasal dari satu lari (k = 1). Satu dari 20 respons lari utama (R10) terpotong (`finish_reason = length`; 643 dari 800 token keluaran terpakai untuk penalaran internal) dan dipertahankan apa adanya. Dua lari tambahan dengan konteks identik dijalankan setelah test dan tidak dilabel; keduanya hanya dipakai untuk analisis stabilitas keputusan (§3.14).
<!-- sumber: config/generator.json → model, temperature, max_tokens, system_prompt, record_per_call, freeze_rule; config/protocol.json → determinism.generator, determinism.generator_runs.k=1 (D15); CLAUDE.md aturan 15. -->

### 3.6 Pertanyaan dan evidence (Track R)

Track R memuat 20 pertanyaan: 16 pertanyaan berjawab yang berjangkar pada kutipan verbatim di satu halaman fisik PDF asli, dan 4 probe (R17–R20) yang jawabannya tidak ada dalam korpus. Jenis pertanyaan berjawab: durasi 7, tanggal 3, uang 2, jumlah 1, rentang 1, persen 1, dan definisi 1. Pertanyaan dan kutipan berasal dari PDF, bukan dari web. Kutipan dan nomor halaman diperiksa otomatis terhadap teks halaman fisik PDF asli, kemudian diperiksa manusia terhadap gambar halaman. Pada pemeriksaan ini beberapa kutipan diperluas atau dipersempit agar subjek dan cakupannya jelas, tanpa mengubah angka, pertanyaan, atau halaman, dan seluruhnya sebelum protokol dikunci. Untuk R03, kutipan dibatasi pada fragmen yang tidak memuat galat OCR lapisan teks bawaan. Ketidakhadiran jawaban probe diperiksa dengan penelusuran istilah pada seluruh PDF korpus (11 November 2026). Pemeriksaan visual keempat probe dilakukan peneliti dengan bantuan agen AI; hal ini diungkapkan sebagai keterbatasan (§5). Pada 20 pertanyaan, `group_id` dan `evidence_group` berbeda untuk setiap pertanyaan. Pada Tahap I, evidence oracle adalah kutipan jangkar (`source_quote`) pada halaman fisik tersebut.
<!-- sumber: data/cases/questions_draft.jsonl (20 baris: kind answerable 16, not_in_corpus 4 = R17-R20; question_type: numeric_duration 7, numeric_date 3, numeric_money 2, numeric_count 1, numeric_range 1, numeric_percent 1, definition 1; 20 group_id, 20 evidence_group). Status: DRAFT_UNVERIFIED_BY_HUMAN. Periksa ulang setelah S08. CLAUDE.md aturan 10, 17. -->

### 3.7 Pelabelan

Unit label adalah satu jawaban. Label biner LAYAK/TIDAK_LAYAK ditetapkan manusia (validator tunggal, yaitu penulis) menurut rubrik mekanis yang dikunci sebelum pelabelan. Jawaban berjawab dinilai LAYAK bila seluruh syarat berikut terpenuhi: (i) setiap klaim faktual yang menjawab pertanyaan didukung kutipan verbatim pada halaman jangkar; (ii) nilai, satuan, tanggal, dan subjek sama dengan kutipan setelah normalisasi (misalnya "6 (enam) bulan" = "6 bulan"); (iii) tidak ada negasi atau pengecualian pada kalimat sekitar yang mengubah makna, dan jawaban tidak membalik polaritas; dan (iv) tidak ada klaim status hukum di luar konteks yang diberikan. Fakta tambahan yang benar dan ada pada halaman jangkar tidak membuat jawaban tidak layak. Pada Tahap I, jawaban yang menyatakan informasi tidak ada padahal kutipan ada dalam konteks dinilai TIDAK_LAYAK (abstain keliru). Untuk probe, jawaban LAYAK bila secara eksplisit menyatakan informasi tidak tersedia dalam konteks, dan TIDAK_LAYAK bila mengarang fakta, memakai fakta tetangga, atau membuat klaim status hukum. Pelabelan dilakukan buta terhadap skor evaluator, label dikunci sebelum skor dihitung, dan keluaran evaluator tidak pernah dipakai sebagai label. Untuk Tahap II, pelabel juga mengisi kolom `abstain` (ya/tidak) bagi setiap jawaban berjawab.

Konsistensi pelabelan diperiksa dengan relabel intra-rater atas 8 jawaban unik (minimum 6) yang dipilih dengan aturan SHA256 pra-registrasi dan terstratifikasi (sekurang-kurangnya 2 mutasi, 2 probe, dan 2 jawaban asli TIDAK_LAYAK; sisanya jawaban asli LAYAK). Jawaban disajikan acak tanpa label pertama dan tanpa skor, dengan jeda minimum 12 jam setelah pelabelan pertama. Dilaporkan persentase kesepakatan, daftar selisih, dan κ Cohen hanya bila terdefinisi. Relabel ini mengukur konsistensi diri, bukan validasi independen. Jeda yang direncanakan (≥ 12 jam) terpenuhi untuk jawaban asli, tetapi tidak untuk record mutasi: jeda terdokumentasi terpendek 7,18 jam. Deviasi ini diakui sebelum impor dan dilaporkan. Upaya validator kedua menghasilkan penilaian delapan record oleh seorang rekan yang dibantu alat AI. Karena prosesnya tidak independen dari AI dan tidak dapat diverifikasi, penilaian itu tidak dipakai dalam analisis kuantitatif.
<!-- sumber: config/protocol.json → label_rubric.answerable.LAYAK_iff_all (i-iv), extra_facts_rule, false_abstention_rule, probe_not_in_corpus; relabel (n_sample=8, minimum_n=6, strata_min 2/2/2, seed, min_gap_hours=12 [D15], blind_to, report); second_validator; SPEC §1.3. Kolom abstain: src/ta_rag/labeling.py (ABSTAIN_HINT). -->

### 3.8 Track M (mutasi terkontrol)

Karena FAR pada jawaban asli bergantung pada kesalahan alami generator dan tidak terdefinisi bila tidak ada jawaban TIDAK_LAYAK, disusun Track M untuk mengukur kemampuan evaluator menahan kesalahan yang terkontrol. Untuk setiap jawaban asli berjawab yang berlabel LAYAK (maksimum 16) dibuat satu mutasi: satu blok token berdekatan diubah sehingga fakta terbalik, tanpa mengubah bagian lain. Operasinya ditetapkan sebelum jawaban dilihat: `numeric_value` (angka kunci diganti k kali nilainya, dengan k yang pertama dari 2, 3, 5 sehingga nilai baru tidak muncul pada angka mana pun di halaman jangkar), `unit` (satuan waktu dialihkan: hari→bulan, minggu→bulan, bulan→hari, tahun→bulan), `date` (tahun digeser +1), dan `negation` (sisipan "tidak" sebelum kata kerja atau modal utama, atau pembalikan "tanpa" ↔ "dengan"). Family ditetapkan secara deterministik menurut jenis pertanyaan: pertanyaan durasi bergantian antara `numeric_value` dan `unit` menurut urutan lembar, pertanyaan definisi memakai `negation`, dan jenis lain memakai satu-satunya family-nya; peneliti tidak memilih family. Urutan kandidat ditentukan oleh SHA256 dari seed pra-registrasi dan case_id, bukan oleh skor atau kemudahan mutasi. Setiap mutasi diverifikasi otomatis (berbeda dari asli, satu blok perubahan, angka atau tanggal baru tidak ada di halaman jangkar) dan manual (peneliti mencatat halaman jangkar yang membuktikan kebalikannya). Label mutasi adalah TIDAK_LAYAK menurut konstruksi, berasal `mutasi_terkontrol`, dan dihitung hanya pada Track M. Dari 12 kandidat terbentuk 11 pasangan (numeric_value 7, unit 3, date 1). R05 dilewati karena ketiga kandidat nilai (2, 3, 5) muncul sebagai angka di halaman jangkar. Satu-satunya pertanyaan definisi berlabel TIDAK_LAYAK, sehingga family negation tidak terwakili.
<!-- sumber: config/protocol.json → track_m.mutation (changes_per_answer=1, families_by_question_type, operations, verification, family_assignment), track_m.seed, track_m.ordering, track_m.take, track_m.shortfall; SPEC §2 D13; src/ta_rag/protocol.py (assign_mutation_families). -->

### 3.9 Evaluator

Empat konfigurasi dibandingkan pada input identik: A (hanya leksikal), B (hanya semantik), C (hybrid), dan D (hybrid ditambah hard-fail). Skor leksikal L adalah F1 himpunan token antara jawaban dan evidence (normalisasi NFKC, *casefold*, token `\w+`). Skor semantik S = (cos + 1)/2, dengan cos adalah kosinus embedding *paraphrase-multilingual-MiniLM-L12-v2* untuk jawaban dan evidence. Skor akhir H = (1 − w_s)·L + w_s·S. Keputusan: ACCEPT bila H ≥ t (ambang ACCEPT), REVIEW bila H ≥ 0,50, dan REJECT selain itu. Konfigurasi A memakai w_s = 0, B memakai w_s = 1, dan C memakai 0 < w_s < 1. Konfigurasi D adalah C ditambah dua aturan hard-fail: (1) bila jawaban memuat angka nilai yang tidak ada pada evidence maupun pertanyaan, keputusan menjadi REJECT; (2) bila polaritas negasi jawaban berbeda dari evidence (kata negasi: tidak, bukan, tanpa, belum, tak, dilarang, kecuali, nihil) dan L ≥ 0,70, keputusan ACCEPT diturunkan menjadi REVIEW. Ekstraksi angka mengikuti format Indonesia (titik sebagai pemisah ribuan, koma sebagai desimal, awalan "Rp" menempel pada angka), sehingga "Rp8.000,00" dibaca sebagai satu nilai. Angka sitasi diabaikan, yaitu nomor dan tahun peraturan ("Nomor 59 Tahun 2024"), "Pasal N", "ayat (N)", "angka N", serta "hlm./halaman N", demikian pula angka yang sudah muncul pada pertanyaan; yang diperiksa adalah nilai (jumlah, durasi, tanggal, uang) pada jawaban. Evaluator deterministik; skor L, S, dan penanda dihitung sekali per record, dan sweep hanya mengubah parameter keputusan.
<!-- sumber: src/ta_rag/evaluators.py (lexical_f1, semantic_score, combine, route; REVIEW_THRESHOLD=0.50; NEG_F1_GATE=0.70; NEG_WORDS); src/ta_rag/numbers.py (_CITATION, unsupported_answer_numbers); config/protocol.json → baselines (A-D); SPEC §2 D12. -->

### 3.10 Pemisahan data dan pemilihan parameter

Rekaman dibagi menjadi validation (70%) dan test (30%) menurut komponen terhubung dari `group_id` ∪ `evidence_group` dengan seed pra-registrasi, sehingga dua jawaban dari pertanyaan yang sama, termasuk jawaban asli dan mutasinya, selalu berada pada split yang sama; penjaga kebocoran memeriksanya. Pembagian tidak terstratifikasi menurut label, dan sebarannya dilaporkan (`splits.json`). Parameter dipilih hanya pada validation. Tiga langkah sensitivitas dijalankan: (1) bobot semantik 0–100% dengan langkah 1% (101 titik) pada ambang ACCEPT 0,78; (2) ambang ACCEPT 0–1 dengan langkah 0,01 (101 titik) pada bobot 60:40; dan (3) grid penuh bobot semantik {0; 0,25; 0,5; 0,6; 0,75; 1} × ambang {0,70; 0,75; 0,78; 0,80; 0,85}, yaitu 30 kombinasi untuk C dan 30 untuk D (60 baris). Langkah 1 dan 2 bersifat eksploratif.

Parameter dipilih dengan aturan yang dikunci sebelum pelabelan, terpisah untuk setiap konfigurasi: A dari baris w_s = 0, B dari baris w_s = 1, dan C dari 30 baris hybrid tanpa hard-fail; D memakai parameter C dengan hard-fail menyala; sebagai analisis sekunder yang juga dipra-registrasi, D\* memilih parameternya sendiri dari 30 baris D. Aturan R1: di antara kombinasi dengan FAR Track M pada validation ≤ α = 0,05 (FAR terdefinisi), dipilih CAR Track R tertinggi; seri diputus berurutan oleh REVIEW rate Track R yang lebih rendah, latency p95 yang lebih rendah (hanya bila selisih relatif ≥ 10%), w_s yang lebih kecil, lalu ambang ACCEPT yang lebih besar. Aturan R2: bila tidak ada kombinasi yang memenuhi, dilaporkan `NO_ELIGIBLE_PARAMETER` sebagai temuan tanpa melonggarkan α (parameter acuan adalah FAR terendah); bila validation tidak memuat satu pun TIDAK_LAYAK pada Track M, tidak ada pemilihan (`FAR_UNDEFINED_NO_SELECTION`). Nilai α = 0,05 adalah contoh toleransi untuk latihan dari Panduan, bukan ambang keselamatan. FAR Track R dan FAR Track M tidak pernah digabung. Parameter terpilih dibekukan dan dievaluasi sekali pada test set; kelima konfigurasi (A, B, C, D, D\*) dinilai dalam satu proses test yang sama. Sensitivitas pada test hanya diagnostik dan tidak dipakai memilih ulang.
<!-- sumber: config/protocol.json → split (seed, validation_fraction=0.7, unit), selection (alpha=0.05, R1, R2, tie_break_chain, far_undefined, far_used_for_selection, per_configuration), test_policy.runs_allowed=1; src/ta_rag/sweep.py (W_GRID, T_GRID, stage_a/b/c: 101/101/60; accept 0.78 pada langkah 1, bobot 0.60 pada langkah 2); SPEC §2 D10, D11; Panduan §8. -->

### 3.11 Metrik dan analisis statistik

Untuk penghitungan biner, ACCEPT berarti dilepas ke pengguna, sedangkan REVIEW dan REJECT berarti ditahan. CAR (*correct acceptance rate*) adalah jumlah LAYAK→ACCEPT dibagi seluruh jawaban LAYAK; FAR (*false acceptance rate*) adalah jumlah TIDAK_LAYAK→ACCEPT dibagi seluruh jawaban TIDAK_LAYAK; *false rejection* adalah jumlah LAYAK→REJECT dibagi seluruh jawaban LAYAK; REVIEW rate dan REJECT rate adalah proporsi jawaban yang diputuskan REVIEW dan REJECT dari seluruh jawaban, dilaporkan terpisah karena dampaknya berbeda. Setiap rasio dilaporkan sebagai pembilang/penyebut dengan interval kepercayaan 95% Clopper–Pearson dua sisi; bila penyebut nol, metrik ditulis "tidak terdefinisi (n=0)", bukan 0%. Metrik dilaporkan terpisah untuk Track R dan Track M, dan matriks konfusi 2×3 (label × keputusan) disajikan. Latency p50 dan p95 mengukur waktu evaluator saja (bukan waktu seluruh RAG) dengan interval bootstrap persentil (1.000 resample), 100 iterasi setelah 10 pemanasan, pada CPU 4 inti dan RAM 16 GB (Linux, Python 3.12). Pengukuran pra-seleksi (S33) hanya mencakup A, C, dan D pada w_s = 0,6. Untuk pelaporan, latency diukur ulang pasca-test pada parameter tiap konfigurasi terpilih; latency tidak memutus seri pada seleksi mana pun. Perbandingan berpasangan antar-konfigurasi pada input identik memakai uji McNemar eksak dan selisih proporsi dengan CI. Pernyataan bahwa satu konfigurasi lebih baik hanya ditulis bila selisih signifikan secara statistik, setidaknya 10 poin persentase, dan CI selisihnya tidak memuat 0; selain itu ditulis "tidak ada bukti perbedaan pada data pilot ini; CI lebar". Setiap klaim CAR/FAR diawali "Di bawah pelabelan validator tunggal (intra-rater agreement X%, n=…):".
<!-- sumber: src/ta_rag/metrics.py (summarize, rate, clopper_pearson, latency_stats n_boot=1000, mcnemar_exact, paired_diff); config/protocol.json → intervals, significance_claims (>= 10 poin), claim_prefix; Panduan Tabel 7. -->

### 3.12 Tahap II (deskriptif)

Parameter yang dibekukan pada Tahap I diterapkan pada 20 jawaban asli dengan konteks hasil retrieval (bukan evidence oracle). Tidak ada sweep atau test tambahan, dan hasilnya tidak digabung dengan Tahap I. Label Tahap II diturunkan secara mekanis dari label Tahap I, kolom `abstain`, dan `retrieval_ok`, yaitu apakah salah satu dari empat chunk terambil memuat halaman jangkar pada dokumen sumber: jawaban abstain atas pertanyaan berjawab dinilai LAYAK hanya bila `retrieval_ok` salah, dan tetap TIDAK_LAYAK bila retrieval menemukan evidence. Probe tidak memiliki `retrieval_ok` (tidak terdefinisi).
<!-- sumber: config/protocol.json → split.stage_II (D14), label_rubric.answerable.false_abstention_rule; src/ta_rag/pipeline.py (retrieval_ok, score_rows, run_stage2). -->

### 3.13 Ketertelusuran dan ketersediaan

Penelitian dijalankan oleh orkestrator deterministik (`ta_rag.agent`) dengan ledger berantai-hash. Langkah yang melibatkan keputusan manusia (QA parsing, verifikasi pertanyaan, pelabelan, mutasi, relabel, dan pengiriman ringkasan pra-evaluator) hanya dapat ditandai selesai oleh manusia pada terminal interaktif, dan penjaga data memeriksa provenans (PDF asli, JSON mentah Reducto, respons generator, label) sebelum langkah berikutnya. Urutan kunci protokol → pelabelan → skor → test dapat ditelusuri pada ledger dan riwayat git. Dokumen sumber adalah peraturan dan laporan publik tanpa data pribadi; PDF dan JSON mentah tidak didistribusikan ulang, sedangkan manifest dan SHA256 disertakan. Kode, protokol, tes, label, dan hasil tersedia dari penulis atas permintaan.
<!-- sumber: src/ta_rag/agent.py, src/ta_rag/guards.py, config/workflow.json; CLAUDE.md aturan 16, 22-23; data/agent/ledger.jsonl. -->

### 3.14 Analisis diagnostik pasca-uji (tidak dipra-registrasi)

Setelah test dijalankan, lima analisis deskriptif ditambahkan tanpa mengubah label, split, parameter, atau hasil test: (1) rincian keputusan Track M per family mutasi; (2) rerata L dan S jawaban asli pada Tahap I dibandingkan Tahap II; (3) stabilitas keputusan antar-lari, yaitu keputusan parameter beku tiap konfigurasi untuk jawaban lari 1–3 terhadap evidence oracle, tanpa label; (4) stabilitas seleksi, yaitu 1.000 replikasi bootstrap atas komponen pertanyaan pada validation dengan seleksi R1/R2 diulang pada tiap replikasi, serta sensitivitas terhadap α = 0,05, 0,10, dan 0,20; dan (5) BERTScore (implementasi resmi, model `bert-base-multilingual-cased`, lapisan 9, tanpa idf dan tanpa baseline rescaling) terhadap kutipan evidence, dengan selisih berpasangan antara mutasi dan jawaban asalnya. Analisis (4) hanya memakai split validation; analisis (5) memakai seluruh 27 record Tahap I dan hanya bersifat deskriptif. Seluruhnya dilaporkan terpisah dari hasil utama dan tidak dipakai untuk klaim keunggulan.
<!-- sumber: SPEC v4.2.8-4.2.9; data/results/report/family_mutasi.md, stage2.md; data/results/exploratory/run_stability.json, sweep_stability.json, bertscore_pilot.json, latency_selected.json. -->

## 4. Hasil dan Pembahasan

> Semua angka di bagian ini disalin dari `data/results/**` (sumber di komentar). Klaim CAR/FAR diawali "Di bawah pelabelan validator tunggal (intra-rater agreement 75%, n=8)". Interval = Clopper–Pearson dua sisi 95%.

### 4.1 Data akhir dan pelabelan

Dari 20 jawaban lari utama, validator melabeli 14 LAYAK dan 6 TIDAK_LAYAK. Pada 16 pertanyaan berjawab, 12 jawaban LAYAK dan 4 TIDAK_LAYAK; keempatnya adalah abstain keliru (R04, R08, R11, R14), yaitu generator menyatakan informasi tidak ada padahal kutipannya ada di halaman jangkar. Tiga di antaranya terjadi ketika tidak satu pun chunk terambil memuat halaman jangkar (`retrieval_ok` salah). Pada R08, konteks memuat halaman jangkar tetapi tidak memuat kalimat buktinya. Tidak ada jawaban berjawab yang memuat angka, tanggal, atau satuan yang salah. Dari 4 probe, 2 LAYAK (abstain eksplisit) dan 2 TIDAK_LAYAK (R18, R20: abstain benar, tetapi disertai klaim tambahan yang tidak didukung). Track M memuat 11 mutasi dari 12 jawaban LAYAK (numeric_value 7, unit 3, date 1).

Relabel intra-rater atas 8 record menghasilkan kesepakatan 6/8 (75%; κ = 0,50). Kedua selisih terjadi pada probe R18 dan R20 (TIDAK_LAYAK pada pelabelan pertama, LAYAK pada relabel). Selisih ini menunjukkan bahwa rubrik probe ambigu ketika abstain yang benar disertai klaim tambahan.

Populasi Tahap I berisi 27 record (16 jawaban asli berjawab dan 11 mutasi). Validation memuat 19 record (Track R: 8 LAYAK dan 4 TIDAK_LAYAK; Track M: 7). Test memuat 8 record (Track R: 4 LAYAK; Track M: 4). Karena tidak ada TIDAK_LAYAK alami di test, FAR Track R pada test tidak terdefinisi (n = 0).
<!-- sumber: data/labels/labels.jsonl, labels_all.jsonl, mutants_log.json, relabel_result.json; data/results/I/selection.json → split_report; data/results/scored_II.jsonl (retrieval_ok) -->

### 4.2 Sensitivitas dan seleksi pada validation

Konfigurasi semantik saja (B, w_s = 1) menerima 7/7 mutasi validation pada setiap ambang ≤ 0,78, dan 6/7 pada 0,80. Pada ambang 0,85 masih 4/7 mutasi diterima, sedangkan CAR turun menjadi 4/8. Karena tidak ada ambang yang memenuhi FAR Track M ≤ 5%, B berstatus `NO_ELIGIBLE_PARAMETER`, dan parameter acuannya (0,85) adalah FAR terendah menurut aturan R2. Tiga konfigurasi lain memiliki kombinasi yang lolos batas FAR (Tabel 2):
- A (0:100, ambang 0,75): CAR 3/8, FAR Track M 0/7.
- C (25:75, ambang 0,80): CAR 3/8, FAR Track M 0/7.
- D\* (0:100 dengan hard-fail, ambang 0,75): CAR 3/8, FAR Track M 0/7. D\* seri dengan D pada 25:75/0,80 dan diputus oleh REVIEW rate Track R yang lebih rendah (0,17 terhadap 0,33).

Karena Track M validation hanya 7 record, FAR bukan nol terkecil adalah 1/7 (14,3%). Batas α = 5% praktis berarti FAR harus 0/7, sehingga aturan R1 memaksa pilihan ke parameter yang paling konservatif. Sebagai pembanding, D pada 100:0 dengan ambang 0,80 mencapai CAR 8/8 dan FAR Track M 1/7 di validation, tetapi tidak memenuhi batas. Kurva langkah sensitivitas 1–2 disajikan pada Gambar 2–3.
Pita interval kepercayaan 95% pada Gambar 2–3 memperlihatkan bahwa kurva CAR dan FAR Track M saling tumpang tindih sepanjang sumbu: dengan 8 jawaban LAYAK dan 7 mutasi, sweep ini menunjukkan arah, bukan parameter optimal. Untuk menilai seberapa jauh seleksi bergantung pada sampel, seleksi diulang pada 1.000 replikasi bootstrap atas 12 komponen pertanyaan di validation (pasca-uji; §3.14). Seleksi terkunci direproduksi persis dari data validation (5 dari 5 konfigurasi). B tidak memiliki parameter yang memenuhi batas FAR pada 99,1% replikasi. C dan D memilih parameter terkunci (25:75; 0,80) pada 97,4% replikasi, A pada 67,8%, dan D\* hanya pada 43,1%. Pada α = 0,05 dan 0,10 seleksi identik, karena dengan 7 mutasi FAR bukan nol terkecil adalah 1/7 (14,3%). Pada α = 0,20 hanya D\* berubah, ke 100:0 dengan ambang 0,80 (CAR 8/8; FAR Track M 1/7). Dengan demikian temuan kualitatif (semantik saja tidak memenuhi batas FAR) kokoh, sedangkan nilai parameter persis A dan D\* tidak.
<!-- sumber: data/results/exploratory/sweep_stability.json -->
<!-- sumber: data/results/I/stage_C.csv, selection.json; data/results/report/table12.md, fig_stage_A.png, fig_stage_B.png -->

### 4.3 Hasil uji tunggal

Test dijalankan satu kali dengan parameter beku (`rerun = false`). Di bawah pelabelan validator tunggal (intra-rater agreement 75%, n=8):

**Tabel 3.** Hasil test (n Track R = 4 LAYAK; n Track M = 4 TIDAK_LAYAK). FAR Track R tidak terdefinisi (n = 0) untuk semua konfigurasi.

| Konfigurasi | Bobot S:L | Ambang | CAR Track R | FAR Track M | REVIEW Track R | REJECT Track R | p95 (ms) |
|---|---|---|---|---|---|---|---|
| A | 0:100 | 0,75 | 1/4 (25%; 0,6–80,6) | 0/4 (0%; 0–60,2) | 2/4 | 1/4 | 0,48 |
| B (acuan, tidak lolos validation) | 100:0 | 0,85 | 4/4 (100%; 39,8–100) | 4/4 (100%; 39,8–100) | 0/4 | 0/4 | 257 |
| C | 25:75 | 0,80 | 0/4 (0%; 0–60,2) | 0/4 (0%; 0–60,2) | 4/4 | 0/4 | 385 |
| D | 25:75 | 0,80 | 0/4 (0%; 0–60,2) | 0/4 (0%; 0–60,2) | 3/4 | 1/4 | 268 |
| D\* | 0:100 | 0,75 | 1/4 (25%; 0,6–80,6) | 0/4 (0%; 0–60,2) | 2/4 | 1/4 | 0,66 |

Pada Track M di test, D dan D\* me-REJECT 3/4 mutasi dan me-REVIEW 1/4. A me-REVIEW 3/4, dan C me-REVIEW 4/4. B menerima keempatnya. Selisih B terhadap D pada keempat mutasi yang sama (b = 4, c = 0) menghasilkan McNemar eksak p = 0,125. Selisih sebaliknya pada CAR Track R (B 4/4, D 0/4) juga p = 0,125. Menurut aturan klaim yang dipra-registrasi, tidak ada bukti perbedaan pada data pilot ini; CI lebar. Arah hasil test sama dengan validation: semantik saja menerima mutasi, sedangkan konfigurasi leksikal/hybrid menahan hampir semua jawaban, baik yang salah maupun yang benar.

Latency p95 evaluator (100 iterasi, CPU) adalah 0,48 ms untuk A dan 0,66 ms untuk D\* (tanpa embedding), serta 257–385 ms untuk B, C, dan D (dengan embedding). Selisih antara C dan D berada dalam derau pengukuran: jalur komputasinya sama, kecuali aturan hard-fail.
<!-- sumber: data/results/I/test_result.json; data/results/report/table11.md, confusion_test.md; data/results/exploratory/latency_selected.json; McNemar dihitung dengan ta_rag.metrics.mcnemar_exact dari per_case.csv -->

### 4.4 Rincian per family mutasi (pasca-uji)

**Tabel 4.** Keputusan atas 11 mutasi Track M (validation + test) dengan parameter beku.

| Family | n | B diterima | D: REJECT / REVIEW / ACCEPT |
|---|---|---|---|
| numeric_value | 7 | 6 | 7 / 0 / 0 |
| date | 1 | 0 | 1 / 0 / 0 |
| unit | 3 | 2 | 0 / 3 / 0 |

Hard-fail angka me-REJECT seluruh mutasi `numeric_value` dan `date` (8/8). Sebaliknya, tidak satu pun mutasi `unit` ditolaknya (0/3), karena perubahan "bulan"→"hari" tidak mengubah angka. Mutasi `unit` hanya tertahan sebagai REVIEW oleh skor H. Pada bobot semantik yang tinggi (100:0, ambang 0,80), dua dari tiga mutasi `unit` (M:R02, M:R12) diterima D.
<!-- sumber: data/results/report/family_mutasi.md; per_case.csv (route_D) -->

### 4.5 Kasus rinci

Aturan pemilihan kasus pra-registrasi untuk konfigurasi D menghasilkan tiga temuan:
- **Benar-ACCEPT:** kategori ini kosong di test, sehingga kasus diambil dari validation dan ditandai sebagai cadangan (run1:R01).
- **Salah-tertahan:** M:R02, mutasi `unit` yang di-REVIEW.
- **Salah-tetap-ACCEPT:** tidak ditemukan di antara 15 record TIDAK_LAYAK Tahap I.

Satu false rejection D di test patut dicatat. R16 berlabel LAYAK, tetapi di-REJECT karena menyebut Rp1.000 dan Rp10.000. Kedua nilai itu benar dan ada di halaman jangkar, tetapi tidak ada di fragmen kutipan yang menjadi evidence. Rubrik manusia menilai halaman jangkar, sedangkan evaluator hanya melihat fragmen kutipan. Perbedaan granularitas evidence ini menghasilkan penolakan atas jawaban yang benar.
Untuk konfigurasi B (tambahan, tidak dipra-registrasi; aturan pemilihan kasus yang sama), kategori salah-tetap-ACCEPT ditemukan: M:R02 di test, jawaban yang mengubah "3 (tiga) bulan" menjadi "3 (tiga) hari" dengan skor semantik 0,896 dan keputusan ACCEPT. Pasangan benar-ACCEPT dan salah-tertahan untuk B ada pada `kasus_tabel14_B.md`.
<!-- sumber: data/results/report/kasus_tabel14.md, kasus_tabel14_B.md; per_case.csv (run1:R16 flags_D = UNSUPPORTED_NUMBER) -->

### 4.6 Tahap II (deskriptif)

Dengan konteks hasil retrieval sebagai evidence, A, C, D, dan D\* me-REJECT 20/20 jawaban asli. B menerima 10/17 jawaban LAYAK dan 0/3 jawaban TIDAK_LAYAK, serta me-REVIEW 10/20. Rerata L jawaban berjawab turun dari 0,531 (Tahap I, kutipan oracle) menjadi 0,182 (Tahap II, empat chunk), sedangkan rerata S hampir tetap (0,845 dan 0,859). F1 himpunan token terhadap konteks gabungan yang panjang menekan recall leksikal, sehingga H konfigurasi leksikal/hybrid hampir selalu di bawah 0,50. Hasil Tahap II untuk A, C, D, dan D\* karena itu mencerminkan definisi evidence, bukan mutu jawaban. Sebagai analisis pasca-uji, evidence diganti dengan satu satuan konteks terbaik (baris atau kalimat dengan F1 tertinggi terhadap jawaban), sedangkan angka diperiksa terhadap seluruh konteks. Rerata L jawaban berjawab kembali ke 0,593 (kutipan oracle: 0,530) dan REJECT konfigurasi D turun dari 20/20 menjadi 7/20 dengan parameter yang sama. Pemilihan satuan memakai jawaban sedikit menaikkan skor, dan jawaban abstain yang benar tetap ditolak karena tidak ada evidence yang dapat dicocokkan. `retrieval_ok` bernilai benar pada 13 dari 16 pertanyaan berjawab.
<!-- sumber: data/results/II/stage2_result.json; data/results/report/stage2.md -->

### 4.7 Stabilitas keputusan antar-lari (pasca-uji, tanpa label)

Jawaban lari 2 dan 3 dibangkitkan dengan konteks yang sama persis. Setelah normalisasi spasi dan huruf, hanya 1 dari 40 jawaban yang identik dengan jawaban lari 1. Dari 16 pertanyaan berjawab, jumlah pertanyaan yang keputusannya sama pada ketiga lari adalah: A 9, B 12, C 12, D 10, dan D\* 9. Variasi generator pada temperature 0 cukup besar untuk mengubah keputusan evaluator pada 4–7 dari 16 pertanyaan. Satu lari berlabel (k = 1) tidak menggambarkan variasi ini.
<!-- sumber: data/results/exploratory/run_stability.json; data/runs/answers_run{1,2,3}.jsonl -->

### 4.8 Pembanding BERTScore (deskriptif, pasca-uji)

BERTScore F1 dihitung untuk 27 jawaban Tahap I terhadap kutipan evidence (implementasi resmi `bert-score`, `bert-base-multilingual-cased`, lapisan 9, tanpa idf dan tanpa baseline rescaling). Pada 11 pasangan jawaban asli dan mutasinya, mutasi menurunkan BERTScore F1 pada 10 pasangan, dengan selisih median −0,0034. Sebagai perbandingan, kosinus semantik turun median 0,0081 (11 dari 11 pasangan) dan F1 token turun median 0,0571 (11 dari 11). Sebaran skor antar jawaban LAYAK asli jauh lebih lebar: 0,678–0,871 untuk BERTScore F1, 0,802–0,974 untuk kosinus, dan 0,314–0,800 untuk F1 token. Satu mutasi karena itu menggeser BERTScore F1 sekitar 2% dari sebaran skor antar jawaban yang benar. Keempat jawaban TIDAK_LAYAK alami pada pertanyaan berjawab (semuanya abstain keliru) berskor 0,636–0,678, di dasar rentang jawaban benar. Pada data ini kemiripan menangkap perubahan isi yang besar (abstain), tetapi hampir tidak peka terhadap perubahan satu fakta. Analisis ini deskriptif: BERTScore tidak diberi ambang, tidak dipilih parameternya, dan tidak diuji sebagai konfigurasi.
<!-- sumber: data/results/exploratory/bertscore_pilot.json -->

### 4.9 Pembahasan

> Draf; sesuaikan dengan suara Anda, dan tambahkan hubungan dengan literatur hanya dari bacaan yang tercantum pada Tabel 1.

**Semantik saja tidak peka terhadap kesalahan satu fakta.** Mutasi yang hanya mengubah satu angka, satuan, atau tahun mempertahankan kosinus yang tinggi (S rerata 0,891 pada Track M), sehingga B menerima sebagian besar mutasi pada semua ambang yang diuji. BERTScore F1 menunjukkan pola yang sama (§4.8). Temuan ini sejalan dengan hipotesis Panduan §3. Karena n kecil, temuan ini adalah indikasi, bukan bukti statistik.

**Aturan hard-fail menutup celah angka, tetapi tidak celah satuan, dan dapat menolak jawaban benar.** Pada data ini, hard-fail menolak semua mutasi angka dan tanggal. Mutasi satuan lolos dari aturan karena angkanya tetap. R16 menunjukkan biaya sebaliknya: angka benar yang tidak termuat di fragmen evidence dianggap tidak didukung. Kedua kasus menunjukkan bahwa aturan berbasis angka bergantung pada (a) jenis kesalahan yang dicari dan (b) granularitas evidence.

**Batas FAR pada n kecil menentukan pilihan parameter.** Dengan 7 mutasi validation, batas α = 5% setara dengan nol mutasi diterima. Seleksi pun jatuh pada parameter yang menahan sebagian besar jawaban benar (CAR test 0–1/4), sementara beban REVIEW tinggi. Hasil ini adalah konsekuensi kombinasi aturan seleksi dan ukuran sampel, bukan sifat bawaan evaluator.

**Kesalahan alami generator pada data ini adalah abstain, bukan halusinasi angka.** Keempat kesalahan jawaban berjawab adalah abstain keliru yang berkaitan dengan retrieval. Track M menguji kelas kesalahan yang tidak muncul secara alami pada 16 jawaban ini, sehingga FAR Track M tidak dapat dibaca sebagai prevalensi kesalahan RAG.

**Definisi evidence menentukan perilaku Tahap II.** Skor leksikal yang wajar terhadap kutipan pendek runtuh terhadap konteks panjang. Evaluator berbasis F1 untuk konteks retrieval memerlukan evidence pada tingkat kalimat atau chunk terbaik. Hal ini tidak diuji di sini dan menjadi pekerjaan lanjutan.

**Hubungan dengan llm-eval-layer.** Evaluator di sini adalah implementasi independen yang mengambil ide lapisan keputusan ACCEPT/REVIEW/REJECT dan bobot 60:40 semantik:leksikal. Implementasi ini bukan replikasi. Repositori tersebut menghitung overlap Jaccard atas token huruf saja (angka dibuang), memakai embedding berbahasa Inggris, dan tidak memeriksa angka atau negasi. Aturan hard-fail di sini menargetkan celah yang tepat ditunjukkan oleh hasil B (Alexander, 2026).

## 5. Keterbatasan

1. **Validator tunggal.** Penulis pertanyaan, penulis mutasi, dan pelabel adalah orang yang sama. Relabel intra-rater (75%, n = 8; κ = 0,50) mengukur konsistensi diri, bukan validasi independen. Penilaian validator kedua dibantu AI dan tidak dipakai.
2. **Sampel sangat kecil.** Test hanya 8 record (4 LAYAK Track R, 4 mutasi), tanpa TIDAK_LAYAK alami. Lebar CI 95% berkisar 60–86 poin persentase, dan tidak ada perbedaan antar-konfigurasi yang signifikan.
3. **Mutasi terkontrol bukan kesalahan alami.** Kesalahan alami pada data ini adalah abstain keliru dan klaim tambahan pada probe, sedangkan Track M menguji perubahan angka, satuan, dan tahun. Family negation tidak terwakili.
4. **Titik buta hard-fail.** Mutasi satuan tidak tertangkap; angka sitasi diabaikan menurut desain (D12). Evidence berupa fragmen kutipan dapat menyebabkan false rejection atas angka benar (R16). Aturan negasi adalah heuristik berbasis daftar kata.
5. **Generator.** Hanya satu model dan satu prompt, dengan satu lari berlabel. Dua lari tambahan menunjukkan keputusan berubah pada 4–7 dari 16 pertanyaan, tetapi tidak dilabel. Satu respons lari utama terpotong (R10).
6. **Cakupan korpus.** 267 dari 1.346 halaman, satu domain, satu bahasa. Tabel tarif INA-CBG tidak dievaluasi, dan dokumen induk tidak ada. SHA256 dokumen cocok dengan audit penulis, tetapi belum dengan server penerbit.
7. **QA parsing dan verifikasi.** Pemeriksaan manusia hanya pada halaman jangkar. Ketidakhadiran jawaban probe diperiksa dengan bantuan agen AI dan dikonfirmasi peneliti, bukan diperiksa secara independen.
8. **Tahap II tidak informatif untuk konfigurasi leksikal/hybrid** karena F1 dihitung terhadap konteks gabungan. Selain itu, `retrieval_ok` adalah proksi rentang halaman, bukan pemeriksaan keberadaan kutipan. Model embedding yang sama dipakai oleh retrieval dan evaluator semantik.
9. **Pembanding.** RAGAS, RAGChecker, dan LLM-as-judge tidak dijalankan. BERTScore hanya dihitung secara deskriptif pada 27 record setelah test; ia tidak diberi ambang, tidak dipilih parameternya, dan tidak diuji sebagai konfigurasi.
10. **Deviasi dan analisis tambahan.** Jeda relabel untuk record mutasi 7,18 jam, di bawah 12 jam yang dipra-registrasi (diakui sebelum impor). Latency dan analisis §4.4, §4.7 dihitung pasca-uji. Perubahan kode selama pelaksanaan baru di-commit setelah test, sehingga urutan kunci → label → skor → test dibuktikan oleh ledger berantai-hash, bukan oleh riwayat git.
11. **Domain administratif.** Penelitian ini tidak menguji keamanan klinis dan tidak membuat klaim tentangnya.

## 6. Kesimpulan

1. Di bawah pelabelan validator tunggal (intra-rater agreement 75%, n=8), pada studi pilot ini evaluator semantik saja menerima seluruh mutasi satu fakta di test (4/4; CI 39,8–100%). Konfigurasi leksikal, hybrid, dan hybrid + hard-fail yang dipilih dengan batas FAR 5% menolak atau menahan keempat mutasi (0/4; CI 0–60,2%), tetapi juga menahan hampir semua jawaban benar (CAR 0–1/4). Perbedaan ini tidak signifikan secara statistik pada n = 4.
2. Aturan hard-fail angka menolak semua mutasi angka dan tanggal (8/8), tidak menangkap mutasi satuan (0/3), dan menolak satu jawaban benar karena evidence berupa fragmen kutipan. Temuan ini memberi arah perbaikan yang konkret: pemeriksaan satuan, dan evidence pada tingkat yang sama dengan rubrik manusia.
3. **Pekerjaan lanjutan:** jumlah pertanyaan dan jawaban berlabel yang jauh lebih besar; validator independen; pelabelan beberapa lari generator; evidence tingkat kalimat untuk konteks retrieval; aturan satuan; family mutasi negasi dan sitasi; serta pembanding BERTScore/RAGAS yang benar-benar dijalankan.

## Daftar Pustaka

> Kandidat bacaan awal dari Panduan (daftar referensi awal). Pertahankan hanya yang benar-benar Anda baca dan kutip; periksa DOI/URL; tambahkan rujukan dari bacaan Anda sendiri.

Alexander, E. P. (2026, 17 Mei). LLM evals are based on vibes — I built the missing layer that decides what ships. *Towards Data Science*. Kode: https://github.com/Emmimal/llm-eval-layer (lisensi MIT). Diakses 13 November 2026.

Es, S., James, J., Espinosa Anke, L., & Schockaert, S. (2024). RAGAs: Automated evaluation of retrieval augmented generation. *Proceedings of the 18th Conference of the European Chapter of the Association for Computational Linguistics: System Demonstrations*, 150–158. https://doi.org/10.18653/v1/2024.eacl-demo.16

Ji, Z., Lee, N., Frieske, R., dkk. (2023). Survey of hallucination in natural language generation. *ACM Computing Surveys, 55*(12), 1–38. https://doi.org/10.1145/3571730

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W., Rocktäschel, T., Riedel, S., & Kiela, D. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. *Advances in Neural Information Processing Systems 33 (NeurIPS 2020)*. arXiv:2005.11401.

Reimers, N., & Gurevych, I. (2019). Sentence-BERT: Sentence embeddings using Siamese BERT-networks. *EMNLP-IJCNLP*. https://aclanthology.org/D19-1410/

Reimers, N., & Gurevych, I. (2020). Making monolingual sentence embeddings multilingual using knowledge distillation. *EMNLP 2020*. arXiv:2004.09813.

Ru, D., Qiu, L., dkk. (2024). RAGChecker: A fine-grained framework for diagnosing retrieval-augmented generation. arXiv:2408.08067. https://github.com/amazon-science/RAGChecker

Zhang, T., Kishore, V., Wu, F., Weinberger, K. Q., & Artzi, Y. (2020). BERTScore: Evaluating text generation with BERT. *International Conference on Learning Representations (ICLR)*. arXiv:1904.09675.

Peraturan Presiden Republik Indonesia Nomor 59 Tahun 2024 tentang Perubahan Ketiga atas Peraturan Presiden Nomor 82 Tahun 2018 tentang Jaminan Kesehatan.

Peraturan Menteri Kesehatan Republik Indonesia Nomor 3 Tahun 2023 tentang Standar Tarif Pelayanan Kesehatan dalam Penyelenggaraan Program Jaminan Kesehatan.

Reducto. (2026). *Reducto documentation: Parse*. https://docs.reducto.ai. Diakses 13 November 2026.

Xiaomi. (2026). *Xiaomi MiMo API Open Platform* (model mimo-v2.6-flash). https://mimo.mi.com; https://platform.xiaomimimo.com. Diakses 13 November 2026.
<!-- Ringkasan isi makalah di §2 diambil dari abstrak dan teks lengkap yang dibaca 13 Nov 2026: BERTScore §3 (greedy matching, P/R/F1, idf opsional, baseline rescaling); RAGAS §3 dan Tabel 4 (gpt-3.5-turbo-16k; WikiEval 50 halaman; 0,95/0,78/0,70); README RAGChecker (LLM extractor/checker, gt_answer wajib, daftar metrik); kode llm-eval-layer (heuristics/similarity.py, scorers/faithfulness.py, configs/thresholds.yaml). Penulis tetap wajib membaca dan memeriksa ulang sebelum submit. -->

## Lampiran A. Berkas bukti

| Bukti | Berkas |
|---|---|
| Protokol terkunci | `config/protocol.lock.json` |
| Manifest parsing dan QA | `data/reducto/manifests/*.manifest.json`, `data/reducto/corpus_manifest.json` |
| Cakupan korpus | `data/manifest/scope_manifest.json` |
| Generator beku | `config/generator.json` (hash prompt dicatat di protokol) |
| Jawaban run 1 | `data/runs/answers_run1.jsonl` |
| Label dan relabel | `data/labels/labels_all.jsonl`, `relabel.jsonl`, `relabel_result.json` |
| Ringkasan pra-evaluator | `data/agent/pre_evaluator_sent.txt` |
| Seleksi, split, test | `data/results/I/{selection,splits,test_result}.json`, `stage_{A,B,C}.csv`, `per_case.csv` |
| Latency | `data/results/latency.json` (pra-seleksi: A, C, D) dan `data/results/exploratory/latency_selected.json` (parameter terpilih) |
| Tahap II | `data/results/II/stage2_result.json`, `per_case_II.csv` |
| Tabel dan gambar | `data/results/report/{table11,table12}.{md,csv}`, `fig_stage_{A,B}.png`, `confusion_test.md`, `kasus_tabel14.md`, `kasus_tabel14_B.md`, `family_mutasi.md`, `stage2.md` |
| Analisis pasca-uji | `data/results/exploratory/{sweep_stability,bertscore_pilot,run_stability}.json` |
| Ledger | `data/agent/ledger.jsonl` (periksa dengan `python -m ta_rag.agent verify`) |

## Lampiran B. Pemeriksaan sebelum submit (hapus lampiran ini)

```bash
# 1. Slot yang belum diisi: harus kosong
grep -n "\[ISI" docs/naskah/naskah_draft.md

# 2. Frasa terlarang (aturan 13): harus kosong setelah blok Catatan Penulis dan Lampiran B dihapus
grep -niE "lebih aman|lebih akurat|tervalidasi klinis|divalidasi secara klinis" docs/naskah/naskah_draft.md

# 3. Kalimat berangka CAR/FAR di §4 tanpa awalan klaim (tinjau manual)
sed -n '/^## 4\./,/^## 5\./p' docs/naskah/naskah_draft.md | grep -n "CAR\|FAR" | grep -v "Di bawah pelabelan validator tunggal"

# 4. Ledger utuh dan urutan kunci protokol < label < skor < test
python -m ta_rag.agent verify
git log --format='%h %ad %s' --date=iso | head -30
```

Angka di §4 disalin dari `data/results/**`, bukan diketik ulang; periksa satu per satu terhadap `table11.md`, `test_result.json`, dan `stage2_result.json`.
