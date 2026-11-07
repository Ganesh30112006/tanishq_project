// A dangerous value the laboratory printed only an "H" beside must still get
// "see a doctor today" - and the patient must not be told the lab called it
// critical when it did not.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const value = (label: string, critical_source: string) => ({
  analyte: label.toLowerCase(), label, value: 7.0, unit: 'mmol/L', reference_text: '3.5 - 5.1',
  reference_status: 'ABOVE', printed_flag: critical_source === 'LAB_FLAG' ? 'HH' : 'H',
  critical: true, critical_source, page: 1, source_text: `${label} 7.0 mmol/L H`, text_source: 'PDF_TEXT',
  state: 'USED', note: '',
});
let ANALYSIS: Record<string, unknown> = {};

vi.mock('@workspace/api-client-react', () => ({
  getGetReportAnalysisQueryKey: (id: string) => ['analysis', id],
  useGetReportAnalysis: () => ({ data: ANALYSIS, isLoading: false, isError: false }),
  useRetryReportAnalysis: () => ({ mutate: () => {}, isPending: false }),
}));

const { AiAnalysisSection } = await import('./ai-analysis');

function show(values: unknown[]) {
  ANALYSIS = { status: 'READY', reason: '', urgent: true, values, findings: [], policy_version: 'patient-analysis-2', knowledge_version: '' };
  render(<QueryClientProvider client={new QueryClient()}><AiAnalysisSection reportId="r1" /></QueryClientProvider>);
  return screen.getByTestId('alert-ai-urgent');
}

describe('urgent banner', () => {
  it('names a danger-limit value without claiming the lab flagged it', () => {
    const banner = show([value('Potassium', 'DANGER_LIMIT')]);
    expect(banner).toHaveTextContent('Please see a doctor today');
    expect(banner).toHaveTextContent('at a level that can be dangerous: Potassium');
    expect(banner).not.toHaveTextContent('Your laboratory marked');
  });

  it('still credits the laboratory when it printed the critical flag', () => {
    const banner = show([value('Sodium', 'LAB_FLAG')]);
    expect(banner).toHaveTextContent('Your laboratory marked a result on this report as critical: Sodium');
  });
});
