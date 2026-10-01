import { ArrowRight, CheckCircle2, GraduationCap, KeyRound, LifeBuoy, MailCheck, RefreshCw, ShieldCheck } from 'lucide-react';
import { useMemo, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Brand } from '@/components/brand';
import { Button, Field } from '@/components/ui';
import { educationAccessRequestApi } from '@/lib/education-access-request-api';
import {
  educationAccessRecoveryApi,
  type EducationRecoveryIdentityType,
} from '@/lib/education-access-recovery-api';
import './VerifyEmailPage.css';

type RecoveryStep = 'identify' | 'verify' | 'success';

const identityOptions: Array<{ value: EducationRecoveryIdentityType; label: string; placeholder: string }> = [
  { value: 'whatsapp', label: 'WhatsApp number', placeholder: '+919876543210' },
  { value: 'telegram', label: 'Telegram user ID', placeholder: '123456789' },
  { value: 'website_login', label: 'Website login', placeholder: 'student-login' },
];

export function EducationAccessRecoveryPage() {
  const [searchParams] = useSearchParams();
  const initialAgent = searchParams.get('agent')?.trim() ?? '';
  const [step, setStep] = useState<RecoveryStep>('identify');
  const [agentPublicId, setAgentPublicId] = useState(initialAgent);
  const [studentNumber, setStudentNumber] = useState('');
  const [email, setEmail] = useState('');
  const [identityType, setIdentityType] = useState<EducationRecoveryIdentityType>('whatsapp');
  const [identifier, setIdentifier] = useState('');
  const [requestId, setRequestId] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [supportNote, setSupportNote] = useState('');
  const [supportBusy, setSupportBusy] = useState(false);
  const [supportMessage, setSupportMessage] = useState('');
  const selectedIdentity = useMemo(
    () => identityOptions.find((item) => item.value === identityType) ?? identityOptions[0]!,
    [identityType],
  );

  const proofComplete = Boolean(
    agentPublicId.trim() && studentNumber.trim() && email.trim() && identifier.trim(),
  );

  const start = async (event: FormEvent) => {
    event.preventDefault();
    setMessage('');
    if (!proofComplete) {
      setMessage('Complete all fields to request a verification code.');
      return;
    }
    setBusy(true);
    try {
      const result = await educationAccessRecoveryApi.start({
        agentPublicId,
        studentNumber,
        email,
        identityType,
        identifier,
      });
      setRequestId(result.requestId);
      setCode('');
      setStep('verify');
      setMessage('If those details match an active enrollment, a verification code has been sent to the student email address.');
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : 'Unable to request education access recovery.');
    } finally {
      setBusy(false);
    }
  };

  const verify = async (event: FormEvent) => {
    event.preventDefault();
    setMessage('');
    if (!/^\d{6}$/.test(code.trim())) {
      setMessage('Enter the six-digit verification code.');
      return;
    }
    setBusy(true);
    try {
      await educationAccessRecoveryApi.verify(requestId, code);
      setStep('success');
      setMessage('Student identity verified. Return to the Education Agent and send the message again.');
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : 'Verification code is invalid or expired.');
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    setBusy(true);
    setMessage('');
    try {
      const result = await educationAccessRecoveryApi.start({
        agentPublicId,
        studentNumber,
        email,
        identityType,
        identifier,
      });
      setRequestId(result.requestId);
      setCode('');
      setMessage('If those details match an active enrollment, a new verification code has been sent.');
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : 'Unable to request another verification code.');
    } finally {
      setBusy(false);
    }
  };

  const requestSupport = async () => {
    setSupportMessage('');
    if (!proofComplete) {
      setSupportMessage('Complete the Agent, Student, email, and channel identity fields before requesting support.');
      return;
    }
    setSupportBusy(true);
    try {
      await educationAccessRequestApi.create({
        agentPublicId,
        studentNumber,
        email,
        identityType,
        identifier,
        message: supportNote || null,
      });
      setSupportMessage('Your request has been sent for academy review. This confirmation does not disclose whether the submitted enrollment details matched.');
      setSupportNote('');
    } catch (reason) {
      setSupportMessage(reason instanceof Error ? reason.message : 'Unable to request academy support.');
    } finally {
      setSupportBusy(false);
    }
  };

  return <div className="login-page verify-email-page">
    <section className="login-panel verify-email-panel">
      <div className="login-panel__inner verify-email-inner">
        <Brand />
        <div className="login-heading verify-email-heading">
          <span className="eyebrow-pill"><GraduationCap /> Student access</span>
          <h1>{step === 'success' ? 'Access verified' : step === 'verify' ? 'Enter verification code' : 'Recover Education access'}</h1>
          <p>{step === 'identify'
            ? 'Verify an enrolled student before linking this channel identity to private course access.'
            : step === 'verify'
              ? 'For privacy, the same confirmation is shown whether or not the submitted enrollment details matched.'
              : 'Your verified identity can now pass the normal Education authorization checks.'}</p>
        </div>

        {step === 'identify' ? <form className="login-form verify-email-form" onSubmit={(event) => void start(event)} noValidate>
          <Field label="Education Agent ID" htmlFor="education-agent-id">
            <input id="education-agent-id" value={agentPublicId} onChange={(event) => setAgentPublicId(event.target.value)} placeholder="agt_..." autoComplete="off" />
          </Field>
          <Field label="Student ID" htmlFor="education-student-id">
            <input id="education-student-id" value={studentNumber} onChange={(event) => setStudentNumber(event.target.value)} placeholder="STUDENT-001" autoComplete="off" />
          </Field>
          <Field label="Student email" htmlFor="education-student-email">
            <input id="education-student-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="student@example.com" autoComplete="email" />
          </Field>
          <Field label="Channel identity" htmlFor="education-identity-type">
            <select id="education-identity-type" value={identityType} onChange={(event) => { setIdentityType(event.target.value as EducationRecoveryIdentityType); setIdentifier(''); }}>
              {identityOptions.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}
            </select>
          </Field>
          <Field label={selectedIdentity.label} htmlFor="education-identity-value">
            <input id="education-identity-value" value={identifier} onChange={(event) => setIdentifier(event.target.value)} placeholder={selectedIdentity.placeholder} autoComplete="off" />
          </Field>
          {message ? <div className="form-error" role="alert">{message}</div> : null}
          <Button size="lg" type="submit" disabled={busy}>{busy ? <span className="button-spinner verification-spinner" /> : <MailCheck />} Send verification code <ArrowRight /></Button>
        </form> : null}

        {step === 'verify' ? <>
          <div className="verification-card">
            <span className="verification-card__icon"><KeyRound /></span>
            <div><strong>Check the enrolled email address</strong><p>{message}</p></div>
          </div>
          <form className="login-form verify-email-form" onSubmit={(event) => void verify(event)} noValidate>
            <Field label="Six-digit code" htmlFor="education-recovery-code">
              <input id="education-recovery-code" inputMode="numeric" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="000000" autoComplete="one-time-code" />
            </Field>
            {message && !message.startsWith('If those details') && !message.startsWith('If those') ? <div className="form-error" role="alert">{message}</div> : null}
            <Button size="lg" type="submit" disabled={busy}>{busy ? <span className="button-spinner verification-spinner" /> : <ShieldCheck />} Verify student identity</Button>
            <Button type="button" variant="secondary" disabled={busy} onClick={() => void resend()}><RefreshCw /> Request a new code</Button>
          </form>
          <button className="text-button" type="button" onClick={() => { setStep('identify'); setRequestId(''); setCode(''); setMessage(''); }}>Change details</button>
        </> : null}

        {step !== 'success' ? <div className="verification-card">
          <span className="verification-card__icon"><LifeBuoy /></span>
          <div style={{ width: '100%' }}>
            <strong>Still cannot verify?</strong>
            <p>Send these details to academy support for manual review. Support approval still returns through the normal Education authorization checks.</p>
            <Field label="Support note" htmlFor="education-support-note" hint="Optional. Do not include passwords or verification codes.">
              <textarea id="education-support-note" value={supportNote} maxLength={1000} onChange={(event) => setSupportNote(event.target.value)} placeholder="Describe the access problem" />
            </Field>
            {supportMessage ? <p role="status">{supportMessage}</p> : null}
            <Button type="button" variant="secondary" icon={LifeBuoy} disabled={supportBusy} onClick={() => void requestSupport()}>{supportBusy ? 'Sending…' : 'Request academy support'}</Button>
          </div>
        </div> : null}

        {step === 'success' ? <div className="verification-success">
          <span><CheckCircle2 /></span>
          <div><strong>Verification complete</strong><p>{message}</p></div>
          <Button size="lg" type="button" onClick={() => window.history.back()}>Return to Education Agent <ArrowRight /></Button>
        </div> : null}

        <div className="verify-email-actions"><Link className="text-button" to="/login">Northstar admin sign in</Link></div>
      </div>
    </section>
    <section className="login-story" aria-label="Student access security overview">
      <div className="login-glow login-glow--one" /><div className="login-glow login-glow--two" />
      <div className="story-copy"><span className="story-kicker"><span /> Education privacy</span><h2>Private course knowledge stays locked until enrollment is proven.</h2><p>Recovery verifies Student ID, enrolled email, active Agent assignment, Course, Batch and enrollment validity before linking a channel identity.</p></div>
      <div className="verification-story-card"><ShieldCheck /><div><strong>Recovery never bypasses authorization</strong><small>After verification, the normal Education access service still checks the Student, enrollment, Course, Batch and Agent before RAG can run.</small></div></div>
    </section>
  </div>;
}
