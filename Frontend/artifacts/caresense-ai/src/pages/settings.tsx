import type { ReactNode } from 'react';
import { Link } from 'wouter';
import { ArrowRight, Fingerprint, LockKeyhole, LogOut, ShieldCheck, UserRound } from 'lucide-react';
import { PageHeading, shortDate } from '@/components/ui-kit';
import { useAuth } from '@/lib/auth';
import { initialsOf, primaryRole, ROLE_LABEL } from '@/lib/display';

const SECTIONS = [
  { id: 'profile', label: 'Profile', icon: UserRound },
  { id: 'privacy', label: 'Privacy & your data', icon: ShieldCheck },
  { id: 'security', label: 'Security', icon: LockKeyhole },
  { id: 'session', label: 'Session', icon: Fingerprint },
];

export default function Settings() {
  const { user, logout } = useAuth();
  const role = user ? primaryRole(user.roles) : undefined;
  return (
    <div className="page-enter">
      <PageHeading eyebrow="CareSense / settings" title="Settings" detail="Your account, your data, and how your record is protected." />
      <div className="grid gap-8 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav aria-label="Settings sections" className="lg:sticky lg:top-24 lg:self-start">
          <ul className="flex gap-1 overflow-x-auto lg:flex-col">
            {SECTIONS.map(({ id, label, icon: Icon }) => (
              <li key={id}><a href={`#${id}`} className="flex h-11 items-center gap-2.5 whitespace-nowrap rounded-xl px-3 text-sm font-bold text-muted-foreground hover:bg-secondary hover:text-foreground"><Icon size={16} />{label}</a></li>
            ))}
          </ul>
        </nav>

        <div className="space-y-6">
          <Section id="profile" title="Profile" detail="The details on your account.">
            <div className="flex items-center gap-4">
              <span className="grid size-16 place-items-center rounded-2xl bg-[hsl(var(--brand))] font-display text-2xl font-semibold text-[hsl(var(--brand-foreground))]">{user ? initialsOf(user.full_name || user.email) : '—'}</span>
              <div><p className="font-display text-[24px] font-semibold">{user?.full_name || '—'}</p><p className="text-sm text-muted-foreground">{user?.email}</p></div>
            </div>
            <dl className="mt-6 divide-y divide-border rounded-xl border border-border">
              <Line label="Account type" value={role ? ROLE_LABEL[role] : '—'} />
              <Line label="Member since" value={shortDate(user?.date_joined)} />
            </dl>
          </Section>

          <Section id="privacy" title="Privacy & your data" detail="What we keep, and what you can ask us to do with it.">
            <ul className="space-y-3 text-[15px] leading-relaxed">
              <li className="flex gap-3"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-[hsl(var(--brand))]" />We keep your account details, the reports you upload, and what our AI found in them.</li>
              <li className="flex gap-3"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-[hsl(var(--brand))]" />We do not sell your data and we do not use it for advertising.</li>
              <li className="flex gap-3"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-[hsl(var(--brand))]" />You can ask for a copy of your data, ask us to correct it, or ask us to delete it.</li>
            </ul>
            <Link href="/privacy" className="mt-5 inline-flex h-11 items-center gap-2 rounded-xl border border-input px-4 text-sm font-bold hover:bg-secondary" data-testid="link-settings-privacy">Read the full privacy policy<ArrowRight size={15} /></Link>
          </Section>

          <Section id="security" title="Security" detail="How your record is protected.">
            <p className="text-[15px] leading-relaxed text-muted-foreground">Every request is checked on our server against your real account, not against anything this app claims. Your record is narrowed down before it is ever sent, and every time it is opened, we write it to a log that cannot be edited.</p>
            <details className="group mt-4 rounded-xl border border-border p-4">
              <summary className="flex list-none items-center justify-between text-sm font-bold">Technical: what this account is allowed to do<span className="text-muted-foreground transition-transform group-open:rotate-45">+</span></summary>
              <div className="mt-3 flex flex-wrap gap-1.5">{(user?.permissions || []).map((code) => <span key={code} className="rounded-md bg-secondary px-2 py-1 font-mono text-[12px] text-muted-foreground">{code}</span>)}</div>
            </details>
          </Section>

          <Section id="session" title="Session" detail="You are signed in on this device.">
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-[hsl(var(--success)/.3)] bg-[hsl(var(--success)/.07)] p-4">
              <div className="flex items-center gap-3"><span className="status-dot bg-[hsl(var(--success))]" /><div><p className="font-bold">Signed in</p><p className="text-[13px] text-muted-foreground">{user?.email}</p></div></div>
              <button onClick={() => logout()} className="inline-flex h-11 items-center gap-2 rounded-xl border border-input bg-card px-4 text-sm font-bold hover:bg-secondary" data-testid="button-settings-logout"><LogOut size={15} />Sign out</button>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}

function Section({ id, title, detail, children }: { id: string; title: string; detail: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 rounded-[22px] border border-border bg-card p-6 sm:p-8" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className="text-[26px]">{title}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
      <div className="mt-6">{children}</div>
    </section>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between px-4 py-3 text-[15px]"><dt className="text-muted-foreground">{label}</dt><dd className="font-bold">{value}</dd></div>;
}
