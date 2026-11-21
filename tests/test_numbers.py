import pytest

from ta_rag.numbers import extract_numbers, unsupported_numbers

EVIDENCE_KAPITASI = (
    "Puskesmas sebesar Rp3.600,00 (tiga ribu enam ratus rupiah) sampai dengan Rp9.000,00 "
    "(sembilan ribu rupiah) per peserta per bulan"
)


@pytest.mark.parametrize("text, expected", [
    ("Rp8.000,00 per peserta per bulan", {"8000"}),
    ("Rp 8.000,00", {"8000"}),
    ("8.000", {"8000"}),
    ("Rp10.000,00", {"10000"}),
    ("Rp1.250.000,50", {"1250000.5"}),
    ("2,5% (dua koma lima persen)", {"2.5"}),
    ("40% - 60%", {"40", "60"}),
    ("paling lama 28 (dua puluh delapan) hari", {"28"}),
    ("tanggal 9 Januari 2023", {"9", "2023"}),
    ("Pasal 11 ayat (1) huruf a angka 3", {"11", "1", "3"}),
    ("tidak ada angka di sini", set()),
    ("", set()),
])
def test_extract_numbers_indonesian_formats(text, expected):
    assert extract_numbers(text) == expected


def test_regression_rupiah_fragment_bug_of_research_regex():
    """Kode riset: 'Rp8.000,00' -> {'000,00'} dan 'Rp10.000,00' -> {'000,00'} (identik). Di sini harus berbeda."""
    assert extract_numbers("Rp8.000,00") != extract_numbers("Rp10.000,00")
    assert extract_numbers("Rp8.000,00") != extract_numbers("Rp9.000,00")


@pytest.mark.parametrize("answer, flagged", [
    ("Rp9.000,00 per peserta per bulan", set()),                 # ada di evidence
    ("Rp 9.000 per peserta per bulan", set()),                   # format beda, nilai sama
    ("Rp8.000,00 per peserta per bulan", {"8000"}),              # nominal salah
    ("Rp10.000,00 per peserta per bulan", {"10000"}),            # nominal salah
    ("Rp3.700,00 sampai Rp9.000,00", {"3700"}),                  # satu ujung rentang salah
])
def test_unsupported_numbers_catches_wrong_nominals(answer, flagged):
    assert unsupported_numbers(answer, EVIDENCE_KAPITASI) == flagged


def test_unsupported_numbers_mutations_on_duration_and_date():
    ev = "Peserta dapat mengganti FKTP setelah jangka waktu 3 (tiga) bulan sejak 1 Januari 2024"
    assert unsupported_numbers("3 bulan", ev) == set()
    assert unsupported_numbers("6 bulan", ev) == {"6"}
    assert unsupported_numbers("sejak 1 Januari 2025", ev) == {"2025"}


# --- D12: hard-fail mengabaikan angka sitasi dan angka yang sudah ada di pertanyaan, nilai jawaban tetap diperiksa

from ta_rag.numbers import unsupported_answer_numbers as uan

Q_R02 = "Menurut Peraturan Presiden Nomor 59 Tahun 2024 (perubahan Pasal 7), setelah berapa lama Peserta dapat didaftarkan?"
EV_R02 = "Peserta wajib mendaftar paling lambat setelah 3 (tiga) bulan sejak dibentuk"


@pytest.mark.parametrize("answer", [
    "Menurut Perpres Nomor 59 Tahun 2024, Pasal 7 ayat (1), jangka waktunya 3 (tiga) bulan.",
    "Berdasarkan Pasal 7A ayat (2) huruf a angka 1 pada halaman 9, jangka waktunya 3 bulan.",
    "Menurut Kepmenkes Nomor HK.01.07/MENKES/1511/2023 (hlm. 5-6), jangka waktunya 3 bulan.",
])
def test_citation_numbers_in_answer_are_not_hard_fail(answer):
    assert uan(answer, EV_R02) == set()


def test_numbers_already_in_question_are_not_hard_fail_but_value_numbers_still_are():
    assert uan("Pada tahun 2024 jangka waktunya 3 bulan.", EV_R02, question="Berapa lama pada tahun 2024?") == set()
    assert uan("Jangka waktunya 6 (enam) bulan menurut Pasal 7 ayat (1).", EV_R02, Q_R02) == {"6"}


def test_value_mutations_survive_citation_stripping():
    ev = "mulai berlaku pada tanggal 1 September 2023 dan dibayar Rp8.000,00"
    assert uan("Berlaku pada 1 September 2024 (Pasal 4).", ev) == {"2024"}
    assert uan("Dibayar Rp16.000,00 sesuai Pasal 10 ayat (3).", ev) == {"16000"}
    assert uan("Pada tahun 2024 berlaku", ev) == {"2024"}  # 'tahun 2024' tanpa 'Nomor N' adalah nilai, bukan sitasi


def test_default_unsupported_numbers_is_unchanged_by_the_new_rule():
    assert unsupported_numbers("Pasal 7 ayat (1) 3 bulan", EV_R02) == {"7", "1"}


# ------------------------------------------------------------------ aturan satuan (konfigurasi E)

from ta_rag.numbers import unit_mismatches  # noqa: E402

EV_GANTI = "Peserta dapat mengganti FKTP tempat Peserta terdaftar setelah jangka waktu 3 (tiga) bulan"


@pytest.mark.parametrize("answer, evidence, question, expected", [
    ("setelah jangka waktu 3 (tiga) hari", EV_GANTI, "", ["3 hari"]),              # angka sama, satuan beda
    ("setelah jangka waktu 3 (tiga) bulan", EV_GANTI, "", []),                      # sama persis
    ("3 bulan", "paling lama 3 bulan", "", []),                                     # tanpa kata angka dalam kurung
    ("selama 4 hari", EV_GANTI, "", []),                                            # angka beda: urusan hard-fail angka, bukan satuan
    ("3 hari", "dalam 3 hari atau 3 bulan", "", []),                                # evidence memuat kedua satuan
    ("Menurut Peraturan Presiden Nomor 59 Tahun 2024, 6 bulan", "paling singkat 6 bulan", "", []),  # sitasi bukan satuan waktu
    ("sejak Peraturan Menteri Kesehatan Nomor 3 Tahun 2023 berlaku 14 hari", "dalam waktu 14 (empat belas) hari", "", []),
    ("Menurut Permenkes Nomor 3 Tahun 2023, setelah 3 (tiga) bulan", EV_GANTI, "", []),  # nomor peraturan = angka di evidence: bukan "3 tahun"
    ("15 bulan", "dalam waktu 15 hari", "", ["15 bulan"]),
    ("3 hari", EV_GANTI, "apakah benar 3 hari?", []),                               # pasangan yang sudah ada di pertanyaan tidak dihitung
    ("", EV_GANTI, "", []),
])
def test_unit_mismatches(answer, evidence, question, expected):
    assert unit_mismatches(answer, evidence, question) == expected
