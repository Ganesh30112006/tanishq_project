// A scan's numbers come from a picture, and OCR can misread a digit with high
// confidence. Found on 2026-11-07: an ALP of 147 read as 447 from a low-quality
// scan. The patient must be told to check, whatever the reader's confidence.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

let analysis: Record<string, unknown> = {};

vi.mock('@workspace/api-client-react', () => ({
  getGetReportAnalysisQueryKey: (id: string) => ['analysis', id],
  useGetReportAnalysis: () => ({ data: analysis, isLoading: false, isError: false }),
  useRetryReportAnalysis: () => ({ mutate: () => {}, isPending: false }),
}));

const { AiAnalysisSection } = await import('./ai-analysis');

function show(over: Record<string, unknown>) {
  analysis = {
    status: 'READY', reason: '', urgent: false, policy_version: 'p', knowledge_version: '',
    values: [], findings: [], ...over,
  };
  render(<QueryClientProvider client={new QueryClient()}><AiAnalysisSection reportId="r1" /></QueryClientProvider>);
}

describe('notice on a scanned report', () => {
  beforeEach(() => { analysis = {}; });

  it('asks the patient to check the numbers when they were read from a picture', () => {
    show({ text_source: 'OCR' });
    expect(screen.getByTestId('text-ai-scanned-report')).toHaveTextContent(/check each number/);
  });

  it('says nothing on a PDF whose text could be read directly', () => {
    show({ text_source: 'EMBEDDED_TEXT_LAYER' });
    expect(screen.queryByTestId('text-ai-scanned-report')).toBeNull();
  });

  it('says nothing when the analysis was held back and shows no numbers to check', () => {
    show({ status: 'HELD_BACK', reason: 'Not sure enough', text_source: 'OCR' });
    expect(screen.queryByTestId('text-ai-scanned-report')).toBeNull();
  });
});
