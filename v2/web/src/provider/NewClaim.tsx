import { ArrowLeft, ChevronRight, ClipboardList, FileText, FlaskConical, LoaderCircle, Paperclip, Receipt, ShieldCheck, Stethoscope } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, putFile } from "../api";
import { Card, SectionTitle } from "../components/Card";
import { Stepper, type Step } from "../components/Stepper";
import { AddTile, MAX_BYTES, UploadTile } from "../components/UploadTile";

type EvidenceType = "MEDICAL_RECORD" | "LAB_REPORT" | "PRIMARY_EOB" | "OTHER";
const GROUPS: { type: EvidenceType; title: string; tile: string; icon: typeof Stethoscope; help: string }[] = [
  { type: "MEDICAL_RECORD", title: "Medical Records", tile: "Upload a visit or procedure note", icon: Stethoscope,
    help: "Progress notes, procedure notes, therapy plans of care for each date of service." },
  { type: "LAB_REPORT", title: "Lab & Imaging Reports", tile: "Upload a lab or imaging report", icon: FlaskConical,
    help: "Lab results, X-ray/echo/ECG reports, spirometry and other test results." },
  { type: "PRIMARY_EOB", title: "Primary Payer EOB", tile: "Upload the other payer's EOB", icon: Receipt,
    help: "Required when another plan pays first (item 11d = YES)." },
  { type: "OTHER", title: "Additional Documentation", tile: "Upload a document", icon: Paperclip,
    help: "Invoices for miscellaneous supplies, authorization letters, anything else." },
];
const MAX_EVIDENCE = 9;

interface CreateResponse {
  claim_id: string;
  uploads: { key: string; upload_url: string; content_type: string }[];
}

export default function NewClaim() {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<File | null>(null);
  const [evidence, setEvidence] = useState<{ file: File; type: EvidenceType }[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const all = [...(form ? [{ file: form, type: "CMS1500" as const }] : []), ...evidence];
  const tooBig = all.some((f) => f.file.size > MAX_BYTES);
  const addEvidence = (type: EvidenceType, files: File[]) =>
    setEvidence((ev) => [...ev, ...files.map((file) => ({ file, type }))].slice(0, MAX_EVIDENCE));
  const steps: Step[] = [
    { name: "Claim Form", sub: "(Approx 1 Min)" },
    { name: "Evidence", sub: "(Approx 2 Min)" },
    { name: "Review & Submit", sub: "(Approx 1 Min)" },
  ].map((s, i) => ({ ...s, state: i < step ? "done" : i === step ? "current" : "todo" }));

  async function submit() {
    setError("");
    try {
      setBusy("Creating claim…");
      const created = await api<CreateResponse>("/claims", {
        method: "POST",
        body: { documents: all.map((f) => ({ file_name: f.file.name, content_type: f.file.type || "application/pdf", declared_type: f.type })) },
      });
      for (let i = 0; i < all.length; i++) {
        setBusy(`Uploading ${i + 1} of ${all.length}…`);
        await putFile(created.uploads[i].upload_url, all[i].file, created.uploads[i].content_type);
      }
      setBusy("Submitting…");
      await api(`/claims/${created.claim_id}/submit`, { method: "POST", body: {} });
      navigate(`/provider/claims/${created.claim_id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy("");
    }
  }

  return (
    <>
      <Stepper steps={steps} />
      <Card title={["Upload your Claim Form.", "Add Supporting Evidence.", "Review & Submit."][step]}
            hint={["(Approx 1 Minute)", "(Approx 2 Minutes)", "(Approx 1 Minute)"][step]}>
        {step === 0 && (
          <div className="card-body grid-3">
            <div>
              <SectionTitle icon={FileText} title="CMS-1500 Claim Form" />
              <div className="tiles">
                <UploadTile label="Upload the CMS-1500" file={form} onFile={setForm} onRemove={() => setForm(null)} />
              </div>
            </div>
            <div>
              <SectionTitle icon={ClipboardList} title="Before you upload" />
              <ul className="stack muted" style={{ paddingLeft: 18, margin: 0 }}>
                <li>One claim form per submission (NUCC 02-12 or HCFA-1500).</li>
                <li>Billing NPI (33a), patient DOB (3) and a diagnosis pointer (24E) on every line.</li>
                <li>Telehealth lines use modifier 95 with POS 02 or 10.</li>
              </ul>
            </div>
            <div>
              <SectionTitle icon={ShieldCheck} title="What happens next" />
              <p className="muted" style={{ margin: 0 }}>
                Documents are read automatically, then AI agents check data quality, eligibility, medical necessity and plan
                policy. A claims examiner reviews anything that is not a clean approval.
              </p>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="evidence-grid">
            {GROUPS.map((g) => {
              const files = evidence.map((e, i) => ({ ...e, i })).filter((e) => e.type === g.type);
              return (
                <div key={g.type}>
                  <SectionTitle icon={g.icon} title={g.title} count={files.length ? `${files.length} attached` : undefined} />
                  <p className="muted small" style={{ margin: "-6px 0 14px 42px" }}>{g.help}</p>
                  <div className="tiles" style={{ marginLeft: 42 }}>
                    {files.map((e) => (
                      <UploadTile key={e.i} label={g.title} file={e.file} onFile={() => undefined}
                                  onRemove={() => setEvidence((ev) => ev.filter((_, j) => j !== e.i))} />
                    ))}
                    {evidence.length < MAX_EVIDENCE && (files.length === 0
                      ? <UploadTile label={g.tile} onFile={(f) => addEvidence(g.type, [f])} />
                      : <AddTile label={`Add more: ${g.title}`} onFiles={(fs) => addEvidence(g.type, fs)} />)}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {step === 2 && (
          <div className="card-body">
            <SectionTitle icon={ClipboardList} title="Documents" count={`${all.length} file${all.length === 1 ? "" : "s"}`} />
            <table className="table" style={{ marginBottom: 18 }}>
              <thead><tr><th>Document</th><th>Type</th><th className="num">Size</th></tr></thead>
              <tbody>
                {all.map((f, i) => (
                  <tr key={i}><td>{f.file.name}</td><td>{f.type === "CMS1500" ? "Claim form" : GROUPS.find((g) => g.type === f.type)?.title}</td>
                    <td className="num">{(f.file.size / 1024 / 1024).toFixed(1)} MB</td></tr>
                ))}
              </tbody>
            </table>
            {evidence.length === 0 && (
              <div className="banner info">No supporting evidence attached. Lines that need documentation will be pended until records are provided.</div>
            )}
            {tooBig && <p className="error-text">One or more files are larger than 20 MB.</p>}
            {error && <div className="banner bad" style={{ marginTop: 12 }}>{error}</div>}
          </div>
        )}

        <div className="actions">
          {step > 0 && <button className="btn quiet" onClick={() => setStep(step - 1)} disabled={!!busy}><ArrowLeft size={16} /> Back</button>}
          {step < 2 ? (
            <button className="btn" onClick={() => setStep(step + 1)} disabled={!form || tooBig}>Continue <ChevronRight size={16} /></button>
          ) : (
            <button className="btn" onClick={submit} disabled={!form || tooBig || !!busy}>
              {busy ? <><LoaderCircle size={16} className="spin" /> {busy}</> : "Submit claim"}
            </button>
          )}
        </div>
      </Card>
    </>
  );
}
