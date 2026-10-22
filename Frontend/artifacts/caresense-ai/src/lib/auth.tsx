import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { ApiError, getMe, login as apiLogin, logout as apiLogout, register as apiRegister, setAuthTokenGetter } from '@workspace/api-client-react';
import type { Me, UserRole } from '@workspace/api-client-react';

const TOKEN_STORAGE_KEY = 'caresense.access_token';

/**
 * Canonical permission codes, mirroring the backend's registry
 * (`apps/accounts/permissions.py`). The server is always the authority; these
 * are used only to decide which controls are worth showing.
 */
export const PERM = {
  // Patient (self scope)
  PATIENT_READ_OWN: 'patient.read.own',
  REPORT_READ_OWN: 'report.read.own',
  REPORT_UPLOAD_OWN: 'report.upload.own',
  RISK_REQUEST_OWN: 'risk.request.own',
  APPOINTMENT_BOOK: 'appointment.book',
  // Doctor
  PATIENT_READ_ASSIGNED: 'patient.read.assigned',
  REPORT_READ_ASSIGNED: 'report.read.assigned',
  CLINICAL_NOTE_CREATE: 'clinical_note.create',
  RISK_REQUEST: 'risk.request',
  ALERT_MANAGE: 'alert.manage',
  AI_USE: 'ai.use',
  APPOINTMENT_MANAGE: 'appointment.manage',
  // Lab technician
  LAB_WORKFLOW_ACCESS: 'lab.workflow.access',
  LAB_REPORT_UPLOAD: 'lab.report.upload',
  LAB_RESULT_ENTER: 'lab.result.enter',
  LAB_RESULT_VALIDATE: 'lab.result.validate',
  RISK_REVIEW: 'risk.review',
  // Staff / registration
  PATIENT_REGISTER: 'patient.register',
  // Admin
  USERS_MANAGE: 'users.manage',
  STAFF_MANAGE: 'staff.manage',
  AUDIT_READ: 'audit.read',
  RECONCILIATION_MANAGE: 'reconciliation.manage',
  PATIENT_IDENTITY_MANAGE: 'patient.identity.manage',
  MODEL_GOVERNANCE_MANAGE: 'model.governance.manage',
} as const;

interface AuthContextValue {
  user: Me | null;
  isLoading: boolean;
  error: string | null;
  /** The server could not be reached while restoring a session. The token is
   *  kept - a network blip is not a reason to sign someone out. */
  unreachable: boolean;
  /** A stored session was refused by the server (expired or revoked). */
  sessionEnded: boolean;
  /** Try restoring the session again after `unreachable`. */
  retryConnection: () => void;
  login: (email: string, password: string) => Promise<void>;
  /** Public patient sign-up. Creates a login, never a clinical record. */
  register: (details: RegisterDetails) => Promise<void>;
  logout: () => Promise<void>;
  /** True once the caller holds every permission code listed. */
  hasPermission: (...codes: string[]) => boolean;
  /** True once the caller holds at least one of the permission codes listed. */
  hasAnyPermission: (...codes: string[]) => boolean;
  /** True when the caller holds at least one of the roles listed. */
  hasRole: (...roles: UserRole[]) => boolean;
}

export interface RegisterDetails {
  email: string;
  fullName: string;
  password: string;
  /** Age is a model input; without it the risk engine blocks rather than guess. */
  dateOfBirth?: string;
  sex?: 'FEMALE' | 'MALE' | 'INTERSEX' | 'UNKNOWN';
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    // Private browsing / storage disabled: fall back to session-only auth.
    return null;
  }
}

function writeStoredToken(token: string | null): void {
  try {
    if (token) {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // Ignore - the session still works for the current tab via memory state.
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => readStoredToken());
  const [user, setUser] = useState<Me | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [sessionEnded, setSessionEnded] = useState(false);
  const [attempt, setAttempt] = useState(0);

  // The token getter is read fresh on every request (see custom-fetch.ts),
  // so a logout/login mid-session is picked up without re-registering it.
  useEffect(() => {
    setAuthTokenGetter(() => token);
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    async function restore() {
      if (!token) {
        setIsLoading(false);
        return;
      }
      try {
        const me = await getMe();
        if (!cancelled) {
          setUser(me);
          setUnreachable(false);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status < 500) {
          // A stale/expired/revoked token fails closed: drop it and require a
          // fresh login rather than showing a half-authenticated app.
          setToken(null);
          writeStoredToken(null);
          setSessionEnded(true);
          setUnreachable(false);
        } else {
          // No answer, or the server failed. Say so, and keep the session for
          // when it comes back.
          setUnreachable(true);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    void restore();
    return () => {
      cancelled = true;
    };
    // Only re-run when the token identity changes, or on an explicit retry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, attempt]);

  const retryConnection = useCallback(() => {
    setIsLoading(true);
    setAttempt((n) => n + 1);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setError(null);
    setSessionEnded(false);
    try {
      const issued = await apiLogin({ email, password });
      writeStoredToken(issued.access_token);
      // Update the getter synchronously: `setToken` below only takes effect
      // on the next render, and the immediate `getMe()` call must not race
      // it with the previous (absent) token.
      setAuthTokenGetter(() => issued.access_token);
      setToken(issued.access_token);
      const me = await getMe();
      setUser(me);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.status === 401 || err.status === 400
            ? 'Incorrect email or password.'
            : err.message
          : 'Unable to reach CareSense. Check your connection and try again.';
      setError(message);
      throw err;
    }
  }, []);

  const register = useCallback(async (details: RegisterDetails) => {
    setError(null);
    try {
      const issued = await apiRegister({
        email: details.email,
        full_name: details.fullName,
        password: details.password,
        date_of_birth: details.dateOfBirth || null,
        sex: details.sex,
      });
      writeStoredToken(issued.access_token);
      setAuthTokenGetter(() => issued.access_token);
      setToken(issued.access_token);
      const me = await getMe();
      setUser(me);
    } catch (err) {
      // The server deliberately refuses to confirm whether an address is
      // already registered, so pass its wording through rather than guessing.
      const message =
        err instanceof ApiError
          ? err.status === 400
            ? err.message.replace(/^HTTP 400[^:]*:\s*/, '')
            : err.message
          : 'Unable to reach CareSense. Check your connection and try again.';
      setError(message);
      throw err;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // Revocation is best-effort from the client's point of view - the
      // local session ends either way.
    }
    writeStoredToken(null);
    setToken(null);
    setUser(null);
  }, []);

  const hasPermission = useCallback(
    (...codes: string[]) => codes.every((code) => user?.permissions.includes(code)),
    [user],
  );

  const hasAnyPermission = useCallback(
    (...codes: string[]) => codes.some((code) => user?.permissions.includes(code)),
    [user],
  );

  const hasRole = useCallback(
    (...roles: UserRole[]) => roles.some((role) => user?.roles.includes(role)),
    [user],
  );

  const value = useMemo<AuthContextValue>(
    () => ({ user, isLoading, error, unreachable, sessionEnded, retryConnection, login, register, logout, hasPermission, hasAnyPermission, hasRole }),
    [user, isLoading, error, unreachable, sessionEnded, retryConnection, login, register, logout, hasPermission, hasAnyPermission, hasRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
