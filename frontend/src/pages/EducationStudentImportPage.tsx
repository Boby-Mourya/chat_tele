import {
  AlertTriangle, ArrowLeft, CheckCircle2, ClipboardPaste, Download, FileSpreadsheet, Upload, UsersRound,
} from 'lucide-react';
import { useMemo, useRef, useState, type ChangeEvent } from 'react';
import { Link } from 'react-router-dom';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState } from '@/components/ui';
import {
  STUDENT_IMPORT_TEMPLATE,
  educationStudentImportApi,
  parseStudentImportText,
  StudentImportParseError,
  type StudentImportCommitResult,
  type StudentImportPreview,
  type StudentImportRow,
} from '@/lib/education-student-import-api';
import {
  parseStudentImportFile,
  serializeStudentImportRows,
} from '@/lib/education-student-import-file-api';
import './EducationStudentImportPage.css';

function downloadTemplate(): void {
  const blob = new Blob([STUDENT_IMPORT_TEMPLATE], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'northstar-student-import-template.csv';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function enrollmentLabel(row: StudentImportRow): string {
  if (!row.courseCode) return 'No enrollment';
  return `${row.courseCode} · ${row.batchCode ?? '—'} · ${row.enrollmentStatus ?? 'active'}`;
}

function identityLabel(row: StudentImportRow): string {
  if (!row.identityType || !row.identifier) return 'No identity';
  return `${row.identityType.replace('_', ' ')} · ${row.identifier}${row.identityVerified ? ' · verified' : ' · pending'}`;
}

export function EducationStudentImportPage() {
  const { pushToast } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [sourceText, setSourceText] = useState(STUDENT_IMPORT_TEMPLATE);
  const [sourceName, setSourceName] = useState('Template');
  const [parsedRows, setParsedRows] = useState<StudentImportRow[]>([]);
  const [preview, setPreview] = useState<StudentImportPreview | null>(null);
  const [result, setResult] = useState<StudentImportCommitResult | null>(null);
  const [busy, setBusy] = useState<'file' | 'preview' | 'commit' | null>(null);
  const [error, setError] = useState('');

  const hasWarnings = useMemo(
    () => Boolean(preview?.rows.some((row) => row.warnings.length)),
    [preview],
  );

  const changeSource = (value: string, name = 'Bulk paste') => {
    setSourceText(value);
    setSourceName(name);
    setParsedRows([]);
    setPreview(null);
    setResult(null);
    setError('');
  };

  const readFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (file.size > 2_000_000) {
      setError('Import file is too large. Use a CSV/TSV/XLSX file no larger than 2 MB and 500 student rows.');
      return;
    }
    setBusy('file');
    setError('');
    try {
      const rows = await parseStudentImportFile(file);
      changeSource(serializeStudentImportRows(rows), file.name);
      pushToast(`${rows.length} row${rows.length === 1 ? '' : 's'} loaded from ${file.name}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The selected student import file could not be parsed.');
    } finally {
      setBusy(null);
    }
  };

  const parseRows = (): StudentImportRow[] | null => {
    try {
      const rows = parseStudentImportText(sourceText);
      setParsedRows(rows);
      setError('');
      return rows;
    } catch (reason) {
      setParsedRows([]);
      setPreview(null);
      setResult(null);
      const message = reason instanceof StudentImportParseError
        ? reason.problems.join(' ')
        : reason instanceof Error ? reason.message : 'Import data could not be parsed.';
      setError(message);
      return null;
    }
  };

  const runPreview = async () => {
    const rows = parseRows();
    if (!rows) return;
    setBusy('preview');
    setResult(null);
    try {
      const nextPreview = await educationStudentImportApi.preview(rows);
      setPreview(nextPreview);
      if (nextPreview.invalidRows) {
        pushToast(`${nextPreview.invalidRows} import row${nextPreview.invalidRows === 1 ? '' : 's'} need attention`, 'error');
      } else {
        pushToast(`${nextPreview.validRows} student row${nextPreview.validRows === 1 ? '' : 's'} ready to import`);
      }
    } catch (reason) {
      setPreview(null);
      setError(reason instanceof Error ? reason.message : 'Student import preview failed.');
    } finally {
      setBusy(null);
    }
  };

  const commit = async () => {
    if (!preview || preview.invalidRows || !parsedRows.length) return;
    setBusy('commit');
    setError('');
    try {
      const response = await educationStudentImportApi.commit(parsedRows);
      setPreview(response.preview);
      if (!response.committed || !response.result) {
        setResult(null);
        setError('The import changed after preview. Fix the reported rows and preview again before committing.');
        return;
      }
      setResult(response.result);
      pushToast(`${response.result.createdStudents} students imported`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Student import failed.');
    } finally {
      setBusy(null);
    }
  };

  return <div className="page student-import-page">
    <div className="page-heading page-heading--split">
      <div>
        <Link className="student-import-back" to="/education/students"><ArrowLeft /> Students</Link>
        <h2>Import students</h2>
        <p>Preview and atomically create Student profiles, optional identities, and optional Course/Batch/Agent enrollments in the active workspace.</p>
      </div>
      <div className="student-import-heading-actions">
        <Button variant="secondary" icon={Download} onClick={downloadTemplate}>Download CSV template</Button>
        <Button variant="secondary" icon={Upload} disabled={Boolean(busy)} onClick={() => fileInput.current?.click()}>{busy === 'file' ? 'Reading file…' : 'Choose CSV / Excel'}</Button>
        <input
          ref={fileInput}
          className="sr-only"
          type="file"
          accept=".csv,.tsv,.txt,.xlsx,text/csv,text/tab-separated-values,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(event) => void readFile(event)}
        />
      </div>
    </div>

    <div className="student-import-grid">
      <Card className="student-import-source">
        <div className="student-import-section-heading">
          <div><span className="student-import-icon"><ClipboardPaste /></span><div><h3>CSV, Excel, or spreadsheet paste</h3><p>Upload CSV/TSV/XLSX directly, or copy cells from Excel/Google Sheets including the header row and paste them below.</p></div></div>
          <Badge tone="neutral">{sourceName}</Badge>
        </div>
        <textarea
          aria-label="Student import data"
          value={sourceText}
          spellCheck={false}
          onChange={(event) => changeSource(event.target.value)}
          placeholder="student_id,name,email,identity_type,identifier,..."
        />
        <div className="student-import-help">
          <strong>Required:</strong> <code>student_id</code>, <code>name</code>. Optional provisioning columns include email, identity, Course, Batch, Agent, enrollment dates/status and JSON custom fields. Maximum 500 rows.
        </div>
        {error ? <div className="student-import-error" role="alert"><AlertTriangle />{error}</div> : null}
        <div className="student-import-actions">
          <Button icon={FileSpreadsheet} disabled={Boolean(busy)} onClick={() => void runPreview()}>{busy === 'preview' ? 'Validating…' : 'Preview import'}</Button>
          <Button
            icon={CheckCircle2}
            disabled={Boolean(busy) || !preview || preview.invalidRows > 0 || !parsedRows.length || Boolean(result)}
            onClick={() => void commit()}
          >{busy === 'commit' ? 'Importing…' : 'Commit import'}</Button>
        </div>
      </Card>

      <Card className="student-import-rules">
        <div className="student-import-section-heading"><div><span className="student-import-icon"><UsersRound /></span><div><h3>Validation rules</h3><p>The server revalidates every rule again at commit time.</p></div></div></div>
        <ul>
          <li>Student IDs must be valid and unique inside the workspace and import batch.</li>
          <li>Phone/login identities are normalized and cannot already belong to another Student.</li>
          <li>Course and Batch must exist, be active, and belong together.</li>
          <li>Agent must have Education purpose. Draft bots can be provisioned here, then activated after enrollment.</li>
          <li>Enrollment dates must be ordered and stay within selected Batch bounds.</li>
          <li>Pending identities do not grant messaging access until verified.</li>
          <li>If any row is invalid, Commit creates nothing.</li>
        </ul>
        <p className="student-import-api-note">LMS and other systems can use the same JSON Preview/Commit API, so external imports receive identical server-side validation.</p>
      </Card>
    </div>

    {result ? <Card className="student-import-success">
      <CheckCircle2 />
      <div><h3>Import completed</h3><p>{result.createdStudents} Students, {result.createdIdentities} identities and {result.createdEnrollments} enrollments were created atomically.</p></div>
      <Link className="button button--secondary button--md" to="/education/students">View students</Link>
    </Card> : null}

    {preview ? <Card className="student-import-preview">
      <div className="student-import-preview-heading">
        <div><h3>Server validation preview</h3><p>{preview.totalRows} total · {preview.validRows} valid · {preview.invalidRows} invalid{hasWarnings ? ' · warnings present' : ''}</p></div>
        <div className="student-import-summary-badges">
          <Badge tone="success">{preview.validRows} ready</Badge>
          {preview.invalidRows ? <Badge tone="danger">{preview.invalidRows} blocked</Badge> : null}
          {hasWarnings ? <Badge tone="warning">Warnings</Badge> : null}
        </div>
      </div>
      {preview.rows.length ? <div className="student-import-table-wrap"><table className="student-import-table">
        <thead><tr><th>Row</th><th>Status</th><th>Student</th><th>Identity</th><th>Enrollment</th><th>Validation</th></tr></thead>
        <tbody>{preview.rows.map((item) => <tr key={item.rowNumber} className={item.valid ? '' : 'is-invalid'}>
          <td>{item.rowNumber}</td>
          <td><Badge tone={item.valid ? 'success' : 'danger'}>{item.valid ? 'Valid' : 'Blocked'}</Badge></td>
          <td><strong>{item.row.studentNumber}</strong><small>{item.row.name}</small><small>{item.row.email || 'No email'}</small></td>
          <td><span>{identityLabel(item.row)}</span></td>
          <td><span>{enrollmentLabel(item.row)}</span></td>
          <td>{item.errors.map((message) => <div className="student-import-message is-error" key={message}>{message}</div>)}{item.warnings.map((message) => <div className="student-import-message is-warning" key={message}>{message}</div>)}{!item.errors.length && !item.warnings.length ? <span className="student-import-ok">Ready</span> : null}</td>
        </tr>)}</tbody>
      </table></div> : <EmptyState icon={FileSpreadsheet} title="No rows to preview" description="Add one or more student rows and preview again." />}
    </Card> : null}
  </div>;
}
