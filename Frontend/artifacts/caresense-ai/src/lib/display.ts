/**
 * Display vocabulary shared across pages: role names, status colours and the
 * words a patient reads for a report's state.
 */
import type { ReportClass, ReportProcessingState, UserRole } from '@workspace/api-client-react';
import { ATTENTION_BADGE, CRITICAL_BADGE, NEUTRAL_BADGE, POSITIVE_BADGE, titleCase } from '@/components/ui-kit';
import { PERM } from '@/lib/auth';

export const ROLE_LABEL: Record<UserRole, string> = {
  DOCTOR: 'Clinician',
  LAB_TECHNICIAN: 'Lab technician',
  ADMIN: 'Administrator',
  PATIENT: 'Patient',
};

// Matches the server's own precedence (apps/dashboard/service.py) so the
// default view picked here agrees with what the backend would pick anyway.
const ROLE_PRECEDENCE: UserRole[] = ['ADMIN', 'DOCTOR', 'LAB_TECHNICIAN', 'PATIENT'];
export function primaryRole(roles: UserRole[]): UserRole | undefined {
  return ROLE_PRECEDENCE.find((role) => roles.includes(role)) ?? roles[0];
}

/**
 * Someone who can only ever see their own record is reading this as a patient,
 * not as staff. Everything they read has to be written for them: no workflow
 * vocabulary, no pipeline internals, and no list furniture for a list of one.
 */
export function isPatientView(hasPermission: (...codes: string[]) => boolean): boolean {
  return hasPermission(PERM.PATIENT_READ_OWN) && !hasPermission(PERM.PATIENT_READ_ASSIGNED);
}

export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || '?';
}

export const riskClass = (value?: string | null) => value === 'CRITICAL' ? CRITICAL_BADGE : value === 'HIGH' ? 'bg-[hsl(var(--risk-high)/.12)] text-[hsl(var(--risk-high))] ring-[hsl(var(--risk-high)/.3)]' : value === 'MEDIUM' ? ATTENTION_BADGE : POSITIVE_BADGE;
export const statusClass = (value?: string | null) => value === 'REVIEW_REQUIRED' || value === 'REJECTED' ? CRITICAL_BADGE : value === 'MONITORING' || IN_PROGRESS_STATES.has(value || '') ? ATTENTION_BADGE : POSITIVE_BADGE;

// The lab order/result vocabulary is its own; running it through the
// report-oriented `statusClass` painted every state green, including
// "Requested" (nothing has happened yet) and "Cancelled".
export const labStatusClass = (value?: string | null) => {
  switch (value) {
    case 'RESULTED':
    case 'VALIDATED':
    case 'PASSED':
      return POSITIVE_BADGE;
    case 'IN_PROGRESS':
    case 'COLLECTED':
    case 'PENDING':
    case 'REVIEW_REQUIRED':
      return ATTENTION_BADGE;
    case 'CANCELLED':
    case 'FAILED':
      return CRITICAL_BADGE;
    default:
      return NEUTRAL_BADGE; // REQUESTED and anything unrecognised
  }
};

export const lifecycleBadgeClass = (value?: string | null) => {
  switch (value) {
    case 'FINALIZED':
    case 'CLINICALLY_REVIEWED':
      return POSITIVE_BADGE;
    case 'REVIEW_REQUIRED':
      return ATTENTION_BADGE;
    case 'INSUFFICIENT_DATA':
    case 'CANCELLED':
      return CRITICAL_BADGE;
    default:
      return NEUTRAL_BADGE;
  }
};

export const IN_PROGRESS_STATES = new Set<string>([
  'RECEIVED', 'VALIDATING_FILE', 'EXTRACTING', 'CLASSIFYING', 'STRUCTURING', 'RECONCILING',
]);

export const REPORT_CLASS_OPTIONS: ReportClass[] = [
  'CBC', 'LIPID', 'GLUCOSE', 'HBA1C', 'LIVER', 'KIDNEY', 'THYROID', 'ELECTROLYTES', 'URINALYSIS',
  'PATHOLOGY', 'RADIOLOGY', 'PRESCRIPTION', 'DISCHARGE', 'CLINICAL_NOTE', 'OTHER',
];

// Every report type in the words an Indian patient uses for it. Title-casing
// the code gave "Liver", "Kidney" and "Clinical Note", none of which says what
// kind of report it is.
export const REPORT_CLASS_LABEL: Record<ReportClass, string> = {
  CBC: 'Blood count (CBC)',
  LIPID: 'Cholesterol (lipid profile)',
  GLUCOSE: 'Blood sugar',
  HBA1C: 'HbA1c (3-month sugar)',
  LIVER: 'Liver function (LFT)',
  KIDNEY: 'Kidney function (KFT)',
  THYROID: 'Thyroid',
  ELECTROLYTES: 'Electrolytes',
  URINALYSIS: 'Urine test',
  PATHOLOGY: 'Pathology / biopsy',
  RADIOLOGY: 'Scan / X-ray',
  PRESCRIPTION: 'Prescription',
  DISCHARGE: 'Discharge summary',
  CLINICAL_NOTE: "Doctor's note",
  OTHER: 'Other',
};

type Typed = { report_class?: string | null; ai_report_class?: string | null };

/**
 * The kind of report, for a patient. The reading pipeline's own type comes
 * first; where it could not tell, the server sends the type the AI reader
 * worked out (`ai_report_class`), and `byAi` says so.
 */
export function reportType(report: Typed): { label: string; byAi: boolean } | null {
  const own = report.report_class && report.report_class !== 'OTHER' ? report.report_class : '';
  const code = own || report.ai_report_class || report.report_class || '';
  if (!code) return null;
  const label = REPORT_CLASS_LABEL[code as ReportClass] ?? titleCase(code);
  return { label, byAi: !own && Boolean(report.ai_report_class) };
}

export const reportTypeLabel = (report: Typed, empty = 'Unclassified') => reportType(report)?.label ?? empty;

/**
 * A report's processing state, in the words a patient reads.
 *
 * "Review required" was addressed to a reviewer this product no longer has;
 * shown to a patient it reads as "something is wrong with you". What they need
 * to know is whether the report has been read and where to look.
 */
export function patientReportStatus(state?: ReportProcessingState | string | null): { label: string; className: string; busy: boolean } {
  if (IN_PROGRESS_STATES.has(state || '')) return { label: 'Being read', className: ATTENTION_BADGE, busy: true };
  if (state === 'FINALIZED') return { label: 'Read', className: POSITIVE_BADGE, busy: false };
  if (state === 'REJECTED') return { label: 'Could not be read', className: CRITICAL_BADGE, busy: false };
  return { label: 'Read by AI', className: NEUTRAL_BADGE, busy: false };
}

/** Report filters in patient words. The API filters on one exact state, so
 *  "being read" (six states) is not offered as a filter - it is shown on cards. */
export const REPORT_FILTERS: { key: string; label: string; status?: ReportProcessingState }[] = [
  { key: 'all', label: 'All reports' },
  { key: 'review', label: 'Read by AI', status: 'REVIEW_REQUIRED' as ReportProcessingState },
  { key: 'final', label: 'Read', status: 'FINALIZED' as ReportProcessingState },
  { key: 'rejected', label: 'Could not be read', status: 'REJECTED' as ReportProcessingState },
];
