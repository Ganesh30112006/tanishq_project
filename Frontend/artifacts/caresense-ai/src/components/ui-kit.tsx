/**
 * Shared presentation primitives and clinical value formatting.
 *
 * Extracted from `App.tsx` so the admin console can reuse the same building
 * blocks without importing the router module back into itself.
 */
import { AlertCircle, ChevronLeft, ChevronRight, Loader2, Lock, RefreshCw, X } from 'lucide-react';
import type { ReactNode } from 'react';

// ---------------------------------------------------------------------------
// Value formatting
// ---------------------------------------------------------------------------

// Clinical shorthand that must stay upper-case: title-casing turns "CVD" into
// "Cvd" and "HDL" into "Hdl", which reads as a different (wrong) term.
const ACRONYMS = new Set([
  'CVD', 'BMI', 'BP', 'HDL', 'LDL', 'MRN', 'WBC', 'RBC', 'CBC', 'HBA1C', 'A1C',
  'SPO2', 'EGFR', 'LOINC', 'OCR', 'AI', 'ID', 'IQR', 'MAD', 'OOD', 'SHAP',
]);

// Enum codes come off the API in American spelling. Humanising them here is
// the only place they become words a person reads, so the spelling pass has to
// happen here too - otherwise a filter says "Finalized" next to a metric that
// says "Finalised".
const SPELLINGS: Record<string, string> = {
  Finalized: 'Finalised',
  Normalized: 'Normalised',
  Unauthorized: 'Unauthorised',
  Authorized: 'Authorised',
  Cancelled: 'Cancelled',
  Canceled: 'Cancelled',
  Analyzed: 'Analysed',
  Prioritized: 'Prioritised',
  Summarized: 'Summarised',
};

export const titleCase = (value?: string | null) =>
  (value || '')
    .replace(/_/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => {
      const upper = word.toUpperCase();
      if (ACRONYMS.has(upper)) return upper;
      const cased = upper.charAt(0) + word.slice(1).toLowerCase();
      return SPELLINGS[cased] ?? cased;
    })
    .join(' ');

export const shortDate = (value?: string | null) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
};

export const dateTime = (value?: string | null) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date);
};

export const relativeTime = (value?: string | null) => {
  if (!value) return 'Recently';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const minutes = Math.max(1, Math.floor((Date.now() - date.getTime()) / 60000));
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} hr ago`;
  return `${Math.floor(minutes / 1440)} d ago`;
};

/**
 * Clinical values arrive as fixed-precision decimal strings ("29.000000"), so
 * printing them raw shows a precision the measurement never had.
 */
export const formatValue = (value?: string | number | null) => {
  if (value === null || value === undefined || value === '') return '—';
  const num = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return String(Number(num.toFixed(4)));
};

/** MRNs are often already prefixed ("MRN-DEMO-1001"); don't print "MRN MRN-…". */
export const formatMrn = (mrn?: string | null) => {
  if (!mrn) return '—';
  return /^mrn/i.test(mrn) ? mrn : `MRN ${mrn}`;
};

// ---------------------------------------------------------------------------
// Badge palettes
// ---------------------------------------------------------------------------

export const NEUTRAL_BADGE = 'bg-secondary text-muted-foreground';
export const POSITIVE_BADGE = 'bg-[hsl(162_28%_90%)] text-[hsl(162_42%_28%)]';
export const ATTENTION_BADGE = 'bg-[hsl(var(--accent)/.22)] text-[hsl(30_48%_26%)]';
export const CRITICAL_BADGE = 'bg-[hsl(var(--destructive)/.1)] text-[hsl(var(--destructive))]';

export const FIELD_CLASS =
  'h-10 w-full rounded-xl border border-input bg-background px-3 text-sm outline-none focus:border-primary';

// ---------------------------------------------------------------------------
// Layout primitives
// ---------------------------------------------------------------------------

export function Badge({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <span className={`inline-flex items-center rounded-md px-2 py-1 text-[11px] font-semibold ${className}`}>{children}</span>;
}

export function PageHeading({ eyebrow, title, detail, action }: { eyebrow: string; title: string; detail?: string; action?: ReactNode }) {
  return <div className="mb-8 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><p className="mono-label text-muted-foreground">{eyebrow}</p><h1 className="mt-2 text-3xl font-semibold tracking-[-.04em] text-foreground sm:text-[38px]">{title}</h1>{detail && <p className="mt-2 max-w-2xl text-sm text-muted-foreground">{detail}</p>}</div>{action}</div>;
}

export function SectionTitle({ eyebrow, title, id, action }: { eyebrow: string; title: string; id: string; action?: ReactNode }) {
  return <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-4 sm:px-6"><div><p className="mono-label text-muted-foreground">{eyebrow}</p><h2 id={id} className="mt-1 text-lg font-semibold">{title}</h2></div>{action}</div>;
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-secondary ${className}`} aria-hidden="true" />;
}

export function PageLoading() {
  return <div className="space-y-6" aria-label="Loading"><div className="space-y-3"><Skeleton className="h-3 w-24" /><Skeleton className="h-10 w-64" /></div><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><Skeleton className="h-32" /><Skeleton className="h-32" /><Skeleton className="h-32" /><Skeleton className="h-32" /></div><Skeleton className="h-80 w-full" /></div>;
}

export function QueryError({ onRetry, message = 'We could not load this workspace.' }: { onRetry: () => void; message?: string }) {
  return <div className="flex flex-col items-center justify-center rounded-2xl border border-[hsl(var(--destructive)/.25)] bg-[hsl(var(--destructive)/.04)] px-6 py-16 text-center"><AlertCircle className="text-[hsl(var(--destructive))]" size={24} /><h2 className="mt-3 font-semibold">{message}</h2><p className="mt-1 max-w-sm text-sm text-muted-foreground">Check your session and connection, then try again.</p><button onClick={onRetry} className="mt-5 inline-flex min-h-10 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground" data-testid="button-retry"><RefreshCw size={15} />Try again</button></div>;
}

export function EmptyState({ icon: Icon, title, detail }: { icon: typeof AlertCircle; title: string; detail: string }) {
  return <div className="flex flex-col items-center justify-center px-6 py-14 text-center"><span className="grid size-11 place-items-center rounded-2xl bg-secondary text-muted-foreground"><Icon size={20} /></span><h3 className="mt-3 text-sm font-semibold">{title}</h3><p className="mt-1 text-xs text-muted-foreground">{detail}</p></div>;
}

/**
 * A page this account is not allowed to open.
 *
 * A bare heading over one grey line reads as a page that failed to load. This
 * says plainly that the page exists, that the account is not meant to use it,
 * and where to go instead - so nothing looks broken.
 */
export function NoAccessPage({ title, detail }: { title: string; detail: string }) {
  return <div className="page-enter flex min-h-[60vh] flex-col items-center justify-center px-6 text-center" data-testid="page-no-access">
    <span className="grid size-14 place-items-center rounded-2xl bg-secondary text-muted-foreground"><Lock size={24} /></span>
    <h1 className="mt-5 text-2xl font-semibold tracking-[-.03em]">{title}</h1>
    <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">{detail}</p>
    <a href="/" className="mt-6 inline-flex h-10 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground" data-testid="link-back-overview">Go to Overview</a>
  </div>;
}

export function InlineUnavailable({ label }: { label: string }) {
  return <div className="flex items-center gap-2 rounded-xl bg-secondary px-4 py-3 text-sm text-muted-foreground"><AlertCircle size={16} />{label}</div>;
}

export function PageButton({ page, pageSize, count, onChange }: { page: number; pageSize: number; count: number; onChange: (page: number) => void }) {
  const numPages = Math.max(1, Math.ceil(count / pageSize));
  if (numPages <= 1) return null;
  return (
    <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
      <span>Page {page} of {numPages} · {count} total</span>
      <div className="flex items-center gap-2">
        <button onClick={() => onChange(page - 1)} disabled={page <= 1} className="inline-flex h-8 items-center gap-1 rounded-lg border border-input bg-card px-2.5 font-medium disabled:opacity-40" data-testid="button-page-prev"><ChevronLeft size={14} />Prev</button>
        <button onClick={() => onChange(page + 1)} disabled={page >= numPages} className="inline-flex h-8 items-center gap-1 rounded-lg border border-input bg-card px-2.5 font-medium disabled:opacity-40" data-testid="button-page-next">Next<ChevronRight size={14} /></button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dialog + form primitives
// ---------------------------------------------------------------------------

export function Modal({ title, description, onClose, children }: { title: string; description?: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[hsl(var(--foreground)/.45)] sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="max-h-[92dvh] w-full max-w-lg overflow-y-auto rounded-t-2xl border border-border bg-card p-5 shadow-xl sm:rounded-2xl sm:p-6">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">{title}</h2>
            {description && <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p>}
          </div>
          <button onClick={onClose} aria-label="Close dialog" className="shrink-0 rounded-lg p-1.5 text-muted-foreground hover:bg-secondary" data-testid="button-modal-close"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function FormField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="block"><span className="mb-1.5 block text-xs font-semibold text-muted-foreground">{label}</span>{children}{hint ? <span className="mt-1 block text-[11px] text-muted-foreground">{hint}</span> : null}</label>;
}

export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : 'Something went wrong. Please try again.';
  return <div className="mt-4 flex items-start gap-2 rounded-xl bg-[hsl(var(--destructive)/.08)] px-3 py-2.5 text-xs text-[hsl(var(--destructive))]" data-testid="text-form-error"><AlertCircle size={15} className="mt-0.5 shrink-0" /><span>{message}</span></div>;
}

export function ModalActions({ onClose, submitting, disabled = false, submitLabel = 'Save' }: { onClose: () => void; submitting: boolean; disabled?: boolean; submitLabel?: string }) {
  return (
    <div className="mt-5 flex items-center justify-end gap-2">
      <button type="button" onClick={onClose} className="inline-flex h-10 items-center rounded-xl border border-input bg-card px-3 text-sm font-medium hover:bg-secondary" data-testid="button-modal-cancel">Cancel</button>
      <button type="submit" disabled={submitting || disabled} className="inline-flex h-10 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60" data-testid="button-modal-submit">{submitting && <Loader2 size={15} className="animate-spin" />}{submitLabel}</button>
    </div>
  );
}

export function ActionButton({ icon: Icon, label, onClick, variant = 'ghost', disabled = false }: { icon: typeof AlertCircle; label: string; onClick: () => void; variant?: 'ghost' | 'primary' | 'danger'; disabled?: boolean }) {
  const base = 'inline-flex h-10 items-center gap-2 rounded-xl px-3 text-sm font-medium disabled:opacity-50';
  const style = variant === 'primary'
    ? 'bg-primary text-primary-foreground'
    : variant === 'danger'
      ? 'border border-[hsl(var(--destructive)/.4)] text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/.06)]'
      : 'border border-input bg-card hover:bg-secondary';
  return <button type="button" onClick={onClick} disabled={disabled} className={`${base} ${style}`} data-testid={`button-action-${label.toLowerCase().replace(/\s+/g, '-')}`}><Icon size={15} />{label}</button>;
}
