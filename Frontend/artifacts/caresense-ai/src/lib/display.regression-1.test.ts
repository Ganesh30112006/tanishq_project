// Regression: ISSUE-002 — a thyroid report was shown as "Other"
// Found by /qa on 2026-10-22
// Report: .gstack/qa-reports/run-20261022T144739Z/qa-report-127-0-0-1-2026-10-22.md
import { describe, expect, it } from 'vitest';
import { REPORT_CLASS_LABEL, REPORT_CLASS_OPTIONS, reportType, reportTypeLabel } from './display';

describe('reportType', () => {
  it('has a patient name for every report type', () => {
    for (const code of REPORT_CLASS_OPTIONS) {
      expect(REPORT_CLASS_LABEL[code]).toBeTruthy();
      expect(reportTypeLabel({ report_class: code })).toBe(REPORT_CLASS_LABEL[code]);
    }
  });

  it("uses the AI reader's type where the pipeline could not tell, and says so", () => {
    for (const code of REPORT_CLASS_OPTIONS.filter((c) => c !== 'OTHER')) {
      expect(reportType({ report_class: 'OTHER', ai_report_class: code })).toEqual({ label: REPORT_CLASS_LABEL[code], byAi: true });
      expect(reportType({ report_class: '', ai_report_class: code })?.byAi).toBe(true);
    }
  });

  it("keeps the pipeline's own type where it named one", () => {
    expect(reportType({ report_class: 'GLUCOSE', ai_report_class: null })).toEqual({ label: 'Blood sugar', byAi: false });
  });

  it('says "Other" or the fallback when nobody could tell', () => {
    expect(reportTypeLabel({ report_class: 'OTHER', ai_report_class: null })).toBe('Other');
    expect(reportTypeLabel({ report_class: '' })).toBe('Unclassified');
  });
});
