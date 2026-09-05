import { Router, type IRouter } from "express";
import {
  GetDashboardSummaryQueryParams,
  GetDashboardSummaryResponse,
  GetPatientAiSummaryParams,
  GetPatientAiSummaryResponse,
  GetPatientResponse,
  GetPatientRiskParams,
  GetPatientRiskResponse,
  GetPatientTimelineParams,
  GetPatientTimelineQueryParams,
  GetPatientTimelineResponse,
  ListAlertsQueryParams,
  ListAlertsResponse,
  ListPatientsQueryParams,
  ListPatientsResponse,
  ListReportsQueryParams,
  ListReportsResponse,
} from "@workspace/api-zod";

const router: IRouter = Router();

const patients = [
  {
    id: "pt-1048",
    name: "Maya Chen",
    initials: "MC",
    age: 42,
    sex: "Female",
    riskLevel: "HIGH",
    riskScore: 72,
    trend: "UP",
    lastUpdated: "Today, 09:42",
    status: "REVIEW_REQUIRED",
    latestAlert: "Risk score increased by 12 points",
    dateOfBirth: "May 18, 1984",
    careTeam: "Dr. Lena Ortiz · Cardiology",
    conditions: ["Hypertension", "Elevated LDL cholesterol"],
    allergies: ["Penicillin"],
    medications: ["Lisinopril 10mg", "Atorvastatin 20mg"],
    measurements: [
      { label: "Blood pressure", value: "142/91", unit: "mmHg", recordedAt: "Today, 09:35", status: "OUT_OF_RANGE" },
      { label: "Heart rate", value: "78", unit: "bpm", recordedAt: "Today, 09:35", status: "IN_RANGE" },
      { label: "Glucose", value: "104", unit: "mg/dL", recordedAt: "Yesterday, 08:12", status: "ATTENTION" },
      { label: "SpO2", value: "98", unit: "%", recordedAt: "Yesterday, 08:12", status: "IN_RANGE" },
    ],
  },
  {
    id: "pt-1182",
    name: "Jonas Williams",
    initials: "JW",
    age: 58,
    sex: "Male",
    riskLevel: "MEDIUM",
    riskScore: 48,
    trend: "DOWN",
    lastUpdated: "Yesterday, 16:20",
    status: "MONITORING",
    latestAlert: null,
    dateOfBirth: "October 2, 1967",
    careTeam: "Dr. Lena Ortiz · Primary care",
    conditions: ["Type 2 diabetes"],
    allergies: [],
    medications: ["Metformin 500mg"],
    measurements: [
      { label: "Blood pressure", value: "128/82", unit: "mmHg", recordedAt: "Yesterday, 16:10", status: "IN_RANGE" },
      { label: "Heart rate", value: "72", unit: "bpm", recordedAt: "Yesterday, 16:10", status: "IN_RANGE" },
      { label: "Glucose", value: "118", unit: "mg/dL", recordedAt: "Yesterday, 08:12", status: "ATTENTION" },
      { label: "SpO2", value: "97", unit: "%", recordedAt: "Yesterday, 08:12", status: "IN_RANGE" },
    ],
  },
  {
    id: "pt-0934",
    name: "Amina Okafor",
    initials: "AO",
    age: 31,
    sex: "Female",
    riskLevel: "LOW",
    riskScore: 18,
    trend: "STABLE",
    lastUpdated: "Aug 28, 11:05",
    status: "STABLE",
    latestAlert: null,
    dateOfBirth: "January 21, 1995",
    careTeam: "Dr. Lena Ortiz · Primary care",
    conditions: [],
    allergies: ["Peanuts"],
    medications: [],
    measurements: [
      { label: "Blood pressure", value: "116/74", unit: "mmHg", recordedAt: "Aug 28, 11:00", status: "IN_RANGE" },
      { label: "Heart rate", value: "68", unit: "bpm", recordedAt: "Aug 28, 11:00", status: "IN_RANGE" },
      { label: "Glucose", value: "92", unit: "mg/dL", recordedAt: "Aug 28, 08:12", status: "IN_RANGE" },
      { label: "SpO2", value: "99", unit: "%", recordedAt: "Aug 28, 08:12", status: "IN_RANGE" },
    ],
  },
  {
    id: "pt-1276",
    name: "Samuel Price",
    initials: "SP",
    age: 67,
    sex: "Male",
    riskLevel: "CRITICAL",
    riskScore: 91,
    trend: "UP",
    lastUpdated: "Today, 07:18",
    status: "REVIEW_REQUIRED",
    latestAlert: "Urgent lab result requires review",
    dateOfBirth: "June 9, 1957",
    careTeam: "Dr. Lena Ortiz · Cardiology",
    conditions: ["Atrial fibrillation", "Chronic kidney disease"],
    allergies: ["Sulfa drugs"],
    medications: ["Apixaban 5mg", "Amlodipine 5mg"],
    measurements: [
      { label: "Blood pressure", value: "166/98", unit: "mmHg", recordedAt: "Today, 07:10", status: "OUT_OF_RANGE" },
      { label: "Heart rate", value: "112", unit: "bpm", recordedAt: "Today, 07:10", status: "OUT_OF_RANGE" },
      { label: "Glucose", value: "132", unit: "mg/dL", recordedAt: "Today, 06:50", status: "ATTENTION" },
      { label: "SpO2", value: "94", unit: "%", recordedAt: "Today, 07:10", status: "ATTENTION" },
    ],
  },
] as const;

const riskByPatient = {
  "pt-1048": {
    overallLevel: "HIGH",
    score: 72,
    previousScore: 60,
    trend: "UP",
    updatedAt: "Today, 09:42",
    modelVersion: "CareSense Risk v2.4",
    confidence: "High confidence · 91%",
    factors: [
      { label: "Blood pressure", contribution: 82, direction: "INCREASES", detail: "Recent readings are above the recommended range." },
      { label: "LDL cholesterol", contribution: 64, direction: "INCREASES", detail: "The latest lab value is higher than the previous measurement." },
      { label: "Activity level", contribution: 31, direction: "INCREASES", detail: "Recorded activity has decreased over the last 14 days." },
      { label: "Heart rate", contribution: 18, direction: "DECREASES", detail: "Resting heart rate remains within the expected range." },
    ],
  },
  "pt-1182": {
    overallLevel: "MEDIUM",
    score: 48,
    previousScore: 55,
    trend: "DOWN",
    updatedAt: "Yesterday, 16:20",
    modelVersion: "CareSense Risk v2.4",
    confidence: "Moderate confidence · 84%",
    factors: [
      { label: "Glucose", contribution: 52, direction: "INCREASES", detail: "Morning glucose remains slightly above the target range." },
      { label: "Blood pressure", contribution: 22, direction: "DECREASES", detail: "Blood pressure has improved since the last assessment." },
      { label: "Medication adherence", contribution: 18, direction: "DECREASES", detail: "Recent entries suggest consistent medication use." },
    ],
  },
  "pt-0934": {
    overallLevel: "LOW",
    score: 18,
    previousScore: 18,
    trend: "STABLE",
    updatedAt: "Aug 28, 11:05",
    modelVersion: "CareSense Risk v2.4",
    confidence: "High confidence · 95%",
    factors: [
      { label: "Blood pressure", contribution: 12, direction: "DECREASES", detail: "Recent readings are consistently within the expected range." },
      { label: "Activity level", contribution: 10, direction: "DECREASES", detail: "Activity pattern is stable and healthy." },
    ],
  },
  "pt-1276": {
    overallLevel: "CRITICAL",
    score: 91,
    previousScore: 76,
    trend: "UP",
    updatedAt: "Today, 07:18",
    modelVersion: "CareSense Risk v2.4",
    confidence: "High confidence · 97%",
    factors: [
      { label: "Heart rate", contribution: 94, direction: "INCREASES", detail: "Resting heart rate is significantly above the expected range." },
      { label: "Blood pressure", contribution: 88, direction: "INCREASES", detail: "Recent readings require prompt clinical review." },
      { label: "Kidney function", contribution: 62, direction: "INCREASES", detail: "Recent lab values changed from the previous report." },
    ],
  },
} as const;

const reports = [
  { id: "rp-391", patientId: "pt-1048", patientName: "Maya Chen", title: "Lipid panel", reportType: "Laboratory", uploadedAt: "Today, 08:56", uploadedBy: "Northstar Labs", status: "REVIEW_REQUIRED", extractedInformation: "LDL cholesterol is above the care target." },
  { id: "rp-390", patientId: "pt-1276", patientName: "Samuel Price", title: "Metabolic panel", reportType: "Laboratory", uploadedAt: "Today, 07:16", uploadedBy: "Northstar Labs", status: "COMPLETED", extractedInformation: "Creatinine increased from 1.4 to 1.7 mg/dL." },
  { id: "rp-389", patientId: "pt-1182", patientName: "Jonas Williams", title: "A1C test", reportType: "Laboratory", uploadedAt: "Yesterday, 15:42", uploadedBy: "Northstar Labs", status: "PROCESSING", extractedInformation: null },
  { id: "rp-388", patientId: "pt-0934", patientName: "Amina Okafor", title: "Annual physical", reportType: "Clinical report", uploadedAt: "Aug 28, 10:22", uploadedBy: "Dr. Lena Ortiz", status: "COMPLETED", extractedInformation: "No significant changes from the previous assessment." },
] as const;

const alerts = [
  { id: "al-01", title: "Risk score increased", detail: "Maya Chen's estimated cardiovascular risk moved from 60% to 72%.", category: "RISK_UPDATE", severity: "HIGH", createdAt: "18 minutes ago", read: false },
  { id: "al-02", title: "Urgent lab result", detail: "Samuel Price's metabolic panel is ready for clinical review.", category: "LAB_RESULT", severity: "CRITICAL", createdAt: "2 hours ago", read: false },
  { id: "al-03", title: "Report ready", detail: "Amina Okafor's annual physical report is available.", category: "REPORT_READY", severity: "LOW", createdAt: "Yesterday", read: true },
  { id: "al-04", title: "New measurement recorded", detail: "Jonas Williams submitted a new glucose measurement.", category: "HEALTH_EVENT", severity: "MEDIUM", createdAt: "Yesterday", read: true },
] as const;

const timelineByPatient = {
  "pt-1048": [
    { id: "ev-01", title: "Risk assessment updated", detail: "AI-estimated cardiovascular risk increased to 72%.", occurredAt: "Today, 09:42", type: "assessment" },
    { id: "ev-02", title: "Lipid panel uploaded", detail: "New report from Northstar Labs is ready for review.", occurredAt: "Today, 08:56", type: "report" },
    { id: "ev-03", title: "Blood pressure recorded", detail: "142/91 mmHg · above the recommended range.", occurredAt: "Today, 09:35", type: "measurement" },
    { id: "ev-04", title: "Clinical note added", detail: "Follow-up requested within 7 days.", occurredAt: "Yesterday, 14:20", type: "note" },
  ],
  "pt-1182": [
    { id: "ev-05", title: "A1C test uploaded", detail: "Report is currently being processed.", occurredAt: "Yesterday, 15:42", type: "report" },
    { id: "ev-06", title: "Glucose recorded", detail: "118 mg/dL · slightly above the target range.", occurredAt: "Yesterday, 08:12", type: "measurement" },
    { id: "ev-07", title: "Risk assessment updated", detail: "AI-estimated risk decreased to 48%.", occurredAt: "Yesterday, 16:20", type: "assessment" },
  ],
  "pt-0934": [
    { id: "ev-08", title: "Annual physical completed", detail: "No significant changes from the previous assessment.", occurredAt: "Aug 28, 11:05", type: "report" },
    { id: "ev-09", title: "Blood pressure recorded", detail: "116/74 mmHg · within the expected range.", occurredAt: "Aug 28, 11:00", type: "measurement" },
  ],
  "pt-1276": [
    { id: "ev-10", title: "Urgent lab result ready", detail: "Metabolic panel requires clinical review.", occurredAt: "Today, 07:18", type: "alert" },
    { id: "ev-11", title: "Heart rate recorded", detail: "112 bpm · above the expected range.", occurredAt: "Today, 07:10", type: "measurement" },
    { id: "ev-12", title: "Risk assessment updated", detail: "AI-estimated risk increased to 91%.", occurredAt: "Today, 07:18", type: "assessment" },
  ],
} as const;

const dashboardByRole = {
  PATIENT: {
    greeting: "Good morning, Maya",
    metrics: [
      { label: "Current risk", value: "72%", context: "High · increased 12 pts", tone: "warning" },
      { label: "Measurements", value: "4", context: "Recorded this week", tone: "positive" },
      { label: "Reports", value: "2", context: "1 needs your review", tone: "neutral" },
      { label: "Next check-in", value: "Sep 12", context: "With Dr. Ortiz", tone: "neutral" },
    ],
  },
  DOCTOR: {
    greeting: "Good morning, Dr. Ortiz",
    metrics: [
      { label: "Total patients", value: "128", context: "Across 3 care groups", tone: "neutral" },
      { label: "High risk", value: "12", context: "3 new since yesterday", tone: "warning" },
      { label: "New alerts", value: "4", context: "2 require review", tone: "critical" },
      { label: "Pending reports", value: "7", context: "2 processing now", tone: "neutral" },
    ],
  },
  LAB_TECHNICIAN: {
    greeting: "Good morning, Alex",
    metrics: [
      { label: "Pending work", value: "18", context: "6 uploaded today", tone: "warning" },
      { label: "Processing", value: "7", context: "Average 12 min", tone: "neutral" },
      { label: "Completed", value: "42", context: "This week", tone: "positive" },
      { label: "Needs review", value: "3", context: "Requires validation", tone: "critical" },
    ],
  },
  ADMIN: {
    greeting: "Good morning, Priya",
    metrics: [
      { label: "Active users", value: "384", context: "12 added this month", tone: "positive" },
      { label: "Security events", value: "2", context: "Both resolved", tone: "neutral" },
      { label: "Audit entries", value: "1,248", context: "Last 30 days", tone: "neutral" },
      { label: "System status", value: "Healthy", context: "All services operational", tone: "positive" },
    ],
  },
} as const;

const recentActivity = [
  { id: "act-01", title: "Risk assessment updated", detail: "Maya Chen · estimated risk moved to 72%", timestamp: "18 min ago", type: "risk" },
  { id: "act-02", title: "Report ready for review", detail: "Samuel Price · metabolic panel", timestamp: "2 hr ago", type: "report" },
  { id: "act-03", title: "Clinical note added", detail: "Jonas Williams · follow-up requested", timestamp: "Yesterday", type: "note" },
  { id: "act-04", title: "Measurement recorded", detail: "Amina Okafor · blood pressure in range", timestamp: "Aug 28", type: "measurement" },
] as const;

function notFound(res: Parameters<Parameters<IRouter["get"]>[1]>[1]) {
  res.status(404).json({ error: "Resource unavailable" });
}

router.get("/dashboard/summary", (req, res) => {
  const parsed = GetDashboardSummaryQueryParams.safeParse(req.query);
  if (!parsed.success) return res.status(422).json({ error: "Invalid dashboard parameters" });
  const role = parsed.data.role ?? "DOCTOR";
  const summary = GetDashboardSummaryResponse.parse({ role, ...dashboardByRole[role], recentActivity });
  return res.json(summary);
});

router.get("/patients", (req, res) => {
  const parsed = ListPatientsQueryParams.safeParse(req.query);
  if (!parsed.success) return res.status(422).json({ error: "Invalid patient filters" });
  const { risk, status, search } = parsed.data;
  const normalizedSearch = search?.trim().toLowerCase();
  const filtered = patients.filter((patient) => {
    const matchesRisk = !risk || patient.riskLevel === risk;
    const matchesStatus = !status || patient.status === status;
    const matchesSearch = !normalizedSearch || patient.name.toLowerCase().includes(normalizedSearch);
    return matchesRisk && matchesStatus && matchesSearch;
  });
  return res.json(ListPatientsResponse.parse(filtered));
});

router.get("/patients/:patientId", (req, res) => {
  const parsed = GetPatientResponse.safeParse(patients.find((patient) => patient.id === req.params.patientId));
  if (!parsed.success) return notFound(res);
  return res.json(parsed.data);
});

router.get("/patients/:patientId/risk", (req, res) => {
  const params = GetPatientRiskParams.safeParse(req.params);
  if (!params.success) return res.status(422).json({ error: "Invalid patient identifier" });
  const assessment = riskByPatient[params.data.patientId as keyof typeof riskByPatient];
  if (!assessment) return notFound(res);
  return res.json(GetPatientRiskResponse.parse(assessment));
});

router.get("/patients/:patientId/timeline", (req, res) => {
  const params = GetPatientTimelineParams.safeParse(req.params);
  const query = GetPatientTimelineQueryParams.safeParse(req.query);
  if (!params.success || !query.success) return res.status(422).json({ error: "Invalid timeline parameters" });
  const events = timelineByPatient[params.data.patientId as keyof typeof timelineByPatient];
  if (!events) return notFound(res);
  return res.json(GetPatientTimelineResponse.parse(events.slice(0, query.data.limit)));
});

router.get("/reports", (req, res) => {
  const parsed = ListReportsQueryParams.safeParse(req.query);
  if (!parsed.success) return res.status(422).json({ error: "Invalid report filters" });
  const filtered = reports.filter((report) => (!parsed.data.patientId || report.patientId === parsed.data.patientId) && (!parsed.data.status || report.status === parsed.data.status));
  return res.json(ListReportsResponse.parse(filtered));
});

router.get("/alerts", (req, res) => {
  const parsed = ListAlertsQueryParams.safeParse(req.query);
  if (!parsed.success) return res.status(422).json({ error: "Invalid alert filters" });
  const filtered = parsed.data.unreadOnly ? alerts.filter((alert) => !alert.read) : alerts;
  return res.json(ListAlertsResponse.parse(filtered));
});

router.get("/patients/:patientId/ai-summary", (req, res) => {
  const params = GetPatientAiSummaryParams.safeParse(req.params);
  if (!params.success || !patients.some((patient) => patient.id === params.data.patientId)) return notFound(res);
  const patient = patients.find((item) => item.id === params.data.patientId)!;
  const risk = riskByPatient[params.data.patientId as keyof typeof riskByPatient];
  const summary = {
    summary: `${patient.name} has an AI-estimated ${risk.overallLevel.toLowerCase()} cardiovascular risk of ${risk.score}%. The score is ${risk.trend === "UP" ? "higher" : risk.trend === "DOWN" ? "lower" : "unchanged"} than the previous assessment.`,
    generatedAt: "Today, 09:45",
    context: "Based on the latest measurements, laboratory reports, and health history available in CareSense.",
    disclaimer: "This summary is AI-generated decision support, not a diagnosis. Discuss changes with a qualified clinician.",
    highlights: risk.factors.slice(0, 3).map((factor) => `${factor.label}: ${factor.detail}`),
  };
  return res.json(GetPatientAiSummaryResponse.parse(summary));
});

export default router;