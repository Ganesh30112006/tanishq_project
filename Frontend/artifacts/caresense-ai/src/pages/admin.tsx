/**
 * Administration console.
 *
 * Every section here hands out or reviews access, so each one is gated on the
 * specific permission the server enforces for it. An admin who lacks a
 * permission does not see a disabled control - they see nothing, and the
 * server would refuse the call anyway.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent, type ReactNode } from 'react';
import {
  Activity, Building2, ClipboardList, FlaskConical, KeyRound, Link2, Plus,
  ScrollText, ShieldCheck, UserPlus, Users, UserX,
} from 'lucide-react';
import {
  getListAuditLogsQueryKey,
  getListLaboratoriesQueryKey,
  getListMissingDataTasksQueryKey,
  getListPatientsQueryKey,
  getListReconciliationEventsQueryKey,
  getListUsersQueryKey,
  useCreateLaboratory,
  useCreateUser,
  useDeactivateUser,
  useGrantRole,
  useLinkPatientAccount,
  useListAuditLogs,
  useListLaboratories,
  useListMissingDataTasks,
  useListPatients,
  useListReconciliationEvents,
  useListUsers,
  useRegisterPatient,
  useRevokeRole,
  useRevokeUserTokens,
} from '@workspace/api-client-react';
import type { AdminUser, PatientSex, UserRole } from '@workspace/api-client-react';
import { PERM, useAuth } from '@/lib/auth';
import {
  ActionButton, ATTENTION_BADGE, Badge, CRITICAL_BADGE, dateTime, EmptyState, FIELD_CLASS,
  FormError, FormField, InlineUnavailable, Modal, ModalActions, NEUTRAL_BADGE, NoAccessPage, PageButton,
  PageHeading, POSITIVE_BADGE, QueryError, SectionTitle, shortDate, Skeleton, titleCase,
} from '@/components/ui-kit';

// Account roles this console can grant. Doctor and lab-technician accounts
// are still served by the backend - existing holders keep working exactly as
// before - but this build no longer carries a clinician or lab workspace for
// them to use, so creating a new one from here would be a dead end.
const ROLES: UserRole[] = ['PATIENT', 'ADMIN'];
const SEXES: PatientSex[] = ['FEMALE', 'MALE', 'INTERSEX', 'UNKNOWN'];

type TabKey = 'people' | 'patients' | 'laboratories' | 'oversight';

interface Tab {
  key: TabKey;
  label: string;
  icon: typeof Users;
  anyPerm: string[];
}

const TABS: Tab[] = [
  { key: 'people', label: 'People', icon: Users, anyPerm: [PERM.USERS_MANAGE] },
  { key: 'patients', label: 'Patients', icon: UserPlus, anyPerm: [PERM.PATIENT_REGISTER, PERM.USERS_MANAGE] },
  { key: 'laboratories', label: 'Laboratories', icon: FlaskConical, anyPerm: [PERM.STAFF_MANAGE] },
  { key: 'oversight', label: 'Oversight', icon: ShieldCheck, anyPerm: [PERM.AUDIT_READ, PERM.RECONCILIATION_MANAGE] },
];

export default function AdminConsole() {
  const { hasAnyPermission } = useAuth();
  const tabs = TABS.filter((tab) => hasAnyPermission(...tab.anyPerm));
  const [active, setActive] = useState<TabKey | null>(tabs[0]?.key ?? null);

  if (!tabs.length) {
    return (
      <NoAccessPage title="Administration" detail="This page is for administrators, who manage accounts, staff and audit records. Your account does not have any administrative access." />
    );
  }

  return (
    <div className="page-enter">
      <PageHeading
        eyebrow="CareSense / administration"
        title="Administration"
        detail="Accounts, clinical staff and the care relationships that grant access to patient records. Every change here is written to the audit trail."
      />
      <div className="mb-6 flex flex-wrap gap-2" role="tablist" aria-label="Administration sections">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            role="tab"
            aria-selected={active === key}
            onClick={() => setActive(key)}
            className={`inline-flex h-10 items-center gap-2 rounded-xl px-3 text-sm font-medium ${
              active === key ? 'bg-primary text-primary-foreground' : 'border border-input bg-card hover:bg-secondary'
            }`}
            data-testid={`tab-admin-${key}`}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </div>

      {active === 'people' && <PeopleSection />}
      {active === 'patients' && <PatientsSection />}
      {active === 'laboratories' && <LaboratoriesSection />}
      {active === 'oversight' && <OversightSection />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared building blocks
// ---------------------------------------------------------------------------

function Panel({ eyebrow, title, action, children }: { eyebrow: string; title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-border bg-card">
      <SectionTitle eyebrow={eyebrow} title={title} id={`panel-${title.toLowerCase().replace(/\s+/g, '-')}`} action={action} />
      {children}
    </section>
  );
}

function RowSkeleton() {
  return <div className="space-y-3 p-5"><Skeleton className="h-10" /><Skeleton className="h-10" /><Skeleton className="h-10" /></div>;
}

function roleBadgeClass(role: string) {
  if (role === 'ADMIN') return CRITICAL_BADGE;
  if (role === 'DOCTOR') return POSITIVE_BADGE;
  if (role === 'LAB_TECHNICIAN') return ATTENTION_BADGE;
  return NEUTRAL_BADGE;
}

// ---------------------------------------------------------------------------
// People: accounts and role grants
// ---------------------------------------------------------------------------

function PeopleSection() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [roleFor, setRoleFor] = useState<AdminUser | null>(null);
  const params = { page };
  const query = useListUsers(params, { query: { queryKey: getListUsersQueryKey(params) } });
  const deactivate = useDeactivateUser();
  const revokeTokens = useRevokeUserTokens();
  const refresh = () => queryClient.invalidateQueries({ queryKey: getListUsersQueryKey(params) });

  const data = query.data;
  return (
    <>
      <Panel
        eyebrow="Accounts"
        title="User accounts"
        action={<ActionButton icon={Plus} label="New account" variant="primary" onClick={() => setCreating(true)} />}
      >
        {query.isLoading ? <RowSkeleton />
          : query.isError ? <div className="p-5"><QueryError onRetry={() => query.refetch()} message="Accounts are unavailable." /></div>
          : data?.results.length ? (
            <div className="divide-y divide-border">
              {data.results.map((user) => (
                <div key={user.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4" data-testid={`row-user-${user.id}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{user.full_name || user.email}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{user.email} · joined {shortDate(user.date_joined)}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {user.roles.length
                        ? user.roles.map((role) => <Badge key={role} className={roleBadgeClass(role)}>{titleCase(role)}</Badge>)
                        : <Badge className={NEUTRAL_BADGE}>No role</Badge>}
                      {!user.is_active && <Badge className={CRITICAL_BADGE}>Deactivated</Badge>}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <ActionButton icon={ShieldCheck} label="Roles" onClick={() => setRoleFor(user)} />
                    <ActionButton
                      icon={KeyRound}
                      label="Revoke sessions"
                      onClick={() => revokeTokens.mutate({ userId: user.id }, { onSuccess: refresh })}
                    />
                    {user.is_active && (
                      <ActionButton
                        icon={UserX}
                        label="Deactivate"
                        variant="danger"
                        onClick={() => deactivate.mutate({ userId: user.id }, { onSuccess: refresh })}
                      />
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : <EmptyState icon={Users} title="No accounts" detail="Create the first account to get started." />}
      </Panel>
      {data && <PageButton page={page} pageSize={data.page_size} count={data.count} onChange={setPage} />}
      {creating && <CreateUserModal onClose={() => setCreating(false)} onDone={refresh} />}
      {roleFor && <RolesModal user={roleFor} onClose={() => setRoleFor(null)} onDone={refresh} />}
    </>
  );
}

function CreateUserModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ email: '', full_name: '', password: '' });
  const [role, setRole] = useState<UserRole>('PATIENT');
  const create = useCreateUser();
  const grant = useGrantRole();
  const update = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.email || !form.full_name) return;
    create.mutate(
      { data: { email: form.email, full_name: form.full_name, password: form.password || undefined, is_active: true } },
      {
        onSuccess: (user) => {
          // An account with no role can sign in but do nothing, so grant the
          // intended role as part of creating it.
          grant.mutate({ userId: user.id, data: { role } }, { onSuccess: () => { onDone(); onClose(); } });
        },
      },
    );
  }

  return (
    <Modal title="New account" description="Creates the login and grants its starting role. Clinical access still depends on a care relationship." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-create-user">
        <FormField label="Full name"><input value={form.full_name} onChange={update('full_name')} required className={FIELD_CLASS} data-testid="input-user-name" /></FormField>
        <FormField label="Email"><input type="email" value={form.email} onChange={update('email')} required className={FIELD_CLASS} data-testid="input-user-email" /></FormField>
        <FormField label="Temporary password" hint="Leave blank to create the account without a usable password (federated sign-in).">
          <input type="password" value={form.password} onChange={update('password')} minLength={12} className={FIELD_CLASS} data-testid="input-user-password" />
        </FormField>
        <FormField label="Role">
          <select value={role} onChange={(e) => setRole(e.target.value as UserRole)} className={FIELD_CLASS} data-testid="select-user-role">
            {ROLES.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
          </select>
        </FormField>
        <FormError error={create.error || grant.error} />
        <ModalActions onClose={onClose} submitting={create.isPending || grant.isPending} disabled={!form.email || !form.full_name} submitLabel="Create account" />
      </form>
    </Modal>
  );
}

function RolesModal({ user, onClose, onDone }: { user: AdminUser; onClose: () => void; onDone: () => void }) {
  const [role, setRole] = useState<UserRole>('PATIENT');
  const grant = useGrantRole();
  const revoke = useRevokeRole();
  const busy = grant.isPending || revoke.isPending;

  return (
    <Modal title={`Roles · ${user.full_name || user.email}`} description="A role decides what kind of action this account may attempt. It never, on its own, grants access to a specific patient." onClose={onClose}>
      <div className="space-y-4">
        <div>
          <p className="mb-2 text-xs font-semibold text-muted-foreground">Current roles</p>
          <div className="flex flex-wrap gap-2">
            {user.roles.length ? user.roles.map((held) => (
              <span key={held} className="inline-flex items-center gap-2 rounded-lg border border-input bg-card px-2.5 py-1.5 text-xs font-medium">
                {titleCase(held)}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => revoke.mutate({ userId: user.id, roleCode: held }, { onSuccess: () => { onDone(); onClose(); } })}
                  className="text-muted-foreground hover:text-[hsl(var(--destructive))]"
                  aria-label={`Revoke ${held}`}
                  data-testid={`button-revoke-role-${held}`}
                >
                  ×
                </button>
              </span>
            )) : <p className="text-sm text-muted-foreground">This account holds no roles.</p>}
          </div>
        </div>
        <FormField label="Grant a role">
          <select value={role} onChange={(e) => setRole(e.target.value as UserRole)} className={FIELD_CLASS} data-testid="select-grant-role">
            {ROLES.filter((r) => !user.roles.includes(r)).map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
          </select>
        </FormField>
        <FormError error={grant.error || revoke.error} />
        <div className="mt-5 flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="inline-flex h-10 items-center rounded-xl border border-input bg-card px-3 text-sm font-medium hover:bg-secondary">Close</button>
          <button
            type="button"
            disabled={busy}
            onClick={() => grant.mutate({ userId: user.id, data: { role } }, { onSuccess: () => { onDone(); onClose(); } })}
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60"
            data-testid="button-grant-role"
          >
            Grant role
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Patients: registration and account linking
// ---------------------------------------------------------------------------

function PatientsSection() {
  const { hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [registering, setRegistering] = useState(false);
  const [linkFor, setLinkFor] = useState<{ id: string; name: string } | null>(null);
  const params = { search: search.trim() || undefined, page };
  const query = useListPatients(params, { query: { queryKey: getListPatientsQueryKey(params) } });
  const refresh = () => queryClient.invalidateQueries({ queryKey: getListPatientsQueryKey(params) });

  const canRegister = hasPermission(PERM.PATIENT_REGISTER);
  const canLink = hasPermission(PERM.USERS_MANAGE);
  const data = query.data;

  return (
    <>
      <Panel
        eyebrow="Records"
        title="Patient records"
        action={canRegister ? <ActionButton icon={UserPlus} label="Register patient" variant="primary" onClick={() => setRegistering(true)} /> : undefined}
      >
        <div className="border-b border-border p-4">
          <input
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            placeholder="Search by name or MRN"
            className={FIELD_CLASS}
            data-testid="input-admin-patient-search"
          />
        </div>
        {query.isLoading ? <RowSkeleton />
          : query.isError ? <div className="p-5"><QueryError onRetry={() => query.refetch()} message="Patient records are unavailable to this account." /></div>
          : data?.results.length ? (
            <div className="divide-y divide-border">
              {data.results.map((patient) => (
                <div key={patient.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4" data-testid={`row-admin-patient-${patient.id}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{patient.full_name}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{patient.mrn} · {patient.age ?? '—'} years · {titleCase(patient.sex)}</p>
                  </div>
                  {canLink && <ActionButton icon={Link2} label="Link account" onClick={() => setLinkFor({ id: patient.id, name: patient.full_name })} />}
                </div>
              ))}
            </div>
          ) : <EmptyState icon={UserPlus} title="No patient records" detail="Register a patient to create the first record." />}
      </Panel>
      {data && <PageButton page={page} pageSize={data.page_size} count={data.count} onChange={setPage} />}
      {registering && <RegisterPatientModal onClose={() => setRegistering(false)} onDone={refresh} />}
      {linkFor && <LinkAccountModal patient={linkFor} onClose={() => setLinkFor(null)} onDone={refresh} />}
    </>
  );
}

function RegisterPatientModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ mrn: '', given_name: '', family_name: '', date_of_birth: '', phone: '' });
  const [sex, setSex] = useState<PatientSex>('UNKNOWN');
  const register = useRegisterPatient();
  const update = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.mrn || !form.given_name || !form.family_name) return;
    register.mutate(
      {
        data: {
          mrn: form.mrn,
          given_name: form.given_name,
          family_name: form.family_name,
          date_of_birth: form.date_of_birth || null,
          sex,
          phone: form.phone || undefined,
        },
      },
      { onSuccess: () => { onDone(); onClose(); } },
    );
  }

  return (
    <Modal
      title="Register patient"
      description="Creates an identity only. Conditions, medications and results are recorded through their own validated paths."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4" data-testid="form-register-patient">
        <FormField label="Medical record number (MRN)"><input value={form.mrn} onChange={update('mrn')} required className={FIELD_CLASS} data-testid="input-patient-mrn" /></FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Given name"><input value={form.given_name} onChange={update('given_name')} required className={FIELD_CLASS} data-testid="input-patient-given" /></FormField>
          <FormField label="Family name"><input value={form.family_name} onChange={update('family_name')} required className={FIELD_CLASS} data-testid="input-patient-family" /></FormField>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Date of birth"><input type="date" value={form.date_of_birth} onChange={update('date_of_birth')} className={FIELD_CLASS} data-testid="input-patient-dob" /></FormField>
          <FormField label="Sex">
            <select value={sex} onChange={(e) => setSex(e.target.value as PatientSex)} className={FIELD_CLASS} data-testid="select-patient-sex">
              {SEXES.map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </select>
          </FormField>
        </div>
        <FormField label="Phone (optional)"><input value={form.phone} onChange={update('phone')} className={FIELD_CLASS} data-testid="input-patient-phone" /></FormField>
        <FormError error={register.error} />
        <ModalActions onClose={onClose} submitting={register.isPending} disabled={!form.mrn || !form.given_name || !form.family_name} submitLabel="Register patient" />
      </form>
    </Modal>
  );
}

function LinkAccountModal({ patient, onClose, onDone }: { patient: { id: string; name: string }; onClose: () => void; onDone: () => void }) {
  const [email, setEmail] = useState('');
  const link = useLinkPatientAccount();

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!email) return;
    link.mutate({ patientId: patient.id, data: { user_email: email } }, { onSuccess: () => { onDone(); onClose(); } });
  }

  return (
    <Modal
      title={`Link account · ${patient.name}`}
      description="This is the moment a person gains access to this record. Confirm the identity out-of-band first; the link is written to the audit trail."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4" data-testid="form-link-account">
        <FormField label="Account email" hint="Must be an existing account holding the Patient role.">
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className={FIELD_CLASS} data-testid="input-link-email" />
        </FormField>
        <FormError error={link.error} />
        <ModalActions onClose={onClose} submitting={link.isPending} disabled={!email} submitLabel="Link account" />
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Laboratories
//
// This used to carry two panels: the laboratory directory below, and a
// "Laboratory technicians" staff panel for onboarding lab-technician
// accounts. That staff panel was retired along with the lab workspace itself
// (see the note in App.tsx) - existing technician accounts and the lab
// report pipeline underneath them keep working, there is just no screen
// here to create new ones. The laboratory directory stays: facilities are
// still real institutional data, referenced by reports regardless of who
// uploads them.
// ---------------------------------------------------------------------------

function LaboratoriesSection() {
  const queryClient = useQueryClient();
  const [creatingLab, setCreatingLab] = useState(false);
  const labsQuery = useListLaboratories({ query: { queryKey: getListLaboratoriesQueryKey() } });
  const refreshLabs = () => queryClient.invalidateQueries({ queryKey: getListLaboratoriesQueryKey() });

  return (
    <div className="space-y-6">
      <Panel eyebrow="Facilities" title="Laboratories" action={<ActionButton icon={Plus} label="New laboratory" variant="primary" onClick={() => setCreatingLab(true)} />}>
        {labsQuery.isLoading ? <RowSkeleton />
          : labsQuery.isError ? <div className="p-5"><QueryError onRetry={() => labsQuery.refetch()} message="Laboratories are unavailable." /></div>
          : labsQuery.data?.results.length ? (
            <div className="divide-y divide-border">
              {labsQuery.data.results.map((lab) => (
                <div key={lab.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4" data-testid={`row-lab-${lab.id}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{lab.name}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{lab.code}{lab.address ? ` · ${lab.address}` : ''}</p>
                  </div>
                  <Badge className={lab.is_active ? POSITIVE_BADGE : NEUTRAL_BADGE}>{lab.is_active ? 'Active' : 'Inactive'}</Badge>
                </div>
              ))}
            </div>
          ) : <EmptyState icon={Building2} title="No laboratories" detail="Create a laboratory to get started." />}
      </Panel>

      {creatingLab && <CreateLaboratoryModal onClose={() => setCreatingLab(false)} onDone={refreshLabs} />}
    </div>
  );
}

function CreateLaboratoryModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ code: '', name: '', address: '' });
  const create = useCreateLaboratory();
  const update = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.code || !form.name) return;
    create.mutate({ data: { ...form, address: form.address || undefined } }, { onSuccess: () => { onDone(); onClose(); } });
  }

  return (
    <Modal title="New laboratory" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-create-lab">
        <FormField label="Code" hint="Stored upper-case, e.g. LAB-NORTH."><input value={form.code} onChange={update('code')} required className={FIELD_CLASS} data-testid="input-lab-code" /></FormField>
        <FormField label="Name"><input value={form.name} onChange={update('name')} required className={FIELD_CLASS} data-testid="input-lab-name" /></FormField>
        <FormField label="Address (optional)"><input value={form.address} onChange={update('address')} className={FIELD_CLASS} data-testid="input-lab-address" /></FormField>
        <FormError error={create.error} />
        <ModalActions onClose={onClose} submitting={create.isPending} disabled={!form.code || !form.name} submitLabel="Create laboratory" />
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Oversight: audit trail, conflicts and outstanding tasks
// ---------------------------------------------------------------------------

function OversightSection() {
  const { hasPermission } = useAuth();
  const [page, setPage] = useState(1);
  const auditParams = { page, page_size: 25 };
  const auditQuery = useListAuditLogs(auditParams, {
    query: { queryKey: getListAuditLogsQueryKey(auditParams), enabled: hasPermission(PERM.AUDIT_READ) },
  });
  const reconQuery = useListReconciliationEvents(undefined, { query: { queryKey: getListReconciliationEventsQueryKey() } });
  const tasksQuery = useListMissingDataTasks(undefined, { query: { queryKey: getListMissingDataTasksQueryKey() } });

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-2">
        <Panel eyebrow="Conflicts" title="Reconciliation">
          <p className="border-b border-border bg-secondary/40 px-5 py-3 text-xs leading-relaxed text-muted-foreground">
            Conflicting values are preserved side by side, never silently resolved.
          </p>
          {reconQuery.isLoading ? <RowSkeleton />
            : reconQuery.isError ? <div className="p-5"><InlineUnavailable label="Reconciliation events are unavailable to this account." /></div>
            : reconQuery.data?.results.length ? (
              <div className="divide-y divide-border">
                {reconQuery.data.results.slice(0, 8).map((event) => (
                  <div key={event.id} className="px-5 py-4" data-testid={`row-recon-${event.id}`}>
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium">{titleCase(event.kind)}</p>
                      <Badge className={event.status === 'OPEN' ? ATTENTION_BADGE : NEUTRAL_BADGE}>{titleCase(event.status)}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{event.summary || `${event.items.length} conflicting source(s)`} · {shortDate(event.detected_at)}</p>
                  </div>
                ))}
              </div>
            ) : <EmptyState icon={Activity} title="No conflicts" detail="No preserved data conflicts are awaiting review." />}
        </Panel>

        <Panel eyebrow="Workflow" title="Missing-information tasks">
          {tasksQuery.isLoading ? <RowSkeleton />
            : tasksQuery.isError ? <div className="p-5"><InlineUnavailable label="Tasks are unavailable to this account." /></div>
            : tasksQuery.data?.results.length ? (
              <div className="divide-y divide-border">
                {tasksQuery.data.results.slice(0, 8).map((task) => (
                  <div key={task.id} className="px-5 py-4" data-testid={`row-task-${task.id}`}>
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium">{titleCase(task.requested_data)}</p>
                      <Badge className={task.status === 'RESOLVED' || task.status === 'CLOSED' ? POSITIVE_BADGE : ATTENTION_BADGE}>{titleCase(task.status)}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{task.reason || task.source_workflow} · {titleCase(task.assigned_role)} · {shortDate(task.created_at)}</p>
                  </div>
                ))}
              </div>
            ) : <EmptyState icon={ClipboardList} title="No open tasks" detail="Nothing is blocking an assessment right now." />}
        </Panel>
      </div>

      {hasPermission(PERM.AUDIT_READ) && (
        <>
          <Panel eyebrow="Traceability" title="Audit trail">
            <p className="border-b border-border bg-secondary/40 px-5 py-3 text-xs leading-relaxed text-muted-foreground">
              Append-only. Every access, change and model decision is recorded here.
            </p>
            {auditQuery.isLoading ? <RowSkeleton />
              : auditQuery.isError ? <div className="p-5"><QueryError onRetry={() => auditQuery.refetch()} message="The audit trail is unavailable." /></div>
              : auditQuery.data?.results.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left mono-label text-muted-foreground">
                        <th className="px-5 py-3 font-normal">When</th>
                        <th className="px-3 py-3 font-normal">Actor</th>
                        <th className="px-3 py-3 font-normal">Action</th>
                        <th className="px-3 py-3 font-normal">Resource</th>
                        <th className="px-5 py-3 font-normal">Result</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {auditQuery.data.results.map((row) => (
                        <tr key={row.id} data-testid={`row-audit-${row.id}`}>
                          <td className="whitespace-nowrap px-5 py-3 text-xs text-muted-foreground">{dateTime(row.created_at)}</td>
                          <td className="px-3 py-3 text-xs">{row.actor_label || 'System'}</td>
                          <td className="px-3 py-3 font-medium">{row.action}</td>
                          <td className="px-3 py-3 text-xs text-muted-foreground">{row.resource_type || '—'}</td>
                          <td className="px-5 py-3">
                            <Badge className={row.result === 'SUCCESS' ? POSITIVE_BADGE : row.result === 'DENIED' ? CRITICAL_BADGE : NEUTRAL_BADGE}>{titleCase(row.result)}</Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <EmptyState icon={ScrollText} title="No audit records" detail="Activity will appear here as the system is used." />}
          </Panel>
          {auditQuery.data && <PageButton page={page} pageSize={auditQuery.data.page_size} count={auditQuery.data.count} onChange={setPage} />}
        </>
      )}
    </div>
  );
}
