import { Search, Sparkles, X } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { helpApi } from '@/lib/help-api';
import type { HelpSearchResult } from '@/lib/help-types';

export function HelpSearchBox({ initialQuery = '', autoFocus = false }: { initialQuery?: string; autoFocus?: boolean }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState(initialQuery);
  const [suggestions, setSuggestions] = useState<HelpSearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);

  useEffect(() => setQuery(initialQuery), [initialQuery]);
  useEffect(() => {
    const value = query.trim();
    if (value.length < 2) { setSuggestions([]); setOpen(false); return; }
    const current = ++generation.current; setLoading(true);
    const timer = window.setTimeout(() => {
      void helpApi.search(value, undefined, 1, 6).then((result) => {
        if (current !== generation.current) return;
        setSuggestions(result.items.slice(0, 6)); setOpen(true); setActive(-1);
      }).catch(() => { if (current === generation.current) setSuggestions([]); }).finally(() => { if (current === generation.current) setLoading(false); });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  function submit(event?: FormEvent) {
    event?.preventDefault(); const value = query.trim(); if (value.length < 2) return;
    setOpen(false); navigate(`/help/search?q=${encodeURIComponent(value)}`);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') { setOpen(false); return; }
    if (!open || !suggestions.length) return;
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive((value) => Math.min(suggestions.length - 1, value + 1)); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setActive((value) => Math.max(-1, value - 1)); }
    else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); const item = suggestions[active]; if (item) { void helpApi.event('search_click', item.id, query.trim()); setOpen(false); navigate(`/help/articles/${item.slug}`); } }
  }

  return <div className="help-search-wrap">
    <form className="help-search" role="search" onSubmit={submit}>
      <Search aria-hidden="true" /><label className="sr-only" htmlFor="help-search-input">Search Northstar Help</label>
      <input id="help-search-input" autoFocus={autoFocus} value={query} onChange={(event) => setQuery(event.target.value)} onFocus={() => { if (suggestions.length) setOpen(true); }} onKeyDown={onKeyDown} placeholder="Search Northstar Help…" autoComplete="off" aria-autocomplete="list" aria-expanded={open} aria-controls="help-search-suggestions" />
      {loading ? <span className="help-search__loading" aria-label="Searching" /> : query ? <button type="button" className="icon-button" aria-label="Clear search" onClick={() => { setQuery(''); setSuggestions([]); setOpen(false); }}><X /></button> : null}
      <button type="submit" className="button button--primary button--md">Search</button>
    </form>
    <Link className="help-ask-link" to={`/help/ask${query.trim() ? `?q=${encodeURIComponent(query.trim())}` : ''}`}><Sparkles /> Ask Help AI</Link>
    {open ? <div className="help-search__suggestions" id="help-search-suggestions" role="listbox">{suggestions.length ? suggestions.map((item, index) => <button key={item.id} type="button" role="option" aria-selected={index === active} className={index === active ? 'is-active' : ''} onMouseDown={(event) => event.preventDefault()} onClick={() => { void helpApi.event('search_click', item.id, query.trim()); setOpen(false); navigate(`/help/articles/${item.slug}`); }}><Search /><span><strong>{item.title}</strong><small>{item.categoryTitle}</small></span></button>) : <div className="help-search__no-suggestions">No direct matches. Press Search for more options.</div>}</div> : null}
  </div>;
}
