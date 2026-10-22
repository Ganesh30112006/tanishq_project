import { useState } from 'react';
import { Link, useParams } from 'wouter';
import { BarChart3, CalendarDays, ChevronLeft, Download, FileText, Loader2, Lock, Sparkles, Stethoscope, Wrench } from 'lucide-react';
import { downloadReportFile, getGetReportQualityQueryKey, getGetReportQueryKey, useGetReport, useGetReportQuality } from '@workspace/api-client-react';
import type { MedicalReport, ReportQuality } from '@workspace/api-client-react';
import { AiAnalysisSection } from '@/components/ai-analysis';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge, EmptyState, formatValue, InlineUnavailable, NEUTRAL_BADGE, PageLoading, QueryError, shortDate, titleCase } from '@/components/ui-kit';
import { useAuth } from '@/lib/auth';
import { isPatientView, labStatusClass, patientReportStatus } from '@/lib/display';

export default function ReportDetailPage() {
  const { reportId = '' } = useParams<{ reportId: string }>();
  const { hasPermission } = useAuth();
  const patientView = isPatientView(hasPermission);
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
  if (reportQuery.isError || !report) return <QueryError onRetry={() => reportQuery.refetch()} message="This report is unavailable." error={reportQuery.error} />;
  const quality = qualityQuery.data as ReportQuality | undefined;
  const state = patientReportStatus(report.processing_state);

  return (
    <div className="page-enter">
      <Link href="/reports" className="mb-6 inline-flex items-center gap-1 text-sm font-bold text-muted-foreground hover:text-foreground" data-testid="link-back-reports"><ChevronLeft size={16} />{patientView ? 'My reports' : 'All reports'}</Link>

      <header className="mb-8 flex flex-col gap-5 border-b border-border pb-8 sm:flex-row sm:items-start">
        <span className="grid size-16 shrink-0 place-items-center rounded-2xl bg-[hsl(var(--brand)/.1)] text-[hsl(var(--brand))]"><FileText size={26} /></span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="mono-label text-[hsl(var(--brand))]">{titleCase(report.report_class) || 'Unclassified'}</span>
            <Badge className={state.className}>{state.label}</Badge>
          </div>
          <h1 className="mt-2 break-words text-[32px] leading-tight sm:text-[42px]">{report.title}</h1>
          <p className="mt-2 text-[15px] text-muted-foreground">{patientView ? 'Uploaded' : <>For <Link href={`/patients/${report.patient_id}`} className="font-bold hover:underline" data-testid="link-report-patient">{report.patient_name}</Link> · uploaded</>} {shortDate(report.created_at)}{report.uploaded_by ? ` by ${report.uploaded_by}` : ''}</p>
        </div>
      </header>

      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Tabs defaultValue="ai" className="min-w-0">
          <TabsList className="mb-6 h-12 w-full justify-start gap-1 rounded-xl bg-secondary p-1 sm:w-auto">
            <TabsTrigger value="ai" className="h-10 gap-2 rounded-lg px-4 text-sm font-bold data-[state=active]:bg-card data-[state=active]:shadow-sm" data-testid="tab-ai"><Sparkles size={15} />What our AI found</TabsTrigger>
            <TabsTrigger value="technical" className="h-10 gap-2 rounded-lg px-4 text-sm font-bold data-[state=active]:bg-card data-[state=active]:shadow-sm" data-testid="tab-technical"><Wrench size={15} />Technical details</TabsTrigger>
          </TabsList>
          <TabsContent value="ai" className="mt-0"><AiAnalysisSection reportId={reportId} /></TabsContent>
          <TabsContent value="technical" className="mt-0"><TechnicalDetails report={report} quality={quality} /></TabsContent>
        </Tabs>

        <aside className="space-y-4 xl:sticky xl:top-24 xl:self-start">
          <section className="rounded-2xl border border-border bg-card p-5" aria-labelledby="facts-title">
            <h2 id="facts-title" className="text-[20px]">About this report</h2>
            <dl className="mt-4 space-y-3 text-sm">
              <Fact icon={FileText} label="Type" value={titleCase(report.report_class) || 'Not worked out yet'} />
              <Fact icon={CalendarDays} label="Sample taken" value={shortDate(report.collected_at)} />
              <Fact icon={CalendarDays} label="Uploaded" value={shortDate(report.created_at)} />
            </dl>
            {report.original_filename ? <>
              <button onClick={handleDownload} disabled={downloading} className="mt-5 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-input bg-background text-sm font-bold hover:bg-secondary disabled:opacity-60" data-testid="button-download-report">{downloading ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}Download original</button>
              {downloadError && <p className="mt-2 text-[13px] text-[hsl(var(--destructive))]" role="alert">{downloadError}</p>}
            </> : null}
          </section>

          <section className="rounded-2xl bg-[linear-gradient(135deg,hsl(var(--brand))_0%,hsl(171_72%_22%)_100%)] p-5 text-[hsl(var(--brand-foreground))]">
            <Stethoscope size={20} />
            <h2 className="mt-3 text-[20px]">Next step: see a doctor</h2>
            <p className="mt-2 text-sm leading-relaxed opacity-90">Take this report and what our AI found to a doctor. Only a doctor can tell you what it means for you.</p>
          </section>

          <p className="flex items-start gap-2 px-1 text-[13px] leading-relaxed text-muted-foreground"><Lock size={14} className="mt-0.5 shrink-0" /><span>Every time this report is opened, we record who opened it and when.{' '}<Link href="/privacy" className="font-bold underline underline-offset-2">Privacy policy</Link></span></p>
        </aside>
      </div>
    </div>
  );
}

function Fact({ icon: Icon, label, value }: { icon: typeof FileText; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <Icon size={15} className="shrink-0 text-muted-foreground" />
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="ml-auto text-right font-bold">{value}</dd>
    </div>
  );
}

function TechnicalDetails({ report, quality }: { report: MedicalReport; quality?: ReportQuality }) {
  const tests = report.tests ?? [];
  const findings = report.findings ?? [];
  return (
    <div className="space-y-5" data-testid="details-report-technical">
      <p className="text-[15px] leading-relaxed text-muted-foreground">This is what our older report reader extracted, kept for reference. Its labels like "review required" were meant for a reviewer, not for you - the AI tab is the one to read.</p>
      {report.review_reason ? <InlineUnavailable label={`Reader note: ${report.review_reason}`} /> : null}
      <div className="grid gap-3 sm:grid-cols-3">
        <MiniStat label="Reader state" value={titleCase(report.processing_state)} />
        <MiniStat label="Values checked" value={quality ? `${quality.tests_validated} of ${quality.tests_total}` : '—'} />
        <MiniStat label="Reading quality" value={quality ? titleCase(quality.extraction_reliability) : '—'} />
      </div>
      <section className="overflow-hidden rounded-2xl border border-border bg-card" aria-labelledby="tests-title">
        <h3 id="tests-title" className="border-b border-border px-5 py-4 font-bold">Values the reader extracted</h3>
        <div className="overflow-x-auto">
          {tests.length ? <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left mono-label text-muted-foreground"><th className="px-5 py-3 font-normal">Test</th><th className="px-3 py-3 font-normal">Value</th><th className="px-3 py-3 font-normal">Range</th><th className="px-5 py-3 font-normal">State</th></tr></thead>
            <tbody className="divide-y divide-border">{tests.map((test, index) => <tr key={`${test.name}-${index}`} data-testid={`row-report-test-${index}`}>
              <td className="px-5 py-3 font-bold">{test.name}</td>
              <td className="px-3 py-3 font-mono">{formatValue(test.value_normalized ?? test.value_raw)} <span className="text-[13px] text-muted-foreground">{test.unit_normalized || test.unit_raw}</span></td>
              <td className="px-3 py-3 text-[13px] text-muted-foreground">{test.reference_range || '—'}</td>
              <td className="px-5 py-3"><div className="flex flex-wrap gap-1.5">{test.state ? <Badge className={`whitespace-nowrap ${NEUTRAL_BADGE}`}>{titleCase(test.state)}</Badge> : null}{test.validation_status ? <Badge className={`whitespace-nowrap ${labStatusClass(test.validation_status)}`}>{titleCase(test.validation_status)}</Badge> : null}</div></td>
            </tr>)}</tbody>
          </table> : <EmptyState icon={BarChart3} title="No values extracted" detail="The older reader did not extract a table from this report." />}
        </div>
      </section>
      {findings.length > 0 && <section className="rounded-2xl border border-border bg-card">
        <h3 className="border-b border-border px-5 py-4 font-bold">Written findings</h3>
        <div className="divide-y divide-border">{findings.map((finding, index) => <div key={index} className="px-5 py-4" data-testid={`row-report-finding-${index}`}><p className="mono-label text-muted-foreground">{titleCase(finding.category)}</p><p className="mt-1 text-sm leading-relaxed">{finding.text}</p></div>)}</div>
      </section>}
      {quality ? <p className="text-[13px] leading-relaxed text-muted-foreground">{quality.note}</p> : null}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-border bg-card p-4"><p className="text-[13px] text-muted-foreground">{label}</p><p className="font-display mt-1 text-xl font-semibold">{value}</p></div>;
}
