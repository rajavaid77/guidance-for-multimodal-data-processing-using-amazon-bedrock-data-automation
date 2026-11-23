import { CircleAlert, CircleCheck, FilePlus2, Files, Hourglass, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Card, Empty } from "../components/Card";
import { Badge, PROCESSING, money, shortId, when } from "../components/Status";
import type { ClaimSummary } from "../types";

export default function ProviderDashboard() {
  const [claims, setClaims] = useState<ClaimSummary[] | null>(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  useEffect(() => {
    api<{ claims: ClaimSummary[] }>("/claims").then((r) => setClaims(r.claims)).catch((e) => setError(e.message));
  }, []);

  const count = (pred: (c: ClaimSummary) => boolean) => (claims ?? []).filter(pred).length;
  const stats = [
    { label: "Claims submitted", value: count(() => true), icon: Files, to: "/provider/claims" },
    { label: "In processing", value: count((c) => PROCESSING.has(c.status)), icon: LoaderCircle },
    { label: "With examiner", value: count((c) => c.status === "PENDING_REVIEW"), icon: Hourglass },
    { label: "Approved", value: count((c) => c.status === "APPROVED"), icon: CircleCheck },
    { label: "Need your attention", value: count((c) => ["DENIED", "PENDED_INFO_REQUESTED", "FAILED"].includes(c.status)), icon: CircleAlert },
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p>Your organization's claims at a glance.</p>
        </div>
        <Link className="btn" to="/provider/new"><FilePlus2 size={18} /> Submit a claim</Link>
      </div>
      {error && <div className="banner bad">{error}</div>}
      <div className="stats">
        {stats.map((s) => (
          <div className="stat" key={s.label}>
            <div className="label"><s.icon size={18} /> {s.label}</div>
            <div className="value">{claims === null ? "–" : s.value.toLocaleString()}</div>
          </div>
        ))}
      </div>
      <Card title="Recent claims" hint={claims ? `${Math.min(claims.length, 8)} of ${claims.length}` : undefined}
            right={<Link to="/provider/claims" style={{ paddingBottom: 18 }}>View all</Link>}>
        <div className="card-body">
          {claims === null ? (
            <p className="muted">Loading…</p>
          ) : claims.length === 0 ? (
            <Empty icon={Files}>No claims yet. <Link to="/provider/new">Submit your first claim</Link>.</Empty>
          ) : (
            <table className="table">
              <thead><tr><th>Claim</th><th>Patient</th><th className="num">Total</th><th>Status</th><th>Submitted</th></tr></thead>
              <tbody>
                {claims.slice(0, 8).map((c) => (
                  <tr key={c.claim_id} className="click" onClick={() => navigate(`/provider/claims/${c.claim_id}`)}>
                    <td><Link to={`/provider/claims/${c.claim_id}`}>{shortId(c.claim_id)}</Link></td>
                    <td>{c.patient_name ?? "—"}</td>
                    <td className="num">{money(c.total_charges)}</td>
                    <td><Badge value={c.status} /></td>
                    <td>{when(c.created_at)}</td>
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
