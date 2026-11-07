// A report must not read as clear because its abnormal rows were the ones the AI
// could not use. Found on 2026-11-08: a blood count with lymphocytes, monocytes and
// MCHC outside range gave no findings and "did not find any result outside the
// normal range". The status names are the ones the reading service really sends.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

let analysis: Record<string, unknown> = {};

vi.mock('@workspace/api-client-react', () => ({
  getGetReportAnalysisQueryKey: (id: string) => ['analysis', id],
  useGetReportAnalysis: () => ({ data: analysis, isLoading: false, isError: false }),
  useRetryReportAnalysis: () => ({ mutate: () => {}, isPending: false }),
}));

const { AiAnalysisSection } = await import('./ai-analysis');

const row = (label: string, state: string, reference_status: string, printed_flag = '') => ({
  analyte: label.toLowerCase(), label, value: 18, unit: '%', reference_text: '20 - 40', reference_status, printed_flag,
  critical: false, critical_source: '', page: 1, source_text: '', text_source: 'EMBEDDED_TEXT_LAYER', state, note: '',
});

function show(values: unknown[]) {
  analysis = { status: 'READY', reason: '', urgent: false, policy_version: 'p', knowledge_version: '', values, findings: [] };
  render(<QueryClientProvider client={new QueryClient()}><AiAnalysisSection reportId="r1" /></QueryClientProvider>);
}

describe('values the AI could not use', () => {
  it('warns and names them when they look outside the range', () => {
    show([row('Haemoglobin', 'USED', 'WITHIN_REFERENCE_RANGE'), row('Lymphocyte', 'NOT_SURE', 'BELOW_REFERENCE_RANGE')]);
    const warning = screen.getByTestId('text-ai-unsure-abnormal');
    expect(warning).toHaveTextContent(/may be outside the normal range/);
    expect(warning).toHaveTextContent('Lymphocyte');
    expect(warning).not.toHaveTextContent('Haemoglobin');
  });

  it('does not say nothing was found', () => {
    show([row('Lymphocyte', 'NOT_SURE', 'BELOW_REFERENCE_RANGE')]);
    expect(screen.queryByTestId('text-ai-nothing-found')).toBeNull();
  });

  it('warns on a lab flag even when no range could be compared', () => {
    show([row('Lymphocyte', 'NOT_SURE', 'UNKNOWN', 'L')]);
    expect(screen.getByTestId('text-ai-unsure-abnormal')).toHaveTextContent('Lymphocyte');
  });

  it('does not warn about rows such as a page number or a normal value', () => {
    show([row('Page', 'NOT_SURE', 'UNKNOWN'), row('Haemoglobin', 'USED', 'WITHIN_REFERENCE_RANGE')]);
    expect(screen.queryByTestId('text-ai-unsure-abnormal')).toBeNull();
    expect(screen.getByTestId('text-ai-nothing-found')).toBeInTheDocument();
  });
});

describe('range label on a value the AI used', () => {
  it.each([
    ['ABOVE_REFERENCE_RANGE', 'Above range'],
    ['BELOW_REFERENCE_RANGE', 'Below range'],
    ['WITHIN_REFERENCE_RANGE', 'In range'],
  ])('shows %s as %s', (status, label) => {
    show([row('Haemoglobin', 'USED', status)]);
    expect(within(screen.getByTestId('ai-value-0')).getByText(label)).toBeInTheDocument();
  });
});
