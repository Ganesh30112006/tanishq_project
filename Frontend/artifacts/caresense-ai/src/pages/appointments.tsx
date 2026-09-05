/**
 * Consultations.
 *
 * Two audiences share this route. A patient browses open times and books one;
 * a clinician publishes availability and works a request queue. Which view you
 * get follows from the permission you hold, not from a client-side toggle.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState, type FormEvent } from 'react';
import {
  CalendarCheck, CalendarPlus, CalendarX, Check, Clock3, Stethoscope, X,
} from 'lucide-react';
import {
  getListAppointmentsQueryKey,
  getListAvailabilityQueryKey,
  getListDoctorDirectoryQueryKey,
  useBookAppointment,
  useCancelAppointment,
  useCompleteAppointment,
  useConfirmAppointment,
  useDeclineAppointment,
  useListAppointments,
  useListAvailability,
  useListDoctorDirectory,
  usePublishAvailability,
  useWithdrawAvailability,
} from '@workspace/api-client-react';
import type { Appointment, AvailabilitySlot } from '@workspace/api-client-react';
import { PERM, useAuth } from '@/lib/auth';
import {
  ActionButton, ATTENTION_BADGE, Badge, CRITICAL_BADGE, EmptyState, FIELD_CLASS, FormError,
  FormField, InlineUnavailable, Modal, ModalActions, NEUTRAL_BADGE, NoAccessPage, PageHeading, POSITIVE_BADGE,
  QueryError, SectionTitle, Skeleton, titleCase,
} from '@/components/ui-kit';

const statusBadge = (status?: string | null) => {
  switch (status) {
    case 'CONFIRMED': return POSITIVE_BADGE;
    case 'REQUESTED': return ATTENTION_BADGE;
    case 'DECLINED':
    case 'CANCELLED': return CRITICAL_BADGE;
    default: return NEUTRAL_BADGE;
  }
};

/** "Thu 12 Sep, 09:30 – 10:00" reads better than two full timestamps. */
function slotLabel(startsAt?: string | null, endsAt?: string | null) {
  if (!startsAt) return '—';
  const start = new Date(startsAt);
  if (Number.isNaN(start.getTime())) return startsAt;
  const day = new Intl.DateTimeFormat('en-GB', {
    weekday: 'short', day: 'numeric', month: 'short',
  }).format(start);
  const time = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' });
  const from = time.format(start);
  const to = endsAt ? time.format(new Date(endsAt)) : '';
  return `${day}, ${from}${to ? ` – ${to}` : ''}`;
}

export default function Appointments() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission(PERM.APPOINTMENT_MANAGE);
  const canBook = hasPermission(PERM.APPOINTMENT_BOOK);

  if (!canManage && !canBook) {
    return (
      <NoAccessPage title="Consultations" detail="This page is for patients booking a consultation and for doctors running their clinic. Your account does not take part in consultations." />
    );
  }

  return (
    <div className="page-enter">
      <PageHeading
        eyebrow="CareSense / consultations"
        title={canManage ? 'Your clinic' : 'Consultations'}
        detail={canManage
          ? 'Publish the times you are available and work through consultation requests.'
          : 'Speak to a doctor about your results. Choose a time that suits you.'}
      />
      {canManage ? <ClinicianView /> : <PatientView />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Patient
// ---------------------------------------------------------------------------

function PatientView() {
  const queryClient = useQueryClient();
  const [booking, setBooking] = useState<AvailabilitySlot | null>(null);
  const [doctorId, setDoctorId] = useState('');

  const slotParams = doctorId ? { doctor_id: doctorId } : undefined;
  const slotsQuery = useListAvailability(slotParams, { query: { queryKey: getListAvailabilityQueryKey(slotParams) } });
  const directoryQuery = useListDoctorDirectory({ query: { queryKey: getListDoctorDirectoryQueryKey() } });
  const mineQuery = useListAppointments(undefined, { query: { queryKey: getListAppointmentsQueryKey() } });
  const cancel = useCancelAppointment();

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: getListAppointmentsQueryKey() });
    queryClient.invalidateQueries({ queryKey: getListAvailabilityQueryKey(slotParams) });
  };

  const upcoming = useMemo(
    () => (mineQuery.data?.results || []).filter((a) => a.status === 'REQUESTED' || a.status === 'CONFIRMED'),
    [mineQuery.data],
  );
  const past = useMemo(
    () => (mineQuery.data?.results || []).filter((a) => a.status !== 'REQUESTED' && a.status !== 'CONFIRMED'),
    [mineQuery.data],
  );

  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-2xl border border-border bg-card">
        <SectionTitle eyebrow="Your bookings" title="Upcoming" id="upcoming-appointments" />
        {mineQuery.isLoading ? <div className="space-y-3 p-5"><Skeleton className="h-14" /><Skeleton className="h-14" /></div>
          : mineQuery.isError ? <div className="p-5"><QueryError onRetry={() => mineQuery.refetch()} message="Your consultations could not be loaded." /></div>
          : upcoming.length ? (
            <div className="divide-y divide-border">
              {upcoming.map((appointment) => (
                <div key={appointment.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4" data-testid={`row-appointment-${appointment.id}`}>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold">{slotLabel(appointment.starts_at, appointment.ends_at)}</p>
                      <Badge className={`whitespace-nowrap ${statusBadge(appointment.status)}`}>{titleCase(appointment.status)}</Badge>
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {appointment.doctor_name}{appointment.specialty ? ` · ${appointment.specialty}` : ''}
                      {appointment.status === 'REQUESTED' ? ' · awaiting confirmation' : ''}
                    </p>
                    {appointment.reason && <p className="mt-1 text-xs text-muted-foreground">“{appointment.reason}”</p>}
                  </div>
                  <ActionButton
                    icon={CalendarX}
                    label="Cancel"
                    variant="danger"
                    onClick={() => cancel.mutate({ appointmentId: appointment.id, data: { reason: 'Cancelled by patient' } }, { onSuccess: refresh })}
                  />
                </div>
              ))}
            </div>
          ) : <EmptyState icon={CalendarCheck} title="No upcoming consultations" detail="Book a time below to speak to a doctor." />}
      </section>

      <section className="overflow-hidden rounded-2xl border border-border bg-card">
        <SectionTitle eyebrow="Book" title="Available times" id="available-slots" />
        <div className="border-b border-border p-4">
          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold text-muted-foreground">Clinician</span>
            <select value={doctorId} onChange={(e) => setDoctorId(e.target.value)} className={FIELD_CLASS} data-testid="select-filter-doctor">
              <option value="">Any doctor</option>
              {(directoryQuery.data?.results || []).map((doctor) => (
                <option key={doctor.id} value={doctor.id}>{doctor.full_name}{doctor.specialty ? ` · ${doctor.specialty}` : ''}</option>
              ))}
            </select>
          </label>
        </div>
        {slotsQuery.isLoading ? <div className="space-y-3 p-5"><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
          : slotsQuery.isError ? <div className="p-5"><QueryError onRetry={() => slotsQuery.refetch()} message="Available times could not be loaded." /></div>
          : slotsQuery.data?.results.length ? (
            <div className="divide-y divide-border">
              {slotsQuery.data.results.map((slot) => (
                <div key={slot.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4" data-testid={`row-slot-${slot.id}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{slotLabel(slot.starts_at, slot.ends_at)}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{slot.doctor_name}{slot.specialty ? ` · ${slot.specialty}` : ''}</p>
                  </div>
                  <ActionButton icon={CalendarPlus} label="Book" variant="primary" onClick={() => setBooking(slot)} />
                </div>
              ))}
            </div>
          ) : <EmptyState icon={Clock3} title="No times available" detail="No doctor has published a free time yet. Please check back later." />}
      </section>

      {past.length > 0 && (
        <section className="overflow-hidden rounded-2xl border border-border bg-card">
          <SectionTitle eyebrow="History" title="Past consultations" id="past-appointments" />
          <div className="divide-y divide-border">
            {past.map((appointment) => (
              <div key={appointment.id} className="px-5 py-4" data-testid={`row-past-${appointment.id}`}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-sm font-medium">{slotLabel(appointment.starts_at, appointment.ends_at)} · {appointment.doctor_name}</p>
                  <Badge className={`whitespace-nowrap ${statusBadge(appointment.status)}`}>{titleCase(appointment.status)}</Badge>
                </div>
                {appointment.outcome_note && <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{appointment.outcome_note}</p>}
                {appointment.resolution_reason && <p className="mt-1.5 text-xs text-muted-foreground">{appointment.resolution_reason}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {booking && <BookModal slot={booking} onClose={() => setBooking(null)} onDone={refresh} />}
    </div>
  );
}

function BookModal({ slot, onClose, onDone }: { slot: AvailabilitySlot; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState('');
  const book = useBookAppointment();

  function submit(event: FormEvent) {
    event.preventDefault();
    book.mutate({ data: { slot_id: slot.id, reason: reason || undefined } }, { onSuccess: () => { onDone(); onClose(); } });
  }

  return (
    <Modal
      title="Book this consultation"
      description={`${slotLabel(slot.starts_at, slot.ends_at)} with ${slot.doctor_name}. The doctor confirms before it is final.`}
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4" data-testid="form-book-appointment">
        <FormField label="What would you like to discuss?" hint="In your own words. This is shared with the doctor so they can prepare.">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={4}
            className="w-full rounded-xl border border-input bg-background p-3 text-sm outline-none focus:border-primary"
            placeholder="e.g. I would like to go through my recent cholesterol results."
            data-testid="input-booking-reason"
          />
        </FormField>
        <FormError error={book.error} />
        <ModalActions onClose={onClose} submitting={book.isPending} submitLabel="Request consultation" />
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Clinician
// ---------------------------------------------------------------------------

function ClinicianView() {
  const queryClient = useQueryClient();
  const [publishing, setPublishing] = useState(false);
  const [completing, setCompleting] = useState<Appointment | null>(null);

  const mineParams = { mine: 'true' };
  const slotsQuery = useListAvailability(mineParams, { query: { queryKey: getListAvailabilityQueryKey(mineParams) } });
  const queueQuery = useListAppointments(undefined, { query: { queryKey: getListAppointmentsQueryKey() } });
  const confirm = useConfirmAppointment();
  const decline = useDeclineAppointment();
  const withdraw = useWithdrawAvailability();

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: getListAppointmentsQueryKey() });
    queryClient.invalidateQueries({ queryKey: getListAvailabilityQueryKey(mineParams) });
  };

  const requests = useMemo(
    () => (queueQuery.data?.results || []).filter((a) => a.status === 'REQUESTED'),
    [queueQuery.data],
  );
  const confirmed = useMemo(
    () => (queueQuery.data?.results || []).filter((a) => a.status === 'CONFIRMED'),
    [queueQuery.data],
  );

  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-2xl border border-border bg-card">
        <SectionTitle eyebrow="Queue" title="Consultation requests" id="requests" />
        <p className="border-b border-border bg-secondary/40 px-5 py-3 text-xs leading-relaxed text-muted-foreground">
          Accepting a request places you on this person's care team and gives you access to their record.
        </p>
        {queueQuery.isLoading ? <div className="space-y-3 p-5"><Skeleton className="h-14" /></div>
          : queueQuery.isError ? <div className="p-5"><QueryError onRetry={() => queueQuery.refetch()} message="Your queue could not be loaded." /></div>
          : requests.length ? (
            <div className="divide-y divide-border">
              {requests.map((appointment) => (
                <div key={appointment.id} className="flex flex-wrap items-start justify-between gap-3 px-5 py-4" data-testid={`row-request-${appointment.id}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{appointment.patient_name}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{slotLabel(appointment.starts_at, appointment.ends_at)}</p>
                    {appointment.reason && <p className="mt-1.5 max-w-xl text-xs leading-relaxed text-muted-foreground">“{appointment.reason}”</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <ActionButton icon={Check} label="Accept" variant="primary" onClick={() => confirm.mutate({ appointmentId: appointment.id }, { onSuccess: refresh })} />
                    <ActionButton icon={X} label="Decline" variant="danger" onClick={() => decline.mutate({ appointmentId: appointment.id, data: { reason: 'Unable to take this consultation' } }, { onSuccess: refresh })} />
                  </div>
                </div>
              ))}
            </div>
          ) : <EmptyState icon={Stethoscope} title="No pending requests" detail="New consultation requests will appear here." />}
      </section>

      <section className="overflow-hidden rounded-2xl border border-border bg-card">
        <SectionTitle eyebrow="Schedule" title="Confirmed consultations" id="confirmed" />
        {confirmed.length ? (
          <div className="divide-y divide-border">
            {confirmed.map((appointment) => (
              <div key={appointment.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4" data-testid={`row-confirmed-${appointment.id}`}>
                <div className="min-w-0">
                  <p className="text-sm font-semibold">{appointment.patient_name}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{slotLabel(appointment.starts_at, appointment.ends_at)}</p>
                </div>
                <ActionButton icon={CalendarCheck} label="Mark held" onClick={() => setCompleting(appointment)} />
              </div>
            ))}
          </div>
        ) : <EmptyState icon={CalendarCheck} title="Nothing scheduled" detail="Consultations you accept will appear here." />}
      </section>

      <section className="overflow-hidden rounded-2xl border border-border bg-card">
        <SectionTitle
          eyebrow="Availability"
          title="Times you have published"
          id="my-availability"
          action={<ActionButton icon={CalendarPlus} label="Publish time" variant="primary" onClick={() => setPublishing(true)} />}
        />
        {slotsQuery.isLoading ? <div className="space-y-3 p-5"><Skeleton className="h-12" /></div>
          : slotsQuery.data?.results.length ? (
            <div className="divide-y divide-border">
              {slotsQuery.data.results.map((slot) => (
                <div key={slot.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4" data-testid={`row-my-slot-${slot.id}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{slotLabel(slot.starts_at, slot.ends_at)}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{slot.is_booked ? 'Booked' : slot.is_open ? 'Open' : 'Withdrawn'}</p>
                  </div>
                  {slot.is_open && !slot.is_booked && (
                    <ActionButton icon={CalendarX} label="Withdraw" onClick={() => withdraw.mutate({ slotId: slot.id }, { onSuccess: refresh })} />
                  )}
                </div>
              ))}
            </div>
          ) : <EmptyState icon={Clock3} title="No availability published" detail="Publish a time so patients can book with you." />}
      </section>

      {publishing && <PublishSlotModal onClose={() => setPublishing(false)} onDone={refresh} />}
      {completing && <CompleteModal appointment={completing} onClose={() => setCompleting(null)} onDone={refresh} />}
    </div>
  );
}

function PublishSlotModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [date, setDate] = useState('');
  const [from, setFrom] = useState('09:00');
  const [minutes, setMinutes] = useState('30');
  const publish = usePublishAvailability();

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!date || !from) return;
    const starts = new Date(`${date}T${from}`);
    const ends = new Date(starts.getTime() + Number(minutes) * 60000);
    publish.mutate(
      { data: { starts_at: starts.toISOString(), ends_at: ends.toISOString() } },
      { onSuccess: () => { onDone(); onClose(); } },
    );
  }

  return (
    <Modal title="Publish a consultation time" description="Patients will be able to book this slot until someone takes it." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-publish-slot">
        <FormField label="Date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} required className={FIELD_CLASS} data-testid="input-slot-date" /></FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Start time"><input type="time" value={from} onChange={(e) => setFrom(e.target.value)} required className={FIELD_CLASS} data-testid="input-slot-time" /></FormField>
          <FormField label="Length">
            <select value={minutes} onChange={(e) => setMinutes(e.target.value)} className={FIELD_CLASS} data-testid="select-slot-length">
              <option value="15">15 minutes</option>
              <option value="30">30 minutes</option>
              <option value="45">45 minutes</option>
              <option value="60">60 minutes</option>
            </select>
          </FormField>
        </div>
        <FormError error={publish.error} />
        <ModalActions onClose={onClose} submitting={publish.isPending} disabled={!date || !from} submitLabel="Publish" />
      </form>
    </Modal>
  );
}

function CompleteModal({ appointment, onClose, onDone }: { appointment: Appointment; onClose: () => void; onDone: () => void }) {
  const [note, setNote] = useState('');
  const complete = useCompleteAppointment();

  function submit(event: FormEvent) {
    event.preventDefault();
    complete.mutate({ appointmentId: appointment.id, data: { note: note || undefined } }, { onSuccess: () => { onDone(); onClose(); } });
  }

  return (
    <Modal
      title={`Mark held · ${appointment.patient_name}`}
      description="A short summary for the patient. Clinical findings belong in a clinical note on their record, not here."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4" data-testid="form-complete-appointment">
        <FormField label="Summary (optional)">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={4} className="w-full rounded-xl border border-input bg-background p-3 text-sm outline-none focus:border-primary" data-testid="input-complete-note" />
        </FormField>
        <FormError error={complete.error} />
        <ModalActions onClose={onClose} submitting={complete.isPending} submitLabel="Mark held" />
      </form>
    </Modal>
  );
}
