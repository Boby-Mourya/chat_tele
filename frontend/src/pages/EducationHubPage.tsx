import { ArrowLeft, ArrowRight, BookOpen, GraduationCap, UsersRound } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { DashboardTrend, DashboardWelcome, LearningTip } from '@/components/academy-dashboard';
import { Badge, Button, EmptyState } from '@/components/ui';
import { useAuth, useWorkspace } from '@/components/providers';
import { educationApi } from '@/lib/education-api';
import { educationEnrollmentApi } from '@/lib/education-enrollment-api';
import { educationNavigation, visibleNavigation } from '@/lib/materialm-navigation';
import { navigationIcons } from '@/components/materialm/navigation-icons';
import { useApi } from '@/lib/use-api';

export function EducationHubPage() {
  const { activeWorkspace } = useWorkspace();
  const { session } = useAuth();
  const courses = useApi(() => educationApi.courses.list());
  const enrollments = useApi(() => educationEnrollmentApi.list());
  const [filter, setFilter] = useState('all');
  const [selected, setSelected] = useState(0);
  const [period, setPeriod] = useState(7);
  const [metric, setMetric] = useState<'enrollments' | 'courses'>('enrollments');
  const records = courses.data ?? [];
  const registrations = enrollments.data ?? [];
  const featured = records[selected % Math.max(records.length, 1)];
  const shown = filter === 'newest' ? [...records].sort((a, b) => b.createdAt.localeCompare(a.createdAt)) : records.filter((course) => filter === 'all' || course.status === filter);
  const sections = visibleNavigation(educationNavigation, { role: session?.user.role, permissions: activeWorkspace?.permissions }).filter((item) => item.to !== '/education');
  const observations = metric === 'enrollments' ? registrations : records;
  const now = new Date();
  const chart = Array.from({ length: period }, (_, index) => {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() - period + index + 1);
    const next = new Date(day); next.setDate(next.getDate() + 1);
    return { label: day.toLocaleDateString('en', period === 7 ? { weekday: 'short' } : { month: 'short', day: 'numeric' }), value: observations.filter((item) => new Date(item.createdAt) >= day && new Date(item.createdAt) < next).length };
  });
  return <div className="academy-education-dashboard">
    <div className="academy-dashboard">
      <div className="academy-dashboard__primary">
        <DashboardWelcome name={session?.user.name?.split(/\s+/)[0] || 'there'}>It’s good to see you and your academy growing.</DashboardWelcome>
        {featured ? <div className="academy-continue"><Link className="academy-continue__record" aria-label={`Continue with ${featured.name}`} to={`/education/courses?search=${encodeURIComponent(featured.code)}`}><span className="academy-record-icon"><GraduationCap /></span><span><strong>{featured.name}</strong><small>{featured.code}</small></span><Badge tone={featured.status === 'active' ? 'success' : 'neutral'}>{featured.status}</Badge><span className="button button--primary">Continue</span></Link><div className="academy-carousel-actions"><button aria-label="Previous course" disabled={records.length < 2} onClick={() => setSelected((value) => (value + records.length - 1) % records.length)}><ArrowLeft /></button><button aria-label="Next course" disabled={records.length < 2} onClick={() => setSelected((value) => (value + 1) % records.length)}><ArrowRight /></button></div></div> : null}
        <section className="academy-records"><div className="academy-section-heading"><h3>Courses</h3><Link to="/education/courses">Manage courses <ArrowRight /></Link></div>
          <div className="academy-tabs" role="group" aria-label="Filter academy courses">{[['all', 'All courses'], ['newest', 'The newest'], ['active', 'Active'], ['archived', 'Archived']].map(([id, label]) => <button key={id} aria-pressed={filter === id} className={filter === id ? 'is-active' : ''} onClick={() => setFilter(id!)}>{label}</button>)}</div>
          {courses.error ? <EmptyState icon={BookOpen} title="Courses are unavailable" description={courses.error} action={<Button onClick={courses.reload}>Try again</Button>} /> : courses.loading ? <p className="academy-empty" role="status">Loading your courses…</p> : shown.length ? <div className="academy-record-list">{shown.map((course) => <article className="academy-record academy-record--course" key={course.id}><span className="academy-record-icon"><BookOpen /></span><div className="academy-record__name"><h4>{course.name}</h4><p>{course.code}{course.description ? ` · ${course.description}` : ''}</p></div><span className="academy-record__metric" title="Active enrollments"><UsersRound />{enrollments.data ? registrations.filter((entry) => entry.courseId === course.id && entry.status === 'active').length : '—'}</span><Badge tone={course.status === 'active' ? 'success' : 'neutral'}>{course.status}</Badge><Link className="button button--secondary" to={`/education/courses?search=${encodeURIComponent(course.code)}`} aria-label={`View course ${course.name}`}>View course</Link></article>)}</div> : <EmptyState icon={BookOpen} title={records.length ? 'No courses match this filter' : 'Your next chapter starts here'} description="Create a course, add students, and connect them to an education bot." action={<Link className="button button--primary" to="/education/courses">Open courses</Link>} />}
        </section>
      </div>
      <aside className="academy-dashboard__secondary">
        <div className="academy-big-stats"><div><strong>{enrollments.data ? registrations.filter((item) => item.status === 'graduated').length : '—'}</strong><span>Enrollments<br />completed</span></div><div><strong>{enrollments.data ? registrations.filter((item) => item.status === 'active').length : '—'}</strong><span>Enrollments<br />active</span></div></div>
        <section className="academy-statistics"><h3>Your statistics</h3><div className="academy-statistics__controls"><div className="academy-tabs" role="group" aria-label="Academy chart metric"><button className={metric === 'enrollments' ? 'is-active' : ''} aria-pressed={metric === 'enrollments'} onClick={() => setMetric('enrollments')}>Enrollments</button><button className={metric === 'courses' ? 'is-active' : ''} aria-pressed={metric === 'courses'} onClick={() => setMetric('courses')}>Courses</button></div><select aria-label="Academy chart period" value={period} onChange={(event) => setPeriod(Number(event.target.value))}><option value="7">Weekly</option><option value="30">Monthly</option></select></div>
          {(metric === 'enrollments' ? enrollments.error : courses.error) ? <EmptyState icon={UsersRound} title="Statistics are unavailable" description={(metric === 'enrollments' ? enrollments.error : courses.error)!} action={<Button onClick={metric === 'enrollments' ? enrollments.reload : courses.reload}>Try again</Button>} /> : (metric === 'enrollments' ? enrollments.loading : courses.loading) ? <p role="status" className="academy-empty">Loading statistics…</p> : <DashboardTrend data={chart} label={`${metric === 'enrollments' ? 'Enrollments' : 'Courses'} created in the last ${period} days`} />}
        </section>
        <LearningTip description="Bring your students together. Enroll them individually or import a whole class." to="/education/enrollments" action="Manage enrollments" />
      </aside>
    </div>
    <section className="academy-tools"><div className="academy-section-heading"><h3>Education workspace</h3><p>Everything you need to run your academy.</p></div><div className="mm-module-grid">{sections.map((item) => { const Icon = navigationIcons[item.icon]; return <Link to={item.to} key={item.to} className="mm-module-card"><span className="mm-module-card__icon"><Icon /></span><h3>{item.label}</h3><p>{item.description}</p><span className="mm-module-card__action">Open {item.label.toLowerCase()} <ArrowRight /></span></Link>; })}</div></section>
  </div>;
}
