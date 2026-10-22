/**
 * Shared presentation primitives and clinical value formatting.
 *
 * Extracted from `App.tsx` so the admin console can reuse the same building
 * blocks without importing the router module back into itself.
 */
import { ApiError } from '@workspace/api-client-react';
import { AlertCircle, ChevronLeft, ChevronRight, Loader2, RefreshCw, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { NoAccessErrorPage } from './error-page';

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

// Each palette is one token at two strengths - a tinted fill and the full
// colour for the text - so light and dark mode stay in step automatically.
// These used to be pairs of unrelated hard-coded values with no dark-mode
// counterpart at all.
export const NEUTRAL_BADGE = 'bg-secondary text-muted-foreground ring-border';
export const POSITIVE_BADGE = 'bg-[hsl(var(--success)/.10)] text-[hsl(var(--success))] ring-[hsl(var(--success)/.28)]';
export const ATTENTION_BADGE = 'bg-[hsl(var(--accent)/.2)] text-[hsl(var(--accent-foreground))] ring-[hsl(var(--accent)/.5)]';
export const CRITICAL_BADGE = 'bg-[hsl(var(--destructive)/.08)] text-[hsl(var(--destructive))] ring-[hsl(var(--destructive)/.3)]';

export const FIELD_CLASS =
  'h-11 w-full rounded-lg border border-input bg-card px-3 text-[15px] outline-none transition-colors placeholder:text-muted-foreground focus:border-ring';

// ---------------------------------------------------------------------------
// Layout primitives
// ---------------------------------------------------------------------------

export function Badge({ children, className = '' }: { children: ReactNode; className?: string }) {
  // A filed tag rather than a pill: squared, hairline-ringed, the ring taking
  // the tint of whichever palette is passed in.
  return <span className={`inline-flex items-center rounded-[4px] px-2 py-px text-[12px] font-bold leading-5 ring-1 ring-inset ring-border ${className}`}>{children}</span>;
}

export function PageHeading({ eyebrow, title, detail, action }: { eyebrow: string; title: string; detail?: string; action?: ReactNode }) {
  // The eyebrow arrives as "CareSense / reports"; only the last part is the
  // page's own name, filed like a section mark above a document title.
  const section = eyebrow.split('/').pop()?.trim() || eyebrow;
  return <div className="mb-9 border-b border-border pb-7"><div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end"><div className="min-w-0"><p className="mono-label flex items-center gap-2 text-[hsl(var(--brand))]"><span aria-hidden="true">§</span>{section}</p><h1 className="mt-3 text-[34px] leading-[1.08] text-foreground sm:text-[46px]">{title}</h1>{detail && <p className="mt-3 max-w-2xl text-[16px] leading-relaxed text-muted-foreground">{detail}</p>}</div>{action ? <div className="shrink-0">{action}</div> : null}</div></div>;
}

export function SectionTitle({ eyebrow, title, id, action }: { eyebrow: string; title: string; id: string; action?: ReactNode }) {
  return <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-4 sm:px-6"><div><p className="mono-label text-muted-foreground">{eyebrow}</p><h2 id={id} className="mt-1 text-[22px] leading-tight">{title}</h2></div>{action}</div>;
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-secondary ${className}`} aria-hidden="true" />;
}

export function PageLoading() {
  return <div className="space-y-6" aria-label="Loading"><div className="space-y-3"><Skeleton className="h-3 w-24" /><Skeleton className="h-10 w-64" /></div><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><Skeleton className="h-32" /><Skeleton className="h-32" /><Skeleton className="h-32" /><Skeleton className="h-32" /></div><Skeleton className="h-80 w-full" /></div>;
}

export function QueryError({ onRetry, message = 'We could not load this workspace.', error }: { onRetry: () => void; message?: string; error?: unknown }) {
  // Not found / not yours is a final answer: trying again will not change it.
  const missing = error instanceof ApiError && (error.status === 404 || error.status === 403);
  const detail = missing
    ? 'We could not find it. The link may be old, or it may not be on your account.'
    : 'This is usually a passing connection problem. Nothing on your record has changed.';
  return <div className="flex flex-col gap-5 rounded-2xl border border-border border-l-[3px] border-l-[hsl(var(--destructive))] bg-card px-6 py-7 sm:flex-row sm:items-center sm:justify-between" role="alert"><div className="flex items-start gap-3"><AlertCircle className="mt-1 shrink-0 text-[hsl(var(--destructive))]" size={20} /><div><h2 className="text-[22px] leading-snug">{message}</h2><p className="mt-1 max-w-md text-[15px] text-muted-foreground">{detail}</p></div></div>{missing ? null : <button onClick={onRetry} className="inline-flex h-11 shrink-0 items-center gap-2 self-start rounded-lg bg-primary px-4 text-sm font-bold text-primary-foreground hover:brightness-110 sm:self-center" data-testid="button-retry"><RefreshCw size={15} />Try again</button>}</div>;
}

export function EmptyState({ icon: Icon, title, detail }: { icon: typeof AlertCircle; title: string; detail: string }) {
  return <div className="flex flex-col items-center justify-center px-6 py-14 text-center"><span className="grid size-12 place-items-center rounded-full border border-dashed border-[hsl(var(--brand)/.45)] text-[hsl(var(--brand))]"><Icon size={19} /></span><h3 className="font-display mt-4 text-xl font-medium">{title}</h3><p className="mt-1 max-w-xs text-sm leading-relaxed text-muted-foreground">{detail}</p></div>;
}

/** A page this account is not allowed to open - see components/error-page. */
export function NoAccessPage({ title, detail }: { title: string; detail: string }) {
  return <NoAccessErrorPage title={title} detail={detail} />;
}

export function InlineUnavailable({ label }: { label: string }) {
  return <div className="flex items-center gap-2 rounded-lg border border-dashed border-border bg-secondary/50 px-4 py-3 text-sm text-muted-foreground"><AlertCircle size={16} className="shrink-0" />{label}</div>;
}

export function PageButton({ page, pageSize, count, onChange }: { page: number; pageSize: number; count: number; onChange: (page: number) => void }) {
  const numPages = Math.max(1, Math.ceil(count / pageSize));
  if (numPages <= 1) return null;
  return (
    <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
      <span>Page {page} of {numPages} · {count} total</span>
      <div className="flex items-center gap-2">
        <button onClick={() => onChange(page - 1)} disabled={page <= 1} className="inline-flex h-10 items-center gap-1 rounded-lg border border-input bg-card px-3 font-bold disabled:opacity-40" data-testid="button-page-prev"><ChevronLeft size={14} />Prev</button>
        <button onClick={() => onChange(page + 1)} disabled={page >= numPages} className="inline-flex h-10 items-center gap-1 rounded-lg border border-input bg-card px-3 font-bold disabled:opacity-40" data-testid="button-page-next">Next<ChevronRight size={14} /></button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dialog + form primitives
// ---------------------------------------------------------------------------

export function Modal({ title, description, onClose, children }: { title: string; description?: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[hsl(222_40%_8%/.55)] backdrop-blur-[2px] sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="page-enter max-h-[92dvh] w-full max-w-lg overflow-y-auto rounded-t-2xl border border-border border-t-[3px] border-t-[hsl(var(--brand))] bg-card p-5 shadow-2xl sm:rounded-2xl sm:p-7">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-[24px] leading-tight">{title}</h2>
            {description && <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{description}</p>}
          </div>
          <button onClick={onClose} aria-label="Close dialog" className="shrink-0 rounded-lg p-1.5 text-muted-foreground hover:bg-secondary" data-testid="button-modal-close"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function FormField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="block"><span className="mb-1.5 block text-[13px] font-bold text-foreground/85">{label}</span>{children}{hint ? <span className="mt-1.5 block text-[12.5px] leading-relaxed text-muted-foreground">{hint}</span> : null}</label>;
}

export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : 'Something went wrong. Please try again.';
  return <div className="mt-4 flex items-start gap-2 rounded-lg border border-[hsl(var(--destructive)/.3)] bg-[hsl(var(--destructive)/.06)] px-3 py-2.5 text-[13px] text-[hsl(var(--destructive))]" role="alert" data-testid="text-form-error"><AlertCircle size={15} className="mt-0.5 shrink-0" /><span>{message}</span></div>;
}

export function ModalActions({ onClose, submitting, disabled = false, submitLabel = 'Save' }: { onClose: () => void; submitting: boolean; disabled?: boolean; submitLabel?: string }) {
  return (
    <div className="mt-5 flex items-center justify-end gap-2">
      <button type="button" onClick={onClose} className="inline-flex h-11 items-center rounded-lg border border-input bg-card px-4 text-sm font-bold transition-colors hover:bg-secondary" data-testid="button-modal-cancel">Cancel</button>
      <button type="submit" disabled={submitting || disabled} className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-5 text-sm font-bold text-primary-foreground transition-[filter,transform] hover:brightness-110 active:translate-y-px disabled:opacity-60" data-testid="button-modal-submit">{submitting && <Loader2 size={15} className="animate-spin" />}{submitLabel}</button>
    </div>
  );
}

export function ActionButton({ icon: Icon, label, onClick, variant = 'ghost', disabled = false }: { icon: typeof AlertCircle; label: string; onClick: () => void; variant?: 'ghost' | 'primary' | 'danger'; disabled?: boolean }) {
  const base = 'inline-flex h-11 items-center gap-2 rounded-lg px-4 text-sm font-bold transition-[background-color,filter,transform] active:translate-y-px disabled:opacity-50';
  const style = variant === 'primary'
    ? 'bg-primary text-primary-foreground hover:brightness-110'
    : variant === 'danger'
      ? 'border border-[hsl(var(--destructive)/.35)] text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/.07)]'
      : 'border border-input bg-card hover:bg-secondary';
  return <button type="button" onClick={onClick} disabled={disabled} className={`${base} ${style}`} data-testid={`button-action-${label.toLowerCase().replace(/\s+/g, '-')}`}><Icon size={15} />{label}</button>;
}
