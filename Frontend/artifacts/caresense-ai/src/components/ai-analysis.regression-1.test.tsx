// Regression: ISSUE-003 — a possible condition hid the evidence it was built on
// Found by /qa on 2026-10-22
// Report: .gstack/qa-reports/run-20261022T144739Z/qa-report-127-0-0-1-2026-10-22.md
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// The shape the API returned for the synthetic thyroid sample report: the
// condition cites free T4 directly and TSH through the "Raised TSH" finding.
const measurement = (key: string, value: number, unit: string, range: string, line: string) => ({
  key, kind: 'measurement', value, unit, reference_text: range, reference_status: '', page: 1, source_text: line,
});
const finding = (code: string, plain_name: string, level: number, evidence_used: unknown[]) => ({
  code, label: plain_name, plain_name, level, category: 'thyroid', confidence: level >= 3 ? 'PROVISIONAL' : 'SUPPORTED',
  validation_status: 'NOT_VALIDATED', evidence_used, evidence_missing: [], caveats: [], plain_explanation: '',
  next_steps: [], withheld: false, withheld_reason: '',
});
const FREE_T4 = measurement('free_t4', 0.6, 'ng/dL', '0.8 - 1.8', 'Free T4  0.6 ng/dL  0.8 - 1.8');
const TSH = measurement('tsh', 8.2, 'uIU/mL', '0.4 - 4.0', 'TSH  8.2 uIU/mL  0.4 - 4.0');
const ANALYSIS = {
  status: 'READY', reason: '', urgent: false, values: [], policy_version: 'patient-analysis-1', knowledge_version: '',
  findings: [
    finding('TSH_ELEVATION_PATTERN', 'Raised TSH', 2, [TSH]),
    finding('POSSIBLE_PRIMARY_HYPOTHYROIDISM', 'Pattern that may suggest an underactive thyroid gland', 3, [
      { key: 'TSH_ELEVATION_PATTERN', kind: 'finding', value: null, unit: '', reference_text: '', reference_status: '', page: null, source_text: '' },
      FREE_T4,
    ]),
  ],
};

vi.mock('@workspace/api-client-react', () => ({
  getGetReportAnalysisQueryKey: (id: string) => ['analysis', id],
  useGetReportAnalysis: () => ({ data: ANALYSIS, isLoading: false, isError: false }),
  useRetryReportAnalysis: () => ({ mutate: () => {}, isPending: false }),
}));

const { AiAnalysisSection } = await import('./ai-analysis');

describe('AiAnalysisSection', () => {
  it('shows every value a possible condition was built on, including those reached through another finding', () => {
    render(<QueryClientProvider client={new QueryClient()}><AiAnalysisSection reportId="r1" /></QueryClientProvider>);
    const card = within(screen.getByTestId('ai-finding-POSSIBLE_PRIMARY_HYPOTHYROIDISM'));
    // Testing Library collapses the report line's double spaces to one.
    expect(card.getByText(/Free T4 0\.6 ng\/dL/)).toBeInTheDocument();
    expect(card.getByText(/TSH 8\.2 uIU\/mL/)).toBeInTheDocument();
    expect(card.getByText(/Raised TSH/)).toBeInTheDocument();
  });
});
