/**
 * Error pages.
 *
 * Every state where the app cannot show what was asked for gets a page that
 * says, in plain words, what happened, whether anything on the person's record
 * changed (nothing ever does), and what they can do next. A page that only says
 * "Something went wrong" leaves a patient wondering whether their health data
 * is safe, which is the one question these pages must always answer.
 *
 * Deliberately free of router imports: the crash page renders when the router
 * itself may be what failed, so every link here is a plain anchor.
 */
import { CloudOff, Compass, Lock, RefreshCw, ServerCrash, WifiOff } from 'lucide-react';
import type { ReactNode } from 'react';

type ErrorPageProps = {
  /** The status code, shown large. Purely a label - never a technical detail. */
  code: string;
  label: string;
  title: string;
  detail: string;
  icon: typeof Compass;
  /** Shown as a short list under the explanation. */
  steps?: string[];
  actions?: ReactNode;
  /** Takes the whole screen: for pages shown outside the signed-in layout. */
  fullScreen?: boolean;
  testId?: string;
};

export function ErrorPage({ code, label, title, detail, icon: Icon, steps, actions, fullScreen = false, testId }: ErrorPageProps) {
  const body = (
    <div className="page-enter mx-auto w-full max-w-2xl" data-testid={testId}>
      <div className="relative overflow-hidden rounded-2xl border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-6 py-3">
          <span className="mono-label text-muted-foreground">CareSense · notice</span>
          <span className="mono-label text-[hsl(var(--brand))]">{label}</span>
        </div>
        <div className="grid gap-8 px-6 py-9 sm:grid-cols-[auto_1fr] sm:px-10 sm:py-12">
          <div className="flex items-start gap-4 sm:flex-col">
            <span className="font-display text-[64px] font-medium leading-none tracking-[-.04em] text-[hsl(var(--brand))] sm:text-[88px]" aria-hidden="true">{code}</span>
            <span className="grid size-10 place-items-center rounded-full border border-border text-muted-foreground sm:mt-2"><Icon size={18} /></span>
          </div>
          <div>
            <h1 className="text-[28px] leading-tight sm:text-[34px]">{title}</h1>
            <p className="mt-3 text-[15px] leading-relaxed text-muted-foreground">{detail}</p>
            {steps && steps.length > 0 && (
              <ol className="mt-6 space-y-2.5 border-t border-border pt-5">
                {steps.map((step, i) => (
                  <li key={step} className="flex gap-3 text-sm leading-relaxed">
                    <span className="mono-label mt-0.5 shrink-0 text-[hsl(var(--brand))]">{String(i + 1).padStart(2, '0')}</span>
                    <span>{step}</span>
                  </li>
                ))}
              </ol>
            )}
            {actions && <div className="mt-8 flex flex-wrap items-center gap-3">{actions}</div>}
          </div>
        </div>
        <p className="border-t border-dashed border-border px-6 py-3 text-xs text-muted-foreground sm:px-10">
          Nothing on your health record has been changed.
        </p>
      </div>
    </div>
  );
  if (!fullScreen) return <div className="flex min-h-[64vh] items-center py-6">{body}</div>;
  return (
    <div className="ruled-paper flex min-h-[100dvh] flex-col bg-background px-4 py-10">
      <a href="/" className="mx-auto mb-10 flex w-full max-w-2xl items-center gap-2.5" aria-label="CareSense home">
        <BrandMark />
        <span className="font-display text-lg font-semibold">CareSense</span>
      </a>
      <div className="flex flex-1 items-center">{body}</div>
    </div>
  );
}

/** The CareSense mark: a report sheet with one value circled. */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      <rect x="1" y="1" width="30" height="30" rx="7" fill="hsl(var(--primary))" />
      <path d="M9 10.5h14M9 15.5h8M9 20.5h11" stroke="hsl(var(--primary-foreground))" strokeWidth="1.8" strokeLinecap="round" opacity=".55" />
      <ellipse cx="20.5" cy="15.5" rx="5" ry="3.6" fill="none" stroke="hsl(var(--accent))" strokeWidth="1.8" transform="rotate(-8 20.5 15.5)" />
    </svg>
  );
}

const PRIMARY_ACTION = 'inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground transition-[filter,transform] hover:brightness-110 active:translate-y-px';
const SECONDARY_ACTION = 'inline-flex h-11 items-center gap-2 rounded-lg border border-input bg-card px-4 text-sm font-medium transition-colors hover:bg-secondary';

export function NotFoundPage({ fullScreen = false }: { fullScreen?: boolean }) {
  return (
    <ErrorPage
      code="404" label="Page not found" icon={Compass} fullScreen={fullScreen} testId="page-not-found"
      title="We could not find that page"
      detail="The link may be old, or the page may have moved. Your reports and results are safe."
      steps={['Check the address for a typing mistake.', 'Go back to your overview and find the page from the menu.']}
      actions={<><a href="/" className={PRIMARY_ACTION} data-testid="link-not-found-home">Go to my overview</a><button type="button" onClick={() => window.history.back()} className={SECONDARY_ACTION}>Go back</button></>}
    />
  );
}

export function NoAccessErrorPage({ title, detail }: { title: string; detail: string }) {
  return (
    <ErrorPage
      code="403" label="No access" icon={Lock} testId="page-no-access"
      title={title}
      detail={detail}
      actions={<a href="/" className={PRIMARY_ACTION} data-testid="link-back-overview">Go to my overview</a>}
    />
  );
}

export function CrashPage({ onRetry, technical }: { onRetry: () => void; technical?: string }) {
  return (
    <ErrorPage
      code="500" label="Something broke" icon={ServerCrash} fullScreen testId="page-crash"
      title="This page stopped working"
      detail="Something went wrong inside the app while showing this page. It is a fault on our side, not something you did."
      steps={['Try again. Most of the time this fixes it.', 'If it keeps happening, sign out and sign in again.']}
      actions={<>
        <button type="button" onClick={onRetry} className={PRIMARY_ACTION} data-testid="button-crash-retry"><RefreshCw size={15} />Try again</button>
        <a href="/" className={SECONDARY_ACTION}>Go to my overview</a>
        {technical ? <pre className="mt-2 w-full overflow-x-auto rounded-lg bg-secondary p-3 text-left font-mono text-[11px] text-muted-foreground">{technical}</pre> : null}
      </>}
    />
  );
}

export function UnreachablePage({ onRetry, retrying = false }: { onRetry: () => void; retrying?: boolean }) {
  return (
    <ErrorPage
      code="503" label="Cannot connect" icon={CloudOff} fullScreen testId="page-unreachable"
      title="We cannot reach CareSense right now"
      detail="Your device is working, but our service did not answer. You are still signed in - nothing has been lost."
      steps={['Check that you are connected to the internet.', 'Wait a minute and try again. The service may be restarting.']}
      actions={<button type="button" onClick={onRetry} disabled={retrying} className={`${PRIMARY_ACTION} disabled:opacity-60`} data-testid="button-unreachable-retry"><RefreshCw size={15} className={retrying ? 'animate-spin' : ''} />{retrying ? 'Trying…' : 'Try again'}</button>}
    />
  );
}

/** A strip across the top while the device has no network. */
export function OfflineBanner() {
  return (
    <div role="status" className="sticky top-0 z-50 flex items-center justify-center gap-2 bg-[hsl(var(--foreground))] px-4 py-2 text-center text-xs font-medium text-[hsl(var(--background))]" data-testid="banner-offline">
      <WifiOff size={14} />You are offline. What you see may be out of date, and nothing new can be uploaded until you reconnect.
    </div>
  );
}
