import { Inbox, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Card, Empty } from "../components/Card";
import { Badge, money, shortId, when } from "../components/Status";

export interface ReviewRow {
  claim_id: string;
  status: string;
  patient_name: string | null;
  provider_name: string;
  total_charges: number | null;
  agent_decision: string | null;
  agent_confidence: number | null;
  updated_at: string;
}
const TABS: [string, string][] = [
  ["PENDING_REVIEW", "Awaiting review"], ["APPROVED", "Approved"], ["PENDED_INFO_REQUESTED", "Info requested"],
  ["DENIED", "Denied"], ["FAILED", "Failed"], ["AGENT_REVIEW", "In AI review"],
];

export default function ReviewQueue() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "PENDING_REVIEW";
  const [rows, setRows] = useState<ReviewRow[] | null>(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const load = () => {
    setRows(null);
    api<{ reviews: ReviewRow[] }>(`/reviews?status=${status}`).then((r) => setRows(r.reviews)).catch((e) => setError(e.message));
  };
  useEffect(load, [status]);
  const decided = status !== "PENDING_REVIEW" && status !== "AGENT_REVIEW";

  return (
    <>
      <div className="page-head">
        <div><h1>{decided ? "Decided Claims" : "Review Queue"}</h1><p>{decided ? "Finalized and failed claims." : "Claims the AI routed to a person."}</p></div>
        <button className="btn ghost" onClick={load}><RefreshCw size={16} /> Refresh</button>
      </div>
      <Card title={TABS.find(([s]) => s === status)?.[1] ?? status} hint={rows ? `${rows.length} claims` : undefined}>
        <div className="card-body">
          <div className="tabs" role="tablist" style={{ marginBottom: 18 }}>
            {TABS.map(([s, label]) => (
              <button key={s} role="tab" aria-selected={s === status} className={s === status ? "on" : ""} onClick={() => setParams({ status: s })}>{label}</button>
            ))}
          </div>
          {error && <div className="banner bad">{error}</div>}
          {rows === null ? <p className="muted">Loading…</p> : rows.length === 0 ? <Empty icon={Inbox}>Nothing here.</Empty> : (
            <table className="table">
              <thead><tr><th>Claim</th><th>Provider</th><th>Patient</th><th className="num">Total</th><th>AI recommendation</th><th>Updated</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.claim_id} className="click" onClick={() => navigate(`/examiner/reviews/${r.claim_id}`)}>
                    <td><Link to={`/examiner/reviews/${r.claim_id}`}>{shortId(r.claim_id)}</Link></td>
                    <td>{r.provider_name}</td><td>{r.patient_name ?? "—"}</td><td className="num">{money(r.total_charges)}</td>
                    <td><span className="row"><Badge value={r.agent_decision} />
                      {r.agent_confidence !== null && <span className="muted small">{Math.round(Number(r.agent_confidence) * 100)}%</span>}</span></td>
                    <td>{when(r.updated_at)}</td>
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
