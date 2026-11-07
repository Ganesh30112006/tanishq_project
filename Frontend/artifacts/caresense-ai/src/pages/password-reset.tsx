/**
 * Getting back into an account after forgetting the password. There is no
 * staff member to call, so without these pages a forgotten password would
 * lose someone every report they uploaded.
 */
import { useState, type FormEvent } from 'react';
import { AlertCircle, ArrowLeft, CheckCircle2, KeyRound, Loader2, MailCheck } from 'lucide-react';
import { useLocation } from 'wouter';
import { ApiError, confirmPasswordReset, requestPasswordReset } from '@workspace/api-client-react';
import { AuthLayout } from '@/components/auth-layout';

const FIELD = 'h-12 w-full rounded-lg border border-input bg-card px-3.5 text-[16px] outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-ring';
const BUTTON = 'inline-flex h-12 w-full items-center justify-center gap-2 rounded-lg bg-primary text-[15px] font-bold text-primary-foreground transition-[filter,transform] hover:brightness-110 active:translate-y-px disabled:opacity-60';

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message.replace(/^HTTP \d+[^:]*:\s*/, '');
  return 'We could not reach CareSense. Please check your internet and try again.';
}

function ErrorNote({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--destructive)/.3)] bg-[hsl(var(--destructive)/.06)] px-3.5 py-3 text-sm text-[hsl(var(--destructive))]" role="alert">
      <AlertCircle size={16} className="mt-0.5 shrink-0" />
      <span>{text}</span>
    </div>
  );
}

function BackToSignIn() {
  const [, navigate] = useLocation();
  return (
    <button type="button" onClick={() => navigate('/')} className="mt-8 inline-flex items-center gap-1.5 text-[15px] font-bold text-[hsl(var(--brand))] underline-offset-4 hover:underline" data-testid="link-back-to-sign-in">
      <ArrowLeft size={15} />Back to sign in
    </button>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await requestPasswordReset({ email });
      setSent(true);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout>
      <p className="mono-label text-[hsl(var(--brand))]">Forgot password</p>
      <h1 className="mt-3 text-[40px] leading-[1.05]">Reset your password</h1>
      {sent ? (
        <div className="mt-8 flex items-start gap-3 rounded-lg border border-border bg-secondary/60 px-4 py-4 text-[15px]" role="status" data-testid="text-reset-sent">
          <MailCheck size={18} className="mt-0.5 shrink-0 text-[hsl(var(--brand))]" />
          <span>If an account uses <strong>{email}</strong>, we have sent it a link to reset the password. The link works for one hour. Please also check your spam folder.</span>
        </div>
      ) : (
        <>
          <p className="mt-3 text-[16px] leading-relaxed text-muted-foreground">Enter the email you signed up with. We will send you a link to choose a new password.</p>
          <form onSubmit={handleSubmit} className="mt-8 space-y-5" data-testid="form-forgot-password">
            <label className="block">
              <span className="mb-1.5 block text-[13px] font-bold">Email</span>
              <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className={FIELD} data-testid="input-reset-email" />
            </label>
            {error && <ErrorNote text={error} />}
            <button type="submit" disabled={submitting} className={BUTTON} data-testid="button-send-reset">
              {submitting ? <Loader2 size={17} className="animate-spin" /> : <KeyRound size={16} />}
              {submitting ? 'Sending…' : 'Send reset link'}
            </button>
          </form>
        </>
      )}
      <BackToSignIn />
    </AuthLayout>
  );
}

export function ResetPassword() {
  const params = new URLSearchParams(window.location.search);
  const uid = params.get('uid') || '';
  const token = params.get('token') || '';
  const [password, setPassword] = useState('');
  const [again, setAgain] = useState('');
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (password !== again) {
      setError('The two passwords are not the same.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await confirmPasswordReset({ uid, token, password });
      setDone(true);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout>
      <p className="mono-label text-[hsl(var(--brand))]">New password</p>
      <h1 className="mt-3 text-[40px] leading-[1.05]">Choose a new password</h1>
      {!uid || !token ? (
        <div className="mt-8"><ErrorNote text="This link is not complete. Please open the link from the email again, or ask for a new one." /></div>
      ) : done ? (
        <div className="mt-8 flex items-start gap-3 rounded-lg border border-border bg-secondary/60 px-4 py-4 text-[15px]" role="status" data-testid="text-reset-done">
          <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-[hsl(var(--success))]" />
          <span>Your password has been changed, and you have been signed out on every device. Please sign in with the new password.</span>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="mt-8 space-y-5" data-testid="form-reset-password">
          <label className="block">
            <span className="mb-1.5 block text-[13px] font-bold">New password</span>
            <input type="password" required minLength={12} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} className={FIELD} data-testid="input-new-password" />
            <span className="mt-1.5 block text-[13px] text-muted-foreground">At least 12 characters. A short sentence is easy to remember.</span>
          </label>
          <label className="block">
            <span className="mb-1.5 block text-[13px] font-bold">Type it again</span>
            <input type="password" required minLength={12} autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} className={FIELD} data-testid="input-new-password-again" />
          </label>
          {error && <ErrorNote text={error} />}
          <button type="submit" disabled={submitting} className={BUTTON} data-testid="button-set-password">
            {submitting ? <Loader2 size={17} className="animate-spin" /> : <KeyRound size={16} />}
            {submitting ? 'Saving…' : 'Save new password'}
          </button>
        </form>
      )}
      <BackToSignIn />
    </AuthLayout>
  );
}
