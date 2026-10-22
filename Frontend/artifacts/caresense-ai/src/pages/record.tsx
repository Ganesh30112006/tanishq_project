import { useState, type FormEvent } from 'react';
import { Link, Redirect, useLocation, useParams } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { ArrowDownRight, ArrowRight, ArrowUpRight, BarChart3, Bell, ChevronLeft, Clock3, FileText, Filter, LockKeyhole, Search, ShieldCheck, SlidersHorizontal, Upload, UserPlus, UsersRound } from 'lucide-react';
import {
  getGetPatientQueryKey, getGetPatientTimelineQueryKey, getListPatientsQueryKey, getListReportsQueryKey, getListRiskAssessmentsQueryKey,
  useGetPatient, useGetPatientTimeline, useListPatients, useListReports, useListRiskAssessments, useRegisterPatient,
} from '@workspace/api-client-react';
import type { MedicalReport, Patient, PatientProfile, PatientSex, PatientStatus, RiskAssessment, RiskLevel, TimelineEvent } from '@workspace/api-client-react';
import { BlockedCard, RiskCard, RunAnalysisButton } from '@/components/risk';
import {
  ActionButton, ATTENTION_BADGE, Badge, CRITICAL_BADGE, EmptyState, FIELD_CLASS, FormError, formatMrn, formatValue, FormField, InlineUnavailable,
  Modal, ModalActions, NoAccessPage, PageButton, PageHeading, PageLoading, POSITIVE_BADGE, QueryError, relativeTime, shortDate, Skeleton, titleCase,
} from '@/components/ui-kit';
import { PERM, useAuth } from '@/lib/auth';
import { isPatientView, patientReportStatus, riskClass, statusClass } from '@/lib/display';
import { isRiskyLevel } from '@/lib/risk-display';
import { requestUpload } from '@/lib/upload-intent';

export function Patients() {
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
    // An administrator reaches this page lacking the read permission on
    // purpose - account administration is kept separate from reading what is
    // inside a clinical record - so they get a pointer to where they can act.
    return <NoAccessPage
      title="Patient records are private"
      detail={hasAnyPermission(PERM.PATIENT_REGISTER, PERM.USERS_MANAGE)
        ? 'Your account manages accounts, not health records. Reading what is inside a record is kept separate on purpose. To register a patient or link a login to a record, use the Admin page.'
        : 'Your account is not allowed to open health records.'}
    />;
  }
  // A patient has exactly one record. A list of one is furniture; open it.
  if (patientView && data?.results.length === 1) return <Redirect to={`/patients/${data.results[0].id}`} replace />;
  return <div className="page-enter">
    <PageHeading eyebrow={patientView ? 'CareSense / my record' : 'CareSense / people'} title={patientView ? 'My health record' : 'Patients'} detail={patientView ? 'Your record, as it is saved in CareSense.' : 'Every patient record you are allowed to see.'} action={<div className="flex flex-wrap items-center gap-2">{hasPermission(PERM.PATIENT_REGISTER) && <ActionButton icon={UserPlus} label="Register patient" variant="primary" onClick={() => setRegistering(true)} />}{!patientView && <ActionButton icon={SlidersHorizontal} label="Reset view" onClick={() => { setSearch(''); setRisk(''); setStatus(''); setPage(1); }} />}</div>} />
    {registering && <RegisterPatientModal onClose={() => setRegistering(false)} onDone={() => queryClient.invalidateQueries({ queryKey: getListPatientsQueryKey(params) })} />}
    {!patientView && <div className="mb-6 grid gap-3 rounded-2xl border border-border bg-card p-3 sm:grid-cols-[1fr_auto_auto]"><label className="relative block"><Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={17} /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Search by name or record number" className={`${FIELD_CLASS} pl-10`} data-testid="input-patient-search" /></label><SelectFilter label="Risk level" value={risk} onChange={(value) => { setRisk(value); setPage(1); }} options={['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']} testId="select-risk-filter" /><SelectFilter label="Care status" value={status} onChange={(value) => { setStatus(value); setPage(1); }} options={['STABLE', 'MONITORING', 'REVIEW_REQUIRED']} testId="select-status-filter" /></div>}
    {query.isLoading ? <PageLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} message="Patient records are unavailable." /> : data?.results.length ? <>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{data.results.map((patient) => <PatientCard patient={patient} key={patient.id} />)}</div>
      <PageButton page={page} pageSize={data.page_size} count={data.count} onChange={setPage} />
    </> : <div className="rounded-2xl border border-border bg-card"><EmptyState icon={UsersRound} title={patientView ? 'Your record is not ready yet' : 'No patients match this view'} detail={patientView ? 'Your account has not been linked to a health record yet.' : 'Try removing a filter, or search for another name.'} /></div>}
  </div>;
}

function SelectFilter({ label, value, onChange, options, testId }: { label: string; value: string; onChange: (value: string) => void; options: string[]; testId: string }) {
  return <label className="flex min-h-11 items-center gap-2 rounded-lg border border-input bg-card px-3 text-sm"><Filter size={15} className="text-muted-foreground" /><span className="sr-only">{label}</span><select value={value} onChange={(event) => onChange(event.target.value)} className="w-full bg-transparent font-bold outline-none" data-testid={testId}><option value="">{`All ${label.toLowerCase()}`}</option>{options.map((option) => <option value={option} key={option}>{titleCase(option)}</option>)}</select></label>;
}

function PatientCard({ patient }: { patient: Patient }) {
  return <Link href={`/patients/${patient.id}`} className="group rounded-2xl border border-border bg-card p-5 transition-[transform,box-shadow] hover:-translate-y-0.5 hover:shadow-md" data-testid={`row-patient-${patient.id}`}>
    <div className="flex items-center gap-3"><span className="grid size-12 shrink-0 place-items-center rounded-full bg-[hsl(var(--brand)/.12)] font-bold text-[hsl(var(--brand))]">{patient.initials}</span><div className="min-w-0 flex-1"><p className="truncate font-bold">{patient.full_name}</p><p className="mt-0.5 text-[13px] text-muted-foreground">{patient.age ?? '—'} yrs · {titleCase(patient.sex)} · <span className="font-mono">{formatMrn(patient.mrn)}</span></p></div><ArrowRight size={16} className="text-muted-foreground transition-transform group-hover:translate-x-0.5" /></div>
    <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4">
      {patient.risk_level ? <Badge className={`whitespace-nowrap ${riskClass(patient.risk_level)}`}>{patient.risk_label || titleCase(patient.risk_level)}{patient.risk_score != null ? ` · ${patient.risk_score}` : ''}</Badge> : <span className="text-[13px] text-muted-foreground">Not assessed</span>}
      <Badge className={statusClass(patient.status)}>{titleCase(patient.status)}</Badge>
      <span className="ml-auto flex items-center gap-1 text-[13px] text-muted-foreground">{patient.trend === 'UP' ? <ArrowUpRight size={14} className="text-[hsl(var(--destructive))]" /> : patient.trend === 'DOWN' ? <ArrowDownRight size={14} className="text-[hsl(var(--success))]" /> : null}{relativeTime(patient.last_updated)}</span>
    </div>
  </Link>;
}

export function PatientProfilePage() {
  const { hasPermission, hasAnyPermission } = useAuth();
  const [, setLocation] = useLocation();
  const patientView = isPatientView(hasPermission);
  const queryClient = useQueryClient();
  const { patientId = '' } = useParams<{ patientId: string }>();
  const enabled = Boolean(patientId);
  const patientQuery = useGetPatient(patientId, { query: { queryKey: getGetPatientQueryKey(patientId), enabled } });
  const riskParams = { patient_id: patientId, page_size: 1 };
  const riskQuery = useListRiskAssessments(riskParams, { query: { queryKey: getListRiskAssessmentsQueryKey(riskParams), enabled } });
  const timelineParams = { limit: 20 };
  const timelineQuery = useGetPatientTimeline(patientId, timelineParams, { query: { queryKey: getGetPatientTimelineQueryKey(patientId, timelineParams), enabled } });
  const reportsParams = { patient_id: patientId };
  const reportsQuery = useListReports(reportsParams, { query: { queryKey: getListReportsQueryKey(reportsParams), enabled } });
  const canUpload = hasPermission(PERM.REPORT_UPLOAD_OWN);
  const canAnalyse = hasAnyPermission(PERM.RISK_REQUEST_OWN);
  // Same gate as the patient list. Without it an administrator who lands here
  // (a stale link, a shared URL) is sent the identity-only projection the
  // server gives account administrators, and this page - which expects a
  // clinical record - crashed reading fields that were deliberately withheld.
  const canReadRecord = hasAnyPermission(PERM.PATIENT_READ_OWN, PERM.PATIENT_READ_ASSIGNED);
  const patient = patientQuery.data as PatientProfile | undefined;
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: getGetPatientQueryKey(patientId) });
    queryClient.invalidateQueries({ queryKey: getListRiskAssessmentsQueryKey(riskParams) });
    queryClient.invalidateQueries({ queryKey: getGetPatientTimelineQueryKey(patientId, timelineParams) });
    queryClient.invalidateQueries({ queryKey: getListReportsQueryKey(reportsParams) });
  };
  if (!canReadRecord) {
    return <NoAccessPage title="Patient records are private" detail="Your account manages accounts, not health records. Reading what is inside a record is kept separate on purpose. To register a patient or link a login to a record, use the Admin page." />;
  }
  if (patientQuery.isLoading) return <PageLoading />;
  if (patientQuery.isError || !patient) return <QueryError onRetry={() => patientQuery.refetch()} message="This health record is unavailable." />;
  const assessment = riskQuery.data?.results?.[0] as RiskAssessment | undefined;
  const timeline = timelineQuery.data as TimelineEvent[] | undefined;
  const reports = reportsQuery.data?.results as MedicalReport[] | undefined;
  const risky = isRiskyLevel(patient.risk_level);

  return <div className="page-enter">
    {!patientView && <Link href="/patients" className="mb-6 inline-flex items-center gap-1 text-sm font-bold text-muted-foreground hover:text-foreground" data-testid="link-back-patients"><ChevronLeft size={16} />All patients</Link>}

    {/* Profile header */}
    <section className="relative overflow-hidden rounded-[22px] border border-border bg-card">
      <div className="h-24 bg-[linear-gradient(120deg,hsl(var(--brand)/.9)_0%,hsl(171_72%_22%)_100%)]" aria-hidden="true" />
      <div className="flex flex-col gap-5 px-6 pb-6 sm:flex-row sm:items-end sm:px-8">
        <span className="-mt-12 grid size-24 shrink-0 place-items-center rounded-[22px] border-4 border-card bg-[hsl(var(--brand))] font-display text-[34px] font-semibold text-[hsl(var(--brand-foreground))] shadow-md">{patient.initials}</span>
        <div className="min-w-0 flex-1">
          <p className="mono-label text-[hsl(var(--brand))]">{patientView ? 'My health record' : 'Health record'}</p>
          <h1 className="mt-1 text-[34px] leading-tight sm:text-[40px]">{patient.full_name}</h1>
          <div className="mt-2 flex flex-wrap gap-2 text-[13px]">
            <span className="rounded-md bg-secondary px-2 py-1 font-bold">{patient.age ?? '—'} years</span>
            <span className="rounded-md bg-secondary px-2 py-1 font-bold">{titleCase(patient.sex)}</span>
            <span className="rounded-md bg-secondary px-2 py-1 font-mono">{formatMrn(patient.mrn)}</span>
            <span className="rounded-md px-2 py-1 text-muted-foreground">Updated {relativeTime(patient.last_updated)}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canUpload ? <button type="button" onClick={() => { requestUpload(); setLocation('/reports'); }} className="inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-5 text-sm font-bold text-primary-foreground hover:brightness-110" data-testid="button-action-upload-report"><Upload size={16} />Upload report</button>
            : <span className="inline-flex h-10 items-center gap-2 rounded-xl border border-input px-3 text-[13px] text-muted-foreground" data-testid="text-no-actions"><LockKeyhole size={14} />Read-only access</span>}
        </div>
      </div>
    </section>

    {/* Figures */}
    <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Tile label="Risk estimate" value={assessment?.interpretation?.band_label || patient.risk_label || (patient.risk_level ? titleCase(patient.risk_level) : 'Not assessed')} note={assessment?.interpretation?.show_score && patient.risk_score != null ? `${patient.risk_score}/100 · ${titleCase(patient.trend)}` : patient.risk_level ? `Trend ${titleCase(patient.trend) || 'stable'}` : 'No completed assessment'} tone={risky ? 'critical' : undefined} />
      <Tile label="Reports on file" value={reportsQuery.data ? String(reportsQuery.data.count) : '—'} note="Uploaded to your record" />
      <Tile label="Date of birth" value={shortDate(patient.date_of_birth)} note={`Age ${patient.age ?? '—'}`} />
      <Tile label="Latest alert" value={patient.latest_alert || 'None'} note={patient.latest_alert ? 'Please show this to a doctor' : 'Nothing needs attention right now'} tone={patient.latest_alert ? 'critical' : undefined} />
    </div>

    <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <section className="rounded-[22px] border border-border bg-card" aria-labelledby="risk-title">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-5"><div><p className="mono-label text-muted-foreground">Your estimate</p><h2 id="risk-title" className="mt-1 text-[24px]">Heart risk analysis</h2></div>{canAnalyse && <RunAnalysisButton patientId={patientId} onDone={refresh} />}</div>
        <div className="p-6">{riskQuery.isLoading ? <div className="space-y-3"><Skeleton className="h-24" /><Skeleton className="h-4" /><Skeleton className="h-4" /></div> : riskQuery.isError ? <InlineUnavailable label="Risk analysis is unavailable just now." /> : assessment?.status === 'BLOCKED' ? <BlockedCard assessment={assessment} /> : assessment ? <RiskCard patient={patient} assessment={assessment} /> : <EmptyState icon={ShieldCheck} title="Not analysed yet" detail={canAnalyse ? 'Run the analysis to see what your saved results suggest.' : 'No estimate is available for this record.'} />}</div>
      </section>

      <div className="space-y-6">
        <section className="rounded-[22px] border border-border bg-card p-6" aria-labelledby="details-title">
          <p className="mono-label text-muted-foreground">Saved on your record</p>
          <h2 id="details-title" className="mt-1 text-[24px]">{patientView ? 'Your health details' : 'Health details'}</h2>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <InfoList title="Conditions" values={patient.conditions} />
            <InfoList title="Allergies" values={patient.allergies} />
            <InfoList title="Medicines" values={patient.medications} />
            <div><p className="mono-label text-muted-foreground">Measurements</p><div className="mt-3 space-y-3">{patient.measurements.length ? patient.measurements.slice(0, 4).map((measurement) => <MeasurementRow key={`${measurement.label}-${measurement.recorded_at}`} measurement={measurement} />) : <p className="text-sm text-muted-foreground">None recorded</p>}</div></div>
          </div>
        </section>

        <section className="rounded-[22px] border border-border bg-card" aria-labelledby="reports-title">
          <div className="flex items-center justify-between px-6 pt-6"><h2 id="reports-title" className="text-[24px]">Recent reports</h2><Link href="/reports" className="text-sm font-bold text-[hsl(var(--brand))] hover:underline">All</Link></div>
          <div className="mt-2 px-3 pb-3">{reportsQuery.isLoading ? <div className="space-y-2 p-3"><Skeleton className="h-12" /><Skeleton className="h-12" /></div> : reportsQuery.isError ? <div className="p-3"><InlineUnavailable label="Reports are unavailable just now." /></div> : reports?.length ? reports.slice(0, 4).map((report) => <ReportRow key={report.id} report={report} />) : <EmptyState icon={FileText} title="No reports yet" detail="Reports you upload will appear here." />}</div>
        </section>
      </div>
    </div>

    <section className="mt-6 rounded-[22px] border border-border bg-card p-6 sm:p-8" aria-labelledby="timeline-title">
      <p className="mono-label text-muted-foreground">Over time</p>
      <h2 id="timeline-title" className="mt-1 text-[24px]">Timeline</h2>
      <div className="mt-6">{timelineQuery.isLoading ? <div className="space-y-5"><Skeleton className="h-12" /><Skeleton className="h-12" /></div> : timelineQuery.isError ? <InlineUnavailable label="Timeline is unavailable just now." /> : timeline?.length ? <ol className="relative ml-4 border-l-2 border-dashed border-border">{timeline.map((event) => <TimelineRow key={event.id} event={event} />)}</ol> : <EmptyState icon={Clock3} title="Nothing here yet" detail="Reports and results will appear here as they are added." />}</div>
    </section>
  </div>;
}

function Tile({ label, value, note, tone }: { label: string; value: string; note: string; tone?: 'critical' }) {
  return <div className={`rounded-2xl border p-5 ${tone === 'critical' ? 'border-[hsl(var(--destructive)/.3)] bg-[hsl(var(--destructive)/.04)]' : 'border-border bg-card'}`}>
    <p className="text-[13px] font-bold text-muted-foreground">{label}</p>
    <p className={`font-display mt-2 text-[24px] font-semibold leading-tight text-balance ${tone === 'critical' ? 'text-[hsl(var(--destructive))]' : ''}`}>{value}</p>
    {note ? <p className="mt-1 text-[13px] text-muted-foreground">{note}</p> : null}
  </div>;
}

function InfoList({ title, values }: { title: string; values?: string[] }) {
  return <div><p className="mono-label text-muted-foreground">{title}</p>{values?.length ? <ul className="mt-3 space-y-2">{values.map((value) => <li key={value} className="text-[15px]">{value}</li>)}</ul> : <p className="mt-3 text-sm text-muted-foreground">None recorded</p>}</div>;
}

function MeasurementRow({ measurement }: { measurement: PatientProfile['measurements'][number] }) {
  return <div className="text-sm">
    <div className="flex items-baseline justify-between gap-3">
      <span className="min-w-0 flex-1 text-muted-foreground">{measurement.label}</span>
      <span className="shrink-0 font-mono font-medium">{formatValue(measurement.value)} <span className="text-[12px] text-muted-foreground">{measurement.unit}</span></span>
    </div>
    {measurement.status && <Badge className={`mt-1 whitespace-nowrap ${measurement.status === 'OUT_OF_RANGE' ? CRITICAL_BADGE : measurement.status === 'ATTENTION' ? ATTENTION_BADGE : POSITIVE_BADGE}`}>{titleCase(measurement.status)}</Badge>}
  </div>;
}

function TimelineRow({ event }: { event: TimelineEvent }) {
  const Icon = event.type === 'alert' ? Bell : event.type === 'report' ? FileText : event.type === 'measurement' ? BarChart3 : event.type === 'assessment' ? ShieldCheck : FileText;
  return <li className="relative pb-7 pl-8 last:pb-0">
    <span className="absolute -left-[17px] top-0 grid size-8 place-items-center rounded-full border-2 border-card bg-[hsl(var(--brand)/.12)] text-[hsl(var(--brand))]"><Icon size={14} /></span>
    <time className="mono-label text-muted-foreground">{shortDate(event.occurred_at)}</time>
    <p className="mt-1 font-bold">{event.title}</p>
    <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">{event.detail}</p>
  </li>;
}

function ReportRow({ report }: { report: MedicalReport }) {
  const state = patientReportStatus(report.processing_state);
  return <Link href={`/reports/${report.id}`} className="flex items-center gap-3 rounded-xl p-3 hover:bg-secondary/60" data-testid={`link-report-${report.id}`}><span className="grid size-10 shrink-0 place-items-center rounded-xl border border-border text-[hsl(var(--brand))]"><FileText size={17} /></span><div className="min-w-0 flex-1"><p className="truncate font-bold">{report.title}</p><p className="mt-0.5 text-[13px] text-muted-foreground">{titleCase(report.report_class) || 'Unclassified'} · {shortDate(report.created_at)}</p></div><Badge className={`whitespace-nowrap ${state.className}`}>{state.label}</Badge></Link>;
}

const PATIENT_SEXES = ['FEMALE', 'MALE', 'INTERSEX', 'UNKNOWN'] as const;

function RegisterPatientModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ mrn: '', given_name: '', family_name: '', date_of_birth: '' });
  const [sex, setSex] = useState<PatientSex>('UNKNOWN');
  const register = useRegisterPatient();
  const update = (key: keyof typeof form) => (event: { target: { value: string } }) => setForm((prev) => ({ ...prev, [key]: event.target.value }));
  const incomplete = !form.mrn.trim() || !form.given_name.trim() || !form.family_name.trim();
  function submit(event: FormEvent) {
    event.preventDefault();
    if (incomplete) return;
    register.mutate(
      { data: { mrn: form.mrn, given_name: form.given_name, family_name: form.family_name, date_of_birth: form.date_of_birth || null, sex } },
      { onSuccess: () => { onDone(); onClose(); } },
    );
  }
  return (
    <Modal title="Register patient" description="Creates an identity only." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-register-patient-inline">
        <FormField label="Record number"><input value={form.mrn} onChange={update('mrn')} required className={FIELD_CLASS} data-testid="input-inline-mrn" /></FormField>
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
        <ModalActions onClose={onClose} submitting={register.isPending} disabled={incomplete} submitLabel="Register patient" />
      </form>
    </Modal>
  );
}
