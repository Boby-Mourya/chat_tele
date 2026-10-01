import { lazy, Suspense } from 'react';
import { PageErrorBoundary } from '@/components/PageErrorBoundary';
import { PageLoader } from '@/components/ui';
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { MaterialmAppShell } from '@/components/materialm/MaterialmAppShell';
import { EducationLayout } from '@/components/materialm/EducationLayout';
import { useAuth } from '@/components/providers';
import { OrganizationProfilePage, WorkspaceSetupGate, WorkspaceStarterPanel } from '@/components/WorkspaceSetup';

const AgentBuilderPage = lazy(() => import('@/pages/AgentBuilderPage').then((module) => ({ default: module.AgentBuilderPage })));
const AgentsPage = lazy(() => import('@/pages/AgentsPage').then((module) => ({ default: module.AgentsPage })));
const AnalyticsPage = lazy(() => import('@/pages/AnalyticsPage').then((module) => ({ default: module.AnalyticsPage })));
const AuditPage = lazy(() => import('@/pages/AuditPage').then((module) => ({ default: module.AuditPage })));
const BatchesPage = lazy(() => import('@/pages/BatchesPage').then((module) => ({ default: module.BatchesPage })));
const BotWorkflowBuilderPage = lazy(() => import('@/pages/BotWorkflowBuilderPage').then((module) => ({ default: module.BotWorkflowBuilderPage })));
const ConversationsPage = lazy(() => import('@/pages/ConversationsPage').then((module) => ({ default: module.ConversationsPage })));
const CoursesPage = lazy(() => import('@/pages/CoursesPage').then((module) => ({ default: module.CoursesPage })));
const CourseKnowledgePage = lazy(() => import('@/features/knowledge').then((module) => ({ default: module.CourseKnowledgePage })));
const CRMWorkflowPage = lazy(() => import('@/pages/CRMWorkflowPage').then((module) => ({ default: module.CRMWorkflowPage })));
const DeployPage = lazy(() => import('@/pages/DeployPage').then((module) => ({ default: module.DeployPage })));
const EducationAccessRecoveryPage = lazy(() => import('@/pages/EducationAccessRecoveryPage').then((module) => ({ default: module.EducationAccessRecoveryPage })));
const EducationAccessRequestsPage = lazy(() => import('@/pages/EducationAccessRequestsPage').then((module) => ({ default: module.EducationAccessRequestsPage })));
const EducationActivityPage = lazy(() => import('@/pages/EducationActivityPage').then((module) => ({ default: module.EducationActivityPage })));
const EducationEnrollmentsPage = lazy(() => import('@/pages/EducationEnrollmentsPage').then((module) => ({ default: module.EducationEnrollmentsPage })));
const EducationHubPage = lazy(() => import('@/pages/EducationHubPage').then((module) => ({ default: module.EducationHubPage })));
const EducationStudentDetailPage = lazy(() => import('@/pages/EducationStudentDetailPage').then((module) => ({ default: module.EducationStudentDetailPage })));
const EducationStudentImportPage = lazy(() => import('@/pages/EducationStudentImportPage').then((module) => ({ default: module.EducationStudentImportPage })));
const ForgotPasswordPage = lazy(() => import('@/pages/ForgotPasswordPage').then((module) => ({ default: module.ForgotPasswordPage })));
const IntegrationsHubPage = lazy(() => import('@/pages/IntegrationsHubPage').then((module) => ({ default: module.IntegrationsHubPage })));
const IntegrationManagementPage = lazy(() => import('@/pages/IntegrationManagementPage').then((module) => ({ default: module.IntegrationManagementPage })));
const HelpArticlePage = lazy(() => import('@/pages/HelpArticlePage').then((module) => ({ default: module.HelpArticlePage })));
const HelpAskPage = lazy(() => import('@/pages/HelpAskPage').then((module) => ({ default: module.HelpAskPage })));
const HelpCategoryPage = lazy(() => import('@/pages/HelpCategoryPage').then((module) => ({ default: module.HelpCategoryPage })));
const HelpCenterPage = lazy(() => import('@/pages/HelpCenterPage').then((module) => ({ default: module.HelpCenterPage })));
const HelpSearchPage = lazy(() => import('@/pages/HelpSearchPage').then((module) => ({ default: module.HelpSearchPage })));
const HelpSupportPage = lazy(() => import('@/pages/HelpSupportPage').then((module) => ({ default: module.HelpSupportPage })));
const HelpSupportRequestPage = lazy(() => import('@/pages/HelpSupportRequestPage').then((module) => ({ default: module.HelpSupportRequestPage })));
const LeadsPage = lazy(() => import('@/pages/LeadsPage').then((module) => ({ default: module.LeadsPage })));
const LoginPage = lazy(() => import('@/pages/LoginPage').then((module) => ({ default: module.LoginPage })));
const MFAChallengePage = lazy(() => import('@/pages/MFAChallengePage').then((module) => ({ default: module.MFAChallengePage })));
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage').then((module) => ({ default: module.NotFoundPage })));
const OverviewPage = lazy(() => import('@/pages/OverviewPage').then((module) => ({ default: module.OverviewPage })));
const PlatformAdminPage = lazy(() => import('@/pages/PlatformAdminPage').then((module) => ({ default: module.PlatformAdminPage })));
const ResetPasswordPage = lazy(() => import('@/pages/ResetPasswordPage').then((module) => ({ default: module.ResetPasswordPage })));
const SignupPage = lazy(() => import('@/pages/SignupPage').then((module) => ({ default: module.SignupPage })));
const StudentsPage = lazy(() => import('@/pages/StudentsPage').then((module) => ({ default: module.StudentsPage })));
const VerifyEmailPage = lazy(() => import('@/pages/VerifyEmailPage').then((module) => ({ default: module.VerifyEmailPage })));
const WorkspaceInvitationPage = lazy(() => import('@/pages/WorkspaceInvitationPage').then((module) => ({ default: module.WorkspaceInvitationPage })));
const WorkspaceSettingsPage = lazy(() => import('@/features/workspace/settings').then((module) => ({ default: module.WorkspaceSettingsPage })));
const WidgetDemoPage = lazy(() => import('@/pages/WidgetDemoPage').then((module) => ({ default: module.WidgetDemoPage })));

const OrganizationsPage = lazy(() => import('@/pages/OrganizationsPage').then((module) => ({ default: module.OrganizationsPage })));
const OrganizationBillingPage = lazy(() => import('@/pages/OrganizationBillingPage').then((module) => ({ default: module.OrganizationBillingPage })));

function OrganizationLayout() {
  const { session } = useAuth();
  const location = useLocation();
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (session.user.emailVerified === false) return <Navigate to="/verify-email" replace />;
  // Remount account-level views after any credential change; never show the
  // previous identity's organization list or billing response during reload.
  return <Outlet key={session.accessToken} />;
}

function ProtectedLayout() {
  const { session } = useAuth(); const location = useLocation();
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (session.user.emailVerified === false) return <Navigate to="/verify-email" replace />;
  return <WorkspaceSetupGate><MaterialmAppShell /></WorkspaceSetupGate>;
}

export function App() {
  return <PageErrorBoundary><Suspense fallback={<PageLoader />}><Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route path="/signup" element={<SignupPage />} />
    <Route path="/verify-email" element={<VerifyEmailPage />} />
    <Route path="/forgot-password" element={<ForgotPasswordPage />} />
    <Route path="/reset-password" element={<ResetPasswordPage />} />
    <Route path="/mfa-challenge" element={<MFAChallengePage />} />
    <Route path="/workspace-invitation" element={<WorkspaceInvitationPage />} />
    <Route path="/education-access-recovery" element={<EducationAccessRecoveryPage />} />
    <Route path="/demo/:agentId?" element={<WidgetDemoPage />} />
    <Route path="/widget/:agentId" element={<WidgetDemoPage embedded />} />
    <Route element={<OrganizationLayout />}>
      <Route path="organizations" element={<OrganizationsPage />} />
      <Route path="organization/billing" element={<OrganizationBillingPage />} />
    </Route>
    <Route element={<ProtectedLayout />}>
      <Route index element={<><WorkspaceStarterPanel /><OverviewPage /></>} />
      <Route path="organization/profile" element={<OrganizationProfilePage />} />
      <Route path="agents" element={<AgentsPage />} />
      <Route path="agents/:agentId/:tab?" element={<AgentBuilderPage />} />
      <Route path="education" element={<EducationLayout />}>
        <Route index element={<EducationHubPage />} />
        <Route path="courses" element={<CoursesPage />} />
        <Route path="knowledge" element={<CourseKnowledgePage />} />
        <Route path="batches" element={<BatchesPage />} />
        <Route path="students" element={<StudentsPage />} />
        <Route path="enrollments" element={<EducationEnrollmentsPage />} />
        <Route path="students/import" element={<EducationStudentImportPage />} />
        <Route path="students/:studentId" element={<EducationStudentDetailPage />} />
        <Route path="access-requests" element={<EducationAccessRequestsPage />} />
        <Route path="activity" element={<EducationActivityPage />} />
      </Route>
      <Route path="conversations" element={<ConversationsPage />} />
      <Route path="leads" element={<LeadsPage />} />
      <Route path="crm-workflow" element={<CRMWorkflowPage />} />
      <Route path="workflows" element={<BotWorkflowBuilderPage />} />
      <Route path="analytics" element={<AnalyticsPage />} />
      <Route path="audit" element={<AuditPage />} />
      <Route path="integrations" element={<IntegrationsHubPage />} />
      <Route path="integrations/advanced" element={<IntegrationManagementPage />} />
      <Route path="deploy" element={<DeployPage />} />
      {/* The settings center is the single workspace administration entry point. */}
      <Route path="workspace" element={<Navigate to="/workspace/settings/general" replace />} />
      {/* Keep the legacy URL, but route it to the complete draft/preview/
          publish white-label control center. */}
      <Route path="workspace/white-label" element={<Navigate to="/workspace/settings/branding" replace />} />
      <Route path="workspace/settings" element={<Navigate to="/workspace/settings/general" replace />} />
      <Route path="workspace/settings/:section" element={<WorkspaceSettingsPage />} />
      {/* Platform control-plane aliases keep the admin hierarchy addressable
          while the current control-plane screen owns the shared data loaders. */}
      <Route path="platform-admin" element={<PlatformAdminPage />} />
      <Route path="platform-admin/dashboard" element={<PlatformAdminPage />} />
      <Route path="platform-admin/tenants" element={<PlatformAdminPage />} />
      <Route path="platform-admin/workspaces" element={<PlatformAdminPage />} />
      <Route path="platform-admin/users" element={<PlatformAdminPage />} />
      <Route path="platform-admin/subscriptions" element={<PlatformAdminPage />} />
      <Route path="platform-admin/plans" element={<PlatformAdminPage />} />
      <Route path="platform-admin/usage" element={<PlatformAdminPage />} />
      <Route path="platform-admin/channels" element={<PlatformAdminPage />} />
      <Route path="platform-admin/integrations" element={<PlatformAdminPage />} />
      <Route path="platform-admin/jobs" element={<PlatformAdminPage />} />
      <Route path="platform-admin/webhooks" element={<PlatformAdminPage />} />
      <Route path="platform-admin/audit" element={<PlatformAdminPage />} />
      <Route path="platform-admin/security" element={<PlatformAdminPage />} />
      <Route path="platform-admin/support" element={<PlatformAdminPage />} />
      <Route path="platform-admin/system" element={<PlatformAdminPage />} />
      <Route path="help" element={<HelpCenterPage />} />
      <Route path="help/search" element={<HelpSearchPage />} />
      <Route path="help/categories/:slug" element={<HelpCategoryPage />} />
      <Route path="help/articles/:slug" element={<HelpArticlePage />} />
      <Route path="help/ask" element={<HelpAskPage />} />
      <Route path="help/support" element={<HelpSupportPage />} />
      <Route path="help/support/:requestId" element={<HelpSupportRequestPage />} />
      <Route path="settings" element={<Navigate to="/workspace/settings/general" replace />} />
    </Route>
    <Route path="*" element={<NotFoundPage />} />
  </Routes></Suspense></PageErrorBoundary>;
}
