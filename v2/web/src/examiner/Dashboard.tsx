import { CircleAlert, CircleCheck, CircleX, Hourglass, Inbox, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Card, Empty } from "../components/Card";
import { Badge, money, shortId, when } from "../components/Status";
import type { ReviewRow } from "./ReviewQueue";

const TILES = [
  { status: "PENDING_REVIEW", label: "Awaiting your review", icon: Hourglass },
  { status: "APPROVED", label: "Approved", icon: CircleCheck },
  { status: "PENDED_INFO_REQUESTED", label: "Info requested", icon: CircleAlert },
  { status: "DENIED", label: "Denied", icon: CircleX },
  { status: "FAILED", label: "Failed processing", icon: TriangleAlert },
];

export default function ExaminerDashboard() {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [queue, setQueue] = useState<ReviewRow[] | null>(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    Promise.all(TILES.map((t) => api<{ reviews: ReviewRow[] }>(`/reviews?status=${t.status}`).then((r) => [t.status, r.reviews] as const)))
      .then((res) => {
        setCounts(Object.fromEntries(res.map(([s, rows]) => [s, rows.length])));
        setQueue(res.find(([s]) => s === "PENDING_REVIEW")?.[1] ?? []);
      })
      .catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <div className="page-head">
        <div><h1>Dashboard</h1><p>Claims routed to people by the AI review, oldest first.</p></div>
        <Link className="btn" to="/examiner/reviews"><Inbox size={18} /> Open review queue</Link>
      </div>
      {error && <div className="banner bad">{error}</div>}
      <div className="stats">
        {TILES.map((t) => (
          <div className="stat" key={t.status}>
            <div className="label"><t.icon size={18} /> {t.label}</div>
            <div className="value">{counts[t.status] === undefined ? "–" : counts[t.status].toLocaleString()}</div>
            <Link to={`/examiner/reviews?status=${t.status}`}>View</Link>
          </div>
        ))}
      </div>
      <Card title="Next up" hint="(oldest first)">
        <div className="card-body">
          {queue === null ? <p className="muted">Loading…</p> : queue.length === 0 ? (
            <Empty icon={Inbox}>Nothing waiting. Clean approvals are finalized automatically.</Empty>
          ) : (
            <table className="table">
              <thead><tr><th>Claim</th><th>Provider</th><th>Patient</th><th className="num">Total</th><th>AI recommendation</th><th>Waiting since</th></tr></thead>
              <tbody>
                {queue.slice(0, 8).map((r) => (
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
