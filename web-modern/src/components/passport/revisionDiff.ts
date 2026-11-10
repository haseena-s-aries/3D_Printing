/** Field-level comparison of two revision contents (BR-034: "who changed what and when"). */
export interface FieldChange {
  key: string;
  before: string;
  after: string;
}

function flatten(value: unknown, prefix: string, out: Record<string, string>) {
  if (value === null || value === undefined || value === "") return;
  if (Array.isArray(value)) {
    if (value.length) out[prefix] = value.map((v) => (typeof v === "object" ? Object.values(v as object).filter(Boolean).join(" ") : String(v))).join("; ");
    return;
  }
  if (typeof value === "object") {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) flatten(v, prefix ? `${prefix}.${k}` : k, out);
    return;
  }
  out[prefix] = typeof value === "boolean" ? (value ? "Yes" : "No") : String(value);
}

export function flattenContent(content: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  flatten(content ?? {}, "", out);
  return out;
}

export function diffContent(before: unknown, after: unknown): FieldChange[] {
  const a = flattenContent(before);
  const b = flattenContent(after);
  return [...new Set([...Object.keys(a), ...Object.keys(b)])]
    .filter((k) => a[k] !== b[k])
    .sort()
    .map((key) => ({ key, before: a[key] ?? "", after: b[key] ?? "" }));
}
