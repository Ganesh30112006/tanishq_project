import { useState } from 'react';
import { Link, useLocation } from 'wouter';
import { Activity, ArrowRight, ArrowUpRight, BarChart3, Bell, FileText, ScanText, ShieldCheck, Sparkles, Stethoscope, Upload } from 'lucide-react';
import { getGetDashboardSummaryQueryKey, getListReportsQueryKey, useGetDashboardSummary, useListReports } from '@workspace/api-client-react';
import type { DashboardSummary, MedicalReport, UserRole } from '@workspace/api-client-react';
import { Badge, EmptyState, PageLoading, QueryError, relativeTime, shortDate, Skeleton } from '@/components/ui-kit';
import { PERM, useAuth } from '@/lib/auth';
import { isPatientView, patientReportStatus, primaryRole, reportTypeLabel, ROLE_LABEL } from '@/lib/display';
import { requestUpload } from '@/lib/upload-intent';

const TONE_BAR: Record<string, string> = {
  critical: 'bg-[hsl(var(--destructive))]',
  warning: 'bg-[hsl(var(--accent))]',
  positive: 'bg-[hsl(var(--success))]',
};

export default function Dashboard() {
  const { user, hasPermission } = useAuth();
  const [, setLocation] = useLocation();
  const patientView = isPatientView(hasPermission);
  const roles = user?.roles ?? [];
  const [role, setRole] = useState<UserRole | undefined>(() => primaryRole(roles));
  const params = role ? { role } : {};
  const query = useGetDashboardSummary(params, { query: { queryKey: getGetDashboardSummaryQueryKey(params) } });
  const summary = query.data as DashboardSummary | undefined;
  const canReadReports = hasPermission(PERM.REPORT_READ_OWN);
  const canUpload = hasPermission(PERM.REPORT_UPLOAD_OWN);
  const isAdmin = hasPermission(PERM.USERS_MANAGE);

  if (query.isLoading) return <PageLoading />;
  if (query.isError) return <QueryError onRetry={() => query.refetch()} message="Your overview could not be loaded." />;

  const metrics = summary?.metrics || [];
  const activity = summary?.recent_activity || [];
  const attention = activity.slice(0, 5);
  const earlier = activity.slice(5, 11);
  const today = new Intl.DateTimeFormat('en-IN', { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date());

  return (
    <div className="page-enter">
      {roles.length > 1 && (
        <div className="mb-5 flex justify-end">
          <label className="sr-only" htmlFor="role-select">Workspace role</label>
          <select id="role-select" value={role} onChange={(event) => setRole(event.target.value as UserRole)} className="h-10 rounded-xl border border-input bg-card px-3 text-sm font-bold" data-testid="select-role">
            {roles.map((item) => <option key={item} value={item}>{ROLE_LABEL[item]} view</option>)}
          </select>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        {/* Hero */}
        <section className="relative overflow-hidden rounded-[22px] bg-[linear-gradient(135deg,hsl(var(--brand))_0%,hsl(171_72%_22%)_100%)] p-7 text-[hsl(var(--brand-foreground))] sm:p-10 xl:col-span-8" aria-labelledby="hero-title">
          <HeroArt />
          <div className="relative max-w-xl">
            <p className="mono-label opacity-75">{today}</p>
            <h1 id="hero-title" className="mt-3 text-[38px] leading-[1.05] sm:text-[52px]">{summary?.greeting || 'Welcome back'}</h1>
            <p className="mt-4 max-w-lg text-[17px] leading-relaxed opacity-90">
              {patientView
                ? 'Upload a lab report and our AI will read it line by line, explain what stands out, and tell you honestly what it could not work out.'
                : isAdmin ? 'Look after accounts, watch how the AI is doing, and keep every patient record safe.' : 'A short view of what needs your attention today.'}
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              {canUpload && <button type="button" onClick={() => { requestUpload(); setLocation('/reports'); }} className="inline-flex h-12 items-center gap-2 rounded-xl bg-white px-5 text-[15px] font-bold text-[hsl(var(--brand))] shadow-lg transition-transform hover:-translate-y-0.5" data-testid="button-hero-upload"><Upload size={17} />Upload a report</button>}
              {canReadReports && <Link href="/reports" className="inline-flex h-12 items-center gap-2 rounded-xl border border-white/35 px-5 text-[15px] font-bold transition-colors hover:bg-white/10" data-testid="link-hero-reports">See my reports<ArrowRight size={16} /></Link>}
              {isAdmin && <Link href="/admin" className="inline-flex h-12 items-center gap-2 rounded-xl bg-white px-5 text-[15px] font-bold text-[hsl(var(--brand))] shadow-lg" data-testid="link-hero-admin">Open admin<ArrowRight size={16} /></Link>}
            </div>
          </div>
        </section>

        {/* At a glance */}
        <section className="flex flex-col rounded-[22px] border border-border bg-card xl:col-span-4" aria-labelledby="glance-title">
          <div className="flex items-center justify-between px-6 pt-6">
            <h2 id="glance-title" className="text-[22px]">At a glance</h2>
            <span className="grid size-9 place-items-center rounded-xl bg-[hsl(var(--brand)/.1)] text-[hsl(var(--brand))]"><BarChart3 size={17} /></span>
          </div>
          <div className="mt-3 flex-1 divide-y divide-border px-6 pb-3">
            {metrics.length ? metrics.map((metric, index) => (
              <div key={metric.label} className={`page-enter stagger-${index + 1} flex items-center gap-4 py-4`} data-testid={`card-metric-${index}`}>
                <span className={`h-10 w-1 shrink-0 rounded-full ${TONE_BAR[metric.tone || ''] ?? 'bg-muted-foreground/30'}`} aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-bold">{metric.label}</p>
                  <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{metric.context}</p>
                </div>
                <p className={`font-display shrink-0 text-[30px] font-semibold leading-none ${metric.tone === 'critical' ? 'text-[hsl(var(--destructive))]' : ''}`}>{metric.value}</p>
              </div>
            )) : <p className="py-6 text-sm text-muted-foreground">Nothing to show yet.</p>}
          </div>
        </section>

        {/* Needs attention */}
        <section className="rounded-[22px] border border-border bg-card xl:col-span-7" aria-labelledby="attention-title">
          <div className="flex items-center justify-between gap-3 px-6 pt-6">
            <div>
              <p className="mono-label text-muted-foreground">For you</p>
              <h2 id="attention-title" className="mt-1 text-[22px]">Needs your attention</h2>
            </div>
            <Link href="/alerts" className="inline-flex items-center gap-1 text-sm font-bold text-[hsl(var(--brand))] hover:underline" data-testid="link-view-all-alerts">View all<ArrowRight size={15} /></Link>
          </div>
          <div className="mt-3 px-3 pb-3">
            {attention.length ? attention.map((item) => <ActivityRow key={item.id} item={item} />) : <EmptyState icon={ShieldCheck} title="Nothing needs you right now" detail="When something on your record needs a look, it will show up here." />}
          </div>
        </section>

        {/* Latest reports */}
        {canReadReports ? <LatestReports /> : (
          <section className="rounded-[22px] border border-border bg-card p-6 xl:col-span-5">
            <h2 className="text-[22px]">Earlier activity</h2>
            <div className="mt-3">{earlier.length ? earlier.map((item) => <ActivityRow key={item.id} item={item} />) : <p className="text-sm text-muted-foreground">No earlier activity.</p>}</div>
          </section>
        )}

        {/* How it works */}
        {patientView && (
          <section className="rounded-[22px] border border-dashed border-[hsl(var(--brand)/.35)] bg-[hsl(var(--brand)/.04)] p-6 sm:p-8 xl:col-span-12" aria-labelledby="how-title">
            <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-end">
              <h2 id="how-title" className="text-[24px]">How CareSense works</h2>
              <p className="text-sm text-muted-foreground">Three steps. Your doctor always has the final word.</p>
            </div>
            <ol className="mt-6 grid gap-4 md:grid-cols-3">
              {[
                { icon: Upload, title: 'Upload your report', detail: 'A PDF from the lab works best. The file stays private to you.' },
                { icon: ScanText, title: 'Our AI reads it', detail: 'It checks each value against the normal range printed on your report, and shows you the exact line it read.' },
                { icon: Stethoscope, title: 'Show it to a doctor', detail: 'You get possible patterns, never a diagnosis. Take them to your doctor to decide what they mean.' },
              ].map((step, index) => (
                <li key={step.title} className="relative rounded-2xl border border-border bg-card p-5">
                  <span className="font-display absolute right-5 top-4 text-[40px] font-semibold leading-none text-[hsl(var(--brand)/.18)]">{index + 1}</span>
                  <span className="grid size-10 place-items-center rounded-xl bg-[hsl(var(--brand))] text-[hsl(var(--brand-foreground))]"><step.icon size={18} /></span>
                  <p className="mt-4 font-bold">{step.title}</p>
                  <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{step.detail}</p>
                </li>
              ))}
            </ol>
          </section>
        )}

        {canReadReports && earlier.length > 0 && (
          <section className="rounded-[22px] border border-border bg-card p-6 xl:col-span-12" aria-labelledby="earlier-title">
            <p className="mono-label text-muted-foreground">History</p>
            <h2 id="earlier-title" className="mt-1 text-[22px]">Earlier activity</h2>
            <div className="mt-3 grid md:grid-cols-2 md:gap-x-6">{earlier.map((item) => <ActivityRow key={item.id} item={item} compact />)}</div>
          </section>
        )}
      </div>
    </div>
  );
}

function LatestReports() {
  const params = { page_size: 4 };
  const query = useListReports(params, { query: { queryKey: getListReportsQueryKey(params) } });
  const reports = (query.data?.results || []) as MedicalReport[];
  return (
    <section className="rounded-[22px] border border-border bg-card xl:col-span-5" aria-labelledby="latest-title">
      <div className="flex items-center justify-between gap-3 px-6 pt-6">
        <div>
          <p className="mono-label text-muted-foreground">Documents</p>
          <h2 id="latest-title" className="mt-1 text-[22px]">Latest reports</h2>
        </div>
        <Link href="/reports" className="inline-flex items-center gap-1 text-sm font-bold text-[hsl(var(--brand))] hover:underline">All<ArrowRight size={15} /></Link>
      </div>
      <div className="mt-3 px-3 pb-3">
        {query.isLoading ? <div className="space-y-2 p-3"><Skeleton className="h-14" /><Skeleton className="h-14" /></div>
          : reports.length ? reports.map((report) => {
            const state = patientReportStatus(report.processing_state);
            return (
              <Link key={report.id} href={`/reports/${report.id}`} className="group flex items-center gap-3 rounded-xl p-3 transition-colors hover:bg-secondary/60" data-testid={`link-latest-report-${report.id}`}>
                <span className="grid size-11 shrink-0 place-items-center rounded-xl border border-border bg-background text-[hsl(var(--brand))]"><FileText size={18} /></span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-bold">{report.title}</span>
                  <span className="mt-0.5 block text-[13px] text-muted-foreground">{reportTypeLabel(report)} · {shortDate(report.created_at)}</span>
                </span>
                <Badge className={`hidden whitespace-nowrap sm:inline-flex ${state.className}`}>{state.label}</Badge>
                <ArrowUpRight size={16} className="shrink-0 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
              </Link>
            );
          }) : <EmptyState icon={Sparkles} title="No reports yet" detail="Upload your first lab report and our AI will explain it." />}
      </div>
    </section>
  );
}

function ActivityRow({ item, compact = false }: { item: DashboardSummary['recent_activity'][number]; compact?: boolean }) {
  const icons = { risk: ShieldCheck, report: FileText, note: FileText, measurement: BarChart3, alert: Bell };
  const Icon = icons[item.type] || Activity;
  return (
    <div className={`flex items-start gap-3 rounded-xl ${compact ? 'border-b border-border px-1 py-3.5 last:border-0' : 'p-3 hover:bg-secondary/60'}`} data-testid={`activity-${item.id}`}>
      <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-full bg-secondary text-muted-foreground"><Icon size={15} /></span>
      <div className="min-w-0 flex-1">
        <p className="font-bold leading-snug">{item.title}</p>
        <p className="mt-0.5 truncate text-[13px] text-muted-foreground">{item.detail}</p>
      </div>
      <time className="mono-label shrink-0 !normal-case !tracking-normal text-muted-foreground">{relativeTime(item.timestamp)}</time>
    </div>
  );
}

/** Decorative: a pulse trace across faint concentric rings. */
function HeroArt() {
  return (
    <svg aria-hidden="true" viewBox="0 0 600 320" preserveAspectRatio="xMaxYMid slice" className="pointer-events-none absolute inset-0 h-full w-full opacity-[.16]">
      <g fill="none" stroke="white">
        <circle cx="520" cy="60" r="70" strokeWidth="1" />
        <circle cx="520" cy="60" r="130" strokeWidth="1" />
        <circle cx="520" cy="60" r="200" strokeWidth="1" />
        <circle cx="520" cy="60" r="280" strokeWidth="1" />
        <path d="M0 250 H250 L272 250 L290 190 L310 300 L330 220 L345 250 H600" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
      </g>
    </svg>
  );
}
