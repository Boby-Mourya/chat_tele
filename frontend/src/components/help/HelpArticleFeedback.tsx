import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { useState } from 'react';
import { useToast } from '@/components/providers';
import { Button, Card, Field } from '@/components/ui';
import { helpApi } from '@/lib/help-api';
import type { HelpFeedbackReason } from '@/lib/help-types';

export function HelpArticleFeedback({ articleId }: { articleId: string }) {
  const { pushToast } = useToast();
  const [choice, setChoice] = useState<boolean | null>(null); const [reason, setReason] = useState<HelpFeedbackReason>('missing_steps'); const [comment, setComment] = useState(''); const [saving, setSaving] = useState(false); const [submitted, setSubmitted] = useState(false);
  async function send(helpful: boolean) {
    setChoice(helpful);
    if (!helpful) return;
    setSaving(true); try { await helpApi.feedback(articleId, true); setSubmitted(true); pushToast('Thanks for your feedback'); } catch (error) { pushToast(error instanceof Error ? error.message : 'Unable to save feedback', 'error'); } finally { setSaving(false); }
  }
  async function sendNegative() {
    setSaving(true); try { await helpApi.feedback(articleId, false, reason, comment.trim() || undefined); setSubmitted(true); pushToast('Thanks — your feedback helps improve Help'); } catch (error) { pushToast(error instanceof Error ? error.message : 'Unable to save feedback', 'error'); } finally { setSaving(false); }
  }
  return <Card className="help-feedback"><h3>{submitted ? 'Thanks for the feedback.' : 'Was this helpful?'}</h3>{!submitted ? <><div className="help-feedback__buttons"><Button variant={choice === true ? 'primary' : 'secondary'} icon={ThumbsUp} disabled={saving} onClick={() => void send(true)}>Yes</Button><Button variant={choice === false ? 'primary' : 'secondary'} icon={ThumbsDown} disabled={saving} onClick={() => setChoice(false)}>No</Button></div>{choice === false ? <div className="help-feedback__details"><Field label="What was missing?"><select value={reason} onChange={(event) => setReason(event.target.value as HelpFeedbackReason)}><option value="missing_steps">Missing steps</option><option value="incorrect">Incorrect</option><option value="outdated">Outdated</option><option value="hard_to_understand">Hard to understand</option><option value="did_not_solve_problem">Did not solve my problem</option><option value="other">Other</option></select></Field><Field label="Optional comment"><textarea rows={3} maxLength={1000} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Tell us what would make this guide better." /></Field><Button disabled={saving} onClick={() => void sendNegative()}>{saving ? 'Sending…' : 'Send feedback'}</Button></div> : null}</> : <p>Your response has been recorded.</p>}</Card>;
}
