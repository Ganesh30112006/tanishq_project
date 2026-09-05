import { setBaseUrl } from '@workspace/api-client-react';

/**
 * The Django backend's origin. Django is the *only* API layer the browser
 * talks to (spec section 3) - the SPA never calls the FastAPI intelligence
 * service or a database directly. Cross-origin requests rely on the
 * exact-origin, credential-less CORS grant configured in
 * `apps/common/cors.py`; the bearer token is attached explicitly per
 * request (see `src/lib/auth.tsx`), never via a cookie.
 */
export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://127.0.0.1:8000';

export function configureApiClient(): void {
  setBaseUrl(API_BASE_URL);
}
