import { useQueryClient } from '@tanstack/react-query';
import {
  getGetReportAnalysisQueryKey,
  useGetReportAnalysis,
  useRetryReportAnalysis,
  type AnalysisEvidence,
  type AnalysisFinding,
  type AnalysisValue,
  type ReportAnalysis,
} from '@workspace/api-client-react';
import { AlertTriangle, Eye, EyeOff, HelpCircle, Loader2, RefreshCw, Sparkles, Stethoscope } from 'lucide-react';
import { ATTENTION_BADGE, Badge, CRITICAL_BADGE, InlineUnavailable, NEUTRAL_BADGE, POSITIVE_BADGE, Skeleton, formatValue, titleCase } from './ui-kit';

// The AI's analysis of one report, as the patient sees it.
//
// Every possible condition here is a possibility, never a diagnosis, and the
// text comes from the approved knowledge base - this component adds no medical
// wording of its own beyond labels. What the AI held back is always shown with
// its reason: silence would read as a clean result.

const CONFIDENCE: Record<string, { label: string; className: string }> = {
  SUPPORTED: { label: 'Clear signs', className: ATTENTION_BADGE },
  PROVISIONAL: { label: 'Some signs', className: NEUTRAL_BADGE },
  INSUFFICIENT: { label: 'Not enough information', className: NEUTRAL_BADGE },
};

const VALUE_STATE: Record<string, { label: string; className: string }> = {
  USED: { label: 'Used', className: POSITIVE_BADGE },
  NOT_SURE: { label: 'Not used', className: NEUTRAL_BADGE },
  READERS_DISAGREE: { label: 'Held back', className: ATTENTION_BADGE },
};

const REFERENCE_STATUS: Record<string, string> = {
  ABOVE: 'Above range',
  BELOW: 'Below range',
  WITHIN: 'In range',
};

type Names = Map<string, string>;

// Evidence carries the reader's key ("free_t4", "tsh"); the values table
// carries the name the laboratory printed. Use the printed name for every
// test on the report, whatever the condition - no list of tests to keep up.
export function analyteName(key: string, names: Names): string {
  const printed = names.get(key.toLowerCase());
  if (printed) return printed;
  // Short keys are abbreviations (TSH, ALT, GGT); longer ones are words.
  return !key.includes('_') && key.length <= 4 ? key.toUpperCase() : titleCase(key);
}

// "Needs" lists mix sentences with bare keys; only the keys are renamed.
const missingName = (entry: string, names: Names) => (/^[a-z0-9_]+$/.test(entry) ? analyteName(entry, names) : entry);

export function AiAnalysisSection({ reportId }: { reportId: string }) {
  const queryClient = useQueryClient();
  const query = useGetReportAnalysis(reportId, {
    query: {
      queryKey: getGetReportAnalysisQueryKey(reportId),
      enabled: Boolean(reportId),
      // Keep checking while the AI is still reading, then stop.
      refetchInterval: (q) => ((q.state.data as ReportAnalysis | undefined)?.status === 'PENDING' ? 4000 : false),
    },
  });
  const retry = useRetryReportAnalysis({
    mutation: { onSuccess: () => queryClient.invalidateQueries({ queryKey: getGetReportAnalysisQueryKey(reportId) }) },
  });
  const analysis = query.data as ReportAnalysis | undefined;

  return (
    <section className="mb-6 overflow-hidden rounded-2xl border border-[hsl(var(--brand)/.28)] bg-card shadow-sm" aria-labelledby="ai-analysis-title" data-testid="section-ai-analysis">
      <div className="flex flex-col gap-3 border-b border-border bg-[hsl(var(--brand)/.05)] px-5 py-5 sm:px-6">
        <div className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-xl bg-[hsl(var(--brand)/.12)] text-[hsl(var(--brand))]"><Sparkles size={17} /></span>
          <div>
            <p className="mono-label text-[hsl(var(--brand))]">AI analysis</p>
            <h2 id="ai-analysis-title" className="text-[24px] leading-tight">What our AI found in this report</h2>
          </div>
        </div>
        <p className="flex items-start gap-2 rounded-lg bg-card/70 px-3 py-2.5 text-[13px] leading-relaxed text-muted-foreground">
          <Stethoscope size={14} className="mt-0.5 shrink-0" />
          This is not a diagnosis. Our AI can be wrong. Please show these results to a doctor before you make any decision about your health.
        </p>
      </div>
      <div className="p-5 sm:p-6">
        {query.isLoading ? <div className="space-y-3"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
          : query.isError || !analysis ? <InlineUnavailable label="The AI analysis could not be loaded." />
          : <AnalysisBody analysis={analysis} retrying={retry.isPending} onRetry={() => retry.mutate({ reportId })} />}
      </div>
    </section>
  );
}

function AnalysisBody({ analysis, retrying, onRetry }: { analysis: ReportAnalysis; retrying: boolean; onRetry: () => void }) {
  const values = analysis.values ?? [];
  const findings = analysis.findings ?? [];
  const criticals = values.filter((v) => v.critical);

  if (analysis.status === 'PENDING') {
    return <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="text-ai-pending"><Loader2 size={15} className="animate-spin" />Our AI is reading this report. This usually takes under a minute.</p>;
  }
  if (analysis.status === 'UNAVAILABLE') {
    return (
      <div className="flex flex-col items-start gap-3" data-testid="text-ai-unavailable">
        <p className="text-sm text-muted-foreground">{analysis.reason || 'Our AI could not look at this report right now.'}</p>
        <button onClick={onRetry} disabled={retrying} className="inline-flex h-9 items-center gap-2 rounded-xl border border-input bg-card px-3 text-sm font-medium hover:bg-secondary disabled:opacity-60" data-testid="button-ai-retry">
          {retrying ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}Try again
        </button>
      </div>
    );
  }

  const shown = findings.filter((f) => !f.withheld && f.confidence !== 'INSUFFICIENT');
  const conditions = shown.filter((f) => f.level >= 3);
  const patterns = shown.filter((f) => f.level < 3);
  const couldNotTell = findings.filter((f) => !f.withheld && f.confidence === 'INSUFFICIENT' && f.level >= 3);
  const heldBack = findings.filter((f) => f.withheld);
  const byCode = new Map(findings.map((f) => [f.code, f]));
  const names: Names = new Map(values.filter((v) => v.analyte && v.label).map((v) => [v.analyte.toLowerCase(), v.label]));

  return (
    <div className="space-y-6">
      {(analysis.urgent || criticals.length > 0) && (
        <div className="flex items-start gap-3 rounded-xl border border-[hsl(var(--destructive)/.35)] bg-[hsl(var(--destructive)/.07)] p-4" role="alert" data-testid="alert-ai-urgent">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-[hsl(var(--destructive))]" />
          <div>
            <p className="text-sm font-semibold text-[hsl(var(--destructive))]">Please see a doctor today</p>
            <p className="mt-1 text-sm leading-relaxed">Your laboratory marked {criticals.length === 1 ? 'a result' : 'some results'} on this report as critical{criticals.length ? `: ${criticals.map((v) => v.label).join(', ')}` : ''}. If you feel unwell, go to the nearest emergency department.</p>
          </div>
        </div>
      )}

      {analysis.status === 'HELD_BACK' && (
        <div className="flex items-start gap-3 rounded-xl bg-secondary/60 p-4" data-testid="text-ai-held-back">
          <EyeOff size={17} className="mt-0.5 shrink-0 text-muted-foreground" />
          <p className="text-sm leading-relaxed">{analysis.reason}</p>
        </div>
      )}

      {analysis.status === 'READY' && analysis.reason && (
        <p className="flex items-start gap-2 text-sm text-muted-foreground"><EyeOff size={15} className="mt-0.5 shrink-0" />{analysis.reason}</p>
      )}

      {conditions.length > 0 && (
        <FindingGroup title="Possible conditions" detail="Our AI found a pattern of results that can fit these conditions. Only a doctor can confirm or rule them out.">
          {conditions.map((f) => <FindingCard key={f.code} finding={f} byCode={byCode} names={names} />)}
        </FindingGroup>
      )}

      {patterns.length > 0 && (
        <FindingGroup title="Results outside the normal range" detail="Each of these is a single sign. On its own it does not mean you have a disease.">
          {patterns.map((f) => <FindingCard key={f.code} finding={f} byCode={byCode} names={names} />)}
        </FindingGroup>
      )}

      {analysis.status === 'READY' && conditions.length === 0 && patterns.length === 0 && (
        <p className="text-sm text-muted-foreground" data-testid="text-ai-nothing-found">Our AI did not find any result outside the normal range among the values it could read. This does not rule out a health problem.</p>
      )}

      {couldNotTell.length > 0 && (
        <FindingGroup title="Could not tell" detail="Our AI looked for these but this report does not have enough information.">
          {couldNotTell.map((f) => (
            <div key={f.code} className="flex items-start gap-3 rounded-xl border border-border p-4">
              <HelpCircle size={16} className="mt-0.5 shrink-0 text-muted-foreground" />
              <div>
                <p className="text-sm font-medium">{f.plain_name || f.label}</p>
                {f.evidence_missing.length > 0 && <p className="mt-1 text-xs text-muted-foreground">Needs: {f.evidence_missing.map((m) => missingName(m, names)).join(', ')}</p>}
              </div>
            </div>
          ))}
        </FindingGroup>
      )}

      {heldBack.length > 0 && (
        <FindingGroup title="Held back" detail="Our AI is not showing these because it could not be sure.">
          {heldBack.map((f) => (
            <div key={f.code} className="flex items-start gap-3 rounded-xl border border-dashed border-border p-4" data-testid={`ai-held-${f.code}`}>
              <EyeOff size={16} className="mt-0.5 shrink-0 text-muted-foreground" />
              <div>
                <p className="text-sm font-medium">{f.plain_name || f.label}</p>
                <p className="mt-1 text-xs text-muted-foreground">{f.withheld_reason}</p>
              </div>
            </div>
          ))}
        </FindingGroup>
      )}

      {values.length > 0 && <ValuesRead values={values} />}

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        {findings.some((f) => f.validation_status === 'NOT_VALIDATED')
          ? 'These checks are written from published medical guidance. They have not yet been tested on real patient reports, so treat them as a starting point for a talk with your doctor.'
          : 'Treat these results as a starting point for a talk with your doctor.'}
        {analysis.policy_version ? ` Rules ${analysis.policy_version}${analysis.knowledge_version ? ` · ${analysis.knowledge_version}` : ''}.` : ''}
      </p>
    </div>
  );
}

function FindingGroup({ title, detail, children }: { title: string; detail: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-0.5 text-xs text-muted-foreground">{detail}</p>
      <div className="mt-3 grid gap-3">{children}</div>
    </div>
  );
}

// A finding can rest on another finding (a possible condition on "Raised TSH").
// Follow those links so every value behind the card is shown with its line.
function measuredEvidence(finding: AnalysisFinding, byCode: Map<string, AnalysisFinding>, seen = new Set<string>()): AnalysisEvidence[] {
  seen.add(finding.code);
  return finding.evidence_used.flatMap((e) => {
    if (e.kind !== 'finding') return [e];
    const basis = byCode.get(e.key);
    return basis && !seen.has(basis.code) ? measuredEvidence(basis, byCode, seen) : [];
  });
}

function FindingCard({ finding, byCode, names }: { finding: AnalysisFinding; byCode: Map<string, AnalysisFinding>; names: Names }) {
  const confidence = CONFIDENCE[finding.confidence] ?? { label: finding.confidence, className: NEUTRAL_BADGE };
  const measured = measuredEvidence(finding, byCode).filter((e, i, all) => all.findIndex((o) => o.key === e.key) === i);
  const builtOn = finding.evidence_used
    .filter((e) => e.kind === 'finding')
    .map((e) => byCode.get(e.key)?.plain_name || byCode.get(e.key)?.label)
    .filter(Boolean);
  return (
    <div className="rounded-xl border border-border p-4" data-testid={`ai-finding-${finding.code}`}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold">{finding.plain_name || finding.label}</p>
        <Badge className={confidence.className}>{confidence.label}</Badge>
      </div>
      {finding.plain_explanation && <p className="mt-2 text-sm leading-relaxed">{finding.plain_explanation}</p>}
      {builtOn.length > 0 && <p className="mt-3 text-xs text-muted-foreground">Built on: {builtOn.join(', ')}</p>}
      {measured.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {measured.map((e, i) => (
            <li key={`${e.key}-${i}`} className="text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{analyteName(e.key, names)}</span> {formatValue(e.value)} {e.unit}
              {e.reference_text ? <> · normal range {e.reference_text}</> : null}
              {e.source_text ? <span className="mt-0.5 block font-mono text-[11px]">Read from: “{e.source_text}”</span> : null}
            </li>
          ))}
        </ul>
      )}
      {finding.evidence_missing.length > 0 && <p className="mt-3 text-xs text-muted-foreground">Would help to know: {finding.evidence_missing.map((m) => missingName(m, names)).join(', ')}</p>}
      {finding.next_steps.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs leading-relaxed">
          {finding.next_steps.map((s) => <li key={s}>{s}</li>)}
        </ul>
      )}
    </div>
  );
}

function ValuesRead({ values }: { values: AnalysisValue[] }) {
  return (
    <div>
      <h3 className="flex items-center gap-2 text-sm font-semibold"><Eye size={15} />Values our AI read</h3>
      <p className="mt-0.5 text-xs text-muted-foreground">Read by AI. Please check each value against your printed report.</p>
      <div className="mt-3 overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left mono-label text-muted-foreground"><th className="px-4 py-2.5 font-normal">Test</th><th className="px-3 py-2.5 font-normal">Value</th><th className="px-3 py-2.5 font-normal">Normal range</th><th className="px-4 py-2.5 font-normal">Status</th></tr></thead>
          <tbody className="divide-y divide-border">
            {values.map((v, i) => {
              const state = VALUE_STATE[v.state] ?? { label: v.state, className: NEUTRAL_BADGE };
              const range = REFERENCE_STATUS[v.reference_status];
              return (
                <tr key={`${v.analyte}-${i}`} data-testid={`ai-value-${i}`}>
                  <td className="px-4 py-2.5 align-top">
                    <p className="font-medium">{v.label}</p>
                    {v.source_text && <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{v.page ? `Page ${v.page}: ` : ''}“{v.source_text}”</p>}
                    {v.note && <p className="mt-0.5 text-[11px] text-muted-foreground">{v.note}</p>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 align-top">{formatValue(v.value)} <span className="text-xs text-muted-foreground">{v.unit}</span></td>
                  <td className="px-3 py-2.5 align-top text-xs text-muted-foreground">{v.reference_text || '—'}{range && v.state === 'USED' ? <span className="block">{range}</span> : null}</td>
                  <td className="px-4 py-2.5 align-top"><div className="flex flex-wrap gap-1.5"><Badge className={`whitespace-nowrap ${state.className}`}>{state.label}</Badge>{v.critical ? <Badge className={`whitespace-nowrap ${CRITICAL_BADGE}`}>Critical</Badge> : null}</div></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
