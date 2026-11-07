import { Info } from 'lucide-react';

// What has not been proven about the AI, said wherever someone relies on it.
//
// Each sentence is a fact about the system today, not legal cover: the benchmark
// has 0 of its 200 checked reports (`python -m intelligence.benchmark`) and every
// detector is NOT_VALIDATED. Change the wording when those facts change, and only
// then. It must not claim that CareSense is outside any medical device law; that
// is a question for a lawyer.
export function AiLimitsNote({ className = '' }: { className?: string }) {
  return (
    <p className={`flex items-start gap-2 text-[13px] leading-relaxed text-muted-foreground ${className}`} data-testid="text-ai-limits">
      <Info size={14} className="mt-0.5 shrink-0" />
      <span>
        We have not yet measured how accurate our AI is on real reports, and no doctor checks what it tells you. It can miss results, even ones your lab marked high or low, so please read your full report too. CareSense has not been approved by any medical regulator.{' '}
        <a href="/privacy#medical" target="_blank" rel="noreferrer" className="font-bold text-[hsl(var(--brand))] underline underline-offset-4">Read about its limits</a>
      </span>
    </p>
  );
}
