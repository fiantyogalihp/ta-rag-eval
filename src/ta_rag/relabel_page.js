// Pustaka murni halaman relabel (S26/S28). Tanpa DOM, tanpa dependensi; disisipkan ke tag script oleh pembangun halaman.
// Pustaka tidak pernah menyarankan label: label hanya masuk lewat setField atas aksi manusia.
"use strict";

const LABELS = ["LAYAK", "TIDAK_LAYAK", "INSUFFICIENT_EVIDENCE"];
const FIELDS = ["label_baru", "alasan_bila_berbeda"];

// Satu regex, urutan ref -> num -> kw; diterapkan sekali pada teks yang hanya di-escape &, <, >.
const MARK_RE = new RegExp([
  "(\\bPasal\\s+\\d+[A-Z]?\\b|\\bayat\\s*\\(\\d+\\)|\\bhuruf\\s+[a-z]\\b)",
  "(\\b(?:Rp\\s?)?\\d+(?:[.,]\\d+)*%?)",
  "(\\b(?:tidak|bukan|belum|tanpa|kecuali|selain|hanya|paling|lebih|kurang|sebelum|sesudah|setelah|sejak|sampai)\\b)",
].join("|"), "gi");

function mark(text) {
  const esc = String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(MARK_RE, (m, ref, num) => `<mark class="${ref ? "ref" : num ? "num" : "kw"}">${m}</mark>`);
}

function toCSV(columns, rows) {
  const cell = v => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const line = vals => vals.map(cell).join(",") + "\r\n";
  return String.fromCharCode(0xFEFF) + line(columns) + rows.map(r => line(columns.map(c => r[c]))).join("");
}

function setField(state, itemId, field, value, nowMs, notBeforeMs) {
  if (notBeforeMs !== null && notBeforeMs !== undefined) {
    // Gerbang waktu tertutup bila masukan rusak (NaN, string, Infinity): jangan pernah gagal terbuka.
    if (!Number.isFinite(nowMs) || !Number.isFinite(notBeforeMs)) throw new Error("Gerbang waktu tidak valid: waktu sekarang atau batas waktu bukan angka terhingga.");
    if (nowMs < notBeforeMs) throw new Error("Isian belum dibuka: batas waktu relabel belum tercapai.");
  }
  if (!FIELDS.includes(field)) throw new Error("Kolom tidak boleh diisi: " + field);
  if (field === "label_baru" && !LABELS.includes(value)) throw new Error("Label tidak sah: " + value);
  const next = {};
  for (const k of Object.keys(state)) next[k] = { ...state[k] };
  next[itemId] = { ...(next[itemId] || {}), [field]: String(value) };
  return next;
}

function restoreState(raw, rows) {
  const out = {};
  try {
    const obj = JSON.parse(raw);
    if (obj === null || typeof obj !== "object" || Array.isArray(obj)) return out;
    for (const id of new Set(rows.map(r => r.item_id))) {
      const e = Object.prototype.hasOwnProperty.call(obj, id) ? obj[id] : null;
      if (e === null || typeof e !== "object") continue;
      const kept = {};
      if (LABELS.includes(e.label_baru)) kept.label_baru = e.label_baru;
      if (typeof e.alasan_bila_berbeda === "string") kept.alasan_bila_berbeda = e.alasan_bila_berbeda;
      if (Object.keys(kept).length) out[id] = kept;
    }
  } catch (_) { return {}; }
  return out;
}

function fillRows(rows, state) {
  return rows.map(r => {
    const s = Object.prototype.hasOwnProperty.call(state, r.item_id) ? state[r.item_id] : {};
    return { ...r, label_baru: s.label_baru || "", alasan_bila_berbeda: s.alasan_bila_berbeda || "" };
  });
}

function missing(rows, state) {
  return rows.filter(r => !(Object.prototype.hasOwnProperty.call(state, r.item_id) && LABELS.includes(state[r.item_id].label_baru)))
    .map(r => r.item_id);
}

function keyAction(key, tagName) {
  const tag = String(tagName || "").toUpperCase();
  if (tag === "TEXTAREA" || tag === "INPUT") return null;
  if (key === "1" || key === "2" || key === "3") return { label: LABELS[Number(key) - 1] };
  if (key === "ArrowLeft") return { move: -1 };
  if (key === "ArrowRight") return { move: 1 };
  return null;
}

if (typeof module !== "undefined") module.exports = {LABELS, mark, toCSV, setField, restoreState, fillRows, missing, keyAction};
