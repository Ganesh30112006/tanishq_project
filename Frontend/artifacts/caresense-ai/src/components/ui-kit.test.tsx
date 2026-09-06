import { render, screen } from '@testing-library/react';
import { AlertCircle } from 'lucide-react';
import { describe, expect, it } from 'vitest';

import {
  Badge,
  EmptyState,
  InlineUnavailable,
  NoAccessPage,
  formatMrn,
  formatValue,
  relativeTime,
  shortDate,
  titleCase,
} from './ui-kit';

describe('titleCase', () => {
  it('turns an enum code into a readable phrase', () => {
    expect(titleCase('REVIEW_REQUIRED')).toBe('Review Required');
    expect(titleCase('INSUFFICIENT_DATA')).toBe('Insufficient Data');
  });

  it('uses Indian English spellings', () => {
    // The product is written in Indian English throughout; American spellings
    // leaking out of backend enum values is the way that slips.
    expect(titleCase('FINALIZED')).toBe('Finalised');
    expect(titleCase('CANCELED')).toBe('Cancelled');
    expect(titleCase('CANCELLED')).toBe('Cancelled');
    expect(titleCase('ANALYZED')).toBe('Analysed');
    expect(titleCase('PRIORITIZED')).toBe('Prioritised');
    expect(titleCase('SUMMARIZED')).toBe('Summarised');
  });

  it('keeps acronyms upper case rather than title casing them', () => {
    expect(titleCase('AI')).toBe('AI');
    expect(titleCase('MRN')).toBe('MRN');
  });

  it('survives empty and missing input', () => {
    expect(titleCase('')).toBe('');
    expect(titleCase(null)).toBe('');
    expect(titleCase(undefined)).toBe('');
  });
});

describe('formatValue', () => {
  it('strips the false precision off a decimal string from the API', () => {
    // DRF serialises decimals as strings; printing them raw shows a precision
    // the measurement never had.
    expect(formatValue('29.000000')).toBe('29');
    expect(formatValue('5.827500')).toBe('5.8275');
    expect(formatValue('128.0000')).toBe('128');
  });

  it('shows an em dash rather than "null" for a missing value', () => {
    // A blank clinical field must never render as "null", "undefined" or "NaN".
    expect(formatValue(null)).toBe('—');
    expect(formatValue(undefined)).toBe('—');
    expect(formatValue('')).toBe('—');
  });

  it('passes through something that is not a number instead of printing NaN', () => {
    expect(formatValue('not-a-number')).toBe('not-a-number');
  });

  it('does not round a real measurement away', () => {
    expect(formatValue(0.0001)).toBe('0.0001');
    expect(formatValue(-12.5)).toBe('-12.5');
  });
});

describe('formatMrn', () => {
  it('does not print "MRN MRN-..." when the value is already prefixed', () => {
    expect(formatMrn('MRN-DEMO-1001')).toBe('MRN-DEMO-1001');
    expect(formatMrn('mrn-demo-1001')).toBe('mrn-demo-1001');
  });

  it('adds the label when it is missing', () => {
    expect(formatMrn('DEMO-1001')).toBe('MRN DEMO-1001');
  });

  it('shows an em dash for no record number', () => {
    expect(formatMrn(null)).toBe('—');
  });
});

describe('relativeTime', () => {
  it('describes recent, hourly and daily gaps', () => {
    const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
    expect(relativeTime(ago(5 * 60_000))).toBe('5 min ago');
    expect(relativeTime(ago(3 * 3_600_000))).toBe('3 hr ago');
    expect(relativeTime(ago(2 * 86_400_000))).toBe('2 d ago');
  });

  it('never reports a negative or zero age for a just-now timestamp', () => {
    expect(relativeTime(new Date().toISOString())).toBe('1 min ago');
  });

  it('falls back rather than rendering "Invalid Date"', () => {
    expect(relativeTime(null)).toBe('Recently');
    expect(relativeTime('nonsense')).toBe('nonsense');
  });
});

describe('shortDate', () => {
  it('formats a date and tolerates a bad one', () => {
    expect(shortDate('2026-09-05T10:00:00Z')).toMatch(/Sep/);
    expect(shortDate(null)).toBe('—');
    expect(shortDate('nonsense')).toBe('nonsense');
  });
});

describe('components', () => {
  it('NoAccessPage explains rather than just refusing', () => {
    render(
      <NoAccessPage
        title="You cannot open this page"
        detail="Ask your administrator if you need access."
      />,
    );
    expect(screen.getByText('You cannot open this page')).toBeInTheDocument();
    expect(
      screen.getByText('Ask your administrator if you need access.'),
    ).toBeInTheDocument();
  });

  it('EmptyState says what is missing and what to do', () => {
    render(
      <EmptyState
        icon={AlertCircle}
        title="No reports yet"
        detail="Upload a lab report to get started."
      />,
    );
    expect(screen.getByText('No reports yet')).toBeInTheDocument();
    expect(screen.getByText('Upload a lab report to get started.')).toBeInTheDocument();
  });

  it('InlineUnavailable states the failure instead of showing an empty area', () => {
    render(<InlineUnavailable label="Messages are unavailable just now." />);
    expect(
      screen.getByText('Messages are unavailable just now.'),
    ).toBeInTheDocument();
  });

  it('Badge renders its content', () => {
    render(<Badge>Completed</Badge>);
    expect(screen.getByText('Completed')).toBeInTheDocument();
  });
});
