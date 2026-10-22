/**
 * Privacy policy.
 *
 * Every statement here describes what this codebase actually does - checked
 * against the backend (apps/privacy, apps/audit, apps/reports/analysis) - not a
 * template's promises. Where something is a business fact this code cannot
 * know (the legal entity, the grievance officer, where servers are hosted), it
 * is a field in POLICY below that reads "to be published before launch" until
 * someone fills it in. Have it reviewed by a lawyer before launch.
 */
import type { ReactNode } from 'react';
import { ArrowLeft, Ban, Eye, FileLock2, Server, UserCheck } from 'lucide-react';
import { BrandMark } from '@/components/error-page';

const POLICY = {
  version: '1',
  effective: '21 October 2026',
  organisation: '',
  contactEmail: '',
  grievanceOfficer: '',
  dataLocation: '',
};

const PENDING = 'to be published before launch';

const SECTIONS: { id: string; title: string }[] = [
  { id: 'who', title: 'Who we are' },
  { id: 'collect', title: 'What we collect' },
  { id: 'use', title: 'Why we use it' },
  { id: 'ai', title: 'How our AI handles your report' },
  { id: 'share', title: 'Who can see your data' },
  { id: 'keep', title: 'How long we keep it' },
  { id: 'protect', title: 'How we protect it' },
  { id: 'rights', title: 'Your rights' },
  { id: 'children', title: 'Children' },
  { id: 'medical', title: 'Not medical advice' },
  { id: 'changes', title: 'Changes to this policy' },
  { id: 'contact', title: 'Contact and complaints' },
];

export default function PrivacyPolicy({ standalone = false }: { standalone?: boolean }) {
  const body = (
    <article className="page-enter" data-testid="page-privacy">
      <header className="border-b border-border pb-8">
        <p className="mono-label flex items-center gap-2 text-[hsl(var(--brand))]"><span aria-hidden="true">§</span>Privacy policy</p>
        <h1 className="mt-3 text-[38px] leading-[1.05] sm:text-[52px]">Your health data, and what we do with it</h1>
        <p className="mt-4 max-w-2xl text-[17px] leading-relaxed text-muted-foreground">Written in plain words, because you should not need a lawyer to understand what happens to your reports.</p>
        <div className="mt-5 flex flex-wrap gap-2 text-[13px]">
          <span className="rounded-md bg-secondary px-2.5 py-1 font-bold">Effective {POLICY.effective}</span>
          <span className="rounded-md bg-secondary px-2.5 py-1 font-bold">Version {POLICY.version}</span>
          <span className="rounded-md bg-[hsl(var(--accent)/.2)] px-2.5 py-1 font-bold text-[hsl(var(--accent-foreground))]">Draft - being reviewed before launch</span>
        </div>
      </header>

      <section aria-label="In short" className="mt-8 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Summary icon={Ban} title="Never sold" text="We do not sell your data or use it for advertising." />
        <Summary icon={Server} title="AI on our own systems" text="No outside AI company receives your reports." />
        <Summary icon={Eye} title="Every access logged" text="Each time a report is opened, we record who and when." />
        <Summary icon={UserCheck} title="Your choice" text="Ask us for a copy, a correction or deletion at any time." />
      </section>

      <div className="mt-12 grid gap-10 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav aria-label="On this page" className="hidden lg:sticky lg:top-24 lg:block lg:self-start">
          <p className="mono-label text-muted-foreground">On this page</p>
          <ol className="mt-3 space-y-1 border-l border-border">
            {SECTIONS.map((s, i) => <li key={s.id}><a href={`#${s.id}`} className="-ml-px block border-l-2 border-transparent py-1.5 pl-4 text-sm text-muted-foreground hover:border-[hsl(var(--brand))] hover:text-foreground"><span className="font-mono text-[11px]">{String(i + 1).padStart(2, '0')}</span> {s.title}</a></li>)}
          </ol>
        </nav>

        <div className="max-w-[70ch] space-y-12 text-[16px] leading-[1.7]">
          <Part n={1} id="who" title="Who we are">
            <p>CareSense is a service that reads the lab reports you upload and explains them in simple words using AI. In this policy, "we" means the organisation that runs CareSense: <Fill value={POLICY.organisation} />.</p>
            <p>For your personal data, we are the "data fiduciary" under India's Digital Personal Data Protection Act, 2023 - the party that decides why and how your data is used, and who answers to you for it.</p>
          </Part>

          <Part n={2} id="collect" title="What we collect">
            <List items={[
              <><strong>Your account.</strong> Your name and email. Your password is stored only as a one-way scrambled code (a "hash"), so nobody at CareSense can read it back. Your date of birth and sex, only if you give them.</>,
              <><strong>Your reports.</strong> The files you upload, the text and values read from them, and what our AI found in them.</>,
              <><strong>Security records.</strong> Each time your record or a report is opened, we record who opened it, when, and from which internet (IP) address and browser.</>,
              <><strong>On your device.</strong> The app keeps a sign-in key and small display settings in your browser's storage, so you stay signed in. We use no advertising trackers and no analytics cookies, and our fonts load from our own servers, not from a third party.</>,
            ]} />
          </Part>

          <Part n={3} id="use" title="Why we use it">
            <List items={[
              'To run your account and keep you signed in.',
              'To read your reports and show you what our AI found.',
              'To keep your record safe, and to find out who did what if something goes wrong.',
              'To follow the law.',
            ]} />
            <p>We do <strong>not</strong> use your data for advertising, and we do not sell or rent it to anyone. We will only use de-identified data for research if you separately agree - we will ask you first, and saying no changes nothing about your account.</p>
          </Part>

          <Part n={4} id="ai" title="How our AI handles your report">
            <p>When you upload a report, our AI reads the file itself - which may show your name, as the lab printed it - together with your age and sex, because many normal ranges depend on them. It is not sent your email or password.</p>
            <p>Today our AI runs entirely on CareSense's own systems. No outside AI company receives your reports. If this ever changes, we will update this policy and tell you before it happens.</p>
            <p>What our AI produces is kept separately from your health record, with a note of the rules that produced it, so any result we show you can be traced back. It never changes a value on your record.</p>
          </Part>

          <Part n={5} id="share" title="Who can see your data">
            <List items={[
              <><strong>You.</strong> Your reports and results are shown to you after you sign in.</>,
              <><strong>Account administrators</strong> can see account details - your name, record number and date of birth - so they can help with sign-in problems. They cannot open your reports or results in the app.</>,
              <><strong>Engineers who run our systems</strong> can technically reach stored data. They may do so only to keep the service working.</>,
              <><strong>The law.</strong> We share data only if the law requires it, for example a court order. We will tell you, unless the law forbids us.</>,
            ]} />
          </Part>

          <Part n={6} id="keep" title="How long we keep it">
            <p>Keeping data forever is a risk, so every kind of data has a time limit. These are our current periods. They are being reviewed against the laws that apply to us, and this page will be updated if they change.</p>
            <div className="overflow-hidden rounded-xl border border-border">
              <table className="w-full text-[15px]">
                <tbody className="divide-y divide-border">
                  <Row a="Your health record and the reports you upload" b="At least 3 years after the last entry" />
                  <Row a="What our AI found in a report" b="As long as the report itself" />
                  <Row a="Conversations with the AI assistant" b="1 year" />
                  <Row a="Security records (who opened what)" b="8 years - so that any access to your record can still be checked" />
                </tbody>
              </table>
            </div>
            <p>Your data is stored on servers located in: <Fill value={POLICY.dataLocation} />.</p>
          </Part>

          <Part n={7} id="protect" title="How we protect it">
            <List items={[
              'Report files are stored privately and are only handed out after we check who is asking and whether they are allowed.',
              'Uploads are checked to be real PDF or image files before they are stored.',
              'Every opening of a record or report is written to a log that cannot be edited.',
              'Our AI service only answers requests that carry a secret service key, and it is only given the report it was asked about.',
            ]} />
            <p>No system is perfectly secure. If a breach affects your data, we will tell you and the Data Protection Board of India as the law requires.</p>
          </Part>

          <Part n={8} id="rights" title="Your rights">
            <p>Under the Digital Personal Data Protection Act, 2023, you can:</p>
            <List items={[
              <><strong>Know</strong> what personal data we hold about you and how we use it.</>,
              <><strong>Correct</strong> data that is wrong or incomplete.</>,
              <><strong>Delete</strong> your data. Some records may have to be kept for a fixed time by law - if so, we will tell you which ones and why.</>,
              <><strong>Withdraw your consent.</strong> We will stop using your data from then on. It does not undo what was done lawfully before.</>,
              <><strong>Complain</strong> to our grievance officer, and if you are not satisfied, to the Data Protection Board of India.</>,
              <><strong>Nominate</strong> someone to act for you if you die or cannot act yourself.</>,
            ]} />
            <p>To use any of these rights, write to us at <Fill value={POLICY.contactEmail} />. Controls for this inside the app are on the way.</p>
          </Part>

          <Part n={9} id="children" title="Children">
            <p>CareSense is meant for adults. If you are under 18, a parent or legal guardian must create and manage the account, and must agree to this policy for you.</p>
          </Part>

          <Part n={10} id="medical" title="Not medical advice">
            <p>CareSense explains reports. It does not diagnose, and it can be wrong. Always show your results to a doctor before you make any decision about your health. If you feel unwell, do not wait - contact a doctor or call 112.</p>
          </Part>

          <Part n={11} id="changes" title="Changes to this policy">
            <p>If we change this policy, we will update the date at the top. If a change affects how your data is used, we will tell you in the app before it applies.</p>
          </Part>

          <Part n={12} id="contact" title="Contact and complaints">
            <div className="grid gap-3 sm:grid-cols-2">
              <Card label="Grievance officer" value={POLICY.grievanceOfficer} />
              <Card label="Email" value={POLICY.contactEmail} />
            </div>
          </Part>
        </div>
      </div>
    </article>
  );

  if (!standalone) return body;
  return (
    <div className="min-h-[100dvh] bg-background">
      <header className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between px-5 sm:px-8">
          <a href="/" className="flex items-center gap-2.5" aria-label="CareSense home"><BrandMark size={30} /><span className="font-display text-xl font-semibold">CareSense</span></a>
          <a href="/" className="inline-flex h-10 items-center gap-2 rounded-xl border border-input px-3.5 text-sm font-bold hover:bg-secondary"><ArrowLeft size={15} />Back to sign in</a>
        </div>
      </header>
      <main className="mx-auto max-w-[1200px] px-5 py-10 sm:px-8 sm:py-14">{body}</main>
    </div>
  );
}

function Fill({ value }: { value: string }) {
  return value ? <strong>{value}</strong> : <em className="rounded bg-[hsl(var(--accent)/.18)] px-1.5 not-italic text-[hsl(var(--accent-foreground))]">{PENDING}</em>;
}

function Summary({ icon: Icon, title, text }: { icon: typeof Ban; title: string; text: string }) {
  return <div className="rounded-2xl border border-border bg-card p-5"><span className="grid size-10 place-items-center rounded-xl bg-[hsl(var(--brand)/.1)] text-[hsl(var(--brand))]"><Icon size={18} /></span><p className="mt-4 font-bold">{title}</p><p className="mt-1 text-sm leading-relaxed text-muted-foreground">{text}</p></div>;
}

function Part({ n, id, title, children }: { n: number; id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24" aria-labelledby={`${id}-title`}>
      <p className="mono-label text-[hsl(var(--brand))]">{String(n).padStart(2, '0')}</p>
      <h2 id={`${id}-title`} className="mt-1 text-[28px] leading-tight">{title}</h2>
      <div className="mt-4 space-y-4 text-foreground/90">{children}</div>
    </section>
  );
}

function List({ items }: { items: ReactNode[] }) {
  return <ul className="space-y-3">{items.map((item, i) => <li key={i} className="flex gap-3"><FileLock2 size={16} className="mt-1.5 shrink-0 text-[hsl(var(--brand))]" /><span>{item}</span></li>)}</ul>;
}

function Row({ a, b }: { a: string; b: string }) {
  return <tr><td className="p-4 font-bold">{a}</td><td className="p-4 text-muted-foreground">{b}</td></tr>;
}

function Card({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-border p-4"><p className="mono-label text-muted-foreground">{label}</p><p className="mt-1.5"><Fill value={value} /></p></div>;
}
