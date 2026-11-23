import { Check, X } from "lucide-react";

export interface Step {
  name: string;
  sub?: string;
  state: "done" | "current" | "todo" | "error";
}

export function Stepper({ steps }: { steps: Step[] }) {
  return (
    <ol className="stepper" aria-label="Progress">
      {steps.map((s, i) => (
        <li key={s.name} className={`step ${s.state}`} aria-current={s.state === "current" ? "step" : undefined}>
          <div className="label">
            <span className="num">{String(i + 1).padStart(2, "0")}</span>
            <span className="name">{s.name}</span>
          </div>
          <div className="track">
            <span className="dot">
              {s.state === "done" && <Check size={16} strokeWidth={3} />}
              {s.state === "error" && <X size={16} strokeWidth={3} />}
            </span>
            <span className="line" />
          </div>
          {s.sub && <div className="sub">{s.sub}</div>}
        </li>
      ))}
    </ol>
  );
}

const PIPELINE = ["Submitted", "Reading documents", "AI review", "Examiner review", "Decision"];
const SUBS = ["", "(~1 min)", "(~2-3 min)", "(examiner)", ""];
const POSITION: Record<string, number> = {
  DRAFT: 0,
  SUBMITTED: 1,
  EXTRACTING: 1,
  AGENT_REVIEW: 2,
  PENDING_REVIEW: 3,
  FINALIZING: 4,
  APPROVED: 5,
  DENIED: 5,
  PENDED_INFO_REQUESTED: 5,
};

/** The claim pipeline as a stepper. `failedAt` marks where a FAILED claim stopped. */
export function ClaimPipeline({ status, failedAt = 1 }: { status: string; failedAt?: number }) {
  const failed = status === "FAILED";
  const at = failed ? failedAt : (POSITION[status] ?? 0);
  const steps: Step[] = PIPELINE.map((name, i) => ({
    name,
    sub: i === at && !failed ? SUBS[i] : undefined,
    state: failed ? (i < at ? "done" : i === at ? "error" : "todo") : i < at ? "done" : i === at ? "current" : "todo",
  }));
  return <Stepper steps={steps} />;
}
