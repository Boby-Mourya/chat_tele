import { Download, Upload, Code2, Copy } from 'lucide-react';
import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge, Button, Card, Field, Modal } from '@/components/ui';
import { useToast } from '@/components/providers';
import { AgentStatusControl } from '@/components/agent-status-control';
import { educationStudentImportApi, type StudentImportRow, type StudentImportPreview } from '@/lib/education-student-import-api';
import { parseStudentImportFile, serializeStudentImportRows } from '@/lib/education-student-import-file-api';
import type { EducationCourse, EducationBatch } from '@/lib/education-api';
import type { Agent } from '@/types';
import { useApi } from '@/lib/use-api';
import { enrollmentReadiness } from '@/lib/education-enrollment-events-api';
import './bot-enrollment-panel.css';

export function botEnrollmentTemplate(agent: Agent, course: EducationCourse, batch: EducationBatch): StudentImportRow {
  return { studentNumber: 'STUDENT-001', name: 'Student name', email: 'student@example.com',
    identityType: 'whatsapp', identifier: '+919876543210', identityVerified: false,
    courseCode: course.code, batchCode: batch.code, agentPublicId: agent.publicId,
    enrollmentStatus: 'active', startsOn: batch.startsOn, endsOn: batch.endsOn };
}

export function BotEnrollmentPanel({ agent, courses, batches, onSaved }: { agent: Agent; courses: EducationCourse[]; batches: EducationBatch[]; onSaved: () => void }) {
  const [revision, setRevision] = useState(0);
  const readiness = useApi(() => enrollmentReadiness(agent.id), [agent.id, revision]);
  const refresh = () => { setRevision((value) => value + 1); onSaved(); };
  const activeCourses = courses.filter((course) => course.status === 'active');
  const [courseId, setCourseId] = useState(activeCourses.length === 1 ? activeCourses[0]!.id : '');
  const matchingBatches = batches.filter((batch) => batch.status === 'active' && batch.courseId === courseId);
  const [batchId, setBatchId] = useState('');
  const course = courses.find((item) => item.id === courseId);
  const batch = matchingBatches.find((item) => item.id === batchId) ?? (matchingBatches.length === 1 ? matchingBatches[0] : undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<StudentImportPreview | null>(null);
  const [rows, setRows] = useState<StudentImportRow[]>([]);
  const [automation, setAutomation] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const { pushToast } = useToast();
  const sample = course && batch ? botEnrollmentTemplate(agent, course, batch) : null;
  const endpoint = readiness.data?.endpoint || `${window.location.origin}/api/v1/education/agents/${agent.id}/enrollment-events`;
  const event = sample ? { eventId: 'payment-ORDER-001-access-granted', source: 'your-lms', paymentStatus: 'paid', accessGranted: true,
    paymentReference: 'ORDER-001', consent: false, row: sample } : null;
  const download = () => {
    if (!sample) return;
    const url = URL.createObjectURL(new Blob(['\uFEFF' + serializeStudentImportRows([sample])], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${course!.code}-${batch!.code}-enrollments.csv`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const upload = async (file?: File) => {
    if (!file || !sample) return;
    setBusy(true); setError(''); setPreview(null);
    try {
      const parsed = await parseStudentImportFile(file);
      // The selected bot/course/batch is the explicit assignment for this upload.
      const assigned = parsed.map((row) => ({ ...row, courseCode: sample.courseCode, batchCode: sample.batchCode, agentPublicId: agent.publicId,
        startsOn: row.startsOn ?? sample.startsOn, endsOn: row.endsOn ?? sample.endsOn }));
      if (assigned.some((row) => row.identityType !== 'whatsapp' || !row.identifier)) throw new Error('Every row needs identity_type whatsapp and the student WhatsApp number in identifier.');
      setRows(assigned); setPreview(await educationStudentImportApi.preview(assigned));
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not read the enrollment file'); }
    finally { setBusy(false); }
  };
  const commit = async () => {
    setBusy(true); setError('');
    try {
      const response = await educationStudentImportApi.commit(rows);
      setPreview(response.preview);
      if (!response.committed || !response.result) throw new Error('Enrollment data changed. Review the row errors and upload again.');
      pushToast(`${response.result.createdStudents} students and ${response.result.createdEnrollments} enrollments created for ${agent.name}`);
      setPreview(null); setRows([]); refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Enrollment import failed'); }
    finally { setBusy(false); }
  };
  const copy = async (value: string) => { try { await navigator.clipboard.writeText(value); pushToast('Copied'); } catch { pushToast('Select and copy the text below', 'error'); } };
  return <Card className="bot-enrollment-panel">
    <div className="bot-enrollment-panel__heading"><div><h3>{agent.name} enrollments</h3><p><strong>WhatsApp:</strong> {agent.whatsappNumber || 'No number assigned'} <Link to="/integrations">Manage connection</Link></p></div><Badge tone={agent.status === 'active' ? 'success' : 'warning'}>{agent.status}</Badge></div>
    <AgentStatusControl agent={agent} onSaved={refresh} showEnrollmentLink={false} />
    {readiness.error ? <p role="alert">{readiness.error}</p> : null}
    {readiness.data ? <div className="bot-enrollment-setup"><h4>Setup for student replies</h4><ul>
      <li>{readiness.data.whatsappConnected ? 'WhatsApp number connected.' : <Link to="/integrations">Connect a WhatsApp number and activate its webhook.</Link>}</li>
      <li>{readiness.data.verifiedStudentNumbers} enrolled student numbers verified. {readiness.data.pendingStudentNumbers > 0 || !readiness.data.verifiedStudentNumbers ? <Link to="/education/students">Review and verify student WhatsApp numbers ({readiness.data.pendingStudentNumbers} pending).</Link> : null}</li>
      <li>{readiness.data.knowledgeSources ? `${readiness.data.knowledgeSources} knowledge sources added. Check training and course scope before testing.` : <Link to={`/agents/${agent.id}/knowledge`}>Add the course knowledge this bot should use.</Link>}</li>
      <li>{readiness.data.aiProviderConfigured ? 'AI provider configured.' : 'Ask your deployment administrator to configure the AI provider key.'}</li>
    </ul></div> : null}
    <div className="bot-enrollment-panel__fields">
      <Field label="Enrollment course" htmlFor="bot-enroll-course"><select disabled={busy} id="bot-enroll-course" value={courseId} onChange={(e) => { setCourseId(e.target.value); setBatchId(''); setPreview(null); }}><option value="">Select course</option>{activeCourses.map((item) => <option value={item.id} key={item.id}>{item.code} - {item.name}</option>)}</select></Field>
      <Field label="Enrollment batch" htmlFor="bot-enroll-batch"><select disabled={busy} id="bot-enroll-batch" value={batch?.id ?? ''} onChange={(e) => { setBatchId(e.target.value); setPreview(null); }}><option value="">Select batch</option>{matchingBatches.map((item) => <option value={item.id} key={item.id}>{item.code} - {item.name}</option>)}</select></Field>
    </div>
    <p>Choose a course and batch, then download the template and fill in your students. Upload creates new students and assigns them to <strong>{agent.name}</strong>. Use Add enrollment above for existing students.</p>
    <div className="bot-enrollment-panel__actions"><Button variant="secondary" icon={Download} disabled={!sample || busy} onClick={download}>Download enrollment CSV</Button><Button icon={Upload} disabled={!sample || busy} onClick={() => fileInput.current?.click()}>{busy ? 'Processing...' : 'Upload CSV / Excel'}</Button><Button variant="secondary" icon={Code2} disabled={!sample} onClick={() => setAutomation(true)}>Automatic enrollment API</Button></div>
    <input ref={fileInput} type="file" className="sr-only" aria-label="Upload bot enrollments" accept=".csv,.tsv,.xlsx" onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ''; }} />
    {!activeCourses.length ? <p><Link to="/education/courses">Create an active course</Link> to get started.</p> : course && !matchingBatches.length ? <p><Link to="/education/batches">Create an active batch for this course</Link>.</p> : null}
    <p className="bot-enrollment-panel__note">Keep phone cells as text, including the country code. Set identity_verified to true only after confirming that the number belongs to the student. Unverified numbers cannot access course content.</p>
    {error ? <div className="form-error" role="alert">{error}</div> : null}
    {preview ? <div className="bot-enrollment-preview"><h4>Review enrollment upload</h4><p>{preview.validRows} ready / {preview.totalRows} rows. Bot: {agent.name}; course: {course?.code}; batch: {batch?.code}.</p><div className="bot-enrollment-preview__table"><table><thead><tr><th>Row</th><th>Student</th><th>WhatsApp</th><th>Validation</th></tr></thead><tbody>{preview.rows.map((item) => <tr key={item.rowNumber}><td>{item.rowNumber}</td><td>{item.row.name}<small>{item.row.studentNumber}</small></td><td>{item.row.identifier}</td><td>{[...item.errors, ...item.warnings].join(' ') || 'Ready'}</td></tr>)}</tbody></table></div><Button disabled={busy || preview.invalidRows > 0} onClick={() => void commit()}>Enroll {preview.validRows} students</Button></div> : null}
    <Modal open={automation} onClose={() => setAutomation(false)} title={`Automatic enrollment - ${agent.name}`} description="Connect your CRM or LMS after payment is confirmed and course access is granted." size="lg" footer={<Button variant="secondary" onClick={() => setAutomation(false)}>Close</Button>}>
      <div className="bot-enrollment-api"><ol><li>Create a server API key in <Link to="/workspace?section=developer">Workspace - API keys</Link>.</li><li>Configure your CRM/LMS workflow to send this request only after successful payment and LMS access. Add <code>Authorization: Bearer YOUR_WORKSPACE_API_KEY</code> and <code>Content-Type: application/json</code> headers.</li><li>Replace the sample student, payment and event values. Reuse the same event ID for retries. The student ID must match an existing student when adding another enrollment.</li></ol>
      <Field label="POST endpoint" htmlFor="enrollment-api-url"><input id="enrollment-api-url" readOnly value={endpoint} /></Field><Button variant="ghost" size="sm" icon={Copy} onClick={() => void copy(endpoint)}>Copy endpoint</Button>
      <Field label="JSON request example" htmlFor="enrollment-api-json"><textarea id="enrollment-api-json" readOnly value={JSON.stringify(event, null, 2)} rows={20} /></Field><Button variant="secondary" size="sm" icon={Copy} onClick={() => void copy(JSON.stringify(event, null, 2))}>Copy JSON</Button>
      <p>Set <code>identityVerified</code> to true only when your system has verified this student's WhatsApp number. The API creates or updates the enrollment and a lead, then queues CRM sync. Keep the bot active for replies.</p>
      <p><Link to="/crm-workflow">Review CRM routing and field mapping</Link> for payment_status, payment_reference, course_code, batch_code and student_number. Provider authorization and a valid CRM route are needed for delivery. Review delivery in <Link to="/leads">Leads - View sync</Link>.</p>
      <p>The key belongs on your CRM/LMS server. GET this same endpoint to review the last 25 accepted events. A successful response confirms enrollment and queued CRM work; provider delivery is tracked separately.</p></div>
    </Modal>
  </Card>;
}
