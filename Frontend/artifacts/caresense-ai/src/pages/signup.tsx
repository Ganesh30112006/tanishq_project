import { useState, type FormEvent } from 'react';
import { AlertCircle, Loader2, UserPlus } from 'lucide-react';
import { useGetConsentDocuments } from '@workspace/api-client-react';
import type { ConsentPurposeCode } from '@workspace/api-client-react';
import { AiLimitsNote } from '@/components/ai-limits-note';
import { AuthLayout } from '@/components/auth-layout';
import { useAuth } from '@/lib/auth';

/** Whole years between a YYYY-MM-DD birth date and today. */
function ageOn(dateOfBirth: string, today: string): number {
  const [by, bm, bd] = dateOfBirth.split('-').map(Number);
  const [ty, tm, td] = today.split('-').map(Number);
  return ty - by - (tm < bm || (tm === bm && td < bd) ? 1 : 0);
}

/** Today's date as YYYY-MM-DD in the person's own time zone. */
function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

const FIELD = 'h-12 w-full rounded-lg border border-input bg-card px-3.5 text-[16px] outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-ring';

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
  const [agreed, setAgreed] = useState(false);
  // Optional purposes start unticked: agreement has to be a choice, not a default.
  const [chosen, setChosen] = useState<Set<ConsentPurposeCode>>(new Set());
  const documentsQuery = useGetConsentDocuments();
  const documents = documentsQuery.data?.documents ?? [];
  const toggle = (purpose: ConsentPurposeCode, on: boolean) =>
    setChosen((prev) => {
      const next = new Set(prev);
      if (on) next.add(purpose); else next.delete(purpose);
      return next;
    });
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
    // Mirrors the server's check so the reason is shown in plain words.
    if (dateOfBirth && dateOfBirth > todayIso()) {
      setLocalError('Date of birth cannot be in the future.');
      return;
    }
    if (dateOfBirth && new Date().getFullYear() - Number(dateOfBirth.slice(0, 4)) > 130) {
      setLocalError('Please check the year of birth.');
      return;
    }
    if (dateOfBirth && ageOn(dateOfBirth, todayIso()) < 18) {
      setLocalError('CareSense is for people aged 18 and over. We cannot create an account for anyone younger.');
      return;
    }
    if (!agreed) {
      setLocalError('Please confirm you are 18 or older and have read the privacy policy.');
      return;
    }
    const missing = documents.find((d) => d.is_essential && !chosen.has(d.purpose));
    if (missing) {
      setLocalError(`Please agree to "${missing.label}". We cannot keep your reports without it.`);
      return;
    }
    setSubmitting(true);
    try {
      await register({ email, fullName, password, dateOfBirth, sex, confirmsAdult: agreed, consents: [...chosen] });
    } catch {
      // Surfaced via the shared `error` state from useAuth.
    } finally {
      setSubmitting(false);
    }
  }

  const message = localError || error;

  return (
    <AuthLayout>
      <p className="mono-label text-[hsl(var(--brand))]">Create account</p>
      <h1 className="mt-3 text-[40px] leading-[1.05]">Start with one report</h1>
      <p className="mt-3 text-[16px] leading-relaxed text-muted-foreground">Make your free account, upload a lab report, and our AI will explain what it shows in simple words.</p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-5" data-testid="form-signup">
        <label className="block">
          <span className="mb-1.5 block text-[13px] font-bold">Full name</span>
          <input type="text" required autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} className={FIELD} data-testid="input-signup-name" />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-[13px] font-bold">Email</span>
          <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className={FIELD} data-testid="input-signup-email" />
        </label>

        <fieldset className="rounded-lg border border-border p-4">
          <legend className="px-1 text-[13px] font-bold">About you <span className="font-normal text-muted-foreground">(optional)</span></legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-[13px] font-bold">Date of birth</span>
              <input type="date" max={todayIso()} value={dateOfBirth} onChange={(e) => setDateOfBirth(e.target.value)} className={FIELD} data-testid="input-signup-dob" />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-[13px] font-bold">Sex</span>
              <select value={sex} onChange={(e) => setSex(e.target.value as typeof sex)} className={FIELD} data-testid="select-signup-sex">
                <option value="UNKNOWN">Prefer not to say</option>
                <option value="FEMALE">Female</option>
                <option value="MALE">Male</option>
                <option value="INTERSEX">Intersex</option>
              </select>
            </label>
          </div>
          <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">Many normal ranges depend on age and sex. Without them our AI uses wider ranges and tells you so - it never guesses.</p>
        </fieldset>

        <label className="block">
          <span className="mb-1.5 block text-[13px] font-bold">Password</span>
          <input type="password" required minLength={12} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} className={FIELD} aria-describedby="password-hint" data-testid="input-signup-password" />
          <span id="password-hint" className="mt-1.5 block text-[13px] text-muted-foreground">At least 12 characters.</span>
        </label>
        <label className="block">
          <span className="mb-1.5 block text-[13px] font-bold">Confirm password</span>
          <input type="password" required autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} className={FIELD} data-testid="input-signup-confirm" />
        </label>

        <AiLimitsNote />

        <label className="flex items-start gap-3 rounded-lg bg-secondary/60 p-4 text-[14px] leading-relaxed">
          <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-1 size-[18px] shrink-0 accent-[hsl(var(--brand))]" data-testid="checkbox-signup-privacy" />
          <span>I am 18 or older, and I have read the <a href="/privacy" target="_blank" rel="noreferrer" className="font-bold text-[hsl(var(--brand))] underline underline-offset-4">privacy policy</a>.</span>
        </label>

        {documents.length > 0 && (
          <fieldset className="space-y-3 rounded-lg border border-border p-4" data-testid="fieldset-signup-consents">
            <legend className="px-1 text-[13px] font-bold">What you allow us to do</legend>
            <p className="text-[13px] leading-relaxed text-muted-foreground">You can change any of these later in Settings.</p>
            {documents.map((doc) => (
              <label key={doc.purpose} className="flex items-start gap-3 text-[14px] leading-relaxed">
                <input type="checkbox" checked={chosen.has(doc.purpose)} onChange={(e) => toggle(doc.purpose, e.target.checked)} className="mt-1 size-[18px] shrink-0 accent-[hsl(var(--brand))]" data-testid={`checkbox-consent-${doc.purpose}`} />
                <span>
                  <strong>{doc.label}</strong>{doc.is_essential ? <span className="text-muted-foreground"> (needed to use CareSense)</span> : <span className="text-muted-foreground"> (optional)</span>}
                  <span className="mt-0.5 block whitespace-pre-line text-[13px] text-muted-foreground">{doc.body}</span>
                </span>
              </label>
            ))}
          </fieldset>
        )}

        {message && (
          <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--destructive)/.3)] bg-[hsl(var(--destructive)/.06)] px-3.5 py-3 text-sm text-[hsl(var(--destructive))]" role="alert" data-testid="text-signup-error">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <span>{message}</span>
          </div>
        )}

        <button type="submit" disabled={submitting} className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-lg bg-primary text-[15px] font-bold text-primary-foreground transition-[filter,transform] hover:brightness-110 active:translate-y-px disabled:opacity-60" data-testid="button-signup-submit">
          {submitting ? <Loader2 size={17} className="animate-spin" /> : <UserPlus size={16} />}
          {submitting ? 'Creating account…' : 'Create account'}
        </button>
      </form>

      <p className="mt-8 text-[15px]">
        Already have an account?{' '}
        <button type="button" onClick={onShowLogin} className="font-bold text-[hsl(var(--brand))] underline-offset-4 hover:underline" data-testid="link-to-login">Sign in</button>
      </p>
    </AuthLayout>
  );
}
