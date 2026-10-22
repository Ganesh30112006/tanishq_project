/**
 * The risk estimate, as a patient reads it.
 *
 * Moved out of App.tsx unchanged in what it says. The rules it follows live in
 * lib/risk-display: the band leads, a figure is shown only when it may be, and
 * the gauge is filled by the band - never by a withheld number, which would
 * read as "your risk is zero".
 */
import { useState } from 'react';
import { Activity, AlertCircle, CircleHelp, Clock3, HeartPulse, Loader2, ShieldHalf, Stethoscope, Upload, Zap } from 'lucide-react';
import { useRequestRiskAnalysis } from '@workspace/api-client-react';
import type { DataGap, NextStep, PatientProfile, RiskAssessment, RiskFactor } from '@workspace/api-client-react';
import { Badge, relativeTime, shortDate, titleCase } from '@/components/ui-kit';
import { bandFill, bandHeadline, isRiskyLevel, shouldShowScore, withheldReason } from '@/lib/risk-display';
import { lifecycleBadgeClass, riskClass } from '@/lib/display';

export function RiskGauge({ fill, risky }: { fill: number; risky: boolean }) {
  // A half-dial. Arc length is the band's fill; colour says only "elevated or not".
  const clamped = Math.max(0, Math.min(100, fill));
  const radius = 54;
  const circumference = Math.PI * radius;
  return (
    <svg viewBox="0 0 128 72" className="w-36 shrink-0" role="presentation">
      <path d="M10 64 A54 54 0 0 1 118 64" fill="none" stroke="hsl(var(--secondary))" strokeWidth="11" strokeLinecap="round" />
      <path d="M10 64 A54 54 0 0 1 118 64" fill="none" stroke={risky ? 'hsl(var(--destructive))' : 'hsl(var(--accent))'} strokeWidth="11" strokeLinecap="round" strokeDasharray={`${(clamped / 100) * circumference} ${circumference}`} className="transition-[stroke-dasharray] duration-700" />
    </svg>
  );
}

export function RiskCard({ patient, assessment }: { patient: PatientProfile; assessment: RiskAssessment }) {
  // SHAP contributions describe the model, not the person: "+0.312" reads as
  // a quantity of disease to anyone but a clinician reviewing the output, and
  // this build no longer carries a clinician viewer, so the raw number is
  // never shown - only the plain-language direction.
  const factors = [...(assessment.factors || [])].sort((a, b) => a.rank - b.rank).slice(0, 5);
  const strongest = Math.max(...factors.map((f) => Math.abs(Number(f.contribution))), 1e-6);
  const reading = assessment.interpretation;
  const risky = isRiskyLevel(patient.risk_level);

  return <div>
    {assessment.safety_notice ? <UrgentNotice notice={assessment.safety_notice} /> : null}

    {assessment.superseded_by_new_data && <div className="mb-5 flex items-start gap-2.5 rounded-xl border border-[hsl(var(--accent)/.5)] bg-[hsl(var(--accent)/.1)] p-3.5" data-testid="banner-superseded">
      <Clock3 size={16} className="mt-0.5 shrink-0 text-[hsl(var(--accent-foreground))]" />
      <p className="text-sm leading-relaxed">New results have been added since this estimate was made, so it is now out of date. Please run the analysis again.</p>
    </div>}

    <div className="flex flex-wrap items-center gap-5 rounded-2xl bg-secondary/50 p-5">
      <div className="relative">
        <RiskGauge fill={bandFill(reading, patient.risk_score)} risky={risky} />
        {shouldShowScore(reading) && <p className="absolute inset-x-0 bottom-0 text-center font-display text-2xl font-semibold" data-testid="text-risk-score">{reading!.score_percent}<span className="text-sm text-muted-foreground">/100</span></p>}
      </div>
      <div className="min-w-0 flex-1">
        <p className={`font-display text-[26px] font-semibold leading-tight ${risky ? 'text-[hsl(var(--destructive))]' : ''}`} data-testid="text-risk-band">{bandHeadline(reading, titleCase(patient.risk_level))}</p>
        {reading?.headline && <p className="mt-1.5 text-[15px] leading-relaxed text-muted-foreground">{reading.headline}</p>}
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Badge className={riskClass(patient.risk_level)}>{titleCase(patient.trend) || 'Stable'}</Badge>
          {assessment.lifecycle_state && <Badge className={`whitespace-nowrap ${lifecycleBadgeClass(assessment.lifecycle_state)}`}>{titleCase(assessment.lifecycle_state)}</Badge>}
        </div>
      </div>
    </div>

    {reading && <div className="mt-5 space-y-3 text-sm leading-relaxed">
      <p className="text-muted-foreground">{reading.what_it_means}{reading.horizon ? ` This estimate covers ${reading.horizon}.` : ''}</p>
      {withheldReason(reading) && <p className="text-muted-foreground" data-testid="text-score-withheld">{withheldReason(reading)}</p>}
      {reading.reliability_note && <p className="flex items-start gap-2 font-bold text-[hsl(var(--accent-foreground))]" data-testid="text-reliability-note"><AlertCircle size={15} className="mt-0.5 shrink-0" />{reading.reliability_note}</p>}
      <p className="flex items-start gap-2 rounded-xl border border-dashed border-border p-3.5 text-muted-foreground"><CircleHelp size={15} className="mt-0.5 shrink-0" />{reading.what_it_does_not_mean}</p>
    </div>}

    {reading?.evidence_grade && <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-border p-3.5">
      <ShieldHalf size={16} className="mt-0.5 shrink-0 text-muted-foreground" />
      <div>
        <p className="text-sm font-bold" data-testid="text-evidence-grade">{reading.evidence_grade.label}</p>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{reading.evidence_grade.detail}</p>
      </div>
    </div>}

    {reading?.next_steps?.length ? <div className="mt-6">
      <p className="mono-label text-muted-foreground">What you can do</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">{reading.next_steps.map((step) => <NextStepRow key={step.action} step={step} />)}</div>
    </div> : null}

    {factors.length > 0 && <div className="mt-7">
      <p className="mono-label text-muted-foreground">What mattered most in this estimate</p>
      <div className="mt-3 space-y-3.5">{factors.map((factor: RiskFactor) => {
        const contribution = Number(factor.contribution);
        const up = factor.direction === 'INCREASES';
        return <div key={factor.feature_name}>
          <div className="flex items-baseline justify-between gap-3">
            <p className="min-w-0 truncate text-sm font-bold">{titleCase(factor.feature_name)}</p>
            <span className={`shrink-0 text-[12px] font-bold ${up ? 'text-[hsl(var(--destructive))]' : 'text-[hsl(var(--success))]'}`}>{up ? 'Raised the estimate' : 'Lowered the estimate'}</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-secondary">
            <div className={`h-full rounded-full ${up ? 'bg-[hsl(var(--destructive)/.65)]' : 'bg-[hsl(var(--success)/.75)]'}`} style={{ width: `${Math.max(6, (Math.abs(contribution) / strongest) * 100)}%` }} />
          </div>
        </div>;
      })}</div>
      <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">This shows how the tool reached its estimate. These are not causes of illness, and changing one of them may not change your health.</p>
    </div>}

    {assessment.limitations && assessment.limitations.length > 0 && <details className="group mt-6 rounded-xl border border-[hsl(var(--accent)/.4)] bg-[hsl(var(--accent)/.06)] p-3.5">
      <summary className="mono-label flex list-none items-center justify-between text-[hsl(var(--accent-foreground))]">Notes for your doctor<span className="transition-transform group-open:rotate-45">+</span></summary>
      <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">These are notes about the tool itself, written for a doctor. You do not need to understand them.</p>
      <ul className="mt-2 space-y-1.5">{assessment.limitations.map((item) => <li key={item} className="flex gap-2 text-[13px] leading-relaxed text-muted-foreground"><span aria-hidden="true">·</span><span>{item}</span></li>)}</ul>
    </details>}

    {assessment.reviews && assessment.reviews.length > 0
      ? <div className="mt-4 space-y-2">{assessment.reviews.map((review) => <div key={review.id} className="rounded-xl bg-secondary/60 p-3 text-[13px] leading-relaxed"><span className="font-bold">{titleCase(review.decision)}</span> by {review.reviewer} · {shortDate(review.created_at)}{review.rationale ? <p className="mt-1 text-muted-foreground">{review.rationale}</p> : null}</div>)}</div>
      : <p className="mt-4 flex items-start gap-2 text-[13px] leading-relaxed text-muted-foreground"><AlertCircle size={14} className="mt-0.5 shrink-0" />This is only a help for you and your doctor. No doctor has checked this estimate, and it is not a diagnosis.</p>}

    <p className="mono-label mt-5 border-t border-border pt-4 !normal-case !tracking-normal text-muted-foreground">{assessment.model ? `Model ${assessment.model}` : 'Model unavailable'} · Assessed {relativeTime(assessment.created_at)}</p>
  </div>;
}

export function UrgentNotice({ notice }: { notice: NonNullable<RiskAssessment['safety_notice']> }) {
  return <div className="mb-5 rounded-xl border-l-4 border-l-[hsl(var(--destructive))] border-y border-r border-y-[hsl(var(--destructive)/.25)] border-r-[hsl(var(--destructive)/.25)] bg-[hsl(var(--destructive)/.06)] p-4" role="alert" data-testid="banner-urgent-symptoms">
    <div className="flex items-start gap-2.5">
      <AlertCircle size={18} className="mt-0.5 shrink-0 text-[hsl(var(--destructive))]" />
      <div>
        <p className="font-bold text-[hsl(var(--destructive))]">{notice.headline}</p>
        <p className="mt-1.5 text-sm leading-relaxed text-foreground/80">{notice.detail}</p>
        {notice.emergency_number ? <p className="mt-2 text-sm font-bold">Emergency: {notice.emergency_number}</p> : null}
      </div>
    </div>
  </div>;
}

export function NextStepRow({ step }: { step: NextStep }) {
  const Icon = step.action === 'SEE_A_DOCTOR' ? Stethoscope : step.action === 'ADD_RESULTS' ? Upload : step.action === 'DISCUSS_SYMPTOMS' ? HeartPulse : Activity;
  return <div className="flex items-start gap-3 rounded-xl border border-border bg-card p-3.5">
    <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-[hsl(var(--brand)/.1)] text-[hsl(var(--brand))]"><Icon size={16} /></span>
    <span className="min-w-0">
      <span className="block text-sm font-bold">{step.label}</span>
      <span className="mt-0.5 block text-[13px] leading-relaxed text-muted-foreground">{step.detail}</span>
    </span>
  </div>;
}

export function BlockedCard({ assessment }: { assessment: RiskAssessment }) {
  const block = assessment.blocked_explanation;
  return <div data-testid="card-analysis-blocked">
    <div className="flex items-start gap-3">
      <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-secondary text-muted-foreground"><ShieldHalf size={19} /></span>
      <div className="min-w-0">
        <p className="font-display text-xl font-semibold">{block?.headline || 'The analysis did not give a result.'}</p>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{block?.detail || 'The system stopped instead of giving an estimate it could not stand behind.'}</p>
      </div>
    </div>

    {block?.data_needed?.length ? <div className="mt-5">
      <p className="mono-label text-muted-foreground">What is missing</p>
      <ul className="mt-3 space-y-2.5">{block.data_needed.map((gap: DataGap) => <li key={gap.feature} className="rounded-xl border border-input p-3.5">
        <p className="text-sm font-bold">{gap.label}</p>
        {gap.how_to_supply && <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{gap.how_to_supply}</p>}
      </li>)}</ul>
    </div> : null}

    {block?.resolvable_by_patient === false && <p className="mt-5 flex items-start gap-2 rounded-xl bg-secondary/60 p-3.5 text-[13px] leading-relaxed text-muted-foreground"><CircleHelp size={14} className="mt-0.5 shrink-0" />Adding more results will not change this. Please see a doctor, who can examine you properly. This tool cannot.</p>}

    <p className="mt-5 border-t border-border pt-4 text-[13px] text-muted-foreground">Nothing has been added to your health record from this attempt · {relativeTime(assessment.created_at)}</p>
  </div>;
}

export function RunAnalysisButton({ patientId, onDone }: { patientId: string; onDone: () => void }) {
  const [outcome, setOutcome] = useState<{ tone: 'blocked' | 'paced'; text: string } | null>(null);
  const run = useRequestRiskAnalysis();

  function analyse() {
    setOutcome(null);
    run.mutate(
      { data: { patient_id: patientId, task: 'cvd' } },
      {
        onSuccess: (result) => {
          // A 200 is a *successful* refusal: the evidence was not good enough
          // and the system declined to guess. Say so rather than showing
          // nothing and letting the reader assume it failed.
          if (result.status === 'blocked') {
            setOutcome({ tone: 'blocked', text: result.message || 'There is not enough checked information in your record yet to give a reliable result.' });
          }
          onDone();
        },
        onError: (error) => {
          const message = error instanceof Error ? error.message.replace(/^HTTP \d+[^:]*:\s*/, '') : 'The analysis could not be run just now. Please try again.';
          setOutcome({ tone: 'paced', text: message });
        },
      },
    );
  }

  return (
    <div className="flex flex-col items-end gap-1.5">
      <button type="button" onClick={analyse} disabled={run.isPending} className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-3.5 text-sm font-bold text-primary-foreground hover:brightness-110 disabled:opacity-60" data-testid="button-run-analysis">
        {run.isPending ? <Loader2 size={15} className="animate-spin" /> : <Zap size={15} />}
        {run.isPending ? 'Analysing…' : 'Run analysis'}
      </button>
      {outcome && <p className={`max-w-xs text-right text-[13px] leading-relaxed ${outcome.tone === 'paced' ? 'text-[hsl(var(--accent-foreground))]' : 'text-muted-foreground'}`} data-testid="text-analysis-outcome">{outcome.text}</p>}
    </div>
  );
}
