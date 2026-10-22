import { useState, type FormEvent } from 'react';
import { AlertCircle, Clock3, Loader2, LockKeyhole } from 'lucide-react';
import { AuthLayout } from '@/components/auth-layout';
import { useAuth } from '@/lib/auth';

const FIELD = 'h-12 w-full rounded-lg border border-input bg-card px-3.5 text-[16px] outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-ring';

export default function Login({ onShowSignUp }: { onShowSignUp?: () => void }) {
  const { login, error, sessionEnded } = useAuth();
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
    <AuthLayout>
      <p className="mono-label text-[hsl(var(--brand))]">Sign in</p>
      <h1 className="mt-3 text-[40px] leading-[1.05]">Welcome back</h1>
      <p className="mt-3 text-[16px] leading-relaxed text-muted-foreground">Sign in to see your reports and what our AI found in them.</p>

      {sessionEnded && (
        <div className="mt-6 flex items-start gap-2.5 rounded-lg border border-border bg-secondary/60 px-4 py-3 text-sm" role="status" data-testid="text-session-ended">
          <Clock3 size={16} className="mt-0.5 shrink-0 text-muted-foreground" />
          <span>Your session ended, so we signed you out to keep your record safe. Please sign in again.</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="mt-8 space-y-5" data-testid="form-login">
        <label className="block">
          <span className="mb-1.5 block text-[13px] font-bold">Email</span>
          <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className={FIELD} data-testid="input-email" />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-[13px] font-bold">Password</span>
          <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={FIELD} data-testid="input-password" />
        </label>

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--destructive)/.3)] bg-[hsl(var(--destructive)/.06)] px-3.5 py-3 text-sm text-[hsl(var(--destructive))]" role="alert" data-testid="text-login-error">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <button type="submit" disabled={submitting} className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-lg bg-primary text-[15px] font-bold text-primary-foreground transition-[filter,transform] hover:brightness-110 active:translate-y-px disabled:opacity-60" data-testid="button-login-submit">
          {submitting ? <Loader2 size={17} className="animate-spin" /> : <LockKeyhole size={16} />}
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>

      {onShowSignUp && (
        <div className="mt-8 rounded-lg border border-dashed border-border px-4 py-4 text-[15px]">
          New to CareSense?{' '}
          <button type="button" onClick={onShowSignUp} className="font-bold text-[hsl(var(--brand))] underline-offset-4 hover:underline" data-testid="link-to-signup">Create a free account</button>
          <p className="mt-1 text-[13px] text-muted-foreground">Anyone can sign up. It takes about a minute.</p>
        </div>
      )}
    </AuthLayout>
  );
}
