import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Bell, CheckCircle2, Mail, MailOpen } from 'lucide-react';
import { getListAlertsQueryKey, getListNotificationsQueryKey, useListAlerts, useListNotifications, useMarkNotificationRead } from '@workspace/api-client-react';
import type { Alert, AlertStatus, Notification } from '@workspace/api-client-react';
import { ATTENTION_BADGE, Badge, EmptyState, InlineUnavailable, NEUTRAL_BADGE, NoAccessPage, PageButton, PageHeading, PageLoading, QueryError, relativeTime, Skeleton, titleCase } from '@/components/ui-kit';
import { PERM, useAuth } from '@/lib/auth';

export default function Alerts() {
  const { hasPermission } = useAuth();
  const [openOnly, setOpenOnly] = useState(false);
  const [page, setPage] = useState(1);
  const params: { status?: AlertStatus; page?: number } = { status: openOnly ? ('OPEN' as AlertStatus) : undefined, page };
  const query = useListAlerts(params, { query: { queryKey: getListAlertsQueryKey(params) } });
  const data = query.data;
  if (!hasPermission(PERM.PATIENT_READ_OWN)) {
    return <NoAccessPage title="Alerts are private" detail="Alerts belong to a health record, and your account is not allowed to open health records." />;
  }
  return (
    <div className="page-enter">
      <PageHeading eyebrow="CareSense / alerts" title="Alerts & messages" detail="Results our system has flagged on your record, and messages from CareSense. Please show any alert to a doctor." />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section aria-labelledby="alerts-title">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 id="alerts-title" className="text-[24px]">Alerts</h2>
            <div className="flex gap-1 rounded-xl border border-border bg-card p-1" role="tablist" aria-label="Filter alerts">
              {[{ key: false, label: 'All' }, { key: true, label: 'Open only' }].map((option) => (
                <button key={option.label} type="button" role="tab" aria-selected={openOnly === option.key} onClick={() => { setOpenOnly(option.key); setPage(1); }} className={`h-9 rounded-lg px-3 text-[13px] font-bold ${openOnly === option.key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-secondary'}`} data-testid={option.key ? 'button-toggle-unread' : 'button-toggle-all'}>{option.label}</button>
              ))}
            </div>
          </div>
          {query.isLoading ? <PageLoading /> : query.isError ? <QueryError onRetry={() => query.refetch()} message="Alerts could not be loaded." /> : data?.results.length ? <>
            <div className="space-y-3">{data.results.map((alert) => <AlertCard key={alert.id} alert={alert} />)}</div>
            <PageButton page={page} pageSize={data.page_size} count={data.count} onChange={setPage} />
          </> : <div className="rounded-2xl border border-border bg-card"><EmptyState icon={CheckCircle2} title={openOnly ? 'You are all caught up' : 'No alerts'} detail="Nothing on your record has been flagged right now." /></div>}
        </section>
        <MessagesPanel />
      </div>
    </div>
  );
}

function AlertCard({ alert }: { alert: Alert }) {
  const isOpen = alert.status === 'OPEN';
  const high = alert.severity === 'HIGH';
  return (
    <article className="relative overflow-hidden rounded-2xl border border-border bg-card p-5 pl-7" data-testid={`card-alert-${alert.id}`}>
      <span className={`absolute inset-y-0 left-0 w-1.5 ${high ? 'bg-[hsl(var(--destructive))]' : isOpen ? 'bg-[hsl(var(--accent))]' : 'bg-border'}`} aria-hidden="true" />
      <div className="flex items-start gap-4">
        <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${high ? 'bg-[hsl(var(--destructive)/.1)] text-[hsl(var(--destructive))]' : 'bg-[hsl(var(--accent)/.2)] text-[hsl(var(--accent-foreground))]'}`}><Bell size={17} /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-bold">{alert.title}</h3>
            <Badge className={isOpen ? ATTENTION_BADGE : NEUTRAL_BADGE}>{titleCase(alert.status)}</Badge>
          </div>
          <p className="mt-1.5 text-[15px] leading-relaxed text-muted-foreground">{alert.detail}</p>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted-foreground">
            <span>{titleCase(alert.category)}</span>
            <span className={high ? 'font-bold text-[hsl(var(--destructive))]' : ''}>{titleCase(alert.severity)} importance</span>
            <time>{relativeTime(alert.created_at)}</time>
          </div>
        </div>
      </div>
    </article>
  );
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

  return (
    <section className="self-start rounded-2xl border border-border bg-card xl:sticky xl:top-24" aria-labelledby="messages-title" data-testid="panel-messages">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h2 id="messages-title" className="text-[22px]">Messages</h2>
        {unread > 0 && <span className="rounded-full bg-[hsl(var(--accent))] px-2.5 py-0.5 text-[12px] font-bold text-[hsl(var(--accent-foreground))]">{unread} new</span>}
      </div>
      <div className="max-h-[70vh] overflow-y-auto p-3">
        {query.isLoading ? <Skeleton className="m-2 h-16" />
          : query.isError ? <div className="p-2"><InlineUnavailable label="Messages are unavailable just now." /></div>
          : rows.length ? rows.map((row) => {
            const isNew = row.status !== 'READ';
            return (
              <div key={row.id} className={`flex gap-3 rounded-xl p-3 ${isNew ? 'bg-[hsl(var(--accent)/.08)]' : ''}`} data-testid={`row-message-${row.id}`}>
                <span className={`mt-0.5 shrink-0 ${isNew ? 'text-[hsl(var(--accent-foreground))]' : 'text-muted-foreground'}`}>{isNew ? <Mail size={17} /> : <MailOpen size={17} />}</span>
                <div className="min-w-0 flex-1">
                  <p className={`text-[15px] ${isNew ? 'font-bold' : ''}`}>{row.subject}</p>
                  <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{row.body}</p>
                  <div className="mt-2 flex items-center gap-3">
                    <span className="text-[12px] text-muted-foreground">{relativeTime(row.created_at)}</span>
                    {isNew && <button type="button" onClick={() => markRead.mutate({ id: row.id })} disabled={markRead.isPending} className="text-[12px] font-bold text-[hsl(var(--brand))] hover:underline disabled:opacity-50" data-testid={`button-mark-read-${row.id}`}>Mark as read</button>}
                  </div>
                </div>
              </div>
            );
          }) : <EmptyState icon={Mail} title="No messages" detail="Anything CareSense needs to tell you will appear here." />}
      </div>
    </section>
  );
}
