import { QueryClient } from '@tanstack/react-query';
import { ApiError } from '@workspace/api-client-react';

/**
 * Retry only what may pass on a second try. A 4xx (not found, not yours,
 * signed out) comes back the same every time, so retrying it only keeps the
 * person staring at a blank page before the same answer.
 */
export function retryUnlessClientError(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 3;
}

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: retryUnlessClientError } },
});
