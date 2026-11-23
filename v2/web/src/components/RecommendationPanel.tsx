import { Bot, CircleAlert, ListChecks, ScanSearch, Sparkles } from "lucide-react";
import { Badge, Check } from "./Status";
import { Markdown } from "./Markdown";
import type { Finding, Recommendation, ServiceLine } from "../types";

const AUTO_APPROVE = 0.9;
const VERIFY_CODES = new Set(["LOW_EXTRACTION_CONFIDENCE", "PAYER_PROGRAM_MISMATCH", "CHECKBOX_NOT_MARKED", "COB_PRIMARY_EOB_MISSING"]);

function firstSentence(text: string) {
  const clean = text.replace(/\*\*/g, "").replace(/\s+/g, " ").trim();
  const m = clean.match(/^(.{20,220}?[.!?])\s/);
  return m ? m[1] : clean.slice(0, 220);
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Make agent text about extracted fields readable: 'snake_case' names -> words, 0.063 confidence -> 6%. */
function humanize(text: string) {
  return text
    .replace(/'([a-z0-9]+(?:_[a-z0-9]+)+)'/g, (_m, f: string) => f.replaceAll("_", " "))
    .replace(/confidence (?:of )?(0?\.\d+)/g, (_m, v: string) => `confidence ${Math.round(Number(v) * 100)}%`);
}

function counts(findings: Finding[], category: string) {
  const f = findings.filter((x) => x.category === category);
  return { errors: f.filter((x) => x.severity === "ERROR").length, warnings: f.filter((x) => x.severity === "WARNING").length };
}

/** Structured view of the AI recommendation. Uses the agent's headline/key points when present, else derives them. */
export function RecommendationPanel({ rec, lines }: { rec: Recommendation; lines: ServiceLine[] }) {
  const headline = rec.headline || firstSentence(rec.summary);
  const keyPoints = rec.key_points?.length
    ? rec.key_points
    : rec.findings.filter((f) => f.severity === "ERROR").slice(0, 5).map((f) => {
        const msg = firstSentence(f.message);
        return f.line_number && !/^line \d/i.test(msg) ? `Line ${f.line_number}: ${msg}` : msg;
      });
  const verify = rec.verify_before_payment?.length
    ? rec.verify_before_payment.map(humanize)
    : rec.findings.filter((f) => VERIFY_CODES.has(f.code)).map((f) => humanize(firstSentence(f.message)));
  const pct = Math.round(rec.confidence * 100);
  const routedReason = rec.decision !== "APPROVE"
    ? "Every non-approval is decided by an examiner."
    : !rec.all_checks_passed ? "Not all checks passed."
    : rec.confidence < AUTO_APPROVE ? `Confidence is below the ${Math.round(AUTO_APPROVE * 100)}% auto-approve threshold.` : "";
  const checks: [string, boolean, string][] = [
    ["Validation", rec.checks.validation, "VALIDATION"],
    ["Eligibility", rec.checks.eligibility, "ELIGIBILITY"],
    ["Clinical", rec.checks.clinical, "CLINICAL"],
  ];

  return (
    <div className="rec">
      <div className="rec-head">
        <Bot size={22} strokeWidth={1.75} className="brand" />
        <p className="rec-headline">{headline}</p>
      </div>

      <div className="rec-grid">
        <div className="rec-block">
          <div className="rec-label">Confidence</div>
          <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="AI confidence">
            <div className="meter-fill" style={{ width: `${pct}%` }} />
            <div className="meter-mark" style={{ left: `${AUTO_APPROVE * 100}%` }} title="Auto-approve threshold" />
          </div>
          <div className="row between small"><b>{pct}%</b><span className="muted">auto-approve at {Math.round(AUTO_APPROVE * 100)}%</span></div>
          {routedReason && <div className="muted small">Routed to you: {routedReason}</div>}
        </div>
        <div className="rec-block">
          <div className="rec-label">Checks</div>
          <div className="stack" style={{ gap: 6 }}>
            {checks.map(([label, ok, cat]) => {
              const c = counts(rec.findings, cat);
              return (
                <div className="row between" key={label}>
                  <Check ok={ok} label={label} />
                  <span className="muted small">{plural(c.errors, "error")} · {plural(c.warnings, "warning")}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="rec-block">
        <div className="rec-label"><ListChecks size={14} /> Line outcomes</div>
        <table className="table compact">
          <tbody>
            {rec.line_decisions.map((d) => {
              const l = lines.find((x) => x.line_number === d.line_number);
              return (
                <tr key={d.line_number}>
                  <td style={{ width: 54 }}>Line {d.line_number}</td>
                  <td style={{ width: 110 }}><b>{l?.procedure_code ?? ""}</b>{l?.modifiers ? ` ${l.modifiers}` : ""}</td>
                  <td style={{ width: 96 }}><Badge value={d.decision} /></td>
                  <td style={{ width: 92 }} className="muted">{[d.carc && `CARC ${d.carc}`, d.rarc].filter(Boolean).join(" · ")}</td>
                  <td>{d.reason}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="rec-grid">
        <div className="rec-block">
          <div className="rec-label"><Sparkles size={14} /> Key points</div>
          {keyPoints.length ? <ul className="rec-list">{keyPoints.map((k, i) => <li key={i}>{k}</li>)}</ul>
            : <p className="muted small" style={{ margin: 0 }}>No blocking issues found.</p>}
        </div>
        <div className="rec-block">
          <div className="rec-label"><ScanSearch size={14} /> Verify before payment</div>
          {verify.length ? (
            <ul className="rec-list warn">{verify.map((v, i) => <li key={i}><CircleAlert size={13} /> <span>{v}</span></li>)}</ul>
          ) : <p className="muted small" style={{ margin: 0 }}>Nothing flagged.</p>}
        </div>
      </div>

      <details className="rec-more">
        <summary>Full AI summary</summary>
        <Markdown text={rec.summary} />
      </details>
    </div>
  );
}
