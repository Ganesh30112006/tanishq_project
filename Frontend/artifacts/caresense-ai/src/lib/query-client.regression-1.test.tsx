// Regression: ISSUE-005 — a missing report waited through retries, then blamed the connection
// Found by /qa on 2026-10-22
// Report: .gstack/qa-reports/run-20261022T144739Z/qa-report-127-0-0-1-2026-10-22.md
import { ApiError } from '@workspace/api-client-react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { QueryError } from '@/components/ui-kit';
import { retryUnlessClientError } from './query-client';

const apiError = (status: number) =>
  new ApiError(new Response(null, { status }), null, { method: 'GET', url: '/api/v1/reports/x/' });

describe('retryUnlessClientError', () => {
  it('does not retry an answer the server will repeat', () => {
    expect(retryUnlessClientError(0, apiError(404))).toBe(false);
    expect(retryUnlessClientError(0, apiError(403))).toBe(false);
  });

  it('still retries a failure that may pass', () => {
    expect(retryUnlessClientError(0, apiError(503))).toBe(true);
    expect(retryUnlessClientError(0, new TypeError('Failed to fetch'))).toBe(true);
    expect(retryUnlessClientError(3, new TypeError('Failed to fetch'))).toBe(false);
  });
});

describe('QueryError', () => {
  it('says a missing item is missing, not a connection problem', () => {
    render(<QueryError onRetry={() => {}} message="This report is unavailable." error={apiError(404)} />);
    expect(screen.queryByText(/connection problem/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId('button-retry')).not.toBeInTheDocument();
    expect(screen.getByText(/could not find it/i)).toBeInTheDocument();
  });

  it('keeps the connection wording and retry button for other failures', () => {
    render(<QueryError onRetry={() => {}} message="This report is unavailable." error={new TypeError('Failed to fetch')} />);
    expect(screen.getByText(/connection problem/i)).toBeInTheDocument();
    expect(screen.getByTestId('button-retry')).toBeInTheDocument();
  });
});
