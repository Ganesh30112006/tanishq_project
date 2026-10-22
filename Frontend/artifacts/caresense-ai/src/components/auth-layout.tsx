import type { ReactNode } from 'react';
import { Eye, ShieldCheck, Stethoscope } from 'lucide-react';
import { BrandMark } from './error-page';

/**
 * The front door: sign in and sign up.
 *
 * The left half shows what CareSense actually does - reads a printed report and
 * writes a plain note in its margin - rather than a stock illustration. The
 * values on it are an example, labelled as one, and belong to nobody.
 */
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-[100dvh] bg-background lg:grid-cols-[1.05fr_1fr]">
      <aside className="ruled-paper relative hidden flex-col justify-between overflow-hidden border-r border-border bg-[hsl(var(--brand)/.035)] px-14 py-12 lg:flex">
        <Wordmark />
        <div className="max-w-xl">
          <p className="mono-label text-[hsl(var(--brand))]">AI report reader</p>
          <h1 className="mt-4 text-[52px] leading-[1.02] xl:text-[60px]">Your lab report, explained in <em className="text-[hsl(var(--brand))]">plain words</em>.</h1>
          <p className="mt-5 max-w-md text-[17px] leading-relaxed text-muted-foreground">Upload a report. Our AI reads every line, shows you which values are outside the normal range, and tells you honestly what it could not work out.</p>
          <ExampleReport />
        </div>
        <ul className="grid max-w-xl grid-cols-3 gap-6 border-t border-border pt-6 text-[13px] leading-snug text-muted-foreground">
          <li className="flex flex-col gap-2"><Eye size={17} className="text-[hsl(var(--brand))]" />Shows the exact line it read each value from</li>
          <li className="flex flex-col gap-2"><ShieldCheck size={17} className="text-[hsl(var(--brand))]" />Holds back anything it is not sure of</li>
          <li className="flex flex-col gap-2"><Stethoscope size={17} className="text-[hsl(var(--brand))]" />Never a diagnosis - always see a doctor</li>
        </ul>
      </aside>
      <main className="flex flex-col px-5 py-8 sm:px-10 lg:px-16">
        <div className="lg:hidden"><Wordmark /></div>
        <div className="mx-auto flex w-full max-w-[420px] flex-1 flex-col justify-center py-10">{children}</div>
        <footer className="mx-auto flex w-full max-w-[420px] flex-wrap items-center justify-between gap-3 border-t border-border pt-5 text-[13px] text-muted-foreground">
          <span>© {new Date().getFullYear()} CareSense</span>
          <a href="/privacy" className="font-bold text-foreground underline-offset-4 hover:underline" data-testid="link-privacy-footer">Privacy policy</a>
        </footer>
      </main>
    </div>
  );
}

function Wordmark() {
  return (
    <a href="/" className="inline-flex items-center gap-2.5" aria-label="CareSense home">
      <BrandMark size={34} />
      <span className="leading-none">
        <span className="font-display block text-[22px] font-semibold tracking-[-.01em]">CareSense</span>
        <span className="mono-label mt-1 block !text-[9.5px] text-muted-foreground">AI report reader</span>
      </span>
    </a>
  );
}

function ExampleReport() {
  return (
    <figure className="relative mt-10 max-w-md" aria-label="An example of how CareSense annotates a report">
      <div className="rotate-[-1.2deg] rounded-xl border border-border bg-card p-5 shadow-lg">
        <div className="flex items-center justify-between border-b border-dashed border-border pb-3">
          <span className="mono-label text-muted-foreground">Complete blood count</span>
          <span className="mono-label rounded-[4px] bg-secondary px-1.5 py-0.5 text-muted-foreground">Example</span>
        </div>
        <table className="mt-3 w-full font-mono text-[12.5px]">
          <tbody className="[&_td]:py-1.5">
            <tr className="text-muted-foreground"><td>WBC</td><td className="text-right">7.2</td><td className="pl-3 text-right">4.0 – 11.0</td></tr>
            <tr>
              <td className="font-medium">Haemoglobin</td>
              <td className="relative text-right font-medium">
                <span className="relative z-10">9.8</span>
                <span aria-hidden="true" className="absolute -inset-x-2 -inset-y-0.5 rounded-[50%] border-2 border-[hsl(var(--accent))]" />
              </td>
              <td className="pl-3 text-right text-muted-foreground">12.0 – 15.5</td>
            </tr>
            <tr className="text-muted-foreground"><td>Platelets</td><td className="text-right">256</td><td className="pl-3 text-right">150 – 410</td></tr>
          </tbody>
        </table>
      </div>
      <figcaption className="relative -mt-3 ml-auto mr-[-8px] w-[78%] rotate-[1deg] rounded-lg border border-[hsl(var(--brand)/.3)] bg-[hsl(var(--brand))] px-4 py-3 text-[13.5px] leading-snug text-[hsl(var(--brand-foreground))] shadow-md">
        <span className="mono-label block !text-[9.5px] opacity-75">AI note</span>
        Haemoglobin is lower than the normal range on this report. Please show it to a doctor.
      </figcaption>
    </figure>
  );
}
