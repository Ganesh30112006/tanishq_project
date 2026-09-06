/**
 * How a risk estimate is allowed to be shown.
 *
 * The server decides whether a patient may see a figure at all - that gate
 * lives in `apps/risk/interpretation.py` and is the authority. This module is
 * the client half of the same rule, kept here rather than inline in a
 * component so that it can be tested on its own.
 *
 * The rule that matters: **the band leads, and the number is optional.** A
 * figure without a band is just a number; a band without a figure is still an
 * answer a person can act on. When the model's evidence does not support a
 * precise figure, the figure is withheld and the reason is shown in its place -
 * never silently dropped, which would read as "no risk".
 */

/** The shape of the server's interpretation block that display depends on. */
export interface RiskReading {
  band?: string | null;
  band_label?: string | null;
  show_score?: boolean | null;
  score_percent?: number | null;
  score_withheld_reason?: string | null;
  headline?: string | null;
  horizon?: string | null;
}

export const isRiskyLevel = (value?: string | null): boolean =>
  value === 'HIGH' || value === 'CRITICAL';

/**
 * A band, not a score, drives the progress bar. If a withheld figure left the
 * track empty, "we are not showing you a number" would look like "your risk is
 * zero" - the opposite of what is meant.
 */
export const BAND_FILL: Record<string, number> = {
  LOW: 20,
  MEDIUM: 45,
  HIGH: 72,
  CRITICAL: 94,
};

export function bandFill(
  reading?: RiskReading | null,
  fallbackScore?: number | null,
): number {
  const fromBand = BAND_FILL[reading?.band ?? ''];
  if (fromBand !== undefined) return fromBand;
  return Math.min(Math.max(fallbackScore ?? 0, 0), 100);
}

/**
 * May this viewer be shown the numeric score?
 *
 * Both conditions are required. `show_score` alone is not enough: a reading can
 * permit the figure and still not carry one, and rendering `null/100` is worse
 * than rendering nothing.
 */
export function shouldShowScore(reading?: RiskReading | null): boolean {
  return Boolean(reading?.show_score) && reading?.score_percent != null;
}

/**
 * The sentence shown where the figure would have been.
 *
 * Only when a figure is actually being withheld. Returning it alongside a
 * visible score would contradict the number on screen.
 */
export function withheldReason(reading?: RiskReading | null): string | null {
  if (shouldShowScore(reading)) return null;
  return reading?.score_withheld_reason || null;
}

/**
 * The headline a person reads first: always a band, never an empty string.
 * `fallbackLevel` is the coarse level on the patient record, used when no
 * interpreted reading is available.
 */
export function bandHeadline(
  reading?: RiskReading | null,
  fallbackLevel?: string | null,
): string {
  return reading?.band_label || fallbackLevel || 'Not assessed';
}
