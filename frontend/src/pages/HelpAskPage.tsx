import { Sparkles } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { HelpAiAnswerView } from '@/components/help/HelpAiAnswer';
import { HelpBreadcrumbs } from '@/components/help/HelpBreadcrumbs';
import { Button, Card, Field } from '@/components/ui';
import { helpApi } from '@/lib/help-api';
import type { HelpAiAnswer } from '@/lib/help-types';

export function HelpAskPage() {
  const [params] = useSearchParams(); const [question, setQuestion] = useState(params.get('q') ?? ''); const [result, setResult] = useState<HelpAiAnswer | null>(null); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  async function submit(event: FormEvent) { event.preventDefault(); const value = question.trim(); if (value.length < 2) return; setLoading(true); setError(''); try { setResult(await helpApi.ask(value)); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Help AI is unavailable'); } finally { setLoading(false); } }
  return <div className="page help-page"><HelpBreadcrumbs items={[{ label: 'Help', to: '/help' }, { label: 'Ask Help AI' }]} /><section className="help-ai-page"><div className="help-ai-page__intro"><span><Sparkles /></span><div><h2>Ask Help AI</h2><p>Ask a product question. Answers are grounded only in official Northstar Help articles visible to your role.</p></div></div><Card className="help-ai-form"><form onSubmit={submit}><Field label="What do you need help with?" htmlFor="help-ai-question" error={error || undefined}><textarea id="help-ai-question" rows={5} maxLength={2000} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="For example: Why is my knowledge source stuck processing?" /></Field><div className="help-ai-form__actions"><Button type="submit" icon={Sparkles} disabled={loading || question.trim().length < 2}>{loading ? 'Checking Help…' : 'Ask Help AI'}</Button></div></form></Card>{result ? <HelpAiAnswerView result={result} /> : null}</section></div>;
}
