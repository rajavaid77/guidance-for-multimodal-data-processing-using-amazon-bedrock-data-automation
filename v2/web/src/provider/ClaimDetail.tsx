import { ArrowLeft, Banknote, CalendarDays, ClipboardList, Eye, FileText, Gavel, Plus, UserRound } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Card, SectionTitle } from "../components/Card";
import { ClaimPipeline } from "../components/Stepper";
import { DocumentViewer } from "../components/DocumentViewer";
import { Modal } from "../components/Modal";
import { BATCH_ACTIVE, BatchBadge, Badge, PROCESSING, money, when } from "../components/Status";
import type { ClaimDocument, DocumentBatch, LineDecision, ServiceLine } from "../types";
import { AddDocuments } from "./AddDocuments";

interface Detail {
  claim: { claim_id: string; status: string; patient_name: string | null; total_charges: number | null;
           final_decision: string | null; created_at: string; updated_at: string; failure_reason?: string };
  documents: ClaimDocument[];
  batches: DocumentBatch[];
  can_add_documents: boolean;
  service_lines: ServiceLine[];
  decision: { decision: string; reason: string; line_decisions: LineDecision[] | string; created_at: string } | null;
}

const TYPE_LABELS: Record<string, string> = {
  CMS1500: "CMS-1500 claim form", MEDICAL_RECORD: "Medical record", LAB_REPORT: "Lab or imaging report",
  PRIMARY_EOB: "Primary payer EOB", DISCHARGE_SUMMARY: "Discharge summary", INSURANCE_CARD: "Insurance card",
  PRESCRIPTION_LABEL: "Prescription label", DRIVER_LICENSE: "Driver license", INVOICE: "Invoice",
  OTHER: "Other document", PACK: "Multi-document pack",
};
const typeLabel = (t: string) => (t === "AUTO" ? "—" : TYPE_LABELS[t] ?? t.replaceAll("_", " ").toLowerCase());

export default function ClaimDetail() {
  const { claimId = "" } = useParams();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [viewing, setViewing] = useState<ClaimDocument | null>(null);
  const [adding, setAdding] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const load = useCallback(() => {
    window.clearTimeout(timer.current);
    return api<Detail>(`/claims/${claimId}`)
      .then((d) => {
        setDetail(d);
        const active =
          PROCESSING.has(d.claim.status) ||
          (d.batches ?? []).some((b) => BATCH_ACTIVE.has(b.stage)) ||
          d.documents.some((x) => x.status === "PROCESSING");
        const delay = active ? 5000 : d.claim.status === "PENDING_REVIEW" ? 15000 : 0;
        if (delay) timer.current = window.setTimeout(() => { if (!document.hidden) load(); }, delay);
      })
      .catch((e) => setError(e.message));
  }, [claimId]);
  useEffect(() => {
    load();
    const onVisible = () => { if (!document.hidden) load(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearTimeout(timer.current);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);
  if (error) return <div className="banner bad">{error}</div>;
  if (!detail) return <p className="muted">Loading…</p>;
  const { claim, documents, service_lines, decision } = detail;
  const batches = detail.batches ?? [];
  const activeBatch = batches.find((b) => BATCH_ACTIVE.has(b.stage));
  const failedBatch = !activeBatch && batches[0]?.stage === "FAILED" ? batches[0] : undefined;
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
          <div className="row between" style={{ marginBottom: 8 }}>
            <SectionTitle icon={FileText} title="Documents" count={documents.filter((d) => d.kind !== "PART" || !documents.some((x) => x.kind === "PACK" && x.document_id === d.document_id)).length} />
            {detail.can_add_documents && (
              <div className="row">
                {claim.status === "PENDED_INFO_REQUESTED" && decision?.reason && (
                  <span className="small" style={{ maxWidth: 420 }}>Requested: {decision.reason}</span>
                )}
                <button className="btn ghost" onClick={() => setAdding(true)}><Plus size={16} /> Add documents</button>
              </div>
            )}
          </div>
          {activeBatch && (
            <div className="banner info" role="status" style={{ marginBottom: 12 }}>
              <span>
                {activeBatch.document_count} additional {activeBatch.document_count === 1 ? "file" : "files"} being processed:{" "}
                <BatchBadge stage={activeBatch.stage} />
              </span>
            </div>
          )}
          {failedBatch && (
            <div className="banner bad" style={{ marginBottom: 12 }}>
              The last set of additional documents could not be processed. Please upload them again.
            </div>
          )}
          {documents.length === 0 ? <p className="muted">No documents yet.</p> : (
            <table className="table">
              <thead><tr><th>Name</th><th>Type</th><th>Pages</th><th>Added</th><th>Status</th><th>View</th></tr></thead>
              <tbody>
                {documents.map((d) => {
                  const isPack = d.kind === "PACK";
                  const isChild = d.kind === "PART" && documents.some((x) => x.kind === "PACK" && x.document_id === d.document_id);
                  const type = isPack ? "Multi-document pack" : typeLabel(d.document_class ?? d.declared_type);
                  const pages = d.page_start
                    ? d.page_end && d.page_end !== d.page_start ? `${d.page_start}-${d.page_end}` : `${d.page_start}`
                    : "—";
                  const canView = d.part_id !== null && d.status === "READY";
                  return (
                    <tr key={d.part_id ?? `doc-${d.document_id}`} className={isChild ? "sub-row" : isPack ? "pack-row" : undefined}>
                      <td>
                        {isChild && <span className="muted" aria-hidden="true">↳ </span>}
                        {d.name}
                        {!isPack && !isChild && d.source_file_name !== d.name && <div className="muted small">from {d.source_file_name}</div>}
                      </td>
                      <td>{type}</td>
                      <td>{pages}</td>
                      <td>{isChild ? "" : d.origin === "ADDITIONAL" ? "Added later" : "Initial"}</td>
                      <td>{isChild ? "" : <Badge value={d.status} />}</td>
                      <td>
                        <button className="btn ghost small-btn" disabled={!canView} onClick={() => setViewing(d)}
                                aria-label={isPack ? `View all pages of ${d.name}` : `View ${d.name}`}
                                title={canView ? undefined : d.status === "FAILED" ? "This document could not be processed" : "Available once the document has been read"}>
                          <Eye size={14} /> {isPack ? "View all" : "View"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </Card>
      {viewing && viewing.part_id !== null && (
        <Modal title={viewing.name} wide onClose={() => setViewing(null)}>
          <DocumentViewer claimId={claim.claim_id} partId={viewing.part_id} name={viewing.name} />
        </Modal>
      )}
      {adding && <AddDocuments claimId={claim.claim_id} onClose={() => setAdding(false)} onDone={() => { setAdding(false); void load(); }} />}
    </>
  );
}
