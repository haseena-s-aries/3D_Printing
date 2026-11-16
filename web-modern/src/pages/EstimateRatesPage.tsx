/**
 * Aries' rates for manufacturing cost estimates (decision of 16 Nov 2026): currency, machine-hour and labour rates,
 * fallback material prices, fixed extras, overhead, margin and the uncertainty range. The Aries Admin or Manager edits
 * them; other Aries staff read them. Every estimate keeps a copy of the rates it used, so a change applies to new
 * estimates only.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { ErrorNotice, Loading, Notice, PageHeader } from "../components/ui";

type Rates = {
  currency: string; machine_rates: Record<string, number>; labour_rates: Record<string, number>; material_prices: Record<string, number>;
  default_material_price: number; heat_treatment_per_batch: number; ndt_per_part: number; shipping_per_order: number;
  oem_shipping_per_order: number; overhead_pct: number; margin_pct: number; uncertainty_pct: number;
};
type Data = { rates: Rates; can_edit: boolean; roles: Record<string, string>; machines: Record<string, string> };

const SINGLE: [keyof Rates, string, string][] = [
  ["default_material_price", "Default material price per kg", "Used when no web price and no listed material matches"],
  ["heat_treatment_per_batch", "Heat treatment per order", ""], ["ndt_per_part", "NDT per part", ""],
  ["shipping_per_order", "Shipping per order (made by Aries)", ""], ["oem_shipping_per_order", "Shipping per order (OEM purchase)", ""],
  ["overhead_pct", "Overhead %", "Added to the direct cost"], ["margin_pct", "Margin %", "Added after overhead"],
  ["uncertainty_pct", "Range ±%", "The estimate is shown as a range: total − x % to total + x %"],
];

export default function EstimateRatesPage() {
  const d = useApi<Data>("/operator/estimate-rates/");
  const [r, setR] = useState<Rates | null>(null);
  const [newMaterial, setNewMaterial] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  useEffect(() => { if (d.data) setR(d.data.rates); }, [d.data]);
  const edit = !!d.data?.can_edit;

  async function save() {
    if (!r) return;
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const res = await api<{ rates: Rates }>("/operator/estimate-rates/", { method: "PUT", body: { rates: r } });
      setR(res.rates);
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  const num = (value: number, onChange: (n: number) => void, label: string) => (
    <input type="number" min={0} step="0.01" aria-label={label} disabled={!edit} value={value} onChange={(e) => onChange(Number(e.target.value || 0))} />
  );
  const group = (key: "machine_rates" | "labour_rates", names: Record<string, string>, unit: string) => r && (
    <dl className="rates-grid">
      {Object.entries(names).map(([k, l]) => (
        <div key={k}><dt>{l} <span className="muted small">{unit}</span></dt>
          <dd>{num(r[key][k] ?? 0, (n) => setR({ ...r, [key]: { ...r[key], [k]: n } }), `${l} ${unit}`)}</dd></div>
      ))}
    </dl>
  );

  return (
    <>
      <PageHeader title="Estimate rates" subtitle="Aries' rates for manufacturing cost estimates. A change applies to new estimates; earlier estimates keep the rates they used." />
      <ErrorNotice error={d.error ?? error} />
      {done && <Notice kind="success">Rates saved. New estimates use them.</Notice>}
      {!edit && d.data && <Notice>Only an Aries Admin or Manager can change the rates.</Notice>}
      {d.loading && !r ? <Loading /> : r && d.data && (
        <form onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <div className="card">
            <h2>Currency</h2>
            <label className="field"><span>Currency (3 letters, e.g. USD, INR, AED)</span>
              <input maxLength={3} disabled={!edit} value={r.currency} onChange={(e) => setR({ ...r, currency: e.target.value.toUpperCase() })} /></label>
            <p className="muted small">Web prices are requested in this currency.</p>
          </div>
          <div className="grid-2">
            <div className="card"><h2>Machine rates</h2>{group("machine_rates", d.data.machines, `${r.currency}/h`)}</div>
            <div className="card"><h2>Labour rates</h2>{group("labour_rates", d.data.roles, `${r.currency}/h`)}</div>
          </div>
          <div className="card">
            <h2>Material prices per kg</h2>
            <p className="muted small">Used when the web search finds no price. The name must match the material Gemini names (e.g. "stainless steel bar").</p>
            <dl className="rates-grid">
              {Object.entries(r.material_prices).map(([k, v]) => (
                <div key={k}><dt>{k} {edit && <button type="button" className="link-btn small" onClick={() => {
                  const next = { ...r.material_prices }; delete next[k]; setR({ ...r, material_prices: next });
                }}>Remove</button>}</dt>
                  <dd>{num(v, (n) => setR({ ...r, material_prices: { ...r.material_prices, [k]: n } }), `${k} per kg`)}</dd></div>
              ))}
            </dl>
            {edit && (
              <div className="toolbar">
                <input placeholder="Material name" aria-label="New material name" value={newMaterial} onChange={(e) => setNewMaterial(e.target.value)} />
                <button type="button" className="btn btn-small" disabled={!newMaterial.trim()} onClick={() => {
                  setR({ ...r, material_prices: { ...r.material_prices, [newMaterial.trim()]: 0 } }); setNewMaterial("");
                }}>Add material</button>
              </div>
            )}
          </div>
          <div className="card">
            <h2>Extras, overhead and margin</h2>
            <dl className="rates-grid">
              {SINGLE.map(([k, l, hint]) => (
                <div key={k}><dt>{l}{hint && <span className="muted small"> · {hint}</span>}</dt>
                  <dd>{num(r[k] as number, (n) => setR({ ...r, [k]: n }), l)}</dd></div>
              ))}
            </dl>
          </div>
          {edit && <div className="form-actions"><button className="btn btn-primary" disabled={busy} aria-busy={busy}>{busy ? "Saving…" : "Save rates"}</button></div>}
        </form>
      )}
    </>
  );
}
