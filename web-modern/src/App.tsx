import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./auth/AuthContext";
import Layout from "./components/Layout";
import { Card, Loading, PageHeader } from "./components/ui";
import AcceptInvitationPage from "./pages/AcceptInvitationPage";
import ClientsPage from "./pages/ClientsPage";
import DashboardPage from "./pages/DashboardPage";
import LoginPage from "./pages/LoginPage";
import PartsPage from "./pages/PartsPage";
import DevOutboxPage from "./pages/DevOutboxPage";
import PassportsPage from "./pages/PassportsPage";
import { ForgotPasswordPage, ResetPasswordPage } from "./pages/PasswordResetPages";
import ProjectsPage from "./pages/ProjectsPage";
import RegisterCompanyPage from "./pages/RegisterCompanyPage";
import RequestStaffAccountPage from "./pages/RequestStaffAccountPage";
import UsersPage from "./pages/UsersPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";

// Workspace pages load on first use (the layout's Suspense shows a skeleton meanwhile); Three.js only with a 3D model.
const AdminInventoryPage = lazy(() => import("./pages/AdminInventoryPage"));
const AuditPage = lazy(() => import("./pages/AuditPage"));
const PassportApprovalsPage = lazy(() => import("./pages/PassportApprovalsPage"));
const DataSharingPage = lazy(() => import("./pages/DataSharingPage"));
const PhotoOriginPage = lazy(() => import("./pages/PhotoOriginPage"));
const AdminCompaniesPage = lazy(() => import("./pages/AdminCompaniesPage"));
const PlatformSettingsPage = lazy(() => import("./pages/PlatformSettingsPage"));
const OriginQueuePage = lazy(() => import("./pages/OriginQueuePage"));
const ThumbnailContractPage = lazy(() => import("./pages/ThumbnailContractPage"));
const ThumbnailContractsPage = lazy(() => import("./pages/ThumbnailContractPage").then((m) => ({ default: m.ThumbnailContractsPage })));
const InventoryImportPage = lazy(() => import("./pages/InventoryImportPage"));
const InventoryImportDetailPage = lazy(() => import("./pages/InventoryImportPage").then((m) => ({ default: m.InventoryImportDetailPage })));
const EditRequestsPage = lazy(() => import("./pages/EditRequestsPage"));
const EditRequestDetailPage = lazy(() => import("./pages/EditRequestsPage").then((m) => ({ default: m.EditRequestDetailPage })));
const ClientManagementPage = lazy(() => import("./pages/ClientManagementPage"));
const PartDetailPage = lazy(() => import("./pages/PartDetailPage"));
const PartSubmissionPage = lazy(() => import("./pages/PartSubmissionPage"));
const PartClonePage = lazy(() => import("./pages/PartClonePage"));
const PassportDetailPage = lazy(() => import("./pages/PassportDetailPage"));
const RegistrationsPage = lazy(() => import("./pages/RegistrationsPage"));
const ModelViewerPage = lazy(() => import("./pages/ModelViewerPage"));
// CN-007 Spare Parts Intelligence by role: Aries Admin management, engineer client sharing, client workspace
const AiManagementPage = lazy(() => import("./pages/AiManagementPage"));
const NeedsAttentionPage = lazy(() => import("./pages/NeedsAttentionPage"));
const AiSharingPage = lazy(() => import("./pages/AiSharingPage"));
const MyPartsIntelligencePage = lazy(() => import("./pages/MyPartsIntelligencePage"));
const MyPartDetailPage = lazy(() => import("./pages/MyPartsIntelligencePage").then((m) => ({ default: m.MyPartDetailPage })));
const MyRequestsPage = lazy(() => import("./pages/MyRequestsPage"));
const RequestDetailPage = lazy(() => import("./pages/RequestDetailPage"));
const ScanRequestPage = lazy(() => import("./pages/ScanRequestPage"));
const IncomingRequestsPage = lazy(() => import("./pages/IncomingRequestsPage"));
const IncomingRequestDetailPage = lazy(() => import("./pages/IncomingRequestDetailPage"));

function RequireAuth({ children }: { children: ReactNode }) {
  const { session, ready, lastUserId } = useAuth();
  const location = useLocation();
  if (!ready) return <Loading />;
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname + location.search, user: lastUserId }} />;
  return <>{children}</>;
}

function RequireAnyCapability({ capabilities, children }: { capabilities: string[]; children: ReactNode }) {
  const { can } = useAuth();
  if (!capabilities.some((c) => can(c))) {
    return (
      <Card>
        <PageHeader title="Not available" subtitle="Your role does not give access to this page." />
      </Card>
    );
  }
  return <>{children}</>;
}

function RequireCapability({ capability, children }: { capability: string; children: ReactNode }) {
  const { can } = useAuth();
  if (!can(capability)) {
    return (
      <Card>
        <PageHeader title="Not available" subtitle="Your role does not give access to this page." />
      </Card>
    );
  }
  return <>{children}</>;
}

/** Aries Admin super-administrator workspaces only (either context: Aries organisation or inside a company). */
function RequireSuperAdmin({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  if (!session?.admin_access || session.membership.role !== "operator_admin") {
    return <Card><PageHeader title="Not available" subtitle="Your role does not give access to this page." /></Card>;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/invite/:token" element={<AcceptInvitationPage />} />
      <Route path="/register" element={<RegisterCompanyPage />} />
      <Route path="/register/staff" element={<RequestStaffAccountPage />} />
      <Route path="/register/verify/:token" element={<VerifyEmailPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password/:token" element={<ResetPasswordPage />} />
      <Route path="/dev/outbox" element={<DevOutboxPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="inventory-import" element={<RequireCapability capability="inventory.import"><InventoryImportPage /></RequireCapability>} />
        <Route path="inventory-import/:id" element={<RequireCapability capability="inventory.import"><InventoryImportDetailPage /></RequireCapability>} />
        <Route path="admin/inventory" element={<RequireCapability capability="inventory.admin_overview"><AdminInventoryPage /></RequireCapability>} />
        <Route path="admin/companies" element={<RequireSuperAdmin><AdminCompaniesPage /></RequireSuperAdmin>} />
        <Route path="admin/settings" element={<RequireCapability capability="clients.manage"><PlatformSettingsPage /></RequireCapability>} />
        <Route path="edit-requests" element={<RequireAnyCapability capabilities={["edits.request", "edits.review"]}><EditRequestsPage /></RequireAnyCapability>} />
        <Route path="edit-requests/:id" element={<RequireAnyCapability capabilities={["edits.request", "edits.review"]}><EditRequestDetailPage /></RequireAnyCapability>} />
        <Route path="clients" element={<RequireCapability capability="clients.view"><ClientsPage /></RequireCapability>} />
        <Route path="clients/:id" element={<RequireCapability capability="clients.view"><ClientManagementPage /></RequireCapability>} />
        <Route path="registrations" element={<RequireCapability capability="registrations.review"><RegistrationsPage /></RequireCapability>} />
        <Route path="registrations/:id" element={<RequireCapability capability="registrations.review"><RegistrationsPage /></RequireCapability>} />
        <Route path="users" element={<RequireCapability capability="users.view"><UsersPage /></RequireCapability>} />
        <Route path="parts" element={<RequireCapability capability="parts.view"><PartsPage /></RequireCapability>} />
        <Route path="parts/:id/clone" element={<RequireCapability capability="parts.submit"><PartClonePage /></RequireCapability>} />
        <Route path="parts/submit" element={<RequireCapability capability="parts.submit"><PartSubmissionPage /></RequireCapability>} />
        <Route path="projects" element={<RequireCapability capability="projects.view"><ProjectsPage /></RequireCapability>} />
        <Route path="parts/:id" element={<RequireCapability capability="parts.view"><PartDetailPage /></RequireCapability>} />
        <Route path="parts/:id/photos/:fileId/origin" element={<RequireAnyCapability capabilities={["files.origin_claim", "files.origin_confirm"]}><PhotoOriginPage /></RequireAnyCapability>} />
        <Route path="origin-claims" element={<RequireCapability capability="files.origin_confirm"><OriginQueuePage /></RequireCapability>} />
        <Route path="thumbnail-contracts" element={<RequireCapability capability="contracts.thumbnail_view"><ThumbnailContractsPage /></RequireCapability>} />
        <Route path="thumbnail-contracts/:clientId" element={<RequireCapability capability="contracts.thumbnail_view"><ThumbnailContractPage /></RequireCapability>} />
        <Route path="passports" element={<RequireCapability capability="passports.view"><PassportsPage /></RequireCapability>} />
        <Route path="passports/:id" element={<RequireCapability capability="passports.view"><PassportDetailPage /></RequireCapability>} />
        <Route path="files/:id/versions/:number/view" element={<RequireCapability capability="files.download_derivative"><Suspense fallback={<Loading />}><ModelViewerPage /></Suspense></RequireCapability>} />
        <Route path="audit" element={<RequireCapability capability="audit.view"><AuditPage /></RequireCapability>} />
        <Route path="passport-approvals" element={<RequireCapability capability="passports.approve"><Suspense fallback={<Loading />}><PassportApprovalsPage /></Suspense></RequireCapability>} />
        <Route path="requests" element={<RequireCapability capability="requests.view"><Suspense fallback={<Loading />}><MyRequestsPage /></Suspense></RequireCapability>} />
        <Route path="requests/new-scan" element={<RequireCapability capability="requests.create"><Suspense fallback={<Loading />}><ScanRequestPage /></Suspense></RequireCapability>} />
        <Route path="requests/:id" element={<RequireCapability capability="requests.view"><Suspense fallback={<Loading />}><RequestDetailPage /></Suspense></RequireCapability>} />
        <Route path="incoming" element={<RequireCapability capability="requests.handle"><Suspense fallback={<Loading />}><IncomingRequestsPage /></Suspense></RequireCapability>} />
        <Route path="incoming/:id" element={<RequireCapability capability="requests.handle"><Suspense fallback={<Loading />}><IncomingRequestDetailPage /></Suspense></RequireCapability>} />
        <Route path="attention" element={<NeedsAttentionPage />} />
        <Route path="company/data-sharing" element={<RequireCapability capability="files.admin_thumbnail_consent"><DataSharingPage /></RequireCapability>} />
        <Route path="ai/management" element={<RequireCapability capability="ai.management"><AiManagementPage /></RequireCapability>} />
        <Route path="ai/sharing" element={<RequireCapability capability="ai.share"><AiSharingPage /></RequireCapability>} />
        <Route path="ai/my-parts" element={<RequireCapability capability="ai.workspace"><MyPartsIntelligencePage /></RequireCapability>} />
        <Route path="ai/my-parts/:id" element={<RequireCapability capability="ai.workspace"><MyPartDetailPage /></RequireCapability>} />
        <Route path="*" element={<Card><PageHeader title="Page not found" /></Card>} />
      </Route>
    </Routes>
  );
}
