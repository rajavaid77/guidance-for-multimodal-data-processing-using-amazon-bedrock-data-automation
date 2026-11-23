import { ArrowLeft, Banknote, CalendarDays, ClipboardList, FileText, Gavel, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Card, SectionTitle } from "../components/Card";
import { ClaimPipeline } from "../components/Stepper";
import { Badge, PROCESSING, money, when } from "../components/Status";
import type { LineDecision, ServiceLine } from "../types";

interface Detail {
  claim: { claim_id: string; status: string; patient_name: string | null; total_charges: number | null;
           final_decision: string | null; created_at: string; updated_at: string; failure_reason?: string };
  documents: { file_name: string; declared_type: string; detected_type: string | null }[];
  service_lines: ServiceLine[];
  decision: { decision: string; reason: string; line_decisions: LineDecision[] | string; created_at: string } | null;
}

export default function ClaimDetail() {
  const { claimId = "" } = useParams();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let timer: number | undefined;
    const load = () =>
      api<Detail>(`/claims/${claimId}`)
        .then((d) => {
          setDetail(d);
          if (PROCESSING.has(d.claim.status) || d.claim.status === "PENDING_REVIEW") timer = window.setTimeout(load, 10000);
        })
        .catch((e) => setError(e.message));
    load();
    return () => window.clearTimeout(timer);
  }, [claimId]);

  if (error) return <div className="banner bad">{error}</div>;
  if (!detail) return <p className="muted">Loading…</p>;
  const { claim, documents, service_lines, decision } = detail;
  const lineDecisions: LineDecision[] =
    typeof decision?.line_decisions === "string" ? JSON.parse(decision.line_decisions) : decision?.line_decisions ?? [];

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/provider/claims" className="row small"><ArrowLeft size={14} /> My Claims</Link>
          <h1 style={{ marginTop: 6 }}>Claim {claim.claim_id}</h1>
        </div>
        <Badge value={claim.status} />
      </div>
      <ClaimPipeline status={claim.status} />
      {claim.failure_reason && <div className="banner bad" style={{ marginBottom: 20 }}>{claim.failure_reason}</div>}

      <Card title="Claim Summary" hint={PROCESSING.has(claim.status) ? "(updates automatically)" : undefined}>
        <div className="card-body grid-3">
          <div>
            <SectionTitle icon={UserRound} title="Patient" />
            <dl className="kv"><dt>Name</dt><dd>{claim.patient_name ?? "—"}</dd></dl>
          </div>
          <div>
            <SectionTitle icon={Banknote} title="Charges" />
            <dl className="kv"><dt>Total billed</dt><dd>{money(claim.total_charges)}</dd><dt>Lines</dt><dd>{service_lines.length}</dd></dl>
          </div>
          <div>
            <SectionTitle icon={CalendarDays} title="Timeline" />
            <dl className="kv"><dt>Submitted</dt><dd>{when(claim.created_at)}</dd><dt>Updated</dt><dd>{when(claim.updated_at)}</dd></dl>
          </div>
        </div>
        <hr className="divider" />
        <div className="card-body">
          <SectionTitle icon={Gavel} title="Decision" />
          {decision ? (
            <div className="stack">
              <div className="row"><Badge value={decision.decision} /><span className="muted small">{when(decision.created_at)}</span></div>
              <p style={{ margin: 0 }}>{decision.reason}</p>
            </div>
          ) : (
            <p className="muted" style={{ margin: 0 }}>No decision yet.</p>
          )}
        </div>
        <hr className="divider" />
        <div className="card-body">
          <SectionTitle icon={ClipboardList} title="Service Lines" count={service_lines.length} />
          {service_lines.length === 0 ? <p className="muted">Lines appear once the claim form has been read.</p> : (
            <table className="table">
              <thead><tr><th>#</th><th>Date</th><th>Code</th><th className="num">Charge</th><th>Decision</th><th>Reason</th></tr></thead>
              <tbody>
                {service_lines.map((l) => {
                  const d = lineDecisions.find((x) => x.line_number === l.line_number);
                  return (
                    <tr key={l.line_number}>
                      <td>{l.line_number}</td><td>{l.service_start_date ?? "—"}</td><td>{l.procedure_code ?? "—"}</td>
                      <td className="num">{money(l.charge_amount)}</td><td><Badge value={d?.decision} /></td>
                      <td className="small">{d ? [d.carc && `CARC ${d.carc}`, d.rarc && `RARC ${d.rarc}`, d.reason].filter(Boolean).join(" · ") : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        <hr className="divider" />
        <div className="card-body">
          <SectionTitle icon={FileText} title="Documents" count={documents.length} />
          <div className="chips">
            {documents.map((d) => (
              <span className="pill neutral" key={d.file_name}><FileText size={13} /> {d.file_name} · {(d.detected_type ?? d.declared_type).replaceAll("_", " ").toLowerCase()}</span>
            ))}
          </div>
        </div>
      </Card>
    </>
  );
}
