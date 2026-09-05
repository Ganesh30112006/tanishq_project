import { useState, type FormEvent } from 'react';
import { AlertCircle, HeartPulse, Loader2, LockKeyhole } from 'lucide-react';
import { useAuth } from '@/lib/auth';

export default function Login({ onShowSignUp }: { onShowSignUp?: () => void }) {
  const { login, error } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await login(email, password);
    } catch {
      // Surfaced via the shared `error` state from useAuth.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <span className="grid size-12 place-items-center rounded-2xl bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]">
            <HeartPulse size={24} strokeWidth={2.5} />
          </span>
          <h1 className="mt-4 text-2xl font-semibold tracking-[-.03em]">CareSense</h1>
          <p className="mt-1 text-sm text-muted-foreground">Clinical intelligence, signed in securely.</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-border bg-card p-6 shadow-sm"
          data-testid="form-login"
        >
          <div className="space-y-4">
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
                data-testid="input-email"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-muted-foreground">Password</span>
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                data-testid="input-password"
              />
            </label>
          </div>

          {error && (
            <div
              className="mt-4 flex items-start gap-2 rounded-xl bg-[hsl(var(--destructive)/.08)] px-3 py-2.5 text-xs text-[hsl(var(--destructive))]"
              data-testid="text-login-error"
            >
              <AlertCircle size={15} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-5 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary text-sm font-semibold text-primary-foreground disabled:opacity-60"
            data-testid="button-login-submit"
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : <LockKeyhole size={15} />}
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
          {onShowSignUp && (
            <p className="mt-4 text-center text-xs text-muted-foreground">
              New patient?{' '}
              <button
                type="button"
                onClick={onShowSignUp}
                className="font-semibold text-foreground underline-offset-2 hover:underline"
                data-testid="link-to-signup"
              >
                Create an account
              </button>
            </p>
          )}
        </form>

        <p className="mt-6 text-center text-xs leading-relaxed text-muted-foreground">
          Clinical and administrative access is granted per account by CareSense. Please contact your
          administrator if you need credentials or your role has changed.
        </p>
      </div>
    </div>
  );
}
