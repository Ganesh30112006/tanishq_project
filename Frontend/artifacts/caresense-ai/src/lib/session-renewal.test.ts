// Access tokens last an hour. Before session renewal existed, every patient
// was signed out an hour after signing in, whatever they were doing.
import { ApiError, getMe, login, setAuthTokenGetter, setBaseUrl, setUnauthorizedHandler } from '@workspace/api-client-react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const ME = { id: 'u1', email: 'a@example.test', full_name: 'A', roles: ['PATIENT'], permissions: [] };

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

afterEach(() => {
  setAuthTokenGetter(null);
  setUnauthorizedHandler(null);
  setBaseUrl(null);
});

describe('session renewal', () => {
  it('renews an expired token once and retries the request with the new one', async () => {
    let token = 'expired';
    setAuthTokenGetter(() => token);
    const renew = vi.fn(async () => { token = 'fresh'; return true; });
    setUnauthorizedHandler(renew);
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(401, { error: { message: 'expired' } }))
      .mockResolvedValueOnce(json(200, ME));

    await expect(getMe()).resolves.toMatchObject({ email: 'a@example.test' });
    expect(renew).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const retried = fetchMock.mock.calls[1][1]?.headers as Headers;
    expect(retried.get('authorization')).toBe('Bearer fresh');
  });

  it('surfaces the 401 when the session cannot be renewed', async () => {
    setAuthTokenGetter(() => 'expired');
    setUnauthorizedHandler(async () => false);
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(401, {}));

    await expect(getMe()).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('never treats a wrong password as an expired session', async () => {
    setAuthTokenGetter(() => 'old');
    const renew = vi.fn(async () => true);
    setUnauthorizedHandler(renew);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(401, {}));

    await expect(login({ email: 'a@example.test', password: 'wrong' })).rejects.toBeInstanceOf(ApiError);
    expect(renew).not.toHaveBeenCalled();
  });

  it('does not try to renew a request that carried no token', async () => {
    setAuthTokenGetter(() => null);
    const renew = vi.fn(async () => true);
    setUnauthorizedHandler(renew);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(401, {}));

    await expect(getMe()).rejects.toBeInstanceOf(ApiError);
    expect(renew).not.toHaveBeenCalled();
  });
});
