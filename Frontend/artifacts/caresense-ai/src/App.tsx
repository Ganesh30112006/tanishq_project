import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { Link, Route, Switch, Router as WouterRouter, useLocation, useParams } from 'wouter';
import {
  Activity, AlertCircle, ArrowRight, ArrowUpRight, ArrowDownRight, BarChart3, Bell,
  CalendarDays, Check, CheckCircle2, ChevronLeft, CircleHelp, Clock3, Download, FlaskConical,
  FileText, Filter, HeartPulse, LayoutDashboard, Loader2, LockKeyhole, LogOut, Menu,
  NotebookPen, Pill, Plus, Search, Settings2, ShieldCheck, ShieldHalf, SlidersHorizontal, Upload, UserPlus, UserRound,
  UsersRound, X, Zap
} from 'lucide-react';
import {
  ActionButton, ATTENTION_BADGE, Badge, CRITICAL_BADGE, EmptyState, FIELD_CLASS, FormError,
  formatMrn, formatValue, FormField, InlineUnavailable, Modal, ModalActions, NEUTRAL_BADGE,
  NoAccessPage, PageButton, PageHeading, PageLoading, POSITIVE_BADGE, QueryError, relativeTime,
  SectionTitle, shortDate, Skeleton, titleCase,
} from '@/components/ui-kit';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/toaster';
import { ErrorBoundary } from '@/components/error-boundary';
import NotFound from '@/pages/not-found';
import Login from '@/pages/login';
import SignUp from '@/pages/signup';
import AdminConsole from '@/pages/admin';
import Appointments from '@/pages/appointments';
import { AuthProvider, PERM, useAuth } from '@/lib/auth';
import {
  downloadReportFile,
  getGetDashboardSummaryQueryKey,
  getGetPatientAiSummaryQueryKey,
  getGetPatientQueryKey,
  getGetPatientTimelineQueryKey,
  getGetReportQualityQueryKey,
  getGetReportQueryKey,
  getListAlertsQueryKey,
  getListNotificationsQueryKey,
  getListClinicalNotesQueryKey,
  getListLabOrdersQueryKey,
  getListPatientsQueryKey,
  getListReportsQueryKey,
  getListRiskAssessmentsQueryKey,
  useAcknowledgeAlert,
  useCreateClinicalNote,
  useCreateLabOrder,
  useCreateMedication,
  useEnterLabResult,
  useGetDashboardSummary,
  useGetPatient,
  useGetPatientAiSummary,
  useGetPatientTimeline,
  useGetReport,
  useGetReportQuality,
  useListAlerts,
  useListNotifications,
  useMarkNotificationRead,
  useListClinicalNotes,
  useListLabOrders,
  useListPatients,
  useListReports,
  useRegisterPatient,
  useRequestRiskAnalysis,
  useListRiskAssessments,
  useResolveAlert,
  useUploadReport,
  useValidateLabResult,
} from '@workspace/api-client-react';
import type {
  Alert, ClinicalDataState, ClinicalNoteType, DashboardSummary, DataGap, LabOrder, LabResult, MedicalReport, NextStep,
  Medication, MedicationStatus, Notification, Patient, PatientProfile, PatientSex, ReportClass, ReportQuality, RiskAssessment, RiskFactor,
  TimelineEvent, UserRole, RiskLevel, PatientStatus, ReportProcessingState, AlertStatus, ValidationStatus,
} from '@workspace/api-client-react';

const queryClient = new QueryClient();

const ROLE_LABEL: Record<UserRole, string> = {
  DOCTOR: 'Clinician',
  LAB_TECHNICIAN: 'Lab technician',
  ADMIN: 'Administrator',
  PATIENT: 'Patient',
};

// Matches the server's own precedence (apps/dashboard/service.py) so the
// default view picked here agrees with what the backend would pick anyway.
const ROLE_PRECEDENCE: UserRole[] = ['ADMIN', 'DOCTOR', 'LAB_TECHNICIAN', 'PATIENT'];
function primaryRole(roles: UserRole[]): UserRole | undefined {
  return ROLE_PRECEDENCE.find((role) => roles.includes(role)) ?? roles[0];
}

type NavItem = { href: string; label: string; icon: typeof LayoutDashboard; anyPerm?: string[] };

// The nav is filtered per caller: an entry with `anyPerm` only renders when the
// signed-in user holds at least one of those permission codes. The server still
// authorizes every request - this just stops showing controls a role can't use.
const NAV_ITEMS: NavItem[] = [
  { href: '/', label: 'Overview', icon: LayoutDashboard },
  {
    href: '/patients',
    label: 'Patients',
    icon: UsersRound,
    anyPerm: [PERM.PATIENT_READ_OWN, PERM.PATIENT_READ_ASSIGNED],
  },
  {
    href: '/reports',
    label: 'Reports',
    icon: FileText,
    anyPerm: [PERM.REPORT_READ_OWN, PERM.REPORT_READ_ASSIGNED, PERM.LAB_REPORT_UPLOAD],
  },
  { href: '/lab', label: 'Lab', icon: FlaskConical, anyPerm: [PERM.LAB_WORKFLOW_ACCESS] },
  {
    href: '/appointments',
    label: 'Consultations',
    icon: CalendarDays,
    anyPerm: [PERM.APPOINTMENT_BOOK, PERM.APPOINTMENT_MANAGE],
  },
  { href: '/alerts', label: 'Alerts', icon: Bell, anyPerm: [PERM.ALERT_MANAGE, PERM.PATIENT_READ_OWN] },
  {
    href: '/admin',
    label: 'Admin',
    icon: ShieldHalf,
    anyPerm: [PERM.USERS_MANAGE, PERM.STAFF_MANAGE, PERM.AUDIT_READ],
  },
];

/**
 * Someone who can only ever see their own record is reading this as a patient,
 * not as staff. Everything they read has to be written for them: no workflow
 * vocabulary, no pipeline internals, and no list furniture for a list of one.
 */
function isPatientView(hasPermission: (...codes: string[]) => boolean): boolean {
  return hasPermission(PERM.PATIENT_READ_OWN) && !hasPermission(PERM.PATIENT_READ_ASSIGNED);
}

// Clinical shorthand that must stay upper-case: title-casing turns "CVD" into
// "Cvd" and "HDL" into "Hdl", which reads as a different (wrong) term.
const ACRONYMS = new Set([
  'CVD', 'BMI', 'BP', 'HDL', 'LDL', 'MRN', 'WBC', 'RBC', 'CBC', 'HBA1C', 'A1C',
  'SPO2', 'EGFR', 'LOINC', 'OCR', 'AI', 'ID', 'IQR', 'MAD', 'OOD', 'SHAP',
]);

/**
 * Clinical values arrive as fixed-precision decimal strings ("29.000000"), so
 * printing them raw shows a precision the measurement never had. Trim the
 * trailing zeros without rounding away real significant digits.
 */
/** MRNs are often already prefixed ("MRN-DEMO-1001"); don't print "MRN MRN-…". */
const isRiskyLevel = (value?: string | null) => value === 'HIGH' || value === 'CRITICAL';
const riskClass = (value?: string | null) => value === 'CRITICAL' ? 'bg-[hsl(var(--destructive)/.1)] text-[hsl(var(--destructive))]' : value === 'HIGH' ? 'bg-[hsl(30_80%_92%)] text-[hsl(24_70%_34%)]' : value === 'MEDIUM' ? 'bg-[hsl(var(--accent)/.22)] text-[hsl(30_48%_26%)]' : 'bg-[hsl(162_28%_90%)] text-[hsl(162_42%_28%)]';
const statusClass = (value?: string | null) => value === 'REVIEW_REQUIRED' || value === 'REJECTED' ? 'text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/.08)]' : value === 'MONITORING' || IN_PROGRESS_STATES.has(value || '') ? 'text-[hsl(30_54%_32%)] bg-[hsl(var(--accent)/.18)]' : 'text-[hsl(162_42%_28%)] bg-[hsl(162_28%_90%)]';

// The lab order/result vocabulary is its own; running it through the
// report-oriented `statusClass` painted every state green, including
// "Requested" (nothing has happened yet) and "Cancelled".
const labStatusClass = (value?: string | null) => {
  switch (value) {
    case 'RESULTED':
    case 'VALIDATED':
    case 'PASSED':
      return POSITIVE_BADGE;
    case 'IN_PROGRESS':
    case 'COLLECTED':
    case 'PENDING':
    case 'REVIEW_REQUIRED':
      return ATTENTION_BADGE;
    case 'CANCELLED':
    case 'FAILED':
      return CRITICAL_BADGE;
    default:
      return NEUTRAL_BADGE; // REQUESTED and anything unrecognised
  }
};

// A prediction is not clinical truth until a clinician has signed it off.
const lifecycleBadgeClass = (value?: string | null) => {
  switch (value) {
    case 'FINALIZED':
    case 'CLINICALLY_REVIEWED':
      return POSITIVE_BADGE;
    case 'REVIEW_REQUIRED':
      return ATTENTION_BADGE;
    case 'INSUFFICIENT_DATA':
    case 'CANCELLED':
      return CRITICAL_BADGE;
    default:
      return NEUTRAL_BADGE;
  }
};

const IN_PROGRESS_STATES = new Set<string>([
  'RECEIVED', 'VALIDATING_FILE', 'EXTRACTING', 'CLASSIFYING', 'STRUCTURING', 'RECONCILING',
]);
const REPORT_FILTER_OPTIONS: ReportProcessingState[] = [
  'RECEIVED', 'VALIDATING_FILE', 'EXTRACTING', 'CLASSIFYING', 'STRUCTURING', 'RECONCILING',
  'REVIEW_REQUIRED', 'FINALIZED', 'REJECTED',
];

export function AppLogo() {
  return (
    <Link href="/" className="flex items-center gap-3" data-testid="link-brand">
      <span className="grid size-9 place-items-center rounded-xl bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]">
        <HeartPulse size={19} strokeWidth={2.5} />
      </span>
      <span className="leading-none">
        <strong className="block text-[15px] tracking-[-.02em]">CareSense</strong>
        <span className="mono-label text-[hsl(var(--sidebar-foreground)/.56)]">clinical intelligence</span>
      </span>
    </Link>
  );
}

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || '?';
}

function Shell({ children }: { children: ReactNode }) {
  const [location, setLocation] = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const { user, logout, hasPermission, hasAnyPermission } = useAuth();
  const activeHref = location.startsWith('/patients') ? '/patients' : location;
  const role = user ? primaryRole(user.roles) : undefined;
  const patientView = isPatientView(hasPermission);
  const navItems = NAV_ITEMS
    .filter((item) => !item.anyPerm || hasAnyPermission(...item.anyPerm))
    .map((item) => (patientView && item.href === '/patients'
      ? { ...item, label: 'My record' }
      : patientView && item.href === '/reports' ? { ...item, label: 'My reports' } : item));
  return (
    <div className="min-h-[100dvh] bg-background text-foreground">
      <aside className={`fixed inset-y-0 left-0 z-40 flex w-[248px] flex-col border-r border-[hsl(var(--sidebar-border))] bg-sidebar px-4 py-5 text-sidebar-foreground transition-transform duration-200 md:translate-x-0 ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="flex items-center justify-between px-2">
          <AppLogo />
          <button className="rounded-lg p-2 text-sidebar-foreground/60 hover:bg-sidebar-accent md:hidden" onClick={() => setMobileOpen(false)} aria-label="Close navigation" data-testid="button-close-navigation"><X size={18} /></button>
        </div>
        <div className="mt-10">
          <p className="mono-label px-3 text-sidebar-foreground/40">Workspace</p>
          <nav className="mt-3 space-y-1" aria-label="Primary navigation">
            {navItems.map(({ href, label, icon: Icon }) => {
              const active = activeHref === href;
              return (
                <Link key={href} href={href} onClick={() => setMobileOpen(false)} className={`flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors ${active ? 'bg-sidebar-accent text-sidebar-foreground' : 'text-sidebar-foreground/62 hover:bg-sidebar-accent/70 hover:text-sidebar-foreground'}`} data-testid={`link-nav-${label.toLowerCase().replace(/\s+/g, '-')}`}>
                  <Icon size={17} strokeWidth={active ? 2.3 : 1.8} />
                  <span>{label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="mt-auto space-y-1">
          <Link href="/settings" onClick={() => setMobileOpen(false)} className={`flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium ${activeHref === '/settings' ? 'bg-sidebar-accent' : 'text-sidebar-foreground/62 hover:bg-sidebar-accent/70 hover:text-sidebar-foreground'}`} data-testid="link-nav-settings"><Settings2 size={17} /><span>Settings</span></Link>
          <div className="mt-4 border-t border-sidebar-border pt-4">
            <div className="flex items-center gap-3 px-2">
              <span className="grid size-9 place-items-center rounded-full bg-sidebar-accent text-xs font-semibold">{user ? initialsOf(user.full_name || user.email) : '—'}</span>
              <div className="min-w-0"><p className="truncate text-sm font-medium">{user?.full_name || user?.email}</p><p className="truncate text-xs text-sidebar-foreground/45">{role ? ROLE_LABEL[role] : ''}</p></div>
              <button onClick={() => logout()} className="ml-auto text-sidebar-foreground/40 hover:text-sidebar-foreground" aria-label="Sign out" data-testid="button-logout"><LogOut size={16} /></button>
            </div>
          </div>
        </div>
      </aside>
      {mobileOpen && <button aria-label="Close menu overlay" className="fixed inset-0 z-30 bg-[hsl(var(--foreground)/.35)] md:hidden" onClick={() => setMobileOpen(false)} data-testid="button-navigation-overlay" />}
      <div className="md:pl-[248px]">
        <header className="sticky top-0 z-20 flex h-[68px] items-center justify-between border-b border-border bg-background/95 px-4 backdrop-blur-sm sm:px-7 lg:px-10">
          <div className="flex items-center gap-3">
            <button className="rounded-xl p-2 hover:bg-secondary md:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation" data-testid="button-open-navigation"><Menu size={20} /></button>
            <div className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex"><span className="size-1.5 rounded-full bg-[hsl(162_42%_42%)]" />Signed in{role ? ` as ${ROLE_LABEL[role]}` : ''}</div>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setLocation('/alerts')} className="relative rounded-xl p-2.5 text-muted-foreground hover:bg-secondary hover:text-foreground" aria-label="Open alerts and messages" data-testid="button-header-alerts"><Bell size={18} /></button>
            <button onClick={() => setHelpOpen(true)} className="rounded-xl p-2.5 text-muted-foreground hover:bg-secondary" aria-label="Help" data-testid="button-help"><CircleHelp size={18} /></button>
          </div>
        </header>
        <main className="mx-auto max-w-[1500px] p-4 sm:p-7 lg:p-10">{children}</main>
      </div>
      <nav className="fixed bottom-0 left-0 right-0 z-20 grid border-t border-border bg-card/95 px-2 py-1.5 backdrop-blur md:hidden" style={{ gridTemplateColumns: `repeat(${navItems.length}, minmax(0, 1fr))` }}>
        {navItems.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={`grid min-h-12 place-items-center gap-0.5 rounded-lg text-[10px] ${activeHref === href ? 'text-foreground' : 'text-muted-foreground'}`} data-testid={`link-mobile-${label.toLowerCase()}`}><Icon size={18} /><span>{label}</span></Link>)}
      </nav>
      {helpOpen && <Modal title="Help" description="What CareSense can and cannot do for you." onClose={() => setHelpOpen(false)}>
        <div className="space-y-3 text-sm leading-relaxed text-muted-foreground">
          <p>What you can see and do here is set by your role, and is checked on every request. If you need access you do not have, please contact your CareSense administrator.</p>
          <p>CareSense is a decision-support tool. It does not diagnose, and it does not replace a doctor. If you are feeling unwell right now, do not wait for anything on this screen - contact a doctor or your local emergency number.</p>
        </div>
        <div className="mt-5 flex justify-end">
          <button type="button" onClick={() => setHelpOpen(false)} className="inline-flex h-10 items-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground" data-testid="button-help-close">Close</button>
        </div>
      </Modal>}
    </div>
  );
}

function Dashboard() {
  const { user, hasPermission } = useAuth();
  const patientView = isPatientView(hasPermission);
  const roles = user?.roles ?? [];
  const [role, setRole] = useState<UserRole | undefined>(() => primaryRole(roles));
  const params = role ? { role } : {};
  const query = useGetDashboardSummary(params, { query: { queryKey: getGetDashboardSummaryQueryKey(params) } });
  const summary = query.data as DashboardSummary | undefined;
  const activity = summary?.recent_activity || [];
  const metrics = summary?.metrics || [];
  // The signal queue and the audit trail previously rendered the same first
  // rows, so every item appeared twice on one screen. Split the feed instead.
  const attention = activity.slice(0, 5);
  const earlier = activity.slice(5, 11);
  if (query.isLoading) return <PageLoading />;
  if (query.isError) return <QueryError onRetry={() => query.refetch()} />;
  return <div className="page-enter">
    <PageHeading eyebrow="CareSense / overview" title={summary?.greeting || 'Welcome back'} detail={patientView ? 'A quick look at your record and anything that needs your attention.' : 'A focused view of the people and signals that need your attention today.'} action={roles.length > 1 ? <div className="flex items-center gap-2"><label className="sr-only" htmlFor="role-select">Workspace role</label><select id="role-select" value={role} onChange={(event) => setRole(event.target.value as UserRole)} className="h-10 rounded-xl border border-input bg-card px-3 text-sm font-medium shadow-sm" data-testid="select-role">{roles.map((item) => <option key={item} value={item}>{ROLE_LABEL[item]} view</option>)}</select></div> : undefined} />
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {(summary?.metrics || []).map((metric, index) => <div key={metric.label} className={`page-enter stagger-${index + 1} rounded-2xl border border-border bg-card p-5`} data-testid={`card-metric-${index}`}><div className="flex items-start justify-between gap-2"><p className="text-sm text-muted-foreground">{metric.label}</p><span className={`status-dot mt-1.5 ${metric.tone === 'critical' ? 'bg-[hsl(var(--destructive))]' : metric.tone === 'warning' ? 'bg-[hsl(var(--accent))]' : metric.tone === 'positive' ? 'bg-[hsl(162_42%_42%)]' : 'bg-muted-foreground/40'}`} /></div><p className="mt-5 text-3xl font-semibold tracking-[-.04em]">{metric.value}</p><p className="mt-1 text-xs text-muted-foreground">{metric.context}</p></div>)}
    </div>
    <div className="mt-6 grid gap-6 xl:grid-cols-[1.4fr_.9fr]">
      <section className="rounded-2xl border border-border bg-card" aria-labelledby="attention-title"><div className="flex items-center justify-between border-b border-border px-5 py-4 sm:px-6"><div><p className="mono-label text-muted-foreground">Signal queue</p><h2 id="attention-title" className="mt-1 text-lg font-semibold">Needs your attention</h2></div><Link href="/alerts" className="text-xs font-semibold text-muted-foreground hover:text-foreground" data-testid="link-view-all-alerts">View all <ArrowRight className="ml-1 inline" size={14} /></Link></div><div className="divide-y divide-border">{attention.map((item) => <ActivityRow key={item.id} item={item} />)}{!attention.length && <EmptyState icon={Activity} title="No active signals" detail="New patient activity will appear here." />}</div></section>
      <section className="rounded-2xl border border-border bg-card p-5 sm:p-6" aria-labelledby="pulse-title"><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-xl bg-[hsl(var(--accent))]"><Zap size={17} /></span><div><p className="mono-label text-muted-foreground">At a glance</p><h2 id="pulse-title" className="mt-1 text-lg font-semibold">Care pulse</h2></div></div>
        {metrics.length ? <dl className="mt-6 space-y-4">{metrics.map((metric) => <div key={metric.label} className="flex items-start justify-between gap-4 border-b border-border pb-3 last:border-0 last:pb-0"><div className="min-w-0"><dt className="text-sm font-medium">{metric.label}</dt><dd className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{metric.context}</dd></div><span className={`shrink-0 text-xl font-semibold tracking-[-.03em] ${metric.tone === 'critical' ? 'text-[hsl(var(--destructive))]' : metric.tone === 'warning' ? 'text-[hsl(30_54%_32%)]' : ''}`}>{metric.value}</span></div>)}</dl>
          : <p className="mt-6 text-sm text-muted-foreground">No metrics are available for this workspace yet.</p>}
      </section>
    </div>
    {earlier.length > 0 && <section className="mt-6 rounded-2xl border border-border bg-card" aria-labelledby="activity-title"><div className="border-b border-border px-5 py-4 sm:px-6"><p className="mono-label text-muted-foreground">Audit trail</p><h2 id="activity-title" className="mt-1 text-lg font-semibold">Earlier activity</h2></div><div className="grid divide-y divide-border md:grid-cols-2 md:divide-x md:divide-y-0">{earlier.map((item) => <ActivityRow key={item.id} item={item} compact />)}</div></section>}
  </div>;
}

function ActivityRow({ item, compact = false }: { item: DashboardSummary['recent_activity'][number]; compact?: boolean }) {
  const icons = { risk: ShieldCheck, report: FileText, note: FileText, measurement: BarChart3, alert: Bell };
  const Icon = icons[item.type] || Activity;
  return <div className={`flex items-start gap-3 px-5 py-4 sm:px-6 ${compact ? '' : 'hover:bg-secondary/40'}`} data-testid={`activity-${item.id}`}><span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground"><Icon size={15} /></span><div className="min-w-0 flex-1"><p className="text-sm font-medium">{item.title}</p><p className="mt-0.5 truncate text-xs text-muted-foreground">{item.detail}</p></div><time className="shrink-0 text-[11px] text-muted-foreground">{relativeTime(item.timestamp)}</time></div>;
}

function Patients() {
  const { hasPermission, hasAnyPermission } = useAuth();
  const patientView = isPatientView(hasPermission);
  const canReadPatients = hasAnyPermission(PERM.PATIENT_READ_OWN, PERM.PATIENT_READ_ASSIGNED);
  const queryClient = useQueryClient();
  const [registering, setRegistering] = useState(false);
  const [search, setSearch] = useState('');
  const [risk, setRisk] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const params: { search?: string; risk?: RiskLevel; status?: PatientStatus; page?: number } = {
    search: search || undefined, risk: (risk || undefined) as RiskLevel | undefined,
    status: (status || undefined) as PatientStatus | undefined, page,
  };
  const query = useListPatients(params, { query: { queryKey: getListPatientsQueryKey(params), enabled: canReadPatients } });
  const data = query.data;
  if (!canReadPatients) {
    // The same page is shown to an administrator and to a laboratory
    // technician, and they need different next steps, so say which applies.
    return <NoAccessPage
      title="Patient records"
      detail={hasAnyPermission(PERM.PATIENT_REGISTER, PERM.USERS_MANAGE)
        ? 'Your account is not allowed to open clinical records. Managing accounts is deliberately kept separate from reading what is inside a record. To register a patient or link a login to a record, use the Admin console.'
        : 'Your account is not allowed to open clinical records. If you are working on a sample, the patient details you need are on the Lab workspace.'}
    />;
  }
  return <div className="page-enter"><PageHeading eyebrow={patientView ? 'CareSense / my record' : 'CareSense / people'} title={patientView ? 'My health record' : 'Patients'} detail={patientView ? 'Your record, as it is saved in CareSense. Open it to see your results and run an analysis.' : 'Every patient record you are authorised to see. Filter by risk or care status to narrow the list.'} action={<div className="flex flex-wrap items-center gap-2">{hasPermission(PERM.PATIENT_REGISTER) && <ActionButton icon={UserPlus} label="Register patient" variant="primary" onClick={() => setRegistering(true)} />}{!patientView && <button onClick={() => { setSearch(''); setRisk(''); setStatus(''); setPage(1); }} className="inline-flex h-10 items-center gap-2 rounded-xl border border-input bg-card px-3 text-sm font-medium hover:bg-secondary" data-testid="button-clear-filters"><SlidersHorizontal size={15} />Reset view</button>}</div>} />
    {registering && <RegisterPatientInlineModal onClose={() => setRegistering(false)} onDone={() => queryClient.invalidateQueries({ queryKey: getListPatientsQueryKey(params) })} />}
    {!patientView && <div className="mb-5 grid gap-3 rounded-2xl border border-border bg-card p-3 sm:grid-cols-[1fr_auto_auto] sm:p-4"><label className="relative block"><Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={17} /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Search by patient name or MRN" className="h-11 w-full rounded-xl border border-input bg-background pl-10 pr-3 text-sm outline-none placeholder:text-muted-foreground focus:border-primary" data-testid="input-patient-search" /></label><SelectFilter label="Risk level" value={risk} onChange={(value) => { setRisk(value); setPage(1); }} options={['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']} testId="select-risk-filter" /><SelectFilter label="Care status" value={status} onChange={(value) => { setStatus(value); setPage(1); }} options={['STABLE', 'MONITORING', 'REVIEW_REQUIRED']} testId="select-status-filter" /></div>}
    {query.isLoading ? <PatientTableLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} message="Patient records are unavailable." /> : data?.results.length ? <>
      <div className="overflow-hidden rounded-2xl border border-border bg-card"><div className="hidden grid-cols-[1.6fr_.7fr_.8fr_.8fr_1.1fr_32px] gap-4 border-b border-border px-5 py-3 text-left mono-label text-muted-foreground md:grid"><span>Patient</span><span>Risk</span><span>Status</span><span>Trend</span><span>Last updated</span><span /></div><div className="divide-y divide-border">{data.results.map((patient) => <PatientRow patient={patient} key={patient.id} />)}</div></div>
      <PageButton page={page} pageSize={data.page_size} count={data.count} onChange={setPage} />
    </> : <div className="rounded-2xl border border-border bg-card"><EmptyState icon={UsersRound} title={patientView ? 'Your record is not ready yet' : 'No patients match this view'} detail={patientView ? 'Your account has not been linked to a health record yet. Please contact the CareSense team.' : 'Try removing a filter, or search for another name.'} /></div>}
  </div>;
}

function SelectFilter({ label, value, onChange, options, testId }: { label: string; value: string; onChange: (value: string) => void; options: string[]; testId: string }) {
  return <label className="flex min-h-11 items-center gap-2 rounded-xl border border-input bg-background px-3 text-sm"><Filter size={15} className="text-muted-foreground" /><span className="sr-only">{label}</span><select value={value} onChange={(event) => onChange(event.target.value)} className="w-full bg-transparent font-medium outline-none" data-testid={testId}><option value="">{`All ${label.toLowerCase()}`}</option>{options.map((option) => <option value={option} key={option}>{titleCase(option)}</option>)}</select></label>;
}

function PatientTableLoading() {
  return <div className="space-y-2 rounded-2xl border border-border bg-card p-5">{[1, 2, 3, 4, 5].map((item) => <div className="flex items-center gap-4 border-b border-border py-4 last:border-0" key={item}><Skeleton className="size-10 rounded-full" /><Skeleton className="h-4 flex-1" /><Skeleton className="h-4 w-20" /><Skeleton className="h-4 w-24" /></div>)}</div>;
}

function PatientRow({ patient }: { patient: Patient }) {
  return <Link href={`/patients/${patient.id}`} className="grid min-h-[78px] items-center gap-3 px-5 py-4 transition-colors hover:bg-secondary/45 md:grid-cols-[1.6fr_.7fr_.8fr_.8fr_1.1fr_32px] md:gap-4" data-testid={`row-patient-${patient.id}`}>
    <div className="flex min-w-0 items-center gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-full bg-secondary text-xs font-semibold">{patient.initials}</span><div className="min-w-0"><p className="truncate text-sm font-semibold">{patient.full_name}</p><p className="mt-0.5 text-xs text-muted-foreground">{patient.age ?? '—'} years · {titleCase(patient.sex)} · {formatMrn(patient.mrn)}</p></div></div>
    <div className="flex items-center gap-2">{patient.risk_level ? <><span className={`status-dot ${isRiskyLevel(patient.risk_level) ? 'bg-[hsl(var(--destructive))]' : 'bg-[hsl(var(--accent))]'}`} /><Badge className={riskClass(patient.risk_level)}>{patient.risk_label || titleCase(patient.risk_level)}{patient.risk_score != null ? ` · ${patient.risk_score}` : ''}</Badge></> : <span className="text-xs text-muted-foreground">Not assessed</span>}</div>
    <Badge className={`w-fit ${statusClass(patient.status)}`}>{titleCase(patient.status)}</Badge>
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">{patient.trend === 'UP' ? <ArrowUpRight size={15} className="text-[hsl(var(--destructive))]" /> : patient.trend === 'DOWN' ? <ArrowDownRight size={15} className="text-[hsl(162_42%_35%)]" /> : null}{titleCase(patient.trend) || '—'}</div>
    <div className="hidden text-xs text-muted-foreground md:block">{relativeTime(patient.last_updated)}</div><ArrowRight className="hidden text-muted-foreground md:block" size={16} />
    {patient.latest_alert && <p className="col-span-full truncate pl-[52px] text-xs text-[hsl(var(--destructive))] md:hidden">{patient.latest_alert}</p>}
  </Link>;
}

function PatientProfilePage() {
  const { hasPermission, hasAnyPermission } = useAuth();
  const patientView = isPatientView(hasPermission);
  const queryClient = useQueryClient();
  const { patientId = '' } = useParams<{ patientId: string }>();
  const enabled = Boolean(patientId);
  const [action, setAction] = useState<'upload' | 'note' | 'prescribe' | null>(null);
  const patientQuery = useGetPatient(patientId, { query: { queryKey: getGetPatientQueryKey(patientId), enabled } });
  const riskParams = { patient_id: patientId, page_size: 1 };
  const riskQuery = useListRiskAssessments(riskParams, { query: { queryKey: getListRiskAssessmentsQueryKey(riskParams), enabled } });
  const timelineParams = { limit: 20 };
  const timelineQuery = useGetPatientTimeline(patientId, timelineParams, { query: { queryKey: getGetPatientTimelineQueryKey(patientId, timelineParams), enabled } });
  const reportsParams = { patient_id: patientId };
  const reportsQuery = useListReports(reportsParams, { query: { queryKey: getListReportsQueryKey(reportsParams), enabled } });
  const canUseAi = hasPermission(PERM.AI_USE);
  const canUpload = hasAnyPermission(PERM.REPORT_UPLOAD_OWN, PERM.LAB_REPORT_UPLOAD);
  const canAuthor = hasPermission(PERM.CLINICAL_NOTE_CREATE);
  const canAnalyse = hasAnyPermission(PERM.RISK_REQUEST, PERM.RISK_REQUEST_OWN);
  const notesParams = { patient_id: patientId };
  const notesQuery = useListClinicalNotes(notesParams, { query: { queryKey: getListClinicalNotesQueryKey(notesParams), enabled: enabled && canAuthor } });
  const aiQuery = useGetPatientAiSummary(patientId, { query: { queryKey: getGetPatientAiSummaryQueryKey(patientId), enabled: enabled && canUseAi } });
  const patient = patientQuery.data as PatientProfile | undefined;
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: getGetPatientQueryKey(patientId) });
    queryClient.invalidateQueries({ queryKey: getListRiskAssessmentsQueryKey(riskParams) });
    queryClient.invalidateQueries({ queryKey: getGetPatientTimelineQueryKey(patientId, timelineParams) });
    queryClient.invalidateQueries({ queryKey: getListReportsQueryKey(reportsParams) });
    queryClient.invalidateQueries({ queryKey: getListClinicalNotesQueryKey(notesParams) });
  };
  if (patientQuery.isLoading) return <PageLoading />;
  if (patientQuery.isError || !patient) return <QueryError onRetry={() => patientQuery.refetch()} message="This patient record is unavailable." />;
  const assessment = riskQuery.data?.results?.[0] as RiskAssessment | undefined;
  const timeline = timelineQuery.data as TimelineEvent[] | undefined;
  const reports = reportsQuery.data?.results as MedicalReport[] | undefined;
  const notes = notesQuery.data?.results;
  const aiData = aiQuery.data as (Record<string, unknown> & { summary?: string; status?: string; message?: string }) | undefined;
  return <div className="page-enter"><Link href="/patients" className="mb-6 inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground" data-testid="link-back-patients"><ChevronLeft size={16} />All patients</Link>
    <div className="mb-7 flex flex-col justify-between gap-5 lg:flex-row lg:items-start"><div className="flex items-start gap-4"><span className="grid size-14 shrink-0 place-items-center rounded-2xl bg-primary text-lg font-semibold text-primary-foreground">{patient.initials}</span><div><div className="flex flex-wrap items-center gap-2"><h1 className="text-3xl font-semibold tracking-[-.045em]">{patient.full_name}</h1><Badge className={statusClass(patient.status)}>{titleCase(patient.status)}</Badge></div><p className="mt-1 text-sm text-muted-foreground">{patient.age ?? '—'} years · {titleCase(patient.sex)} · {formatMrn(patient.mrn)}</p><p className="mt-2 text-xs text-muted-foreground">Last updated {relativeTime(patient.last_updated)}</p></div></div><div className="flex flex-wrap items-center gap-2">{canUpload && <ActionButton icon={Upload} label="Upload report" onClick={() => setAction('upload')} />}{canAuthor && <ActionButton icon={NotebookPen} label="Add note" onClick={() => setAction('note')} />}{canAuthor && <ActionButton icon={Pill} label="Prescribe" onClick={() => setAction('prescribe')} />}{!canUpload && !canAuthor && <span className="inline-flex h-10 items-center gap-2 rounded-xl border border-input bg-card px-3 text-xs text-muted-foreground" data-testid="text-no-actions"><LockKeyhole size={14} />Read-only access</span>}</div></div>
    {action === 'upload' && <UploadReportModal patient={{ id: patientId, name: patient.full_name }} onClose={() => setAction(null)} onDone={refresh} />}
    {action === 'note' && <ClinicalNoteModal patientId={patientId} onClose={() => setAction(null)} onDone={refresh} />}
    {action === 'prescribe' && <PrescribeMedicationModal patientId={patientId} onClose={() => setAction(null)} onDone={refresh} />}
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><ProfileStat wrap label="Risk estimate" value={assessment?.interpretation?.band_label || patient.risk_label || (patient.risk_level ? titleCase(patient.risk_level) : 'Not assessed')} note={assessment?.interpretation?.show_score && patient.risk_score != null ? `${patient.risk_score}/100 · ${titleCase(patient.trend)}` : patient.risk_level ? `Trend ${titleCase(patient.trend) || 'stable'}` : 'No completed assessment'} critical={isRiskyLevel(patient.risk_level)} /><ProfileStat label="Date of birth" value={shortDate(patient.date_of_birth)} note={`Age ${patient.age ?? '—'}`} /><ProfileStat label="Care team" value={patient.care_team || 'Unassigned'} note="Primary team" /><ProfileStat wrap label="Latest alert" value={patient.latest_alert || 'No active alert'} note={patient.latest_alert ? (patientView ? 'Your doctor will look at this' : 'Review recommended') : (patientView ? 'Nothing needs attention right now' : 'Within expected range')} critical={Boolean(patient.latest_alert)} /></div>
    <div className="mt-6 grid gap-6 xl:grid-cols-[1.05fr_1.25fr]"><section className="rounded-2xl border border-border bg-card" aria-labelledby="overview-title"><SectionTitle eyebrow={patientView ? 'My details' : 'Patient record'} title={patientView ? 'Your health details' : 'Clinical overview'} id="overview-title" /><div className="grid gap-6 p-5 sm:grid-cols-2 sm:p-6"><InfoList title="Conditions" values={patient.conditions} /><InfoList title="Allergies" values={patient.allergies} /><InfoList title="Medications" values={patient.medications} /><div><p className="mono-label text-muted-foreground">Measurements</p><div className="mt-3 space-y-3">{patient.measurements.length ? patient.measurements.slice(0, 4).map((measurement) => <MeasurementRow key={`${measurement.label}-${measurement.recorded_at}`} measurement={measurement} />) : <p className="text-sm text-muted-foreground">None recorded</p>}</div></div></div></section><section className="rounded-2xl border border-border bg-card" aria-labelledby="risk-title"><SectionTitle eyebrow={patientView ? 'Your estimate' : 'Explainable model'} title="Risk analysis" id="risk-title" action={canAnalyse ? <RunAnalysisButton patientId={patientId} onDone={refresh} /> : undefined} /><div className="p-5 sm:p-6">{riskQuery.isLoading ? <div className="space-y-3"><Skeleton className="h-20" /><Skeleton className="h-4" /><Skeleton className="h-4" /></div> : riskQuery.isError ? <InlineUnavailable label="Risk assessment unavailable" /> : assessment?.status === 'BLOCKED' ? <BlockedCard assessment={assessment} /> : assessment ? <RiskCard patient={patient} assessment={assessment} /> : <EmptyState icon={ShieldCheck} title="Not analysed yet" detail={canAnalyse ? 'Run the analysis to see what your saved results suggest.' : 'No estimate is available for this record.'} />}</div></section></div>
    <div className="mt-6 grid gap-6 xl:grid-cols-[1.25fr_.95fr]"><section className="rounded-2xl border border-border bg-card" aria-labelledby="timeline-title"><SectionTitle eyebrow="Longitudinal record" title="Timeline" id="timeline-title" /><div className="p-5 sm:p-6">{timelineQuery.isLoading ? <div className="space-y-5"><Skeleton className="h-12" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div> : timelineQuery.isError ? <InlineUnavailable label="Timeline unavailable" /> : timeline?.length ? <div className="space-y-5">{timeline.map((event) => <TimelineRow key={event.id} event={event} />)}</div> : <EmptyState icon={Clock3} title="No timeline events" detail="New events will appear as care progresses." />}</div></section><section className="rounded-2xl border border-border bg-card" aria-labelledby="reports-title"><SectionTitle eyebrow="Documents" title="Recent reports" id="reports-title" /><div className="divide-y divide-border">{reportsQuery.isLoading ? <div className="space-y-3 p-5"><Skeleton className="h-12" /><Skeleton className="h-12" /></div> : reportsQuery.isError ? <InlineUnavailable label="Reports unavailable" /> : reports?.length ? reports.slice(0, 4).map((report) => <ReportRow key={report.id} report={report} />) : <EmptyState icon={FileText} title="No reports yet" detail="Reports linked to this patient will appear here." />}</div></section></div>
    {(canAuthor || notes?.length) ? <section className="mt-6 rounded-2xl border border-border bg-card" aria-labelledby="notes-title">
      <div className="flex items-center justify-between border-b border-border px-5 py-4 sm:px-6"><div><p className="mono-label text-muted-foreground">Clinical record</p><h2 id="notes-title" className="mt-1 text-lg font-semibold">Clinical notes</h2></div>{canAuthor && <ActionButton icon={NotebookPen} label="Add note" onClick={() => setAction('note')} />}</div>
      <div className="divide-y divide-border">{notesQuery.isLoading ? <div className="space-y-3 p-5"><Skeleton className="h-12" /><Skeleton className="h-12" /></div> : notes?.length ? notes.slice(0, 6).map((note) => <div key={note.id} className="px-5 py-4 sm:px-6" data-testid={`row-note-${note.id}`}><div className="flex items-center justify-between gap-3"><Badge className="bg-secondary text-muted-foreground">{titleCase(note.note_type)}</Badge><time className="text-[11px] text-muted-foreground">{shortDate(note.authored_at)}</time></div><p className="mt-2 whitespace-pre-line text-sm leading-relaxed">{note.body}</p><p className="mt-1 text-[11px] text-muted-foreground">{note.author}</p></div>) : <EmptyState icon={NotebookPen} title="No clinical notes" detail="Authored notes will appear here." />}</div>
    </section> : null}
    {canUseAi && <section className="mt-6 overflow-hidden rounded-2xl border border-[hsl(var(--accent)/.6)] bg-[hsl(var(--accent)/.09)]" aria-labelledby="ai-title"><div className="flex items-center justify-between border-b border-[hsl(var(--accent)/.35)] px-5 py-4 sm:px-6"><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-xl bg-[hsl(var(--accent))]"><Zap size={17} /></span><div><p className="mono-label text-muted-foreground">Assistive intelligence</p><h2 id="ai-title" className="mt-1 text-lg font-semibold">AI explanation</h2></div></div><span className="text-[11px] font-medium text-muted-foreground">{aiData?.generated_at ? `Generated ${relativeTime(aiData.generated_at as string)}` : 'Contextual'}</span></div><div className="p-5 sm:p-6">{aiQuery.isLoading ? <div className="space-y-3"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-5/6" /><Skeleton className="h-4 w-2/3" /></div> : aiQuery.isError ? <InlineUnavailable label="AI explanation unavailable" /> : aiData?.status === 'blocked' ? <InlineUnavailable label={aiData.message || 'There is nothing in this record yet that we are allowed to summarise.'} /> : aiData?.summary ? <AiCard summary={aiData as { summary: string; disclaimer: string; highlights: string[] }} /> : <EmptyState icon={Zap} title="No explanation available" detail="An explainable summary will appear when enough context is available." />}</div></section>}
  </div>;
}

function RunAnalysisButton({ patientId, onDone }: { patientId: string; onDone: () => void }) {
  const [outcome, setOutcome] = useState<{ tone: 'blocked' | 'paced'; text: string } | null>(null);
  const run = useRequestRiskAnalysis();

  function analyse() {
    setOutcome(null);
    run.mutate(
      { data: { patient_id: patientId, task: 'cvd' } },
      {
        onSuccess: (result) => {
          // A 200 is a *successful* refusal: the evidence was not good enough
          // and the system declined to guess. Say so rather than showing
          // nothing and letting the reader assume it failed.
          if (result.status === 'blocked') {
            setOutcome({ tone: 'blocked', text: result.message || 'There is not enough checked information in your record yet to give a reliable result.' });
          }
          onDone();
        },
        onError: (error) => {
          const message = error instanceof Error ? error.message.replace(/^HTTP \d+[^:]*:\s*/, '') : 'The analysis could not be run just now. Please try again.';
          setOutcome({ tone: 'paced', text: message });
        },
      },
    );
  }

  return (
    <div className="flex flex-col items-end gap-1.5">
      <button type="button" onClick={analyse} disabled={run.isPending} className="inline-flex h-10 items-center gap-2 rounded-xl bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-60" data-testid="button-run-analysis">
        {run.isPending ? <Loader2 size={15} className="animate-spin" /> : <Zap size={15} />}
        {run.isPending ? 'Analysing…' : 'Run analysis'}
      </button>
      {outcome && <p className={`max-w-xs text-right text-[11px] leading-relaxed ${outcome.tone === 'paced' ? 'text-[hsl(30_54%_32%)]' : 'text-muted-foreground'}`} data-testid="text-analysis-outcome">{outcome.text}</p>}
    </div>
  );
}

function ProfileStat({ label, value, note, critical = false, wrap = false }: { label: string; value: string; note: string; critical?: boolean; wrap?: boolean }) {
  return <div className={`rounded-2xl border p-5 ${critical ? 'border-[hsl(var(--destructive)/.24)] bg-[hsl(var(--destructive)/.04)]' : 'border-border bg-card'}`}><p className="text-xs text-muted-foreground">{label}</p><p className={`mt-3 text-lg font-semibold ${wrap ? 'text-balance leading-snug' : 'truncate'} ${critical ? 'text-[hsl(var(--destructive))]' : ''}`}>{value}</p>{note ? <p className="mt-1 truncate text-xs text-muted-foreground">{note}</p> : null}</div>;
}

function InfoList({ title, values }: { title: string; values?: string[] }) {
  return <div><p className="mono-label text-muted-foreground">{title}</p>{values?.length ? <ul className="mt-3 space-y-2">{values.map((value) => <li key={value} className="text-sm">{value}</li>)}</ul> : <p className="mt-3 text-sm text-muted-foreground">None recorded</p>}</div>;
}

function MeasurementRow({ measurement }: { measurement: PatientProfile['measurements'][number] }) {
  return <div className="text-sm">
    <div className="flex items-baseline justify-between gap-3">
      <span className="min-w-0 flex-1 text-muted-foreground">{measurement.label}</span>
      <span className="shrink-0 font-medium">{formatValue(measurement.value)} <span className="text-xs font-normal text-muted-foreground">{measurement.unit}</span></span>
    </div>
    {measurement.status && <Badge className={`mt-1 whitespace-nowrap ${measurement.status === 'OUT_OF_RANGE' ? CRITICAL_BADGE : measurement.status === 'ATTENTION' ? ATTENTION_BADGE : POSITIVE_BADGE}`}>{titleCase(measurement.status)}</Badge>}
  </div>;
}

function RiskCard({ patient, assessment }: { patient: PatientProfile; assessment: RiskAssessment }) {
  const { hasPermission } = useAuth();
  // SHAP contributions describe the model, not the person. They are meaningful
  // to a clinician reviewing the output and misleading to anyone else, who
  // reads "+0.312" as a quantity of disease.
  const showContributions = hasPermission(PERM.RISK_REVIEW);
  const factors = [...(assessment.factors || [])].sort((a, b) => a.rank - b.rank).slice(0, 5);
  const strongest = Math.max(...factors.map((f) => Math.abs(Number(f.contribution))), 1e-6);
  const reading = assessment.interpretation;

  return <div>
    {assessment.safety_notice ? <UrgentNotice notice={assessment.safety_notice} /> : null}

    {assessment.superseded_by_new_data && <div className="mb-5 flex items-start gap-2.5 rounded-xl border border-[hsl(var(--accent)/.5)] bg-[hsl(var(--accent)/.1)] p-3.5" data-testid="banner-superseded">
      <Clock3 size={16} className="mt-0.5 shrink-0 text-[hsl(30_48%_32%)]" />
      <p className="text-xs leading-relaxed">New results have been added since this estimate was made, so it is now out of date. Please run the analysis again.</p>
    </div>}

    {/* The band leads. A figure without a band is a number; a band without a
        figure is still an answer someone can act on. */}
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <p className={`text-2xl font-semibold tracking-[-.035em] ${isRiskyLevel(patient.risk_level) ? 'text-[hsl(var(--destructive))]' : ''}`} data-testid="text-risk-band">{reading?.band_label || titleCase(patient.risk_level) || 'Not assessed'}</p>
        {reading?.headline && <p className="mt-1.5 max-w-md text-sm leading-relaxed text-muted-foreground">{reading.headline}</p>}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1.5">
        {reading?.show_score && reading.score_percent != null && <p className="text-3xl font-semibold tracking-[-.05em]" data-testid="text-risk-score">{reading.score_percent}<span className="text-base text-muted-foreground">/100</span></p>}
        <Badge className={riskClass(patient.risk_level)}>{titleCase(patient.trend) || 'Stable'}</Badge>
        {assessment.lifecycle_state && <Badge className={`whitespace-nowrap ${lifecycleBadgeClass(assessment.lifecycle_state)}`}>{titleCase(assessment.lifecycle_state)}</Badge>}
      </div>
    </div>

    <div className="mt-4 h-2 overflow-hidden rounded-full bg-secondary" role="presentation">
      <div className={`h-full rounded-full ${isRiskyLevel(patient.risk_level) ? 'bg-[hsl(var(--destructive))]' : 'bg-[hsl(var(--accent))]'}`} style={{ width: `${BAND_FILL[reading?.band ?? ''] ?? Math.min(patient.risk_score ?? 0, 100)}%` }} />
    </div>

    {reading && <div className="mt-5 space-y-3 text-xs leading-relaxed">
      <p className="text-muted-foreground">{reading.what_it_means}{reading.horizon ? ` This estimate covers ${reading.horizon}.` : ''}</p>
      {!reading.show_score && reading.score_withheld_reason && <p className="text-muted-foreground" data-testid="text-score-withheld">{reading.score_withheld_reason}</p>}
      {reading.reliability_note && <p className="flex items-start gap-2 font-medium text-[hsl(30_54%_30%)]" data-testid="text-reliability-note"><AlertCircle size={13} className="mt-0.5 shrink-0" />{reading.reliability_note}</p>}
      <p className="flex items-start gap-2 rounded-xl bg-secondary/60 p-3 text-muted-foreground"><CircleHelp size={13} className="mt-0.5 shrink-0" />{reading.what_it_does_not_mean}</p>
    </div>}

    {reading?.evidence_grade && <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-border p-3">
      <ShieldHalf size={15} className="mt-0.5 shrink-0 text-muted-foreground" />
      <div>
        <p className="text-xs font-semibold" data-testid="text-evidence-grade">{reading.evidence_grade.label}</p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{reading.evidence_grade.detail}</p>
      </div>
    </div>}

    {reading?.next_steps?.length ? <div className="mt-5">
      {/* The copy is addressed to the patient. A clinician still needs to see
          it - it is what their patient is being told - but framed as such. */}
      <p className="mono-label text-muted-foreground">{showContributions ? 'What the patient is told' : 'What you can do'}</p>
      <div className="mt-3 space-y-2">{reading.next_steps.map((step) => <NextStepRow key={step.action} step={step} />)}</div>
    </div> : null}

    {factors.length > 0 && <div className="mt-6">
      <p className="mono-label text-muted-foreground">{showContributions ? 'What the model weighed most' : 'What mattered most in this estimate'}</p>
      <div className="mt-3 space-y-3">{factors.map((factor: RiskFactor) => {
        const contribution = Number(factor.contribution);
        const up = factor.direction === 'INCREASES';
        return <div key={factor.feature_name}>
          <div className="flex items-baseline justify-between gap-3">
            <p className="min-w-0 truncate text-sm font-medium">{titleCase(factor.feature_name)}</p>
            <span className={`shrink-0 text-[11px] font-semibold ${up ? 'text-[hsl(var(--destructive))]' : 'text-[hsl(162_42%_35%)]'}`}>{up ? 'Raised the estimate' : 'Lowered the estimate'}{showContributions ? ` · ${contribution > 0 ? '+' : ''}${contribution.toFixed(3)}` : ''}</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-secondary">
            <div className={`h-full rounded-full ${up ? 'bg-[hsl(var(--destructive)/.65)]' : 'bg-[hsl(162_42%_45%)]'}`} style={{ width: `${Math.max(6, (Math.abs(contribution) / strongest) * 100)}%` }} />
          </div>
        </div>;
      })}</div>
      <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">This shows how the tool reached its estimate. These are not causes of illness, and changing one of them may not change your health.</p>
    </div>}

    {assessment.limitations && assessment.limitations.length > 0 && <div className="mt-6 rounded-xl border border-[hsl(var(--accent)/.4)] bg-[hsl(var(--accent)/.08)] p-3">
      <p className="mono-label text-[hsl(30_48%_26%)]">{showContributions ? 'Known limitations' : 'Notes for your doctor'}</p>{!showContributions && <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">These are notes about the tool itself, written for a doctor. You do not need to understand them.</p>}
      <ul className="mt-2 space-y-1.5">{assessment.limitations.map((item) => <li key={item} className="flex gap-2 text-[11px] leading-relaxed text-muted-foreground"><span aria-hidden="true">·</span><span>{item}</span></li>)}</ul>
    </div>}

    {assessment.reviews && assessment.reviews.length > 0
      ? <div className="mt-4 space-y-2">{assessment.reviews.map((review) => <div key={review.id} className="rounded-xl bg-secondary/60 p-3 text-[11px] leading-relaxed"><span className="font-semibold">{titleCase(review.decision)}</span> by {review.reviewer} · {shortDate(review.created_at)}{review.rationale ? <p className="mt-1 text-muted-foreground">{review.rationale}</p> : null}</div>)}</div>
      : <p className="mt-4 flex items-start gap-2 text-[11px] leading-relaxed text-muted-foreground"><AlertCircle size={13} className="mt-0.5 shrink-0" />This is only a help to your doctor. No doctor has checked this estimate yet, and it is not a diagnosis.</p>}

    <p className="mt-5 border-t border-border pt-4 text-[11px] text-muted-foreground">{assessment.model ? `Model ${assessment.model}` : 'Model unavailable'} · Assessed {relativeTime(assessment.created_at)}</p>
  </div>;
}

// A band, not a score, drives the bar: a withheld figure must not leave an
// empty track that reads as "no risk".
const BAND_FILL: Record<string, number> = { LOW: 20, MEDIUM: 45, HIGH: 72, CRITICAL: 94 };

function UrgentNotice({ notice }: { notice: NonNullable<RiskAssessment['safety_notice']> }) {
  return <div className="mb-5 rounded-xl border-l-4 border-l-[hsl(var(--destructive))] border-y border-r border-y-[hsl(var(--destructive)/.25)] border-r-[hsl(var(--destructive)/.25)] bg-[hsl(var(--destructive)/.06)] p-4" role="alert" data-testid="banner-urgent-symptoms">
    <div className="flex items-start gap-2.5">
      <AlertCircle size={17} className="mt-0.5 shrink-0 text-[hsl(var(--destructive))]" />
      <div>
        <p className="text-sm font-semibold text-[hsl(var(--destructive))]">{notice.headline}</p>
        <p className="mt-1.5 text-xs leading-relaxed text-foreground/80">{notice.detail}</p>
        {notice.emergency_number ? <p className="mt-2 text-xs font-semibold">Emergency: {notice.emergency_number}</p> : null}
      </div>
    </div>
  </div>;
}

function NextStepRow({ step }: { step: NextStep }) {
  const Icon = step.action === 'BOOK_APPOINTMENT' ? CalendarDays : step.action === 'ADD_RESULTS' ? Upload : step.action === 'DISCUSS_SYMPTOMS' ? HeartPulse : Activity;
  const body = <>
    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground"><Icon size={15} /></span>
    <span className="min-w-0">
      <span className="block text-sm font-medium">{step.label}</span>
      <span className="mt-0.5 block text-[11px] leading-relaxed text-muted-foreground">{step.detail}</span>
    </span>
  </>;
  // An elevated estimate with no route to a clinician is alarming and inert,
  // so this one is a real link rather than advice.
  if (step.action === 'BOOK_APPOINTMENT') {
    return <Link href="/appointments" className="flex items-start gap-3 rounded-xl border border-input p-3 transition-colors hover:bg-secondary/50" data-testid="link-book-consultation">
      {body}<ArrowRight size={15} className="ml-auto mt-1.5 shrink-0 text-muted-foreground" />
    </Link>;
  }
  return <div className="flex items-start gap-3 rounded-xl border border-transparent p-3">{body}</div>;
}

function BlockedCard({ assessment }: { assessment: RiskAssessment }) {
  const block = assessment.blocked_explanation;
  return <div data-testid="card-analysis-blocked">
    <div className="flex items-start gap-3">
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-secondary text-muted-foreground"><ShieldHalf size={18} /></span>
      <div className="min-w-0">
        <p className="text-base font-semibold">{block?.headline || 'The analysis did not give a result.'}</p>
        <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{block?.detail || 'The system stopped instead of giving an estimate it could not stand behind.'}</p>
      </div>
    </div>

    {block?.data_needed?.length ? <div className="mt-5">
      <p className="mono-label text-muted-foreground">What is missing</p>
      <ul className="mt-3 space-y-2.5">{block.data_needed.map((gap: DataGap) => <li key={gap.feature} className="rounded-xl border border-input p-3">
        <p className="text-sm font-medium">{gap.label}</p>
        {gap.how_to_supply && <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{gap.how_to_supply}</p>}
      </li>)}</ul>
    </div> : null}

    {block?.resolvable_by_patient === false && <p className="mt-5 flex items-start gap-2 rounded-xl bg-secondary/60 p-3 text-[11px] leading-relaxed text-muted-foreground"><CircleHelp size={13} className="mt-0.5 shrink-0" />Adding more results will not change this. Please see a doctor, who can examine you properly. This tool cannot.</p>}

    <Link href="/appointments" className="mt-5 inline-flex h-10 items-center gap-2 rounded-xl border border-input px-3 text-sm font-medium transition-colors hover:bg-secondary/50" data-testid="link-book-consultation-blocked"><CalendarDays size={15} />Book a consultation instead</Link>

    <p className="mt-5 border-t border-border pt-4 text-[11px] text-muted-foreground">Nothing has been added to your health record from this attempt · {relativeTime(assessment.created_at)}</p>
  </div>;
}

function TimelineRow({ event }: { event: TimelineEvent }) {
  const Icon = event.type === 'alert' ? Bell : event.type === 'report' ? FileText : event.type === 'measurement' ? BarChart3 : event.type === 'assessment' ? ShieldCheck : FileText;
  return <div className="relative flex gap-3 pl-1"><span className="grid size-8 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground"><Icon size={15} /></span><div className="min-w-0"><p className="text-sm font-medium">{event.title}</p><p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{event.detail}</p><time className="mt-1 block text-[11px] text-muted-foreground">{shortDate(event.occurred_at)}</time></div></div>;
}

function ReportRow({ report }: { report: MedicalReport }) {
  return <Link href={`/reports/${report.id}`} className="flex items-center gap-3 px-5 py-4 hover:bg-secondary/40" data-testid={`link-report-${report.id}`}><span className="grid size-9 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground"><FileText size={16} /></span><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{report.title}</p><p className="mt-0.5 text-xs text-muted-foreground">{titleCase(report.report_class)} · {shortDate(report.created_at)}</p></div><Badge className={statusClass(report.processing_state)}>{titleCase(report.processing_state)}</Badge></Link>;
}

function AiCard({ summary }: { summary: { summary: string; disclaimer: string; highlights: string[] } }) {
  return <div><p className="max-w-4xl whitespace-pre-line text-sm leading-7">{summary.summary}</p><div className="mt-5 flex flex-wrap gap-2">{summary.highlights.map((highlight) => <span key={highlight} className="rounded-lg border border-[hsl(var(--accent)/.35)] bg-card/60 px-2.5 py-1.5 text-xs leading-relaxed">{highlight}</span>)}</div><p className="mt-5 text-[11px] leading-relaxed text-muted-foreground">{summary.disclaimer}</p></div>;
}

// ===========================================================================
// Role-gated write actions
// ---------------------------------------------------------------------------
// Every dialog below posts to a real Django endpoint that re-authorizes the
// caller. The permission checks here only decide whether the control is worth
// offering - they are never the enforcement boundary.
// ===========================================================================

const REPORT_CLASS_OPTIONS: ReportClass[] = [
  'CBC', 'LIPID', 'GLUCOSE', 'HBA1C', 'LIVER', 'KIDNEY', 'URINALYSIS', 'PATHOLOGY',
  'RADIOLOGY', 'PRESCRIPTION', 'DISCHARGE', 'CLINICAL_NOTE', 'OTHER',
];
const CLINICAL_DATA_STATES: ClinicalDataState[] = [
  'OBSERVED', 'DERIVED', 'NOT_REPORTED', 'NOT_APPLICABLE', 'PENDING',
];

type PickedPatient = { id: string; name: string };

function PatientPicker({ value, onSelect }: { value: PickedPatient | null; onSelect: (patient: PickedPatient | null) => void }) {
  const [search, setSearch] = useState('');
  const params = { search: search.trim() || undefined, page_size: 6 };
  const query = useListPatients(params, {
    query: { queryKey: getListPatientsQueryKey(params), enabled: !value && search.trim().length > 1 },
  });
  if (value) {
    return (
      <div className="flex items-center justify-between rounded-xl border border-input bg-secondary/40 px-3 py-2.5 text-sm">
        <span className="font-medium">{value.name}</span>
        <button type="button" onClick={() => onSelect(null)} className="text-xs font-semibold text-muted-foreground hover:text-foreground" data-testid="button-change-patient">Change</button>
      </div>
    );
  }
  return (
    <div>
      <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by patient name or MRN" className={FIELD_CLASS} data-testid="input-patient-picker" />
      {search.trim().length > 1 && (
        <div className="mt-2 max-h-44 overflow-y-auto rounded-xl border border-border">
          {query.isLoading ? <p className="px-3 py-2 text-xs text-muted-foreground">Searching…</p>
            : query.data?.results.length ? query.data.results.map((patient) => (
              <button type="button" key={patient.id} onClick={() => onSelect({ id: patient.id, name: patient.full_name })} className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-secondary/60" data-testid={`option-patient-${patient.id}`}>
                <span>{patient.full_name}</span><span className="text-xs text-muted-foreground">{patient.mrn}</span>
              </button>
            )) : <p className="px-3 py-2 text-xs text-muted-foreground">No matching patients.</p>}
        </div>
      )}
    </div>
  );
}

function UploadReportModal({ patient, onClose, onDone }: { patient: PickedPatient | null; onClose: () => void; onDone: () => void }) {
  const [target, setTarget] = useState<PickedPatient | null>(patient);
  const [file, setFile] = useState<File | null>(null);
  const [classHint, setClassHint] = useState('');
  const upload = useUploadReport();
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!target || !file) return;
    upload.mutate(
      { data: { patient_id: target.id, file, class_hint: (classHint || undefined) as ReportClass | undefined } },
      { onSuccess: () => { onDone(); onClose(); } },
    );
  }
  return (
    <Modal title="Upload report" description="The file is stored privately and queued for extraction. Structured values are never read from the client." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-upload-report">
        <FormField label="Patient"><PatientPicker value={target} onSelect={setTarget} /></FormField>
        <FormField label="Report file">
          <input type="file" required onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="block w-full text-sm text-muted-foreground file:mr-3 file:rounded-lg file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium file:text-foreground" data-testid="input-report-file" />
        </FormField>
        <FormField label="Type (optional)">
          <select value={classHint} onChange={(event) => setClassHint(event.target.value)} className={FIELD_CLASS} data-testid="select-report-class">
            <option value="">Let the pipeline classify</option>
            {REPORT_CLASS_OPTIONS.map((option) => <option key={option} value={option}>{titleCase(option)}</option>)}
          </select>
        </FormField>
        <FormError error={upload.error} />
        <ModalActions onClose={onClose} submitting={upload.isPending} disabled={!target || !file} submitLabel="Upload" />
      </form>
    </Modal>
  );
}

function ClinicalNoteModal({ patientId, onClose, onDone }: { patientId: string; onClose: () => void; onDone: () => void }) {
  const [noteType, setNoteType] = useState<ClinicalNoteType>('PROGRESS');
  const [body, setBody] = useState('');
  const create = useCreateClinicalNote();
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!body.trim()) return;
    create.mutate(
      { data: { patient_id: patientId, body, note_type: noteType } },
      { onSuccess: () => { onDone(); onClose(); } },
    );
  }
  return (
    <Modal title="Add clinical note" description="Notes are append-only. A correction is added later as an addendum rather than an edit." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-clinical-note">
        <FormField label="Note type">
          <select value={noteType} onChange={(event) => setNoteType(event.target.value as ClinicalNoteType)} className={FIELD_CLASS} data-testid="select-note-type">
            <option value="PROGRESS">Progress note</option>
            <option value="ASSESSMENT">Assessment</option>
          </select>
        </FormField>
        <FormField label="Body">
          <textarea value={body} onChange={(event) => setBody(event.target.value)} rows={5} required className="w-full rounded-xl border border-input bg-background p-3 text-sm outline-none focus:border-primary" data-testid="input-note-body" />
        </FormField>
        <FormError error={create.error} />
        <ModalActions onClose={onClose} submitting={create.isPending} disabled={!body.trim()} submitLabel="Save note" />
      </form>
    </Modal>
  );
}

function PrescribeMedicationModal({ patientId, onClose, onDone }: { patientId: string; onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ name: '', dose: '', route: '', frequency: '', status: 'ACTIVE' as MedicationStatus });
  const create = useCreateMedication();
  const update = (key: keyof typeof form) => (event: { target: { value: string } }) => setForm((prev) => ({ ...prev, [key]: event.target.value }));
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.name.trim()) return;
    create.mutate(
      {
        data: {
          patient_id: patientId,
          name: form.name,
          dose: form.dose || undefined,
          route: form.route || undefined,
          frequency: form.frequency || undefined,
          status: form.status,
        },
      },
      { onSuccess: () => { onDone(); onClose(); } },
    );
  }
  return (
    <Modal title="Prescribe medication" description="Recorded on the patient's structured medication list with you as the author." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-prescribe-medication">
        <FormField label="Medication"><input value={form.name} onChange={update('name')} required className={FIELD_CLASS} data-testid="input-medication-name" /></FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Dose"><input value={form.dose} onChange={update('dose')} placeholder="e.g. 500 mg" className={FIELD_CLASS} data-testid="input-medication-dose" /></FormField>
          <FormField label="Route"><input value={form.route} onChange={update('route')} placeholder="e.g. oral" className={FIELD_CLASS} data-testid="input-medication-route" /></FormField>
        </div>
        <FormField label="Frequency"><input value={form.frequency} onChange={update('frequency')} placeholder="e.g. twice daily" className={FIELD_CLASS} data-testid="input-medication-frequency" /></FormField>
        <FormField label="Status">
          <select value={form.status} onChange={update('status')} className={FIELD_CLASS} data-testid="select-medication-status">
            <option value="ACTIVE">Active</option>
            <option value="STOPPED">Stopped</option>
            <option value="COMPLETED">Completed</option>
          </select>
        </FormField>
        <FormError error={create.error} />
        <ModalActions onClose={onClose} submitting={create.isPending} disabled={!form.name.trim()} submitLabel="Prescribe" />
      </form>
    </Modal>
  );
}

const PATIENT_SEXES = ['FEMALE', 'MALE', 'INTERSEX', 'UNKNOWN'] as const;

function RegisterPatientInlineModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ mrn: '', given_name: '', family_name: '', date_of_birth: '' });
  const [sex, setSex] = useState<PatientSex>('UNKNOWN');
  const register = useRegisterPatient();
  const update = (key: keyof typeof form) => (event: { target: { value: string } }) => setForm((prev) => ({ ...prev, [key]: event.target.value }));
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.mrn.trim() || !form.given_name.trim() || !form.family_name.trim()) return;
    register.mutate(
      { data: { mrn: form.mrn, given_name: form.given_name, family_name: form.family_name, date_of_birth: form.date_of_birth || null, sex } },
      { onSuccess: () => { onDone(); onClose(); } },
    );
  }
  return (
    <Modal title="Register patient" description="Creates an identity only. Registering a patient as a clinician places you on their care team." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-register-patient-inline">
        <FormField label="Medical record number (MRN)"><input value={form.mrn} onChange={update('mrn')} required className={FIELD_CLASS} data-testid="input-inline-mrn" /></FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Given name"><input value={form.given_name} onChange={update('given_name')} required className={FIELD_CLASS} data-testid="input-inline-given" /></FormField>
          <FormField label="Family name"><input value={form.family_name} onChange={update('family_name')} required className={FIELD_CLASS} data-testid="input-inline-family" /></FormField>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Date of birth"><input type="date" value={form.date_of_birth} onChange={update('date_of_birth')} className={FIELD_CLASS} data-testid="input-inline-dob" /></FormField>
          <FormField label="Sex">
            <select value={sex} onChange={(event) => setSex(event.target.value as PatientSex)} className={FIELD_CLASS} data-testid="select-inline-sex">
              {PATIENT_SEXES.map((option) => <option key={option} value={option}>{titleCase(option)}</option>)}
            </select>
          </FormField>
        </div>
        <FormError error={register.error} />
        <ModalActions onClose={onClose} submitting={register.isPending} disabled={!form.mrn.trim() || !form.given_name.trim() || !form.family_name.trim()} submitLabel="Register patient" />
      </form>
    </Modal>
  );
}

function LabOrderModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [target, setTarget] = useState<PickedPatient | null>(null);
  const [panel, setPanel] = useState('');
  const create = useCreateLabOrder();
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!target || !panel.trim()) return;
    create.mutate(
      { data: { patient_id: target.id, panel } },
      { onSuccess: () => { onDone(); onClose(); } },
    );
  }
  return (
    <Modal title="New lab order" description="Opens a workflow linking your laboratory to this patient." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-lab-order">
        <FormField label="Patient"><PatientPicker value={target} onSelect={setTarget} /></FormField>
        <FormField label="Panel"><input value={panel} onChange={(event) => setPanel(event.target.value)} required placeholder="e.g. LIPID, CBC" className={FIELD_CLASS} data-testid="input-lab-panel" /></FormField>
        <FormError error={create.error} />
        <ModalActions onClose={onClose} submitting={create.isPending} disabled={!target || !panel.trim()} submitLabel="Create order" />
      </form>
    </Modal>
  );
}

function LabResultModal({ order, onClose, onDone }: { order: LabOrder; onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ analyte: '', state: 'OBSERVED' as ClinicalDataState, value: '', unit: '', method: '' });
  const enter = useEnterLabResult();
  const update = (key: keyof typeof form) => (event: { target: { value: string } }) => setForm((prev) => ({ ...prev, [key]: event.target.value }));
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.analyte.trim()) return;
    enter.mutate(
      {
        orderId: order.id,
        data: {
          analyte: form.analyte,
          state: form.state,
          value: form.value.trim() || undefined,
          unit: form.unit || undefined,
          method: form.method || undefined,
        },
      },
      { onSuccess: () => { onDone(); onClose(); } },
    );
  }
  return (
    <Modal title={`Enter result · ${order.panel}`} description="Units are standardised on the server and the values are checked for anything unusual." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-lab-result">
        <FormField label="Analyte"><input value={form.analyte} onChange={update('analyte')} required placeholder="e.g. LDL cholesterol" className={FIELD_CLASS} data-testid="input-result-analyte" /></FormField>
        <FormField label="Reported state">
          <select value={form.state} onChange={update('state')} className={FIELD_CLASS} data-testid="select-result-state">
            {CLINICAL_DATA_STATES.map((state) => <option key={state} value={state}>{titleCase(state)}</option>)}
          </select>
        </FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Value"><input value={form.value} onChange={update('value')} inputMode="decimal" className={FIELD_CLASS} data-testid="input-result-value" /></FormField>
          <FormField label="Unit"><input value={form.unit} onChange={update('unit')} placeholder="e.g. mg/dL" className={FIELD_CLASS} data-testid="input-result-unit" /></FormField>
        </div>
        <FormField label="Method (optional)"><input value={form.method} onChange={update('method')} className={FIELD_CLASS} data-testid="input-result-method" /></FormField>
        <FormError error={enter.error} />
        <ModalActions onClose={onClose} submitting={enter.isPending} disabled={!form.analyte.trim()} submitLabel="Record result" />
      </form>
    </Modal>
  );
}

function LabValidateModal({ result, onClose, onDone }: { result: LabResult; onClose: () => void; onDone: () => void }) {
  const [status, setStatus] = useState<ValidationStatus>('PASSED');
  const [note, setNote] = useState('');
  const validate = useValidateLabResult();
  function submit(event: FormEvent) {
    event.preventDefault();
    validate.mutate(
      { resultId: result.id, data: { status, note: note || undefined } },
      { onSuccess: () => { onDone(); onClose(); } },
    );
  }
  return (
    <Modal title={`Validate · ${result.analyte}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-lab-validate">
        <FormField label="Outcome">
          <select value={status} onChange={(event) => setStatus(event.target.value as ValidationStatus)} className={FIELD_CLASS} data-testid="select-validate-status">
            <option value="PASSED">Passed</option>
            <option value="REVIEW_REQUIRED">Review required</option>
            <option value="FAILED">Failed</option>
          </select>
        </FormField>
        <FormField label="Note (optional)"><input value={note} onChange={(event) => setNote(event.target.value)} className={FIELD_CLASS} data-testid="input-validate-note" /></FormField>
        <FormError error={validate.error} />
        <ModalActions onClose={onClose} submitting={validate.isPending} submitLabel="Submit validation" />
      </form>
    </Modal>
  );
}

function LabWorkspace() {
  const { hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const params = { page };
  const query = useListLabOrders(params, { query: { queryKey: getListLabOrdersQueryKey(params) } });
  const [newOrder, setNewOrder] = useState(false);
  const [resultFor, setResultFor] = useState<LabOrder | null>(null);
  const [validateFor, setValidateFor] = useState<LabResult | null>(null);
  const [uploadFor, setUploadFor] = useState<PickedPatient | null>(null);

  const canWorkflow = hasPermission(PERM.LAB_WORKFLOW_ACCESS);
  const canEnter = hasPermission(PERM.LAB_RESULT_ENTER);
  const canValidate = hasPermission(PERM.LAB_RESULT_VALIDATE);
  const canUpload = hasPermission(PERM.LAB_REPORT_UPLOAD);
  const refresh = () => queryClient.invalidateQueries({ queryKey: getListLabOrdersQueryKey(params) });

  if (!canWorkflow) {
    return <NoAccessPage title="Lab workspace" detail="This page is for laboratory staff, who enter and verify test results. Your account does not have laboratory access." />;
  }

  const data = query.data;
  return <div className="page-enter">
    <PageHeading eyebrow="CareSense / laboratory" title="Lab workspace" detail="Orders linked to your laboratory. Enter and validate results, or upload the source report." action={<ActionButton icon={Plus} label="New order" variant="primary" onClick={() => setNewOrder(true)} />} />
    {query.isLoading ? <PageLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} message="Lab workspace is unavailable." /> : data?.results.length ? <>
      <div className="space-y-4">{data.results.map((order) => (
        <section key={order.id} className="rounded-2xl border border-border bg-card p-5 sm:p-6" data-testid={`card-lab-order-${order.id}`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold">{titleCase(order.panel)}</h2><Badge className={`whitespace-nowrap ${labStatusClass(order.status)}`}>{titleCase(order.status)}</Badge></div>
              <p className="mt-1 text-sm font-medium">{order.patient_name || 'Unnamed patient'} <span className="font-normal text-muted-foreground">{formatMrn(order.patient_mrn)}</span></p>
              <p className="mt-0.5 text-xs text-muted-foreground">{order.laboratory} · Requested {relativeTime(order.requested_at)}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {canEnter && <ActionButton icon={Plus} label="Enter result" onClick={() => setResultFor(order)} />}
              {canUpload && <ActionButton icon={Upload} label="Upload report" onClick={() => setUploadFor({ id: order.patient_id, name: order.patient_name || `Patient ${order.patient_id.slice(0, 8)}` })} />}
            </div>
          </div>
          <div className="mt-4 divide-y divide-border border-t border-border">
            {order.results.length ? order.results.map((result) => {
              const latest = result.validations[result.validations.length - 1];
              return (
                <div key={result.id} className="flex flex-wrap items-center justify-between gap-3 py-3" data-testid={`row-lab-result-${result.id}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{titleCase(result.analyte)}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{formatValue(result.value_normalized ?? result.value_raw)} {result.unit_normalized || result.unit_raw} · {titleCase(result.state)}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {latest ? <Badge className={`whitespace-nowrap ${labStatusClass(latest.status)}`}>{titleCase(latest.status)}</Badge> : <Badge className={`whitespace-nowrap ${NEUTRAL_BADGE}`}>Unvalidated</Badge>}
                    {canValidate && <ActionButton icon={Check} label="Validate" onClick={() => setValidateFor(result)} />}
                  </div>
                </div>
              );
            }) : <p className="py-3 text-xs text-muted-foreground">No results entered yet.</p>}
          </div>
        </section>
      ))}</div>
      <PageButton page={page} pageSize={data.page_size} count={data.count} onChange={setPage} />
    </> : <div className="rounded-2xl border border-border bg-card"><EmptyState icon={FlaskConical} title="No lab orders" detail="Create an order to begin a laboratory workflow." /></div>}
    {newOrder && <LabOrderModal onClose={() => setNewOrder(false)} onDone={refresh} />}
    {resultFor && <LabResultModal order={resultFor} onClose={() => setResultFor(null)} onDone={refresh} />}
    {validateFor && <LabValidateModal result={validateFor} onClose={() => setValidateFor(null)} onDone={refresh} />}
    {uploadFor && <UploadReportModal patient={uploadFor} onClose={() => setUploadFor(null)} onDone={refresh} />}
  </div>;
}

function Reports() {
  const { hasPermission, hasAnyPermission } = useAuth();
  const patientView = isPatientView(hasPermission);
  const queryClient = useQueryClient();
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const [uploadOpen, setUploadOpen] = useState(false);
  const params: { status?: ReportProcessingState; page?: number } = { status: (status || undefined) as ReportProcessingState | undefined, page };
  const query = useListReports(params, { query: { queryKey: getListReportsQueryKey(params) } });
  const reviewQuery = useListReports({ status: 'REVIEW_REQUIRED' as ReportProcessingState, page_size: 1 }, { query: { queryKey: getListReportsQueryKey({ status: 'REVIEW_REQUIRED' as ReportProcessingState, page_size: 1 }) } });
  const finalizedQuery = useListReports({ status: 'FINALIZED' as ReportProcessingState, page_size: 1 }, { query: { queryKey: getListReportsQueryKey({ status: 'FINALIZED' as ReportProcessingState, page_size: 1 }) } });
  const data = query.data;
  const inProgressCount = data?.results.filter((report) => IN_PROGRESS_STATES.has(report.processing_state)).length;
  const canUpload = hasAnyPermission(PERM.REPORT_UPLOAD_OWN, PERM.LAB_REPORT_UPLOAD);
  if (!hasAnyPermission(PERM.REPORT_READ_OWN, PERM.REPORT_READ_ASSIGNED, PERM.LAB_REPORT_UPLOAD)) {
    return <NoAccessPage title="Reports" detail="Your account is not allowed to open patient reports." />;
  }
  return <div className="page-enter"><PageHeading eyebrow={patientView ? 'CareSense / my reports' : 'CareSense / documents'} title={patientView ? 'My reports' : 'Reports'} detail={patientView ? 'Lab reports and other reports saved on your record. Upload a new report to keep your risk estimate up to date.' : 'Track extraction quality and review reports before they reach the care record.'} action={<div className="flex flex-wrap items-center gap-2">{canUpload && <ActionButton icon={Upload} label="Upload report" variant="primary" onClick={() => setUploadOpen(true)} />}<SelectFilter label="Status" value={status} onChange={(value) => { setStatus(value); setPage(1); }} options={REPORT_FILTER_OPTIONS} testId="select-report-status" /></div>} />
    {uploadOpen && <UploadReportModal patient={null} onClose={() => setUploadOpen(false)} onDone={() => queryClient.invalidateQueries({ queryKey: getListReportsQueryKey(params) })} />}
    <div className="mb-6 grid gap-3 sm:grid-cols-3"><ReportMetric label="On this page in processing" value={inProgressCount} /><ReportMetric label="Ready to review (total)" value={reviewQuery.data?.count} /><ReportMetric label="Finalised (total)" value={finalizedQuery.data?.count} /></div>
    {query.isLoading ? <PageLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} message="Report workspace is unavailable." /> : data?.results.length ? <>
      <div className="overflow-hidden rounded-2xl border border-border bg-card"><div className="hidden grid-cols-[1.4fr_1fr_.75fr_.9fr_1fr] gap-4 border-b border-border px-5 py-3 mono-label text-muted-foreground md:grid"><span>Report</span><span>Patient</span><span>Type</span><span>Status</span><span>Uploaded</span></div><div className="divide-y divide-border">{data.results.map((report) => <div key={report.id} className="grid gap-3 px-5 py-4 hover:bg-secondary/35 md:grid-cols-[1.4fr_1fr_.75fr_.9fr_1fr] md:items-center md:gap-4" data-testid={`row-report-${report.id}`}><Link href={`/reports/${report.id}`} className="flex min-w-0 items-center gap-3 hover:underline" data-testid={`link-report-${report.id}`}><span className="grid size-9 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground"><FileText size={16} /></span><div className="min-w-0"><p className="truncate text-sm font-semibold">{report.title}</p><p className="text-xs text-muted-foreground">{report.uploaded_by ? `Uploaded by ${report.uploaded_by}` : 'Upload source unknown'}</p></div></Link><Link href={`/patients/${report.patient_id}`} className="truncate text-sm font-medium hover:underline" data-testid={`link-report-patient-${report.id}`}>{report.patient_name}</Link><p className="text-xs text-muted-foreground">{titleCase(report.report_class) || 'Unclassified'}</p><Badge className={`w-fit ${statusClass(report.processing_state)}`}>{IN_PROGRESS_STATES.has(report.processing_state) && <span className="mr-1.5 size-1.5 animate-pulse rounded-full bg-current" />}{titleCase(report.processing_state)}</Badge><p className="text-xs text-muted-foreground">{shortDate(report.created_at)}</p></div>)}</div></div>
      <PageButton page={page} pageSize={data.page_size} count={data.count} onChange={setPage} />
    </> : <div className="rounded-2xl border border-border bg-card"><EmptyState icon={FileText} title="No reports in this view" detail="Processed and incoming clinical reports will appear here." /></div>}
  </div>;
}

function ReportMetric({ label, value }: { label: string; value?: number }) {
  return <div className="rounded-2xl border border-border bg-card p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-2 text-2xl font-semibold tracking-[-.04em]">{value ?? '—'}</p></div>;
}

function ReportDetailPage() {
  const { reportId = '' } = useParams<{ reportId: string }>();
  const enabled = Boolean(reportId);
  const reportQuery = useGetReport(reportId, { query: { queryKey: getGetReportQueryKey(reportId), enabled } });
  const qualityQuery = useGetReportQuality(reportId, { query: { queryKey: getGetReportQualityQueryKey(reportId), enabled } });
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const report = reportQuery.data as MedicalReport | undefined;

  async function handleDownload() {
    if (!report) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const blob = await downloadReportFile(reportId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = report.original_filename || report.title || 'report';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : 'The original file could not be downloaded.');
    } finally {
      setDownloading(false);
    }
  }

  if (reportQuery.isLoading) return <PageLoading />;
  if (reportQuery.isError || !report) return <QueryError onRetry={() => reportQuery.refetch()} message="This report is unavailable." />;
  const quality = qualityQuery.data as ReportQuality | undefined;
  const tests = report.tests ?? [];
  const findings = report.findings ?? [];
  const isReview = report.processing_state === 'REVIEW_REQUIRED' || report.processing_state === 'REJECTED';
  return <div className="page-enter">
    <Link href="/reports" className="mb-6 inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground" data-testid="link-back-reports"><ChevronLeft size={16} />All reports</Link>
    <div className="mb-7 flex flex-col justify-between gap-5 lg:flex-row lg:items-start">
      <div className="flex items-start gap-4">
        <span className="grid size-14 shrink-0 place-items-center rounded-2xl bg-secondary text-muted-foreground"><FileText size={22} /></span>
        <div>
          <div className="flex flex-wrap items-center gap-2"><h1 className="text-3xl font-semibold tracking-[-.045em]">{report.title}</h1><Badge className={statusClass(report.processing_state)}>{titleCase(report.processing_state)}</Badge></div>
          <p className="mt-1 text-sm text-muted-foreground">{titleCase(report.report_class) || 'Unclassified'} · <Link href={`/patients/${report.patient_id}`} className="font-medium hover:underline" data-testid="link-report-patient">{report.patient_name}</Link></p>
          <p className="mt-2 text-xs text-muted-foreground">{report.uploaded_by ? `Uploaded by ${report.uploaded_by}` : 'Upload source unknown'} · {shortDate(report.created_at)}</p>
        </div>
      </div>
      {report.original_filename ? <div className="flex flex-col items-start gap-1">
        <button onClick={handleDownload} disabled={downloading} className="inline-flex h-10 items-center gap-2 rounded-xl border border-input bg-card px-3 text-sm font-medium hover:bg-secondary disabled:opacity-60" data-testid="button-download-report">{downloading ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}Download original</button>
        {downloadError && <span className="text-xs text-[hsl(var(--destructive))]">{downloadError}</span>}
      </div> : null}
    </div>

    {report.review_reason ? <div className="mb-6"><InlineUnavailable label={`${isReview ? 'Review reason' : 'Note'}: ${report.review_reason}`} /></div> : null}

    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <ProfileStat label="Processing state" value={titleCase(report.processing_state)} note={report.completeness_status ? titleCase(report.completeness_status) : 'Completeness unknown'} critical={isReview} />
      <ProfileStat label="Validation" value={quality ? quality.validation : titleCase(report.validation_status) || '—'} note={quality ? `${quality.tests_validated}/${quality.tests_total} tests validated` : 'Awaiting quality run'} />
      <ProfileStat label="Extraction reliability" value={quality ? titleCase(quality.extraction_reliability) : '—'} note={quality ? `${quality.required_fields_missing} required field(s) missing` : ''} />
      <ProfileStat label="Collected" value={shortDate(report.collected_at)} note={report.reported_at ? `Reported ${shortDate(report.reported_at)}` : 'Reported date unknown'} />
    </div>

    <div className="mt-6 grid gap-6 xl:grid-cols-[1.1fr_.9fr]">
      <section className="overflow-hidden rounded-2xl border border-border bg-card" aria-labelledby="tests-title">
        <SectionTitle eyebrow="Structured extraction" title="Tests" id="tests-title" />
        <div className="overflow-x-auto">
          {tests.length ? <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left mono-label text-muted-foreground"><th className="px-5 py-3 font-normal">Analyte</th><th className="px-3 py-3 font-normal">Value</th><th className="px-3 py-3 font-normal">Reference</th><th className="px-5 py-3 font-normal">State</th></tr></thead>
            <tbody className="divide-y divide-border">{tests.map((test, index) => <tr key={`${test.name}-${index}`} data-testid={`row-report-test-${index}`}>
              <td className="px-5 py-3 font-medium">{test.name}{test.loinc_code ? <span className="ml-2 text-xs text-muted-foreground">{test.loinc_code}</span> : null}</td>
              <td className="px-3 py-3">{formatValue(test.value_normalized ?? test.value_raw)} <span className="text-xs text-muted-foreground">{test.unit_normalized || test.unit_raw}</span></td>
              <td className="px-3 py-3 text-xs text-muted-foreground">{test.reference_range || '—'}</td>
              <td className="px-5 py-3"><div className="flex flex-wrap items-center gap-1.5">{test.state ? <Badge className={`whitespace-nowrap ${NEUTRAL_BADGE}`}>{titleCase(test.state)}</Badge> : null}{test.validation_status ? <Badge className={`whitespace-nowrap ${labStatusClass(test.validation_status)}`}>{titleCase(test.validation_status)}</Badge> : null}</div></td>
            </tr>)}</tbody>
          </table> : <div className="p-5"><EmptyState icon={BarChart3} title="No structured tests" detail="Extraction produced no tabular results for this report." /></div>}
        </div>
      </section>
      <section className="rounded-2xl border border-border bg-card" aria-labelledby="findings-title">
        <SectionTitle eyebrow="Narrative" title="Findings" id="findings-title" />
        <div className="divide-y divide-border">{findings.length ? findings.map((finding, index) => <div key={index} className="px-5 py-4" data-testid={`row-report-finding-${index}`}><p className="mono-label text-muted-foreground">{titleCase(finding.category)}</p><p className="mt-1 text-sm leading-relaxed">{finding.text}</p></div>) : <div className="p-5"><EmptyState icon={FileText} title="No findings" detail="No narrative findings were captured." /></div>}</div>
      </section>
    </div>

    {quality ? <p className="mt-6 text-[11px] leading-relaxed text-muted-foreground">{quality.note}</p> : null}
  </div>;
}

function MessagesPanel() {
  const queryClient = useQueryClient();
  const params = { page_size: 10 };
  const query = useListNotifications(params, { query: { queryKey: getListNotificationsQueryKey(params) } });
  const markRead = useMarkNotificationRead({
    mutation: { onSuccess: () => queryClient.invalidateQueries({ queryKey: getListNotificationsQueryKey(params) }) },
  });
  const rows = (query.data?.results || []) as Notification[];
  const unread = rows.filter((row) => row.status !== 'READ').length;

  return <section className="mb-6 rounded-2xl border border-border bg-card" aria-labelledby="messages-title" data-testid="panel-messages">
    <SectionTitle eyebrow="For you" title={unread ? `Messages (${unread} unread)` : 'Messages'} id="messages-title" />
    <div className="p-5 sm:p-6">
      {query.isLoading ? <Skeleton className="h-16" />
        : query.isError ? <InlineUnavailable label="Messages are unavailable just now." />
        : rows.length ? <div className="space-y-3">{rows.map((row) => <div key={row.id} className={`rounded-xl border p-3.5 ${row.status === 'READ' ? 'border-border' : 'border-[hsl(var(--accent)/.5)] bg-[hsl(var(--accent)/.07)]'}`} data-testid={`row-message-${row.id}`}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold">{row.subject}</p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{row.body}</p>
                <p className="mt-1.5 text-[11px] text-muted-foreground">{relativeTime(row.created_at)}</p>
              </div>
              {row.status !== 'READ' && <button type="button" onClick={() => markRead.mutate({ id: row.id })} disabled={markRead.isPending} className="shrink-0 rounded-lg border border-input px-2.5 py-1 text-[11px] font-medium hover:bg-secondary disabled:opacity-50" data-testid={`button-mark-read-${row.id}`}>Mark as read</button>}
            </div>
          </div>)}</div>
        : <EmptyState icon={Bell} title="No messages" detail="Anything CareSense needs to tell you will appear here." />}
    </div>
  </section>;
}

function Alerts() {
  const queryClient = useQueryClient();
  const { hasPermission, hasAnyPermission } = useAuth();
  const patientView = isPatientView(hasPermission);
  const [openOnly, setOpenOnly] = useState(false);
  const [page, setPage] = useState(1);
  const params: { status?: AlertStatus; page?: number } = { status: openOnly ? ('OPEN' as AlertStatus) : undefined, page };
  const query = useListAlerts(params, { query: { queryKey: getListAlertsQueryKey(params) } });
  const acknowledge = useAcknowledgeAlert({ mutation: { onSuccess: () => queryClient.invalidateQueries({ queryKey: getListAlertsQueryKey(params) }) } });
  const resolve = useResolveAlert({ mutation: { onSuccess: () => queryClient.invalidateQueries({ queryKey: getListAlertsQueryKey(params) }) } });
  const canManage = hasPermission(PERM.ALERT_MANAGE);
  const data = query.data;
  if (!hasAnyPermission(PERM.ALERT_MANAGE, PERM.PATIENT_READ_OWN)) {
    return <NoAccessPage title="Alerts" detail="Alerts belong to a patient record, and your account is not allowed to open patient records." />;
  }
  return <div className="page-enter"><MessagesPanel /><PageHeading eyebrow="CareSense / alerts" title={patientView ? 'My alerts' : 'Alerts'} detail={patientView ? 'Things your care team has flagged on your record. Only your doctor can close them.' : canManage ? 'Clinical signals across the records you are authorised to see, most urgent first.' : 'Clinical signals across the records you are authorised to see. Only the assigned doctor can acknowledge or close them.'} action={<button onClick={() => { setOpenOnly((value) => !value); setPage(1); }} className={`inline-flex h-10 items-center gap-2 rounded-xl border px-3 text-sm font-medium ${openOnly ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-card hover:bg-secondary'}`} aria-pressed={openOnly} data-testid="button-toggle-unread"><Filter size={15} />{openOnly ? 'Open only' : 'All alerts'}</button>} />
    {query.isLoading ? <PageLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} message="Alerts could not be loaded." /> : data?.results.length ? <>
      <div className="space-y-3">{data.results.map((alert) => <AlertRow key={alert.id} alert={alert} canManage={canManage} onAcknowledge={() => acknowledge.mutate({ alertId: alert.id })} onResolve={() => resolve.mutate({ alertId: alert.id })} />)}</div>
      <PageButton page={page} pageSize={data.page_size} count={data.count} onChange={setPage} />
    </> : <div className="rounded-2xl border border-border bg-card"><EmptyState icon={CheckCircle2} title={openOnly ? 'You are all caught up' : 'No active alerts'} detail="There are no signals requiring your attention right now." /></div>}
  </div>;
}

function AlertRow({ alert, canManage, onAcknowledge, onResolve }: { alert: Alert; canManage: boolean; onAcknowledge: () => void; onResolve: () => void }) {
  const isOpen = alert.status === 'OPEN';
  return <article className={`rounded-2xl border bg-card p-4 sm:p-5 ${!isOpen ? 'border-border' : 'border-l-4 border-l-[hsl(var(--accent))] border-y-border border-r-border'}`} data-testid={`card-alert-${alert.id}`}><div className="flex items-start gap-3"><span className={`mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl ${alert.severity === 'HIGH' ? 'bg-[hsl(var(--destructive)/.1)] text-[hsl(var(--destructive))]' : 'bg-[hsl(var(--accent)/.25)] text-[hsl(30_48%_26%)]'}`}><Bell size={16} /></span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold">{alert.title}</h2><Badge className={isOpen ? 'bg-[hsl(var(--accent)/.25)] text-[hsl(30_48%_26%)]' : 'bg-secondary text-muted-foreground'}>{titleCase(alert.status)}</Badge></div><Link href={`/patients/${alert.patient_id}`} className="mt-0.5 block text-xs font-medium text-muted-foreground hover:underline">{alert.patient_name}</Link><p className="mt-1 text-sm leading-relaxed text-muted-foreground">{alert.detail}</p><div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground"><span>{titleCase(alert.category)}</span><span className={alert.severity === 'HIGH' ? 'font-semibold text-[hsl(var(--destructive))]' : ''}>{titleCase(alert.severity)} severity</span><time>{relativeTime(alert.created_at)}</time></div></div>{isOpen && canManage && <div className="flex shrink-0 flex-col gap-1.5"><button onClick={onAcknowledge} className="rounded-lg border border-input bg-card px-2.5 py-1.5 text-xs font-semibold hover:bg-secondary" data-testid={`button-acknowledge-alert-${alert.id}`}>Acknowledge</button><button onClick={onResolve} className="rounded-lg p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground" aria-label={`Resolve ${alert.title}`} data-testid={`button-resolve-alert-${alert.id}`}><Check size={16} /></button></div>}</div></article>;
}

function Settings() {
  const { user, logout, hasPermission } = useAuth();
  const patientView = isPatientView(hasPermission);
  const role = user ? primaryRole(user.roles) : undefined;
  return <div className="page-enter"><PageHeading eyebrow="CareSense / account" title="Settings" detail={patientView ? 'Your account details, and what you are allowed to do in CareSense.' : 'Your account details, and the access your role has been given.'} /><div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
    <SettingsSection icon={UserRound} eyebrow="Account" title="Profile & workspace">
      <SettingLine label="Name" value={user?.full_name || '—'} />
      <SettingLine label="Email" value={user?.email || '—'} />
      <SettingLine label="Role" value={role ? ROLE_LABEL[role] : '—'} />
      <SettingLine label="Member since" value={shortDate(user?.date_joined)} />
    </SettingsSection>
    <SettingsSection icon={ShieldCheck} eyebrow="Security" title="Access & permissions">
      <p className="text-xs leading-relaxed text-muted-foreground">Your access is set for your account by CareSense and is checked on every request. It cannot be changed from this screen.</p>
      <div className="mt-4 flex flex-wrap gap-1.5">{(user?.permissions || []).map((code) => <span key={code} className="rounded-md bg-secondary px-2 py-1 text-[11px] font-medium text-muted-foreground">{code}</span>)}</div>
    </SettingsSection>
    <SettingsSection icon={CircleHelp} eyebrow="Support" title="Session status">
      <div className="flex items-center gap-3 rounded-xl border border-[hsl(162_28%_75%)] bg-[hsl(162_28%_92%)] p-4"><span className="status-dot bg-[hsl(162_42%_42%)]" /><div><p className="text-sm font-semibold">Session active</p><p className="mt-0.5 text-xs text-muted-foreground">Signed in as {user?.email}</p></div></div>
      <button onClick={() => logout()} className="mt-5 inline-flex h-10 items-center gap-2 rounded-xl border border-input bg-card px-3 text-sm font-semibold hover:bg-secondary" data-testid="button-settings-logout"><LogOut size={15} />Sign out</button>
    </SettingsSection>
    <SettingsSection icon={LockKeyhole} eyebrow="Trust" title="How your access is protected">
      <p className="text-xs leading-relaxed text-muted-foreground">Every request is checked on the server against your real role and your real relationships, not against anything this app claims. Patient data is narrowed down before it is ever sent, and every access is written to an audit trail that cannot be edited.</p>
    </SettingsSection>
  </div></div>;
}

function SettingsSection({ icon: Icon, eyebrow, title, children }: { icon: typeof UserRound; eyebrow: string; title: string; children: ReactNode }) {
  return <section className="rounded-2xl border border-border bg-card p-5 sm:p-6"><div className="flex items-start gap-3"><span className="grid size-9 place-items-center rounded-xl bg-secondary text-muted-foreground"><Icon size={17} /></span><div><p className="mono-label text-muted-foreground">{eyebrow}</p><h2 className="mt-1 text-lg font-semibold">{title}</h2></div></div><div className="mt-6">{children}</div></section>;
}

function SettingLine({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between border-b border-border py-3 text-sm last:border-b-0"><span className="text-muted-foreground">{label}</span><span className="font-medium">{value}</span></div>;
}

function AuthenticatedRouter() {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}><Shell><Switch><Route path="/" component={Dashboard} /><Route path="/patients" component={Patients} /><Route path="/patients/:patientId" component={PatientProfilePage} /><Route path="/reports" component={Reports} /><Route path="/reports/:reportId" component={ReportDetailPage} /><Route path="/lab" component={LabWorkspace} /><Route path="/admin" component={AdminConsole} /><Route path="/appointments" component={Appointments} /><Route path="/alerts" component={Alerts} /><Route path="/settings" component={Settings} /><Route component={NotFound} /></Switch></Shell></ErrorBoundary>;
}

function FullPageLoading() {
  return <div className="grid min-h-[100dvh] place-items-center bg-background"><div className="flex flex-col items-center gap-3 text-muted-foreground"><span className="grid size-10 place-items-center rounded-2xl bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]"><HeartPulse size={20} /></span><p className="text-sm">Loading CareSense…</p></div></div>;
}

function Gate() {
  const { user, isLoading } = useAuth();
  const [showSignUp, setShowSignUp] = useState(false);
  if (isLoading) return <FullPageLoading />;
  if (!user) {
    return showSignUp
      ? <SignUp onShowLogin={() => setShowSignUp(false)} />
      : <Login onShowSignUp={() => setShowSignUp(true)} />;
  }
  return <AuthenticatedRouter />;
}

function App() {
  return <QueryClientProvider client={queryClient}><AuthProvider><TooltipProvider><WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}><Gate /></WouterRouter><Toaster /></TooltipProvider></AuthProvider></QueryClientProvider>;
}

export default App;
