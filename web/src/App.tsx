import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./auth/AuthContext";
import Layout from "./components/Layout";
import { Card, Loading, PageHeader } from "./components/ui";
import AcceptInvitationPage from "./pages/AcceptInvitationPage";
import AdminInventoryPage from "./pages/AdminInventoryPage";
import AuditPage from "./pages/AuditPage";
import InventoryImportPage, { InventoryImportDetailPage } from "./pages/InventoryImportPage";
import EditRequestsPage, { EditRequestDetailPage } from "./pages/EditRequestsPage";
import ClientManagementPage from "./pages/ClientManagementPage";
import ClientsPage from "./pages/ClientsPage";
import DashboardPage from "./pages/DashboardPage";
import LoginPage from "./pages/LoginPage";
import PartDetailPage from "./pages/PartDetailPage";
import PartSubmissionPage from "./pages/PartSubmissionPage";
import PartClonePage from "./pages/PartClonePage";
import PartsPage from "./pages/PartsPage";
import PassportDetailPage from "./pages/PassportDetailPage";
import DevOutboxPage from "./pages/DevOutboxPage";
import PassportsPage from "./pages/PassportsPage";
import { ForgotPasswordPage, ResetPasswordPage } from "./pages/PasswordResetPages";
import ProjectsPage from "./pages/ProjectsPage";
import RegisterCompanyPage from "./pages/RegisterCompanyPage";
import RegistrationsPage from "./pages/RegistrationsPage";
import UsersPage from "./pages/UsersPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";

// Three.js is only loaded when a 3D model is opened.
const ModelViewerPage = lazy(() => import("./pages/ModelViewerPage"));
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

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/invite/:token" element={<AcceptInvitationPage />} />
      <Route path="/register" element={<RegisterCompanyPage />} />
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
        <Route path="passports" element={<RequireCapability capability="passports.view"><PassportsPage /></RequireCapability>} />
        <Route path="passports/:id" element={<RequireCapability capability="passports.view"><PassportDetailPage /></RequireCapability>} />
        <Route path="files/:id/versions/:number/view" element={<RequireCapability capability="files.download_derivative"><Suspense fallback={<Loading />}><ModelViewerPage /></Suspense></RequireCapability>} />
        <Route path="audit" element={<RequireCapability capability="audit.view"><AuditPage /></RequireCapability>} />
        <Route path="requests" element={<RequireCapability capability="requests.view"><Suspense fallback={<Loading />}><MyRequestsPage /></Suspense></RequireCapability>} />
        <Route path="requests/new-scan" element={<RequireCapability capability="requests.create"><Suspense fallback={<Loading />}><ScanRequestPage /></Suspense></RequireCapability>} />
        <Route path="requests/:id" element={<RequireCapability capability="requests.view"><Suspense fallback={<Loading />}><RequestDetailPage /></Suspense></RequireCapability>} />
        <Route path="incoming" element={<RequireCapability capability="requests.handle"><Suspense fallback={<Loading />}><IncomingRequestsPage /></Suspense></RequireCapability>} />
        <Route path="incoming/:id" element={<RequireCapability capability="requests.handle"><Suspense fallback={<Loading />}><IncomingRequestDetailPage /></Suspense></RequireCapability>} />
        <Route path="*" element={<Card><PageHeader title="Page not found" /></Card>} />
      </Route>
    </Routes>
  );
}
