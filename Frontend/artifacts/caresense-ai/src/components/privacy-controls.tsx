/**
 * Consent and erasure, from the person's own Settings page. The privacy policy
 * promises both rights; a right that can only be used by emailing someone is
 * not much of a right.
 */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Loader2, Trash2 } from 'lucide-react';
import {
  ApiError,
  getGetMyConsentQueryKey,
  getGetMyErasureQueryKey,
  useChangeMyConsent,
  useGetMyConsent,
  useGetMyErasure,
  useRequestMyErasure,
} from '@workspace/api-client-react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Switch } from '@/components/ui/switch';
import { InlineUnavailable, Skeleton, shortDate } from '@/components/ui-kit';

const ERASURE_STATE: Record<string, string> = {
  REQUESTED: 'We have your request. A person will look at it.',
  UNDER_REVIEW: 'A person is looking at your request.',
  COMPLETED: 'Done. The details that identified you have been destroyed.',
  REFUSED: 'We could not do this yet.',
  WITHDRAWN: 'You cancelled this request.',
};

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message.replace(/^HTTP \d+[^:]*:\s*/, '');
  return 'We could not reach CareSense. Please try again.';
}

export function ConsentControls() {
  const queryClient = useQueryClient();
  const consentQuery = useGetMyConsent();
  const change = useChangeMyConsent();
  const [error, setError] = useState<string | null>(null);

  if (consentQuery.isLoading) return <Skeleton className="h-40" />;
  if (consentQuery.isError || !consentQuery.data) return <InlineUnavailable label="Your choices could not be loaded." />;

  const purposes = consentQuery.data.purposes.filter((p) => p.document_version);
  if (!purposes.length) return null;

  return (
    <div className="space-y-3" data-testid="consent-controls">
      <h3 className="text-[17px] font-bold">What you allow us to do</h3>
      <ul className="divide-y divide-border rounded-xl border border-border">
        {purposes.map((p) => (
          <li key={p.purpose} className="flex items-start justify-between gap-4 p-4">
            <div className="min-w-0">
              <p className="font-bold">{p.label}</p>
              <p className="mt-0.5 whitespace-pre-line text-[13px] leading-relaxed text-muted-foreground">{p.body}</p>
              {p.is_essential && <p className="mt-1 text-[13px] text-muted-foreground">Needed while you have an account. To end it, ask us to delete your data below.</p>}
            </div>
            <Switch
              checked={p.granted}
              disabled={p.is_essential || change.isPending}
              aria-label={p.label}
              data-testid={`switch-consent-${p.purpose}`}
              onCheckedChange={(granted) => {
                setError(null);
                change.mutate(
                  { data: { purpose: p.purpose, granted } },
                  {
                    onSuccess: () => queryClient.invalidateQueries({ queryKey: getGetMyConsentQueryKey() }),
                    onError: (err) => setError(messageOf(err)),
                  },
                );
              }}
            />
          </li>
        ))}
      </ul>
      <p className="text-[13px] text-muted-foreground">{consentQuery.data.note}</p>
      {error && <p className="text-sm text-[hsl(var(--destructive))]" role="alert">{error}</p>}
    </div>
  );
}

export function ErasureControl() {
  const queryClient = useQueryClient();
  const erasureQuery = useGetMyErasure();
  const ask = useRequestMyErasure();
  const [error, setError] = useState<string | null>(null);

  if (erasureQuery.isLoading) return <Skeleton className="h-24" />;
  if (erasureQuery.isError || !erasureQuery.data) return <InlineUnavailable label="Your requests could not be loaded." />;

  const requests = erasureQuery.data.results;
  const open = requests.some((r) => r.state === 'REQUESTED' || r.state === 'UNDER_REVIEW');

  return (
    <div className="space-y-3" data-testid="erasure-control">
      <h3 className="text-[17px] font-bold">Delete my data</h3>
      <p className="text-[14px] leading-relaxed text-muted-foreground">{erasureQuery.data.what_this_means}</p>
      {requests.length > 0 && (
        <ul className="space-y-2">
          {requests.map((r) => (
            <li key={r.id} className="rounded-xl border border-border p-3 text-[14px]">
              <span className="font-bold">Asked on {shortDate(r.created_at)}.</span> {ERASURE_STATE[r.state] ?? r.state}
              {r.decision_note ? <span className="mt-1 block text-muted-foreground">{r.decision_note}</span> : null}
            </li>
          ))}
        </ul>
      )}
      {!open && (
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <button type="button" className="inline-flex h-11 items-center gap-2 rounded-xl border border-[hsl(var(--destructive)/.4)] px-4 text-sm font-bold text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/.06)]" data-testid="button-request-erasure">
              <Trash2 size={15} />Ask us to delete my data
            </button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete your data?</AlertDialogTitle>
              <AlertDialogDescription>{erasureQuery.data.what_this_means} You will not be able to sign in again afterwards.</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep my account</AlertDialogCancel>
              <AlertDialogAction
                data-testid="button-confirm-erasure"
                onClick={() => {
                  setError(null);
                  ask.mutate(
                    { data: {} },
                    {
                      onSuccess: () => queryClient.invalidateQueries({ queryKey: getGetMyErasureQueryKey() }),
                      onError: (err) => setError(messageOf(err)),
                    },
                  );
                }}
              >
                {ask.isPending ? <Loader2 size={15} className="animate-spin" /> : null}Yes, ask to delete
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
      {error && <p className="text-sm text-[hsl(var(--destructive))]" role="alert">{error}</p>}
    </div>
  );
}
