import { LiveMessageTime } from '@/components/live-message-time';
import { WhatsAppContactDetails } from '@/components/whatsapp-contact-details';
import { ProviderLogo, WhatsApp } from '@/components/provider-logo';
import { WhatsAppMessages } from '@/components/whatsapp-messages';
import { WhatsAppReplyComposer, type StructuredReply } from '@/components/whatsapp-reply-composer';
import { VisitorDetailsEditor } from '@/components/visitor-details-editor';
import { Archive, Bot, CheckCircle2, ChevronDown, CircleAlert, Clock3, ExternalLink, Filter, GraduationCap, Inbox, Info, Mail, MessageCircle, MoreHorizontal, Search, Send, Smile, Sparkles, UserRound } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useToast, useWorkspace } from '@/components/providers';
import { Badge, Button, EmptyState, PageLoader } from '@/components/ui';
import { api } from '@/lib/api';
import { apiErrorMessage } from '@/lib/api-error-message';
import { conversationApi } from '@/lib/conversation-api';
import { educationApi, type EducationBatch, type EducationCourse } from '@/lib/education-api';
import { educationEnrollmentApi, type EducationEnrollment } from '@/lib/education-enrollment-api';
import { educationStudentApi, type EducationStudent } from '@/lib/education-student-api';
import { leadStatuses } from '@/lib/lead-status';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import { usePollingApi } from '@/lib/use-polling-api';
import type { Conversation, ConversationState } from '@/types';
import './ConversationsPage.css';
import { WhatsAppTemplateComposer } from '@/components/whatsapp-template-composer';

type ChannelFilter = 'all' | 'widget' | 'api' | 'slack' | 'whatsapp';

export function ConversationsPage() {
  const [params, setParams] = useSearchParams();
  const { pushToast } = useToast();
  const { activeWorkspace } = useWorkspace();
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [filter, setFilter] = useState<'all' | ConversationState>('all');
  const [agentId, setAgentId] = useState('all');
  const [courseId, setCourseId] = useState('all');
  const [batchId, setBatchId] = useState('all');
  const [studentId, setStudentId] = useState('all');
  const [channel, setChannel] = useState<ChannelFilter>('all');
  const [reply, setReply] = useState('');
  const [sending, setSending] = useState(false);
  const [purposeFilter, setPurposeFilter] = useState<'all' | NonNullable<Conversation['purpose']>>('all');
  const [savingState, setSavingState] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const agents = useApi(() => api.agents.list(), [activeWorkspace?.id]);
  const filterAgent = agentId === 'all' ? null : agents.data?.find((item) => item.id === agentId) ?? null;
  const isEducationAgent = filterAgent?.purpose === 'education';

  const courses = useApi(
    () => isEducationAgent
      ? educationApi.courses.list({ status: 'active' })
      : Promise.resolve([] as EducationCourse[]),
    [activeWorkspace?.id, isEducationAgent],
  );
  const batches = useApi(
    () => isEducationAgent && courseId !== 'all'
      ? educationApi.batches.list({ courseId, status: 'active' })
      : Promise.resolve([] as EducationBatch[]),
    [activeWorkspace?.id, isEducationAgent, courseId],
  );
  const enrollments = useApi(
    () => isEducationAgent && courseId !== 'all' && batchId !== 'all'
      ? educationEnrollmentApi.list({ agentId, courseId, batchId })
      : Promise.resolve([] as EducationEnrollment[]),
    [activeWorkspace?.id, isEducationAgent, agentId, courseId, batchId],
  );
  const students = useApi(
    () => isEducationAgent && batchId !== 'all'
      ? educationStudentApi.list({ status: 'active' })
      : Promise.resolve([] as EducationStudent[]),
    [activeWorkspace?.id, isEducationAgent, batchId],
  );
  const eligibleStudentIds = useMemo(
    () => new Set((enrollments.data ?? []).map((item) => item.studentId)),
    [enrollments.data],
  );
  const eligibleStudents = useMemo(
    () => (students.data ?? []).filter((student) => eligibleStudentIds.has(student.id)),
    [students.data, eligibleStudentIds],
  );

  useEffect(() => {
    if (!isEducationAgent) {
      setCourseId('all');
      setBatchId('all');
      setStudentId('all');
    }
  }, [isEducationAgent]);

  useEffect(() => {
    if (
      studentId !== 'all'
      && !eligibleStudents.some((student) => student.id === studentId)
      && !students.loading
    ) {
      setStudentId('all');
    }
  }, [eligibleStudents, studentId, students.loading]);

  const result = usePollingApi(
    (signal) => conversationApi.list({
      purpose: purposeFilter === 'all' ? undefined : purposeFilter,
      agentId: agentId === 'all' ? undefined : agentId,
      educationScope: isEducationAgent,
      courseId: isEducationAgent && courseId !== 'all' ? courseId : undefined,
      batchId: isEducationAgent && batchId !== 'all' ? batchId : undefined,
      studentId: isEducationAgent && studentId !== 'all' ? studentId : undefined,
      channel: channel === 'all' ? undefined : channel,
      state: filter === 'all' ? undefined : filter,
      search: debouncedSearch || undefined,
      page: 1,
      pageSize: 100,
    }, signal),
    [activeWorkspace?.id, agentId, courseId, batchId, studentId, isEducationAgent, channel, filter, debouncedSearch, purposeFilter],
    2000,
  );

  const conversations = useMemo(() => result.data?.items ?? [], [result.data]);
  const showingList = params.get('view') === 'list';
  const selectedId = showingList ? undefined : params.get('selected') ?? conversations[0]?.id;
  const selectedSummary = conversations.find((item) => item.id === selectedId) ?? null;
  const detail = usePollingApi(
    (signal) => selectedId ? conversationApi.get(selectedId, signal) : Promise.resolve(null),
    [activeWorkspace?.id, selectedId],
    2000,
  );
  const selected = detail.data && detail.data.id === selectedId && detail.data.workspaceId === activeWorkspace?.id
    ? detail.data : selectedSummary;
  const selectedAgent = selected ? agents.data?.find((item) => item.id === selected.agentId) : null;
  useEffect(() => {
    if (showingList) return;
    const selectedParam = params.get('selected');
    if ((!selectedParam || !conversations.some((item) => item.id === selectedParam)) && conversations[0]) {
      setParams({ selected: conversations[0].id }, { replace: true });
    }
  }, [conversations, params, setParams, showingList]);

  const changeAgent = (nextAgentId: string) => {
    setAgentId(nextAgentId);
    setCourseId('all');
    setBatchId('all');
    setStudentId('all');
  };

  const changeCourse = (nextCourseId: string) => {
    setCourseId(nextCourseId);
    setBatchId('all');
    setStudentId('all');
  };

  const changeBatch = (nextBatchId: string) => {
    setBatchId(nextBatchId);
    setStudentId('all');
  };

  const setState = async (state: ConversationState, leadStatus?: string) => {
    if (!selected || savingState) return;
    setSavingState(true);
    try {
      if (state === 'resolved') {
        const saved = await conversationApi.resolve(selected.id, leadStatus);
        pushToast(saved.leadStatus === 'qualified'
          ? 'Conversation resolved and lead qualified. Automatic CRM sync requested; check View sync in Leads for delivery.'
          : 'Conversation resolved and lead saved in Leads');
      } else {
        await api.conversations.updateState(selected.id, state);
        pushToast(`Conversation marked ${state}`);
      }
      result.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Conversation could not be updated', 'error');
    } finally {
      setSavingState(false);
    }
  };

  const submitReply = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !reply.trim() || sending) return;
    setSending(true);
    try {
      await api.conversations.reply(selected.id, reply.trim());
      setReply('');
      await result.reload();
      pushToast(selected.channel === 'whatsapp' ? 'Reply queued for WhatsApp' : 'Reply sent');
    } catch {
      pushToast('Reply could not be sent', 'error');
    } finally {
      setSending(false);
    }
  };

  const sendStructuredReply = async (draft: StructuredReply) => {
    if (!selected || sending) return false;
    setSending(true);
    try {
      await api.conversations.reply(selected.id, draft.content, draft.messageFormat);
      await Promise.all([result.reload(), detail.reload()]);
      pushToast(`Formatted ${draft.messageFormat.type} reply queued for WhatsApp`);
      return true;
    } catch (error) {
      pushToast(apiErrorMessage(error, 'Reply could not be sent'), 'error');
      return false;
    } finally {
      setSending(false);
    }
  };

  if (result.loading && !result.data) return <PageLoader />;
  return <div className="inbox-page">
    <section className={`conversation-list-panel ${selected ? 'has-selection' : ''}`}>
      <div className="inbox-title"><div><h2>Conversations</h2><Badge tone="brand">{result.data?.total ?? 0} results</Badge></div><button className="icon-button" aria-label="Conversation actions"><MoreHorizontal /></button></div>
      <div className={`inbox-update-status${result.error ? " inbox-update-status--error" : ""}`} role="status">{result.error ? <>Could not refresh. Retrying automatically.<button type="button" onClick={result.reload}>Retry now</button></> : "Messages update automatically"}</div>
      <div className="inbox-tools">
        <div className="search-box"><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search conversations" /></div>
        <div className="filter-select"><Filter /><select value={agentId} onChange={(event) => changeAgent(event.target.value)} aria-label="Filter by agent"><option value="all">All agents</option>{agents.data?.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select><ChevronDown /></div>
        <div className="filter-select"><Filter /><select value={channel} onChange={(event) => setChannel(event.target.value as ChannelFilter)} aria-label="Filter by channel"><option value="all">All channels</option><option value="widget">Website</option><option value="whatsapp">WhatsApp</option><option value="slack">Slack</option><option value="api">API</option></select><ChevronDown /></div>
        <div className="filter-select"><GraduationCap /><select value={purposeFilter} onChange={(event) => setPurposeFilter(event.target.value as typeof purposeFilter)} aria-label="Filter by purpose"><option value="all">All purposes</option><option value="education">Education</option><option value="lead_generation">Lead generation</option><option value="support">Support</option></select><ChevronDown /></div>
        <div className="filter-select"><Filter /><select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)} aria-label="Filter conversations"><option value="all">All statuses</option><option value="open">Open</option><option value="escalated">Escalated</option><option value="resolved">Resolved</option></select><ChevronDown /></div>
      </div>
      {isEducationAgent ? <div className="education-inbox-filters" aria-label="Education conversation filters">
        <div className="education-inbox-filters__heading"><strong>Education scope</strong><span>Course → Batch → Student</span></div>
        <div className="filter-select"><Filter /><select value={courseId} onChange={(event) => changeCourse(event.target.value)} aria-label="Filter by course"><option value="all">All courses</option>{courses.data?.map((course) => <option key={course.id} value={course.id}>{course.code} · {course.name}</option>)}</select><ChevronDown /></div>
        <div className="filter-select"><Filter /><select value={batchId} disabled={courseId === 'all'} onChange={(event) => changeBatch(event.target.value)} aria-label="Filter by batch"><option value="all">All batches</option>{batches.data?.map((batch) => <option key={batch.id} value={batch.id}>{batch.code} · {batch.name}</option>)}</select><ChevronDown /></div>
        <div className="filter-select"><Filter /><select value={studentId} disabled={batchId === 'all'} onChange={(event) => setStudentId(event.target.value)} aria-label="Filter by student"><option value="all">All students</option>{eligibleStudents.map((student) => <option key={student.id} value={student.id}>{student.studentNumber} · {student.name}</option>)}</select><ChevronDown /></div>
      </div> : null}
      <div className="conversation-items" role="region" aria-label="Conversation list" tabIndex={0}>{conversations.map((conversation) => <button key={conversation.id} className={`conversation-item ${conversation.id === selectedId ? 'is-active' : ''}`} onClick={() => setParams({ selected: conversation.id })}><span className="mini-avatar conversation-list-avatar">{conversation.visitorName.charAt(0)}<ProviderLogo provider={conversation.channel} size={16} className="conversation-channel-logo" /></span><span className="conversation-item__copy"><span><strong>{conversation.visitorName}</strong><time>{relativeTime(conversation.updatedAt)}</time></span><small>{conversation.preview}</small><span className="conversation-item__tags"><Badge tone={conversation.state === 'escalated' ? 'danger' : conversation.state === 'resolved' ? 'neutral' : 'brand'}>{conversation.state}</Badge>{conversation.purpose === 'education' || agents.data?.find((agent) => agent.id === conversation.agentId)?.purpose === 'education' ? <Badge tone="purple">Education</Badge> : null}<em className={`sentiment sentiment--${conversation.sentiment}`}>{conversation.sentiment}</em></span></span>{conversation.unread ? <i className="unread-count">{conversation.unread}</i> : null}</button>)}</div>
      {!conversations.length ? <EmptyState icon={Inbox} title="No conversations here" description={isEducationAgent ? 'Try another Course, Batch, Student, channel, status, or search.' : 'Try another workspace, agent, channel, status, or search.'} /> : null}
    </section>
    {selected ? <ConversationDetail key={selected.id} savingState={savingState} onVisitorSaved={() => { result.reload(); detail.reload(); }} conversation={selected} agentName={selectedAgent?.name ?? 'Assigned agent'} workspaceName={activeWorkspace?.name ?? 'Workspace'} reply={reply} setReply={setReply} submitReply={submitReply} sendStructuredReply={sendStructuredReply} setState={setState} purpose={selected.purpose ?? selectedAgent?.purpose} onBack={() => setParams({ view: 'list' })} sending={sending} /> : <div className="conversation-empty"><MessageCircle /><h3>Select a conversation</h3><p>Read the full context, step in, or mark it resolved.</p></div>}
  </div>;
}

function ConversationDetail({ savingState, onVisitorSaved, conversation, agentName, workspaceName, reply, setReply, submitReply, sendStructuredReply, setState, purpose, onBack, sending }: { savingState: boolean; onVisitorSaved: () => void; conversation: Conversation; agentName: string; workspaceName: string; reply: string; setReply: (value: string) => void; submitReply: (event: FormEvent) => void; sendStructuredReply: (draft: StructuredReply) => Promise<boolean>; setState: (state: ConversationState, leadStatus?: string) => Promise<void>; purpose: Conversation['purpose']; onBack: () => void; sending: boolean }) {
  const [leadStatus, setLeadStatus] = useState(conversation.leadStatus ?? 'new');
  useEffect(() => { setLeadStatus(conversation.leadStatus ?? 'new'); }, [conversation.id, conversation.leadStatus]);
  const [showContactDetails, setShowContactDetails] = useState(false);
  const isWhatsApp = conversation.channel === 'whatsapp';
  const isEducation = purpose === 'education';
  const canEditLeadStatus = !isEducation && conversation.canUpdateLeadStatus === true;
  const statuses = leadStatuses.includes(leadStatus) ? leadStatuses : [leadStatus, ...leadStatuses];
  const statusChanged = leadStatus !== (conversation.leadStatus ?? 'new');
  const resolve = () => void setState('resolved', canEditLeadStatus ? leadStatus : undefined);
  const threadRef = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const [hasNewMessages, setHasNewMessages] = useState(false);
  const latest = conversation.messages.at(-1);
  const jumpToLatest = useCallback(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
    followLatest.current = true;
    setHasNewMessages(false);
  }, [setHasNewMessages]);
  useLayoutEffect(() => {
    if (followLatest.current) jumpToLatest();
    else setHasNewMessages(true);
  }, [latest?.id, latest?.content, conversation.messages.length, jumpToLatest]);
  useEffect(() => {
    const thread = threadRef.current;
    if (!thread || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      if (followLatest.current) thread.scrollTop = thread.scrollHeight;
    });
    observer.observe(thread);
    return () => observer.disconnect();
  }, []);
  return <section className={`conversation-detail ${isWhatsApp ? 'conversation-detail--whatsapp' : ''} ${showContactDetails ? 'conversation-detail--show-info' : ''}`} onKeyDown={event => { if (event.key === 'Escape') setShowContactDetails(false); }}>
    <header className="conversation-detail__header"><button className="mobile-back" aria-label="Back to conversation list" onClick={onBack}>←</button><span className="mini-avatar mini-avatar--lg">{conversation.visitorName.charAt(0)}</span><div><h3>{conversation.visitorName}</h3><p>{isWhatsApp ? <WhatsApp size={16} /> : null} {workspaceName} · {agentName} · {isWhatsApp ? 'WhatsApp' : conversation.channel}</p></div><div className="conversation-actions"><button type="button" className="conversation-details-toggle" aria-label={showContactDetails ? 'Close contact details' : 'Contact details'} aria-expanded={showContactDetails} onClick={() => setShowContactDetails(!showContactDetails)}><Info /></button>{isEducation ? <span className="education-conversation-label"><GraduationCap aria-hidden="true" /> Education chat</span> : <><label className="conversation-lead-status"><span>Lead status</span><span className="conversation-lead-status__field"><select aria-label="Lead status" value={leadStatus} disabled={!canEditLeadStatus || savingState} onChange={(event) => setLeadStatus(event.target.value)} title={canEditLeadStatus ? "Saved when you resolve or save status. Qualified leads sync automatically to your connected CRM." : "You do not have permission to update lead status"}>{statuses.map((status) => <option key={status} value={status}>{status.charAt(0).toUpperCase() + status.slice(1)}</option>)}</select><ChevronDown aria-hidden="true" /></span></label><Button variant="secondary" size="sm" icon={Archive}>Archive</Button>{conversation.state !== 'resolved' || statusChanged ? <Button size="sm" icon={CheckCircle2} disabled={savingState} onClick={resolve}>{savingState ? 'Saving...' : conversation.state === 'resolved' ? 'Save status' : 'Resolve'}</Button> : <Button variant="secondary" size="sm" disabled={savingState} onClick={() => void setState('open')}>Reopen</Button>}</>}</div></header>
    <div className="conversation-layout"><div className="conversation-thread" ref={threadRef} role="log" aria-label="Conversation messages" aria-live="polite" aria-relevant="additions text" tabIndex={0} onScroll={(event) => {
      const thread = event.currentTarget;
      followLatest.current = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 48;
      if (followLatest.current) setHasNewMessages(false);
    }}>{!isWhatsApp ? <><div className="thread-notice"><Sparkles /> <span><strong>{isEducation ? 'Student learning conversation' : conversation.state === 'escalated' ? 'Human attention requested' : 'Northstar handled this conversation'}</strong><small>{isEducation ? 'Kept in Education. This chat does not create a lead or sync to a sales CRM.' : 'The complete AI context is available below.'}</small></span></div><div className="message-day"><span>{new Date(conversation.startedAt).toLocaleDateString('en', { month: 'long', day: 'numeric' })}</span></div></> : null}
      {isWhatsApp ? <WhatsAppMessages messages={conversation.messages} visitorName={conversation.visitorName} agentName={agentName} /> : conversation.messages.map((message) => <div className={`inbox-message inbox-message--${message.role}`} key={message.id}>{message.role === 'user' ? <span className="message-avatar message-avatar--visitor">{conversation.visitorName.charAt(0)}</span> : <span className="message-avatar"><>{message.role === 'agent' ? <UserRound /> : <Sparkles />}</></span>}<div><span className="message-author">{message.role === 'user' ? conversation.visitorName : message.role === 'agent' ? 'You' : 'Northstar AI'} <time>{new Date(message.createdAt).toLocaleTimeString('en', { hour: 'numeric', minute: '2-digit' })}</time></span><div className="message-bubble">{message.content}</div>{message.citations?.map((citation) => <button className="citation-chip" key={citation.title}><ExternalLink />{citation.title}</button>)}</div></div>)}
    </div>{hasNewMessages ? <button type="button" className="conversation-new-messages" onClick={jumpToLatest}>New messages <ChevronDown aria-hidden="true" /></button> : null}{conversation.channel === 'whatsapp' ? <div className="conversation-reply-tools"><WhatsAppTemplateComposer key={conversation.id} agentId={conversation.agentId} conversationId={conversation.id} purpose={purpose} onQueued={onVisitorSaved} /></div> : null}{isWhatsApp ? <WhatsAppReplyComposer sending={sending} onSend={sendStructuredReply} /> : <form className="human-composer" onSubmit={(event) => void submitReply(event)}><textarea value={reply} onChange={(event) => setReply(event.target.value)} placeholder="Reply as a teammate…" rows={2} disabled={sending} onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') event.currentTarget.form?.requestSubmit(); }} /><div><span><button type="button" aria-label="Insert emoji"><Smile /></button><small>⌘ Enter to send</small></span><Button size="sm" icon={Send} disabled={!reply.trim() || sending}>{sending ? 'Sending…' : 'Send'}</Button></div></form>}</div>
    <aside className="visitor-panel">{isWhatsApp ? <WhatsAppContactDetails contact={conversation.whatsappContact} /> : null}<div className="visitor-profile"><span className="mini-avatar mini-avatar--xl">{conversation.visitorName.charAt(0)}</span><h3>{conversation.visitorName}</h3><Badge tone={conversation.sentiment === 'positive' ? 'success' : conversation.sentiment === 'negative' ? 'danger' : 'neutral'}>{conversation.sentiment} sentiment</Badge></div><dl><div><dt><Mail /> Email</dt><dd>{conversation.visitorEmail ?? 'Not provided'}</dd></div><div><dt><Bot /> Workspace</dt><dd>{workspaceName}</dd></div><div><dt><Bot /> Agent</dt><dd>{agentName}</dd></div><div><dt><ProviderLogo provider={conversation.channel} /> Channel</dt><dd>{isWhatsApp ? 'WhatsApp' : conversation.channel}</dd></div><div><dt><Clock3 /> Last message</dt><dd><LiveMessageTime value={conversation.messages.at(-1)?.createdAt ?? conversation.updatedAt} /></dd></div><div><dt><Clock3 /> Conversation started</dt><dd><LiveMessageTime value={conversation.startedAt} /></dd></div><div><dt><CircleAlert /> Status</dt><dd className="capitalize">{conversation.state}</dd></div></dl><VisitorDetailsEditor key={conversation.id} conversation={conversation} onSaved={onVisitorSaved} /><div className="conversation-summary"><strong><Sparkles /> AI summary</strong><p>{conversation.preview} The visitor may benefit from a short, direct follow-up.</p></div></aside>
  </section>;
}
