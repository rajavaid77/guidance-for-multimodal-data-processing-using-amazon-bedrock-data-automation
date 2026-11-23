import { Files, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Card, Empty } from "../components/Card";
import { Badge, PROCESSING, money, shortId, when } from "../components/Status";
import type { ClaimSummary } from "../types";

const FILTERS: [string, (s: string) => boolean][] = [
  ["All", () => true],
  ["In progress", (s) => PROCESSING.has(s) || s === "PENDING_REVIEW"],
  ["Approved", (s) => s === "APPROVED"],
  ["Info requested", (s) => s === "PENDED_INFO_REQUESTED"],
  ["Denied", (s) => s === "DENIED"],
  ["Failed", (s) => s === "FAILED"],
];

export default function MyClaims() {
  const [claims, setClaims] = useState<ClaimSummary[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("All");
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const load = () => {
    setClaims(null);
    api<{ claims: ClaimSummary[] }>("/claims").then((r) => setClaims(r.claims)).catch((e) => setError(e.message));
  };
  useEffect(load, []);
  const rows = useMemo(() => {
    const test = FILTERS.find(([n]) => n === filter)![1];
    const needle = q.trim().toLowerCase();
    return (claims ?? []).filter((c) => test(c.status) &&
      (!needle || c.claim_id.toLowerCase().includes(needle) || (c.patient_name ?? "").toLowerCase().includes(needle)));
  }, [claims, filter, q]);

  return (
    <>
      <div className="page-head">
        <div><h1>My Claims</h1><p>Track every claim from submission to decision.</p></div>
        <button className="btn ghost" onClick={load}><RefreshCw size={16} /> Refresh</button>
      </div>
      <Card title="Claims" hint={claims ? `${rows.length} shown` : undefined}>
        <div className="card-body">
          <div className="row between wrap" style={{ marginBottom: 18 }}>
            <div className="tabs" role="tablist">
              {FILTERS.map(([name]) => (
                <button key={name} role="tab" aria-selected={filter === name} className={filter === name ? "on" : ""}
                        onClick={() => setFilter(name)}>{name}</button>
              ))}
            </div>
            <label className="row" style={{ minWidth: 280 }}>
              <Search size={18} className="muted" />
              <input className="input" placeholder="Search claim or patient" value={q} onChange={(e) => setQ(e.target.value)} />
            </label>
          </div>
          {error && <div className="banner bad">{error}</div>}
          {claims === null ? <p className="muted">Loading…</p> : rows.length === 0 ? (
            <Empty icon={Files}>No claims match. <Link to="/provider/new">Submit a claim</Link>.</Empty>
          ) : (
            <table className="table">
              <thead><tr><th>Claim</th><th>Patient</th><th className="num">Total</th><th>Status</th><th>Submitted</th><th>Updated</th></tr></thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.claim_id} className="click" onClick={() => navigate(`/provider/claims/${c.claim_id}`)}>
                    <td><Link to={`/provider/claims/${c.claim_id}`}>{shortId(c.claim_id)}</Link></td>
                    <td>{c.patient_name ?? "—"}</td>
                    <td className="num">{money(c.total_charges)}</td>
                    <td><Badge value={c.status} /></td>
                    <td>{when(c.created_at)}</td>
                    <td>{when(c.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>
    </>
  );
}
