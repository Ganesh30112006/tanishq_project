import { useEffect, useRef, useState, type DragEvent } from 'react';
import { Link } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { ArrowUpRight, CheckCircle2, FileText, FileUp, Loader2, Upload, X } from 'lucide-react';
import { getListPatientsQueryKey, getListReportsQueryKey, useListPatients, useListReports, useUploadReport } from '@workspace/api-client-react';
import type { MedicalReport, ReportClass, ReportProcessingState } from '@workspace/api-client-react';
import { Badge, EmptyState, FIELD_CLASS, FormError, NoAccessPage, PageButton, PageHeading, QueryError, shortDate, Skeleton } from '@/components/ui-kit';
import { PERM, useAuth } from '@/lib/auth';
import { isPatientView, patientReportStatus, REPORT_CLASS_LABEL, REPORT_CLASS_OPTIONS, REPORT_FILTERS, reportTypeLabel } from '@/lib/display';
import { consumeUploadRequest, onUploadRequested } from '@/lib/upload-intent';

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.tif,.tiff';

export default function Reports() {
  const { hasPermission, hasAnyPermission } = useAuth();
  const patientView = isPatientView(hasPermission);
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(1);
  const status = REPORT_FILTERS.find((f) => f.key === filter)?.status;
  const params: { status?: ReportProcessingState; page?: number } = { status, page };
  const query = useListReports(params, { query: { queryKey: getListReportsQueryKey(params) } });
  const data = query.data;
  const canUpload = hasAnyPermission(PERM.REPORT_UPLOAD_OWN);

  if (!hasAnyPermission(PERM.REPORT_READ_OWN)) {
    return <NoAccessPage title="Reports" detail="Your account is not allowed to open patient reports." />;
  }

  return (
    <div className="page-enter">
      <PageHeading eyebrow="CareSense / reports" title={patientView ? 'My reports' : 'Reports'} detail={patientView ? 'Every report you have uploaded. Open one to see what our AI found in it.' : 'Reports saved on records you can see.'} />

      {canUpload && <UploadPanel onUploaded={() => setPage(1)} />}

      <div className="mb-5 mt-10 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <h2 className="text-[26px]">{data ? `${data.count} report${data.count === 1 ? '' : 's'}` : 'Reports'}</h2>
        <div className="flex flex-wrap gap-1.5 rounded-xl border border-border bg-card p-1" role="tablist" aria-label="Filter reports">
          {REPORT_FILTERS.map((f) => (
            <button key={f.key} type="button" role="tab" aria-selected={filter === f.key} onClick={() => { setFilter(f.key); setPage(1); }}
              className={`h-9 rounded-lg px-3 text-[13px] font-bold transition-colors ${filter === f.key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-secondary hover:text-foreground'}`}
              data-testid={`filter-reports-${f.key}`}>{f.label}</button>
          ))}
        </div>
      </div>

      {query.isLoading ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-56 rounded-2xl" />)}</div>
        : query.isError ? <QueryError onRetry={() => query.refetch()} message="Your reports could not be loaded." />
        : data?.results.length ? <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.results.map((report, index) => <ReportCard key={report.id} report={report} index={index} showPatient={!patientView} />)}
          </div>
          <PageButton page={page} pageSize={data.page_size} count={data.count} onChange={setPage} />
        </> : <div className="rounded-2xl border border-border bg-card"><EmptyState icon={FileText} title={filter === 'all' ? 'No reports yet' : 'No reports in this view'} detail={filter === 'all' ? 'Upload your first lab report above and our AI will explain it.' : 'Try another filter.'} /></div>}
    </div>
  );
}

function ReportCard({ report, index, showPatient }: { report: MedicalReport; index: number; showPatient: boolean }) {
  const state = patientReportStatus(report.processing_state);
  return (
    <Link href={`/reports/${report.id}`} className={`page-enter stagger-${Math.min(index + 1, 4)} group flex flex-col overflow-hidden rounded-2xl border border-border bg-card transition-[transform,box-shadow,border-color] hover:-translate-y-1 hover:border-[hsl(var(--brand)/.4)] hover:shadow-lg`} data-testid={`link-report-${report.id}`}>
      <div className="relative flex h-32 items-end justify-center overflow-hidden bg-[linear-gradient(180deg,hsl(var(--secondary))_0%,hsl(var(--background))_100%)] px-8 pt-6">
        {/* A sheet of paper, peeking up: the report itself, not a generic icon. */}
        <div className="h-full w-36 rounded-t-lg border border-b-0 border-border bg-card px-3 pt-3 shadow-sm transition-transform group-hover:-translate-y-1">
          <div className="h-1.5 w-12 rounded-full bg-[hsl(var(--brand)/.5)]" />
          <div className="mt-2.5 space-y-1.5">{[90, 70, 82, 60, 75].map((w, i) => <div key={i} className="flex justify-between gap-2"><span className="h-1 rounded-full bg-border" style={{ width: `${w * 0.55}%` }} /><span className={`h-1 w-4 rounded-full ${i === 2 ? 'bg-[hsl(var(--accent))]' : 'bg-border'}`} /></div>)}</div>
        </div>
        <span className="mono-label absolute left-4 top-4 rounded-[4px] bg-card/90 px-1.5 py-0.5 text-[hsl(var(--brand))] ring-1 ring-inset ring-border">{reportTypeLabel(report)}</span>
        <ArrowUpRight size={18} className="absolute right-4 top-4 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-[hsl(var(--brand))]" />
      </div>
      <div className="flex flex-1 flex-col p-5">
        <p className="line-clamp-2 font-bold leading-snug">{report.title}</p>
        <p className="mt-1 text-[13px] text-muted-foreground">{showPatient ? `${report.patient_name} · ` : ''}Uploaded {shortDate(report.created_at)}</p>
        <div className="mt-auto pt-4">
          <Badge className={`whitespace-nowrap ${state.className}`}>{state.busy && <span className="mr-1.5 size-1.5 animate-pulse rounded-full bg-current" />}{state.label}</Badge>
        </div>
      </div>
    </Link>
  );
}

type PickedPatient = { id: string; name: string };

function UploadPanel({ onUploaded }: { onUploaded: () => void }) {
  const { hasPermission } = useAuth();
  const patientView = isPatientView(hasPermission);
  const queryClient = useQueryClient();
  const panelRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [classHint, setClassHint] = useState('');
  const [dragging, setDragging] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [picked, setPicked] = useState<PickedPatient | null>(null);
  const upload = useUploadReport();

  // A patient uploads to their own record - there is exactly one they can see,
  // so they are never asked to search for themselves.
  const ownParams = { page_size: 1 };
  const own = useListPatients(ownParams, { query: { queryKey: getListPatientsQueryKey(ownParams), enabled: patientView } });
  const ownRecord = own.data?.results?.[0];
  const target: PickedPatient | null = patientView ? (ownRecord ? { id: ownRecord.id, name: ownRecord.full_name } : null) : picked;

  useEffect(() => {
    const focus = () => {
      panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      window.setTimeout(() => inputRef.current?.focus(), 350);
    };
    if (consumeUploadRequest()) focus();
    return onUploadRequested(focus);
  }, []);

  function choose(next: File | null) {
    setDone(null);
    upload.reset();
    setFile(next);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) choose(dropped);
  }

  function submit() {
    if (!target || !file) return;
    upload.mutate(
      { data: { patient_id: target.id, file, class_hint: (classHint || undefined) as ReportClass | undefined } },
      {
        onSuccess: () => {
          setDone(file.name);
          setFile(null);
          setClassHint('');
          if (inputRef.current) inputRef.current.value = '';
          queryClient.invalidateQueries({ queryKey: getListReportsQueryKey() });
          queryClient.invalidateQueries({ predicate: (q) => Array.isArray(q.queryKey) && String(q.queryKey[0]).includes('/reports') });
          onUploaded();
        },
      },
    );
  }

  return (
    <section ref={panelRef} id="upload" className="scroll-mt-24" aria-labelledby="upload-title">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`relative overflow-hidden rounded-[22px] border-2 border-dashed p-6 transition-colors sm:p-8 ${dragging ? 'border-[hsl(var(--brand))] bg-[hsl(var(--brand)/.07)]' : 'border-[hsl(var(--brand)/.3)] bg-card'}`}
        data-testid="dropzone-report"
      >
        <div className="grid gap-6 lg:grid-cols-[auto_1fr_auto] lg:items-center">
          <span className={`grid size-16 place-items-center rounded-2xl transition-colors ${dragging ? 'bg-[hsl(var(--brand))] text-[hsl(var(--brand-foreground))]' : 'bg-[hsl(var(--brand)/.1)] text-[hsl(var(--brand))]'}`}><FileUp size={28} /></span>
          <div>
            <h2 id="upload-title" className="text-[24px]">{dragging ? 'Drop it here' : 'Upload a lab report'}</h2>
            <p className="mt-1 text-[15px] text-muted-foreground">Drag your report here, or choose a file. PDF from the lab works best; JPG, PNG and TIFF photos are accepted too.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <input ref={inputRef} id="report-file" type="file" accept={ACCEPT} className="sr-only" onChange={(e) => choose(e.target.files?.[0] ?? null)} data-testid="input-report-file" />
            <label htmlFor="report-file" className="inline-flex h-12 cursor-pointer items-center gap-2 rounded-xl border border-input bg-background px-5 text-[15px] font-bold hover:bg-secondary">Choose file</label>
          </div>
        </div>

        {(file || done) && (
          <div className="mt-6 border-t border-dashed border-border pt-6">
            {file ? (
              <div className="grid gap-4 lg:grid-cols-[1fr_260px_auto] lg:items-end">
                <div className="flex items-center gap-3 rounded-xl border border-border bg-background p-3">
                  <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-secondary"><FileText size={18} /></span>
                  <span className="min-w-0 flex-1"><span className="block truncate font-bold">{file.name}</span><span className="text-[13px] text-muted-foreground">{(file.size / 1024).toFixed(0)} KB</span></span>
                  <button type="button" onClick={() => choose(null)} className="grid size-9 place-items-center rounded-lg text-muted-foreground hover:bg-secondary" aria-label="Remove file"><X size={16} /></button>
                </div>
                <label className="block">
                  <span className="mb-1.5 block text-[13px] font-bold">Type of report <span className="font-normal text-muted-foreground">(optional)</span></span>
                  <select value={classHint} onChange={(e) => setClassHint(e.target.value)} className={FIELD_CLASS} data-testid="select-report-class">
                    <option value="">Let our AI work it out</option>
                    {REPORT_CLASS_OPTIONS.map((option) => <option key={option} value={option}>{REPORT_CLASS_LABEL[option]}</option>)}
                  </select>
                </label>
                <button type="button" onClick={submit} disabled={!target || upload.isPending} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-primary px-6 text-[15px] font-bold text-primary-foreground hover:brightness-110 disabled:opacity-60" data-testid="button-upload-submit">
                  {upload.isPending ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}{upload.isPending ? 'Uploading…' : 'Upload'}
                </button>
                {!patientView && <PatientPicker value={picked} onSelect={setPicked} />}
                {patientView && !ownRecord && !own.isLoading && <p className="text-sm text-[hsl(var(--destructive))] lg:col-span-3">Your account is not linked to a health record yet, so reports cannot be uploaded.</p>}
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3 rounded-xl bg-[hsl(var(--success)/.08)] p-4 text-[15px]" role="status" data-testid="text-upload-done">
                <CheckCircle2 size={19} className="text-[hsl(var(--success))]" />
                <span><strong>{done}</strong> is uploaded. Our AI is reading it now - it will appear below in a minute.</span>
              </div>
            )}
            <FormError error={upload.error} />
          </div>
        )}
      </div>
    </section>
  );
}

function PatientPicker({ value, onSelect }: { value: PickedPatient | null; onSelect: (patient: PickedPatient | null) => void }) {
  const [search, setSearch] = useState('');
  const params = { search: search.trim() || undefined, page_size: 6 };
  const query = useListPatients(params, { query: { queryKey: getListPatientsQueryKey(params), enabled: !value && search.trim().length > 1 } });
  if (value) {
    return <div className="flex items-center justify-between rounded-xl border border-input bg-secondary/40 px-3 py-2.5 text-sm lg:col-span-3"><span className="font-bold">{value.name}</span><button type="button" onClick={() => onSelect(null)} className="text-[13px] font-bold text-muted-foreground hover:text-foreground" data-testid="button-change-patient">Change</button></div>;
  }
  return (
    <div className="lg:col-span-3">
      <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by patient name or record number" className={FIELD_CLASS} data-testid="input-patient-picker" />
      {search.trim().length > 1 && (
        <div className="mt-2 max-h-44 overflow-y-auto rounded-xl border border-border">
          {query.isLoading ? <p className="px-3 py-2 text-[13px] text-muted-foreground">Searching…</p>
            : query.data?.results.length ? query.data.results.map((patient) => (
              <button type="button" key={patient.id} onClick={() => onSelect({ id: patient.id, name: patient.full_name })} className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-secondary/60" data-testid={`option-patient-${patient.id}`}>
                <span>{patient.full_name}</span><span className="text-[13px] text-muted-foreground">{patient.mrn}</span>
              </button>
            )) : <p className="px-3 py-2 text-[13px] text-muted-foreground">No matching patients.</p>}
        </div>
      )}
    </div>
  );
}
