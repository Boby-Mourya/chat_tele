import { Bot, CircleAlert } from 'lucide-react';
import { Link } from 'react-router-dom';
import { helpApi } from '@/lib/help-api';
import type { HelpAiAnswer } from '@/lib/help-types';

export function HelpAiAnswerView({ result }: { result: HelpAiAnswer }) {
  return <section className="help-ai-answer" aria-live="polite">
    <div className="help-ai-answer__heading">{result.available ? <Bot /> : <CircleAlert />}<div><strong>{result.available ? 'Help AI answer' : 'Help AI unavailable'}</strong><small>Grounded only in official Northstar Help articles</small></div></div>
    <p className="help-ai-answer__text">{result.answer}</p>
    {result.citations.length ? <div className="help-ai-answer__citations"><strong>Sources</strong>{result.citations.map((item) => <Link key={item.id} to={`/help/articles/${item.slug}`} onClick={() => void helpApi.event('ai_citation_click', item.id)}>{item.title}</Link>)}</div> : null}
  </section>;
}
