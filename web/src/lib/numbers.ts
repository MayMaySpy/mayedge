/** Trader-typed decimal. Last `,` or `.` is the decimal; the other is grouping. */

export function decimalInput(raw: string): string {
  return raw.replace(/[^\d.,]/g, "");
}

/** Digits and a dot only, for a basis-point field. */
export function bpInput(raw: string): string {
  return raw.replace(/[^\d.]/g, "");
}

export function canonicalDecimal(raw: string): string | null {
  let s = raw.trim().replace(/[\s\u00a0\u202f]/g, "");
  if (!s) return null;
  const sign = s[0] === "+" || s[0] === "-" ? s[0] : "";
  if (sign) s = s.slice(1);
  if (!s) return null;

  const lastComma = s.lastIndexOf(",");
  const lastDot = s.lastIndexOf(".");
  if (lastComma >= 0 && lastDot >= 0) {
    s = lastComma > lastDot ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
  } else if (lastComma >= 0) {
    const i = lastComma;
    s = s.slice(0, i).replace(/,/g, "") + "." + s.slice(i + 1);
  }
  if (!/^\d+(\.\d+)?$/.test(s)) return null;
  return sign === "-" ? `-${s}` : s;
}

/** Drop fractional trailing zeros. `110` stays `110`; `1.50` becomes `1.5`. */
export function stripFractionalZeros(s: string): string {
  if (!s.includes(".")) return s;
  return s.replace(/0+$/, "").replace(/\.$/, "") || "0";
}

export function parseDecimal(raw: string): number | null {
  const s = canonicalDecimal(raw);
  if (s == null) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}
