// Regression: ISSUE-004 — evidence lines showed reader keys ("free t4", "tsh")
// Found by /qa on 2026-10-22
// Report: .gstack/qa-reports/run-20261022T144739Z/qa-report-127-0-0-1-2026-10-22.md
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// A liver panel rather than the thyroid sample: the names must come from the
// report, so they work for a panel nobody wrote a label list for.
const measurement = (key: string, value: number, unit: string) => ({
  key, kind: 'measurement', value, unit, reference_text: '', reference_status: '', page: 1, source_text: '',
});
const value = (analyte: string, label: string, v: number, unit: string) => ({
  analyte, label, value: v, unit, reference_text: '', reference_status: 'ABOVE', printed_flag: '', critical: false,
  page: 1, source_text: '', text_source: '', state: 'USED', note: '',
});
const ANALYSIS = {
  status: 'READY', reason: '', urgent: false, policy_version: 'patient-analysis-1', knowledge_version: '',
  values: [value('alt', 'SGPT (ALT)', 140, 'U/L'), value('alkaline_phosphatase', 'Alkaline Phosphatase', 95, 'U/L')],
  findings: [{
    code: 'POSSIBLE_HEPATOCELLULAR_PATTERN', label: 'x', plain_name: 'Liver cell pattern', level: 3, category: 'hepatic',
    confidence: 'PROVISIONAL', validation_status: 'NOT_VALIDATED', caveats: [], plain_explanation: '', next_steps: [],
    withheld: false, withheld_reason: '',
    evidence_used: [measurement('alt', 140, 'U/L'), measurement('alkaline_phosphatase', 95, 'U/L'), measurement('total_bilirubin', 1.1, 'mg/dL')],
    evidence_missing: ['ggt', 'a repeat test after some weeks'],
  }],
};

vi.mock('@workspace/api-client-react', () => ({
  getGetReportAnalysisQueryKey: (id: string) => ['analysis', id],
  useGetReportAnalysis: () => ({ data: ANALYSIS, isLoading: false, isError: false }),
  useRetryReportAnalysis: () => ({ mutate: () => {}, isPending: false }),
}));

const { AiAnalysisSection, analyteName } = await import('./ai-analysis');

describe('evidence names', () => {
  it('uses the name printed on the report, and a readable name otherwise', () => {
    render(<QueryClientProvider client={new QueryClient()}><AiAnalysisSection reportId="r1" /></QueryClientProvider>);
    const card = within(screen.getByTestId('ai-finding-POSSIBLE_HEPATOCELLULAR_PATTERN'));
    expect(card.getByText('SGPT (ALT)')).toBeInTheDocument();
    expect(card.getByText('Alkaline Phosphatase')).toBeInTheDocument();
    expect(card.getByText('Total Bilirubin')).toBeInTheDocument();
    expect(card.getByText(/Would help to know: GGT, a repeat test after some weeks/)).toBeInTheDocument();
    expect(card.queryByText(/alkaline phosphatase|alt\b/)).toBeNull();
  });

  it('falls back to upper case for abbreviations and title case for words', () => {
    const none = new Map<string, string>();
    expect(analyteName('tsh', none)).toBe('TSH');
    expect(analyteName('free_t4', none)).toBe('Free T4');
    expect(analyteName('ferritin', none)).toBe('Ferritin');
    expect(analyteName('TSH', new Map([['tsh', 'Thyroid Stimulating Hormone']]))).toBe('Thyroid Stimulating Hormone');
  });
});
