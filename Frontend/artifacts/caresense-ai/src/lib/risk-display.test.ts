import { describe, expect, it } from 'vitest';

import {
  BAND_FILL,
  bandFill,
  bandHeadline,
  isRiskyLevel,
  shouldShowScore,
  withheldReason,
} from './risk-display';

/**
 * These guard the client half of the patient-safety rule in
 * `apps/risk/interpretation.py`: a precise figure is only ever shown when the
 * model's evidence supports one, and when it is withheld the reason takes its
 * place rather than the space going blank.
 */

describe('shouldShowScore', () => {
  it('shows the figure when the server permits it and one exists', () => {
    expect(shouldShowScore({ show_score: true, score_percent: 4 })).toBe(true);
  });

  it('withholds the figure when the server says not to', () => {
    // The case that matters: an unvalidated model. A number here would look
    // far more certain than the evidence behind it.
    expect(shouldShowScore({ show_score: false, score_percent: 88 })).toBe(false);
  });

  it('renders nothing rather than "null/100" when permission exists but no figure does', () => {
    expect(shouldShowScore({ show_score: true, score_percent: null })).toBe(false);
    expect(shouldShowScore({ show_score: true })).toBe(false);
  });

  it('defaults to withholding when the reading is absent or silent', () => {
    // Fail closed: an unknown state must not reveal a number.
    expect(shouldShowScore(null)).toBe(false);
    expect(shouldShowScore(undefined)).toBe(false);
    expect(shouldShowScore({})).toBe(false);
  });

  it('shows a legitimate zero rather than treating it as missing', () => {
    // 0% is a real answer; `score_percent != null` must not be a truthiness test.
    expect(shouldShowScore({ show_score: true, score_percent: 0 })).toBe(true);
  });
});

describe('withheldReason', () => {
  const reason =
    'We are not showing an exact number here. This tool has not been checked ' +
    'on a separate group of patients.';

  it('explains the absence when a figure is withheld', () => {
    expect(withheldReason({ show_score: false, score_withheld_reason: reason })).toBe(
      reason,
    );
  });

  it('does not contradict a figure that is on screen', () => {
    expect(
      withheldReason({
        show_score: true,
        score_percent: 4,
        score_withheld_reason: reason,
      }),
    ).toBeNull();
  });

  it('returns null when there is nothing to say', () => {
    expect(withheldReason({ show_score: false })).toBeNull();
    expect(withheldReason(null)).toBeNull();
  });

  it('treats an empty reason as nothing to say', () => {
    expect(withheldReason({ show_score: false, score_withheld_reason: '' })).toBeNull();
  });
});

describe('bandFill', () => {
  it('fills the bar from the band, so a withheld figure still shows something', () => {
    // The failure this prevents: a withheld score leaving an empty track,
    // which reads as "your risk is zero".
    expect(bandFill({ band: 'CRITICAL', show_score: false })).toBe(BAND_FILL.CRITICAL);
    expect(bandFill({ band: 'CRITICAL', show_score: false })).toBeGreaterThan(0);
  });

  it('rises with the band', () => {
    expect(bandFill({ band: 'LOW' })).toBeLessThan(bandFill({ band: 'MEDIUM' }));
    expect(bandFill({ band: 'MEDIUM' })).toBeLessThan(bandFill({ band: 'HIGH' }));
    expect(bandFill({ band: 'HIGH' })).toBeLessThan(bandFill({ band: 'CRITICAL' }));
  });

  it('falls back to the raw score only when there is no band', () => {
    expect(bandFill(null, 37)).toBe(37);
    expect(bandFill({ band: 'UNRECOGNISED' }, 37)).toBe(37);
  });

  it('never leaves the track and never overflows it', () => {
    expect(bandFill(null, null)).toBe(0);
    expect(bandFill(null, 250)).toBe(100);
    expect(bandFill(null, -10)).toBe(0);
  });
});

describe('bandHeadline', () => {
  it('leads with the band label', () => {
    expect(bandHeadline({ band_label: 'Lower than average' }, 'LOW')).toBe(
      'Lower than average',
    );
  });

  it('falls back to the coarse level when no reading is available', () => {
    expect(bandHeadline(null, 'High')).toBe('High');
  });

  it('never renders an empty headline', () => {
    // A blank where the answer should be is worse than saying nothing is known.
    expect(bandHeadline(null, null)).toBe('Not assessed');
    expect(bandHeadline({}, '')).toBe('Not assessed');
  });
});

describe('isRiskyLevel', () => {
  it('treats only HIGH and CRITICAL as needing emphasis', () => {
    expect(isRiskyLevel('HIGH')).toBe(true);
    expect(isRiskyLevel('CRITICAL')).toBe(true);
    expect(isRiskyLevel('MEDIUM')).toBe(false);
    expect(isRiskyLevel('LOW')).toBe(false);
    expect(isRiskyLevel(null)).toBe(false);
  });
});
