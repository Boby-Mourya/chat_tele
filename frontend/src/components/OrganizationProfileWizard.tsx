import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui';
import { emptyProfile, setupApi, type OnboardingState, type OrganizationProfile } from '@/lib/setup-api';

export function OrganizationProfileWizard({ initial, onSaved }: {
  initial: OnboardingState; onSaved: (state: OnboardingState, completed: boolean) => void;
}) {
  const [profile, setProfile] = useState<OrganizationProfile>({ ...emptyProfile, ...initial.profile, ...initial.draft });
  const [revision, setRevision] = useState(initial.revision);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const update = <K extends keyof OrganizationProfile>(key: K, value: OrganizationProfile[K]) => setProfile((old) => ({ ...old, [key]: value }));
  async function save(complete: boolean, advance = false) {
    setBusy(true); setError(''); setMessage('');
    try {
      const next = await setupApi.profile(profile, revision, complete);
      setRevision(next.revision); setMessage(complete ? 'Profile completed' : 'Draft saved. You can resume after signing in again.');
      onSaved(next, complete);
      if (!complete && advance) setStep((current) => Math.min(current + 1, 2));
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Profile could not be saved'); }
    finally { setBusy(false); }
  }
  function submit(event: FormEvent) { event.preventDefault(); void save(step === 2, true); }
  function text(key: keyof OrganizationProfile, label: string, required = true, type = 'text') {
    return <label className="setup-field" key={key}>{label}{required ? ' *' : ''}
      <input type={type} value={String(profile[key] ?? '')} required={required} maxLength={key === 'contactEmail' ? 320 : 160}
        onChange={(event) => update(key, event.target.value as OrganizationProfile[typeof key])} />
    </label>;
  }
  return <section className="setup-page" aria-labelledby="setup-heading">
    <header><p className="setup-eyebrow">Organization setup · {step + 1} of 3</p><h1 id="setup-heading">Tell us about your institution or business</h1>
      <p>Your account is ready. Complete the required profile before opening your workspace. No payment or integration is required.</p></header>
    <nav className="setup-steps" aria-label="Profile steps">{['Organization', 'Your work', 'Workspace'].map((label, index) =>
      <button type="button" key={label} aria-current={step === index ? 'step' : undefined} onClick={() => setStep(index)} disabled={busy}>{index + 1}. {label}</button>)}</nav>
    <form onSubmit={submit}>
      {step === 0 ? <div className="setup-grid">
        <label className="setup-field">Organization type *<select value={profile.organizationType} onChange={(event) => update('organizationType', event.target.value as OrganizationProfile['organizationType'])}>
          <option value="institution">Institution / independent educator</option><option value="business">Business / sole proprietor</option></select></label>
        {text('displayName', 'Display name')}{text('organizationSubtype', profile.organizationType === 'institution' ? 'Institution type' : 'Business type')}
        {text('category', 'Category / industry')}{text('country', 'Country')}{text('city', 'City / region', false)}
        {text('contactName', 'Primary contact')}{text('contactEmail', 'Contact email', true, 'email')}{text('phone', 'Phone', false, 'tel')}
        <label className="setup-field">Website (optional)<input type="url" value={profile.website ?? ''} maxLength={2048} onChange={(event) => update('website', event.target.value || null)} /></label>
      </div> : null}
      {step === 1 ? <div className="setup-grid">
        {profile.organizationType === 'institution' ? <>
          <label className="setup-field setup-wide">Teaching / training focus *<textarea required maxLength={1000} value={profile.teachingFocus} onChange={(event) => update('teachingFocus', event.target.value)} /></label>
          <label className="setup-field setup-wide">Program categories (one per line) *<textarea required value={profile.programCategories.join('\n')} onChange={(event) => update('programCategories', event.target.value.split('\n'))} /></label>
          <label className="setup-field">Learner volume *<select required value={profile.learnerVolumeBand} onChange={(event) => update('learnerVolumeBand', event.target.value)}><option value="">Select a range</option>{['1–50', '51–200', '201–1000', '1001–5000', '5001+'].map((value) => <option key={value}>{value}</option>)}</select></label>
          <p>Student data and course enrollment are configured separately. Education stays independent from leads and CRM.</p>
        </> : <>
          <label className="setup-field setup-wide">Products / services *<textarea required maxLength={2000} value={profile.description} onChange={(event) => update('description', event.target.value)} /></label>
          <label className="setup-field">Team size *<select required value={profile.teamSizeBand} onChange={(event) => update('teamSizeBand', event.target.value)}><option value="">Select a range</option>{['1', '2–10', '11–50', '51–200', '201+'].map((value) => <option key={value}>{value}</option>)}</select></label>
          <fieldset><legend>Intended use *</legend>{(['support', 'lead_generation'] as const).map((value) => <label className="setup-check" key={value}><input type="checkbox" checked={profile.useCases.includes(value)} onChange={(event) => update('useCases', event.target.checked ? [...profile.useCases, value] : profile.useCases.filter((item) => item !== value))} />{value === 'support' ? 'Customer support' : 'Lead generation'}</label>)}</fieldset>
        </>}
      </div> : null}
      {step === 2 ? <div className="setup-grid">{text('workspaceName', 'Initial workspace name')}
        <label className="setup-field">Workspace slug *<input required pattern="[a-z0-9]+(-[a-z0-9]+)*" minLength={2} maxLength={80} value={profile.workspaceSlug} onChange={(event) => update('workspaceSlug', event.target.value.toLowerCase())} /></label>
        {text('timezone', 'Timezone (for example Asia/Kolkata)')}{text('preferredLanguage', 'Preferred language')}
        <label className="setup-field">Date format<select value={profile.dateFormat} onChange={(event) => update('dateFormat', event.target.value as OrganizationProfile['dateFormat'])}>{['DD/MM/YYYY', 'MM/DD/YYYY', 'YYYY-MM-DD'].map((value) => <option key={value}>{value}</option>)}</select></label>
        <p className="setup-wide">You receive free starter tutorials and templates. Your plan limits appear in the dashboard. Creating this profile does not connect a provider, purchase a subscription, or grant a student access to a course.</p>
      </div> : null}
      {error ? <p className="setup-error" role="alert">{error}</p> : null}{message ? <p role="status">{message}</p> : null}
      <footer className="setup-actions"><Button type="button" variant="secondary" disabled={busy} onClick={() => void save(false)}>Save progress</Button>
        {step > 0 ? <Button type="button" variant="secondary" disabled={busy} onClick={() => setStep(step - 1)}>Back</Button> : null}
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : step === 2 ? 'Complete profile and open dashboard' : 'Save and continue'}</Button></footer>
    </form>
  </section>;
}
