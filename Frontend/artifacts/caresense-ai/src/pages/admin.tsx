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
  ScrollText, ShieldCheck, Stethoscope, UserPlus, Users, UserX,
} from 'lucide-react';
import {
  getListAssignmentsQueryKey,
  getListAuditLogsQueryKey,
  getListDoctorsQueryKey,
  getListLaboratoriesQueryKey,
  getListLabTechniciansQueryKey,
  getListMissingDataTasksQueryKey,
  getListPatientsQueryKey,
  getListReconciliationEventsQueryKey,
  getListUsersQueryKey,
  useCreateAssignment,
  useCreateDoctor,
  useCreateLaboratory,
  useCreateLabTechnician,
  useCreateUser,
  useDeactivateUser,
  useEndAssignment,
  useGrantRole,
  useLinkPatientAccount,
  useListAssignments,
  useListAuditLogs,
  useListDoctors,
  useListLaboratories,
  useListLabTechnicians,
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

const ROLES: UserRole[] = ['PATIENT', 'DOCTOR', 'LAB_TECHNICIAN', 'ADMIN'];
const SEXES: PatientSex[] = ['FEMALE', 'MALE', 'INTERSEX', 'UNKNOWN'];

type TabKey = 'people' | 'patients' | 'care-teams' | 'laboratories' | 'oversight';

interface Tab {
  key: TabKey;
  label: string;
  icon: typeof Users;
  anyPerm: string[];
}

const TABS: Tab[] = [
  { key: 'people', label: 'People', icon: Users, anyPerm: [PERM.USERS_MANAGE] },
  { key: 'patients', label: 'Patients', icon: UserPlus, anyPerm: [PERM.PATIENT_REGISTER, PERM.USERS_MANAGE] },
  { key: 'care-teams', label: 'Care teams', icon: Stethoscope, anyPerm: [PERM.STAFF_MANAGE] },
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
      {active === 'care-teams' && <CareTeamsSection />}
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
  const [role, setRole] = useState<UserRole>('DOCTOR');
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
  const [role, setRole] = useState<UserRole>('DOCTOR');
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
      description="Creates an identity only. Conditions, medications and results are recorded through their own validated paths. If you are a clinician, you are placed on this patient's care team."
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
// Care teams: clinician profiles and assignments
// ---------------------------------------------------------------------------

function CareTeamsSection() {
  const queryClient = useQueryClient();
  const [creatingDoctor, setCreatingDoctor] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const doctorsQuery = useListDoctors(undefined, { query: { queryKey: getListDoctorsQueryKey() } });
  const assignParams = { status: 'ACTIVE' };
  const assignmentsQuery = useListAssignments(assignParams, { query: { queryKey: getListAssignmentsQueryKey(assignParams) } });
  const endAssignment = useEndAssignment();
  const refreshDoctors = () => queryClient.invalidateQueries({ queryKey: getListDoctorsQueryKey() });
  const refreshAssignments = () => queryClient.invalidateQueries({ queryKey: getListAssignmentsQueryKey(assignParams) });

  return (
    <div className="space-y-6">
      <Panel
        eyebrow="Staff"
        title="Clinicians"
        action={<ActionButton icon={Plus} label="Add clinician" variant="primary" onClick={() => setCreatingDoctor(true)} />}
      >
        {doctorsQuery.isLoading ? <RowSkeleton />
          : doctorsQuery.isError ? <div className="p-5"><QueryError onRetry={() => doctorsQuery.refetch()} message="Clinician profiles are unavailable." /></div>
          : doctorsQuery.data?.results.length ? (
            <div className="divide-y divide-border">
              {doctorsQuery.data.results.map((doctor) => (
                <div key={doctor.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4" data-testid={`row-doctor-${doctor.id}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{doctor.full_name || doctor.email}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{doctor.registration_number}{doctor.specialty ? ` · ${doctor.specialty}` : ''} · {doctor.email}</p>
                  </div>
                  <Badge className={doctor.is_active ? POSITIVE_BADGE : NEUTRAL_BADGE}>{doctor.is_active ? 'Active' : 'Inactive'}</Badge>
                </div>
              ))}
            </div>
          ) : <EmptyState icon={Stethoscope} title="No clinician profiles" detail="Add a profile for an account that already holds the Doctor role." />}
      </Panel>

      <Panel
        eyebrow="Access"
        title="Doctor–patient assignments"
        action={<ActionButton icon={Plus} label="Assign patient" variant="primary" onClick={() => setAssigning(true)} />}
      >
        <p className="border-b border-border bg-secondary/40 px-5 py-3 text-xs leading-relaxed text-muted-foreground">
          An assignment is what authorizes a clinician to open a record. Ending one revokes that access immediately.
        </p>
        {assignmentsQuery.isLoading ? <RowSkeleton />
          : assignmentsQuery.isError ? <div className="p-5"><QueryError onRetry={() => assignmentsQuery.refetch()} message="Assignments are unavailable." /></div>
          : assignmentsQuery.data?.results.length ? (
            <div className="divide-y divide-border">
              {assignmentsQuery.data.results.map((row) => (
                <div key={row.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4" data-testid={`row-assignment-${row.id}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{row.patient_name} <span className="font-normal text-muted-foreground">{row.patient_mrn}</span></p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{row.doctor_name || 'Clinician'} · since {shortDate(row.assigned_at)}{row.reason ? ` · ${row.reason}` : ''}</p>
                  </div>
                  <ActionButton
                    icon={UserX}
                    label="End access"
                    variant="danger"
                    onClick={() => endAssignment.mutate({ assignmentId: row.id, data: { reason: 'Ended by administrator' } }, { onSuccess: refreshAssignments })}
                  />
                </div>
              ))}
            </div>
          ) : <EmptyState icon={Stethoscope} title="No active assignments" detail="Assign a patient to a clinician to grant clinical access." />}
      </Panel>

      {creatingDoctor && <CreateDoctorModal onClose={() => setCreatingDoctor(false)} onDone={refreshDoctors} />}
      {assigning && <AssignPatientModal onClose={() => setAssigning(false)} onDone={refreshAssignments} />}
    </div>
  );
}

function CreateDoctorModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ user_email: '', registration_number: '', specialty: '' });
  const create = useCreateDoctor();
  const update = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.user_email || !form.registration_number) return;
    create.mutate({ data: { ...form, specialty: form.specialty || undefined } }, { onSuccess: () => { onDone(); onClose(); } });
  }

  return (
    <Modal title="Add clinician" description="The account must already hold the Doctor role. Grant it under People first if it does not." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-create-doctor">
        <FormField label="Account email"><input type="email" value={form.user_email} onChange={update('user_email')} required className={FIELD_CLASS} data-testid="input-doctor-email" /></FormField>
        <FormField label="Registration number"><input value={form.registration_number} onChange={update('registration_number')} required className={FIELD_CLASS} data-testid="input-doctor-registration" /></FormField>
        <FormField label="Specialty (optional)"><input value={form.specialty} onChange={update('specialty')} className={FIELD_CLASS} data-testid="input-doctor-specialty" /></FormField>
        <FormError error={create.error} />
        <ModalActions onClose={onClose} submitting={create.isPending} disabled={!form.user_email || !form.registration_number} submitLabel="Add clinician" />
      </form>
    </Modal>
  );
}

function AssignPatientModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [doctorId, setDoctorId] = useState('');
  const [patientId, setPatientId] = useState('');
  const [reason, setReason] = useState('');
  const [search, setSearch] = useState('');
  const doctorsQuery = useListDoctors(undefined, { query: { queryKey: getListDoctorsQueryKey() } });
  const patientParams = { search: search.trim() || undefined, page_size: 8 };
  const patientsQuery = useListPatients(patientParams, { query: { queryKey: getListPatientsQueryKey(patientParams) } });
  const create = useCreateAssignment();

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!doctorId || !patientId) return;
    create.mutate(
      { data: { doctor_id: doctorId, patient_id: patientId, reason: reason || undefined } },
      { onSuccess: () => { onDone(); onClose(); } },
    );
  }

  return (
    <Modal title="Assign patient to clinician" description="This grants the clinician access to that patient's record from now on." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-assign-patient">
        <FormField label="Clinician">
          <select value={doctorId} onChange={(e) => setDoctorId(e.target.value)} required className={FIELD_CLASS} data-testid="select-assign-doctor">
            <option value="">Select a clinician…</option>
            {(doctorsQuery.data?.results || []).filter((d) => d.is_active).map((d) => (
              <option key={d.id} value={d.id}>{d.full_name || d.email} · {d.registration_number}</option>
            ))}
          </select>
        </FormField>
        <FormField label="Patient">
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by name or MRN" className={FIELD_CLASS} data-testid="input-assign-patient-search" />
          <select value={patientId} onChange={(e) => setPatientId(e.target.value)} required className={`${FIELD_CLASS} mt-2`} data-testid="select-assign-patient">
            <option value="">Select a patient…</option>
            {(patientsQuery.data?.results || []).map((p) => (
              <option key={p.id} value={p.id}>{p.full_name} · {p.mrn}</option>
            ))}
          </select>
        </FormField>
        <FormField label="Reason (optional)"><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Cardiology referral" className={FIELD_CLASS} data-testid="input-assign-reason" /></FormField>
        <FormError error={create.error} />
        <ModalActions onClose={onClose} submitting={create.isPending} disabled={!doctorId || !patientId} submitLabel="Grant access" />
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Laboratories and technicians
// ---------------------------------------------------------------------------

function LaboratoriesSection() {
  const queryClient = useQueryClient();
  const [creatingLab, setCreatingLab] = useState(false);
  const [creatingTech, setCreatingTech] = useState(false);
  const labsQuery = useListLaboratories({ query: { queryKey: getListLaboratoriesQueryKey() } });
  const techQuery = useListLabTechnicians(undefined, { query: { queryKey: getListLabTechniciansQueryKey() } });
  const refreshLabs = () => queryClient.invalidateQueries({ queryKey: getListLaboratoriesQueryKey() });
  const refreshTechs = () => queryClient.invalidateQueries({ queryKey: getListLabTechniciansQueryKey() });

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
          ) : <EmptyState icon={Building2} title="No laboratories" detail="Create a laboratory before onboarding technicians." />}
      </Panel>

      <Panel eyebrow="Staff" title="Laboratory technicians" action={<ActionButton icon={Plus} label="Add technician" variant="primary" onClick={() => setCreatingTech(true)} />}>
        {techQuery.isLoading ? <RowSkeleton />
          : techQuery.isError ? <div className="p-5"><QueryError onRetry={() => techQuery.refetch()} message="Technicians are unavailable." /></div>
          : techQuery.data?.results.length ? (
            <div className="divide-y divide-border">
              {techQuery.data.results.map((tech) => (
                <div key={tech.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4" data-testid={`row-tech-${tech.id}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{tech.full_name || tech.email}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{tech.laboratory_code}{tech.employee_id ? ` · ${tech.employee_id}` : ''} · {tech.email}</p>
                  </div>
                  <Badge className={tech.is_active ? POSITIVE_BADGE : NEUTRAL_BADGE}>{tech.is_active ? 'Active' : 'Inactive'}</Badge>
                </div>
              ))}
            </div>
          ) : <EmptyState icon={FlaskConical} title="No technicians" detail="Attach an account holding the Lab technician role to a laboratory." />}
      </Panel>

      {creatingLab && <CreateLaboratoryModal onClose={() => setCreatingLab(false)} onDone={refreshLabs} />}
      {creatingTech && <CreateTechnicianModal labs={labsQuery.data?.results || []} onClose={() => setCreatingTech(false)} onDone={refreshTechs} />}
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

function CreateTechnicianModal({ labs, onClose, onDone }: { labs: { id: string; code: string; name: string }[]; onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ user_email: '', laboratory_id: '', employee_id: '' });
  const create = useCreateLabTechnician();
  const update = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.user_email || !form.laboratory_id) return;
    create.mutate({ data: { ...form, employee_id: form.employee_id || undefined } }, { onSuccess: () => { onDone(); onClose(); } });
  }

  return (
    <Modal title="Add technician" description="The account must already hold the Lab technician role." onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" data-testid="form-create-technician">
        <FormField label="Account email"><input type="email" value={form.user_email} onChange={update('user_email')} required className={FIELD_CLASS} data-testid="input-tech-email" /></FormField>
        <FormField label="Laboratory">
          <select value={form.laboratory_id} onChange={update('laboratory_id')} required className={FIELD_CLASS} data-testid="select-tech-lab">
            <option value="">Select a laboratory…</option>
            {labs.map((lab) => <option key={lab.id} value={lab.id}>{lab.name} · {lab.code}</option>)}
          </select>
        </FormField>
        <FormField label="Employee ID (optional)"><input value={form.employee_id} onChange={update('employee_id')} className={FIELD_CLASS} data-testid="input-tech-employee" /></FormField>
        <FormError error={create.error} />
        <ModalActions onClose={onClose} submitting={create.isPending} disabled={!form.user_email || !form.laboratory_id} submitLabel="Add technician" />
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
