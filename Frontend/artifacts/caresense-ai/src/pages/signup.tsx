import { useState, type FormEvent } from 'react';
import { AlertCircle, HeartPulse, Loader2, UserPlus } from 'lucide-react';
import { useAuth } from '@/lib/auth';

/**
 * Public sign-up.
 *
 * Creates the person's own account and their own health record in one step -
 * this is the self-service entry point. It never resolves onto an existing
 * record belonging to someone else; attaching an account to a pre-existing
 * clinical record stays a staff decision made after verification.
 */
export default function SignUp({ onShowLogin }: { onShowLogin: () => void }) {
  const { register, error } = useAuth();
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [dateOfBirth, setDateOfBirth] = useState('');
  const [sex, setSex] = useState<'FEMALE' | 'MALE' | 'INTERSEX' | 'UNKNOWN'>('UNKNOWN');
  const [localError, setLocalError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLocalError(null);
    if (password !== confirm) {
      setLocalError('Both passwords must match.');
      return;
    }
    if (password.length < 12) {
      setLocalError('Use at least 12 characters.');
      return;
    }
    setSubmitting(true);
    try {
      await register({ email, fullName, password, dateOfBirth, sex });
    } catch {
      // Surfaced via the shared `error` state from useAuth.
    } finally {
      setSubmitting(false);
    }
  }

  const message = localError || error;

  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <span className="grid size-12 place-items-center rounded-2xl bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]">
            <HeartPulse size={24} strokeWidth={2.5} />
          </span>
          <h1 className="mt-4 text-2xl font-semibold tracking-[-.03em]">Create your account</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Upload your results, see what they indicate, and book a clinician if you need one.
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-border bg-card p-6 shadow-sm"
          data-testid="form-signup"
        >
          <div className="space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-muted-foreground">Full name</span>
              <input
                type="text"
                required
                autoComplete="name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Alex Morgan"
                className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                data-testid="input-signup-name"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-muted-foreground">Email</span>
              <input
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                data-testid="input-signup-email"
              />
            </label>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold text-muted-foreground">Date of birth</span>
                <input
                  type="date"
                  value={dateOfBirth}
                  onChange={(e) => setDateOfBirth(e.target.value)}
                  className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  data-testid="input-signup-dob"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold text-muted-foreground">Sex</span>
                <select
                  value={sex}
                  onChange={(e) => setSex(e.target.value as typeof sex)}
                  className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  data-testid="select-signup-sex"
                >
                  <option value="UNKNOWN">Prefer not to say</option>
                  <option value="FEMALE">Female</option>
                  <option value="MALE">Male</option>
                  <option value="INTERSEX">Intersex</option>
                </select>
              </label>
            </div>
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              Your age is used as an input to the analysis. Leave it blank and some results
              cannot be calculated — the system will say so rather than estimate.
            </p>
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-muted-foreground">Password</span>
              <input
                type="password"
                required
                minLength={12}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 12 characters"
                className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                data-testid="input-signup-password"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-muted-foreground">Confirm password</span>
              <input
                type="password"
                required
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="Repeat your password"
                className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                data-testid="input-signup-confirm"
              />
            </label>
          </div>

          {message && (
            <div
              className="mt-4 flex items-start gap-2 rounded-xl bg-[hsl(var(--destructive)/.08)] px-3 py-2.5 text-xs text-[hsl(var(--destructive))]"
              data-testid="text-signup-error"
            >
              <AlertCircle size={15} className="mt-0.5 shrink-0" />
              <span>{message}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-5 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary text-sm font-semibold text-primary-foreground disabled:opacity-60"
            data-testid="button-signup-submit"
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : <UserPlus size={15} />}
            {submitting ? 'Creating account…' : 'Create account'}
          </button>

          <p className="mt-4 text-center text-xs text-muted-foreground">
            Already have an account?{' '}
            <button
              type="button"
              onClick={onShowLogin}
              className="font-semibold text-foreground underline-offset-2 hover:underline"
              data-testid="link-to-login"
            >
              Sign in
            </button>
          </p>
        </form>

        <p className="mt-6 text-center text-xs leading-relaxed text-muted-foreground">
          You get your own private record. Any analysis is decision support with its limits shown
          - it is not a diagnosis, and it does not replace a clinician.
        </p>
      </div>
    </div>
  );
}
