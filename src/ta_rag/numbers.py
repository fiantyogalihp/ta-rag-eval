"""Ekstraksi angka untuk aturan hard-fail D ("angka pada jawaban yang tidak ada di evidence" -> REJECT).

Ditulis baru (v4.2) karena regex pembanding di kode riset 31 Okt (`(?<!\\w)\\d+(?:[.,]\\d+)*(?!\\w)`)
gagal pada rupiah tanpa spasi: "Rp8.000,00" menghasilkan potongan "000,00", sehingga Rp8.000,00,
Rp9.000,00 dan Rp10.000,00 tampak identik dan salah-nominal lolos tanpa hard-fail (diuji, SPEC §17).

Konvensi Indonesia: titik = pemisah ribuan bila diikuti tepat 3 digit, koma = desimal.
Hasil dinormalkan ke string kanonik (mis. "Rp8.000,00" -> "8000", "2,5%" -> "2.5") agar
"8.000" == "8000" == "Rp 8.000,00". Angka dalam kata ("tiga") TIDAK diekstrak: aturan ini hanya untuk digit.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Kelompok ribuan "1.234.567" (opsional ",desimal") | angka biasa "12" / "12,5" / "12.5".
# Lookbehind pada digit/titik/koma mencegah memotong angka di tengah; huruf di depan (mis. "Rp") BOLEH.
_NUM = re.compile(
    r"(?<![\d.,])(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?![\d])"
)


def _canon(raw: str) -> str | None:
    s = raw
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")  # ribuan + desimal koma
    else:
        s = s.replace(",", ".")  # desimal koma atau titik
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    text = format(d.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def extract_numbers(text: str) -> set[str]:
    """Himpunan nilai angka kanonik pada `text`."""
    out = set()
    for m in _NUM.finditer(text or ""):
        c = _canon(m.group(0).rstrip(".,"))
        if c is not None:
            out.add(c)
    return out


def unsupported_numbers(answer: str, evidence: str) -> set[str]:
    """Angka pada jawaban yang tidak ada pada evidence (inti hard-fail UNSUPPORTED_NUMBER)."""
    return extract_numbers(answer) - extract_numbers(evidence)


# Sitasi hukum pada JAWABAN (bukan nilai yang ditanyakan): "Nomor 59 Tahun 2024", "Nomor HK.01.07/MENKES/1511/2023",
# "Pasal 7A", "ayat (1)", "angka 3", "hlm. 5-6"/"halaman 9". "tahun 2024" tanpa "Nomor N" tetap nilai (mutasi tanggal harus tertangkap).
_CITATION = re.compile(
    r"\b(?:Nomor|No\.?)\s+\S+(?:\s+Tahun\s+\d{4})?"
    r"|\bPasal\s+\d+[A-Z]?\b"
    r"|\bayat\s*\(\d+\)"
    r"|\bangka\s+\d+"
    r"|\b(?:hlm\.?|halaman)\s*\d+(?:\s*[-–]\s*\d+)?",
    re.I,
)


def unsupported_answer_numbers(answer: str, evidence: str, question: str = "") -> set[str]:
    """Hard-fail evaluator (D12): angka NILAI pada jawaban yang tidak ada di evidence. Angka sitasi pada jawaban dan angka yang
    sudah ada di pertanyaan diabaikan (MiMo mengulangnya dari pertanyaan; bukan klaim baru). `unsupported_numbers` tetap
    mentah untuk pemakai lain (verifier pertanyaan)."""
    return extract_numbers(_CITATION.sub(" ", answer or "")) - extract_numbers(evidence) - extract_numbers(question)


# Angka + satuan waktu ("3 (tiga) bulan"). "tahun" yang diikuti angka tahun ("Nomor 3 Tahun 2023") adalah sitasi, bukan satuan.
_NUM_UNIT = re.compile(r"\b(\d+)\s*(?:\([^)]*\)\s*)?(hari|minggu|bulan|tahun(?!\s*\d{4}))\b", re.I)


def _number_units(text: str) -> set[tuple[str, str]]:
    return {(n, u.lower()) for n, u in _NUM_UNIT.findall(text or "")}


def unit_mismatches(answer: str, evidence: str, question: str = "") -> list[str]:
    """Angka yang SAMA tetapi satuan waktu BERBEDA terhadap evidence (mis. jawaban "3 hari", evidence "3 bulan"). Angka yang tak ada
    di evidence adalah urusan hard-fail angka (`unsupported_answer_numbers`), bukan aturan ini. Dipakai konfigurasi E (D + satuan)."""
    supported = _number_units(evidence) | _number_units(question)
    ev_units = {}
    for n, u in supported:
        ev_units.setdefault(n, set()).add(u)
    return sorted(f"{n} {u}" for n, u in _number_units(answer) - supported if n in ev_units)

