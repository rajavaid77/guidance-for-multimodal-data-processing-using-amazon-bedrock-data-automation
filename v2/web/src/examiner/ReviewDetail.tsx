import { ArrowLeft, ClipboardList, FileSearch, FileText, Gavel, History, ListChecks, LoaderCircle, ScanText } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { Card, SectionTitle } from "../components/Card";
import { ClaimPipeline } from "../components/Stepper";
import { Badge, money, when } from "../components/Status";
import { RecommendationPanel } from "../components/RecommendationPanel";
import type { Decision, Extraction, Finding, LineDecision, Recommendation, ServiceLine } from "../types";

interface Package {
  claim: {
    claim_id: string; status: string; patient_name: string | null; insured_id_number: string | null;
    total_charges: number | null; agent_decision: string | null; agent_confidence: number | null;
    provider_name: string; provider_npi: string; failure_reason: string | null;
  };
  documents: { document_id: number; file_name: string; content_type: string; declared_type: string;
               detected_type: string | null; view_url: string }[];
  extractions: Extraction[];
  service_lines: ServiceLine[];
  recommendation: Recommendation | null;
  decisions: { decided_by: string; actor: string; decision: string; reason: string; created_at: string }[];
}

const LOW = 0.8;
const CATEGORY_ORDER = ["VALIDATION", "ELIGIBILITY", "CLINICAL", "ADJUDICATION"];
const SEVERITY_ORDER: Record<string, number> = { ERROR: 0, WARNING: 1, INFO: 2 };

export default function ReviewDetail() {
  const { claimId = "" } = useParams();
  const navigate = useNavigate();
  const [pkg, setPkg] = useState<Package | null>(null);
  const [error, setError] = useState("");
  const [viewer, setViewer] = useState<string | null>(null);
  const [decision, setDecision] = useState<Decision>("APPROVE");
  const [reason, setReason] = useState("");
  const [lines, setLines] = useState<LineDecision[]>([]);
  const [busy, setBusy] = useState(false);
  const [category, setCategory] = useState("ALL");
  const [showEmpty, setShowEmpty] = useState(false);

  useEffect(() => {
    api<Package>(`/reviews/${claimId}`)
      .then((p) => {
        setPkg(p);
        if (p.recommendation) {
          setDecision(p.recommendation.decision);
          setLines(p.recommendation.line_decisions);
        }
        setViewer(p.documents[0]?.view_url ?? null);
      })
      .catch((e) => setError(e.message));
  }, [claimId]);

  const fieldsByClass = useMemo(() => {
    const out: Record<string, Extraction[]> = {};
    for (const x of pkg?.extractions ?? []) (out[x.document_class] ??= []).push(x);
    return out;
  }, [pkg]);
  const findings = useMemo(() => {
    const all = [...(pkg?.recommendation?.findings ?? [])].sort(
      (a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3) || CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category),
    );
    return category === "ALL" ? all : all.filter((f) => f.category === category);
  }, [pkg, category]);

  if (error && !pkg) return <div className="banner bad">{error}</div>;
  if (!pkg) return <p className="muted">Loading…</p>;
  const { claim, recommendation: rec } = pkg;
  const canDecide = claim.status === "PENDING_REVIEW";
  const lowCount = pkg.extractions.filter((x) => x.confidence !== null && x.confidence < LOW).length;

  const setLine = (n: number, patch: Partial<LineDecision>) =>
    setLines((ls) =>
      ls.some((l) => l.line_number === n)
        ? ls.map((l) => (l.line_number === n ? { ...l, ...patch } : l))
        : [...ls, { line_number: n, decision: "PEND", reason: "", ...patch }],
    );

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(`/reviews/${claimId}/decision`, { method: "POST", body: { decision, reason, line_decisions: lines } });
      navigate("/examiner/reviews");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/examiner/reviews" className="row small"><ArrowLeft size={14} /> Review Queue</Link>
          <h1 style={{ marginTop: 6 }}>Claim {claim.claim_id}</h1>
          <p>{claim.provider_name} · NPI {claim.provider_npi} · {claim.patient_name ?? "patient unknown"} · insured {claim.insured_id_number ?? "—"} · {money(claim.total_charges)}</p>
        </div>
        <Badge value={claim.status} />
      </div>
      <ClaimPipeline status={claim.status} failedAt={rec ? 3 : 1} />
      {claim.failure_reason && <div className="banner bad" style={{ marginBottom: 20 }}>{claim.failure_reason}</div>}

      <div className="review-grid">
        <div>
          <Card title="Evidence" hint={`(${pkg.documents.length} documents)`}>
            <div className="card-body stack">
              <div className="doc-list">
                {pkg.documents.map((d) => (
                  <button key={d.document_id} className={`doc-btn ${viewer === d.view_url ? "on" : ""}`} onClick={() => setViewer(d.view_url)}>
                    <FileText size={20} />
                    <span style={{ flex: 1 }}>{d.file_name}</span>
                    <span className="muted small">{(d.detected_type ?? d.declared_type).replaceAll("_", " ").toLowerCase()}</span>
                  </button>
                ))}
              </div>
              {viewer && <iframe title="Selected document" src={viewer} className="viewer" referrerPolicy="no-referrer" />}
              <span className="muted small">Document links expire after 5 minutes; reload to refresh.</span>
            </div>
          </Card>
          <Card title="Extracted Fields" hint={lowCount ? `(${lowCount} low confidence)` : undefined}
                right={<label className="row small muted" style={{ paddingBottom: 18 }}>
                  <input type="checkbox" checked={showEmpty} onChange={(e) => setShowEmpty(e.target.checked)} /> Show empty fields</label>}>
            <div className="card-body scroll-card">
              {Object.entries(fieldsByClass).map(([cls, fields]) => (
                <details key={cls} open={cls === "CMS1500"}>
                  <summary><span className="row"><ScanText size={18} className="muted" /> {cls.replaceAll("_", " ")} <span className="muted small">({fields.filter((f) => f.field_value !== null && f.field_value !== "").length} filled)</span></span></summary>
                  <table className="table compact">
                    <tbody>
                      {fields.filter((f) => showEmpty || (f.field_value !== null && f.field_value !== "")).map((f) => {
                        const low = f.confidence !== null && f.confidence < LOW;
                        return (
                          <tr key={`${cls}-${f.field_name}`} className={low ? "low" : ""}>
                            <td>{f.field_name.replaceAll("_", " ")}</td>
                            <td>{f.field_value ?? "—"}</td>
                            <td className="num">{f.confidence === null ? "" : `${Math.round(f.confidence * 100)}%${low ? " ⚠" : ""}`}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </details>
              ))}
            </div>
          </Card>
        </div>

        <div>
          <Card title="AI Recommendation" right={rec ? <span style={{ paddingBottom: 18 }}><Badge value={rec.decision} /></span> : undefined}>
            <div className="card-body stack">
              {!rec ? <p className="muted">No AI recommendation for this claim.</p> : (
                <RecommendationPanel rec={rec} lines={pkg.service_lines} />
              )}
            </div>
            {rec && (
              <>
                <hr className="divider" />
                <div className="card-body scroll-card">
                  <div className="row between wrap">
                    <SectionTitle icon={ListChecks} title="Findings" count={rec.findings.length} />
                    <div className="tabs">
                      {["ALL", ...CATEGORY_ORDER].map((c) => (
                        <button key={c} className={category === c ? "on" : ""} onClick={() => setCategory(c)}>
                          {c === "ALL" ? "All" : c.charAt(0) + c.slice(1).toLowerCase()}
                        </button>
                      ))}
                    </div>
                  </div>
                  {findings.map((f: Finding, i) => (
                    <div className="finding" key={i}>
                      <Badge value={f.severity} />
                      <div>
                        <div><code>{f.code}</code> {f.line_number ? <b>Line {f.line_number}: </b> : null}{f.message}</div>
                        {f.citations.map((c, j) => (
                          <blockquote key={j}>“{c.excerpt}” <span className="muted">— {c.source.split("/").pop()}{c.page ? `, p.${c.page}` : ""}</span></blockquote>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </Card>

        </div>
      </div>
      <Card title="Decision" hint={canDecide ? "(recorded in the audit trail)" : undefined}>
        <form onSubmit={submit}>
          <div className="card-body">
            <SectionTitle icon={ClipboardList} title="Service Lines" count={pkg.service_lines.length} />
            <table className="table">
              <thead><tr><th>#</th><th>Date</th><th>POS</th><th>Code</th><th>Ptr</th><th className="num">Units</th><th className="num">Charge</th><th>Decision</th><th>Reason</th></tr></thead>
              <tbody>
                {pkg.service_lines.map((l) => {
                  const d = lines.find((x) => x.line_number === l.line_number);
                  return (
                    <tr key={l.line_number}>
                      <td>{l.line_number}</td><td>{l.service_start_date ?? "—"}</td><td>{l.place_of_service ?? ""}</td>
                      <td>{l.procedure_code}{l.modifiers ? ` ${l.modifiers}` : ""}</td><td>{l.diagnosis_pointer ?? ""}</td>
                      <td className="num">{l.units ?? ""}</td><td className="num">{money(l.charge_amount)}</td>
                      <td>
                        <select className="input" disabled={!canDecide} value={d?.decision ?? "PEND"} aria-label={`Line ${l.line_number} decision`}
                                onChange={(e) => setLine(l.line_number, { decision: e.target.value as Decision })}>
                          <option value="APPROVE">Approve</option><option value="DENY">Deny</option><option value="PEND">Pend</option>
                        </select>
                      </td>
                      <td style={{ minWidth: 200 }}>
                        <input className="input" disabled={!canDecide} value={d?.reason ?? ""} aria-label={`Line ${l.line_number} reason`}
                               onChange={(e) => setLine(l.line_number, { reason: e.target.value })} />
                        {d?.carc && <div className="muted small" style={{ marginTop: 4 }}>CARC {d.carc}{d.rarc ? ` · RARC ${d.rarc}` : ""}</div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <hr className="divider" />
          <div className="card-body">
            {canDecide ? (
              <div className="grid-2">
                <div>
                  <SectionTitle icon={Gavel} title="Claim Decision" />
                  <div className="radio-row" role="radiogroup" aria-label="Claim decision">
                    {(["APPROVE", "DENY", "PEND"] as Decision[]).map((v) => (
                      <label key={v}><input type="radio" name="decision" checked={decision === v} onChange={() => setDecision(v)} />
                        {v === "APPROVE" ? "Approve" : v === "DENY" ? "Deny" : "Pend – request information"}</label>
                    ))}
                  </div>
                </div>
                <label className="field">
                  <span>Reason</span>
                  <textarea className="input" required minLength={5} value={reason} onChange={(e) => setReason(e.target.value)}
                            placeholder="Why you agree or disagree with the AI recommendation" />
                </label>
              </div>
            ) : <p className="muted" style={{ margin: 0 }}>This claim is not awaiting review.</p>}
            {error && <div className="banner bad" style={{ marginTop: 14 }}>{error}</div>}
          </div>
          {canDecide && (
            <div className="actions">
              <button type="submit" className="btn" disabled={busy || reason.trim().length < 5}>
                {busy ? <><LoaderCircle size={16} className="spin" /> Submitting…</> : "Submit decision"}
              </button>
            </div>
          )}
        </form>
      </Card>

      <Card title="History">
        <div className="card-body">
          <SectionTitle icon={History} title="Decisions" count={pkg.decisions.length} />
          {pkg.decisions.length === 0 ? <p className="muted">No decisions yet.</p> : (
            <table className="table">
              <tbody>
                {pkg.decisions.map((d, i) => (
                  <tr key={i}><td className="small">{when(d.created_at)}</td><td>{d.decided_by.toLowerCase()} · {d.actor}</td>
                    <td><Badge value={d.decision} /></td><td className="small">{d.reason}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted small" style={{ marginTop: 12 }}><FileSearch size={14} /> Models: {rec ? Object.values(rec.models).join(", ") : "—"}</p>
        </div>
      </Card>
    </>
  );
}
