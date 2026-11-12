"""Versioned API v1. Breaking changes go to /api/v2/."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import LogoutView, MembershipsView, MeView, RefreshView, SwitchView, TokenView
from apps.audit.api import AuditEventViewSet
from apps.imports.api import AdminImportsView, InventoryImportViewSet
from apps.intelligence.api import (AdminAssessmentSummaryView, AdminIntelligenceUsageView, AssessmentReportView,
                                   AssessmentRunActionView, AssessmentRunDetailView, AssessmentRunsView, AssessmentScheduleView,
                                   CostComparisonOverviewView, FeasibilityBatchView, FeasibilityOverviewView, FeasibilityReviewView,
                                   IntelligenceBatchView, IntelligenceOverviewView, PartAssessView, PartClassificationView,
                                   PartCostComparisonsView, PartCostPreviewView, PartFeasibilityAssessView, PartFeasibilityView,
                                   PartIntelligenceView, PartRecommendationsView, RecommendationQueueView, RecommendationReviewView)
from apps.intelligence.client_api import (AdminAIManagementView, AdminClientWorkspaceView, ClientDashboardView, ClientIntelligenceView,
                                          ClientMembersView, ClientPartView, ClientReportView, ClientRequestAssessmentView,
                                          DisclosureActionView, DisclosureQueueView, PartDisclosuresView)
from apps.edits.api import EditRequestViewSet
from apps.files.api import DownloadView, EngineeringFileViewSet
from apps.parts.api import SparePartViewSet
from apps.parts.dashboard import DashboardSummaryView
from apps.files.admin_thumbnails import AdminThumbnailConsentView, AdminThumbnailView
from apps.files.thumbnail_provenance import (ContractAuthorizationEventView, ContractAuthorizationView, ContractListView,
                                             ImageOriginView, OriginClaimsQueueView)
from apps.parts.admin_overview import AdminInventoryView
from apps.passports.approval_api import PassportApprovalDetailView, PassportApprovalQueueView
from apps.passports.api import PassportFieldOptionsView, PassportViewSet
from apps.projects.api import ProjectViewSet
from apps.registrations.api import (DevOutboxView, PasswordResetRequestView, PasswordResetView, RegistrationConfigView,
                                    RegistrationResendView, RegistrationSubmitView, RegistrationVerifyView, RegistrationViewSet,
                                    StaffRequestSubmitView)
from apps.servicerequests.api import (ClientRequestViewSet, NotificationListView, NotificationReadView, OperatorOverviewView,
                                      OperatorRequestViewSet)
from apps.tenancy.api import ClientViewSet, OwnCompanyProfileView, UserViewSet
from apps.tenancy.invitations import InvitationAcceptView, InvitationViewSet
from apps.tenancy.platform_settings import PlatformSettingsView

router = DefaultRouter()
router.include_root_view = False
router.register("clients", ClientViewSet, basename="client")
router.register("registrations", RegistrationViewSet, basename="registration")
router.register("users", UserViewSet, basename="user")
router.register("invitations", InvitationViewSet, basename="invitation")
router.register("projects", ProjectViewSet, basename="project")
router.register("parts", SparePartViewSet, basename="part")
router.register("passports", PassportViewSet, basename="passport")
router.register("files", EngineeringFileViewSet, basename="file")
router.register("audit-events", AuditEventViewSet, basename="audit-event")
router.register("requests", ClientRequestViewSet, basename="request")
router.register("operator/requests", OperatorRequestViewSet, basename="operator-request")
router.register("edit-requests", EditRequestViewSet, basename="edit-request")
router.register("inventory-imports", InventoryImportViewSet, basename="inventory-import")

urlpatterns = [
    path("auth/token/", TokenView.as_view(), name="auth-token"),
    path("public/registration-config/", RegistrationConfigView.as_view(), name="registration-config"),
    path("public/registrations/", RegistrationSubmitView.as_view(), name="registration-submit"),
    path("public/staff-requests/", StaffRequestSubmitView.as_view(), name="staff-request-submit"),
    path("public/registrations/resend/", RegistrationResendView.as_view(), name="registration-resend"),
    path("public/registrations/verify/<str:token>/", RegistrationVerifyView.as_view(), name="registration-verify"),
    path("public/password-reset/", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("public/password-reset/<str:token>/", PasswordResetView.as_view(), name="password-reset"),
    path("public/dev-outbox/", DevOutboxView.as_view(), name="dev-outbox"),
    path("auth/refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", MeView.as_view(), name="auth-me"),
    path("auth/memberships/", MembershipsView.as_view(), name="auth-memberships"),
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("organisation/profile/", OwnCompanyProfileView.as_view(), name="own-company-profile"),
    path("admin/inventory/", AdminInventoryView.as_view(), name="admin-inventory"),
    path("admin/inventory/thumbnails/<str:token>/", AdminThumbnailView.as_view(), name="admin-inventory-thumbnail"),
    path("company/admin-thumbnail-consent/", AdminThumbnailConsentView.as_view(), name="admin-thumbnail-consent"),
    path("files/origin-claims/", OriginClaimsQueueView.as_view(), name="file-origin-claims"),
    path("files/<uuid:file_id>/versions/<int:number>/origin/", ImageOriginView.as_view(), name="file-version-origin"),
    path("admin/thumbnail-contracts/", ContractListView.as_view(), name="admin-thumbnail-contracts"),
    path("admin/platform-settings/", PlatformSettingsView.as_view(), name="admin-platform-settings"),
    path("admin/clients/<uuid:client_id>/thumbnail-contract/", ContractAuthorizationView.as_view(), name="admin-thumbnail-contract"),
    path("admin/clients/<uuid:client_id>/thumbnail-contract/<uuid:auth_id>/events/", ContractAuthorizationEventView.as_view(),
         name="admin-thumbnail-contract-event"),
    path("admin/inventory-imports/", AdminImportsView.as_view(), name="admin-inventory-imports"),
    path("admin/intelligence-usage/", AdminIntelligenceUsageView.as_view(), name="admin-intelligence-usage"),
    path("parts/<uuid:pk>/intelligence/", PartIntelligenceView.as_view(), name="part-intelligence"),
    path("parts/<uuid:pk>/intelligence/assess/", PartAssessView.as_view(), name="part-intelligence-assess"),
    path("parts/<uuid:pk>/intelligence/classification/", PartClassificationView.as_view(), name="part-intelligence-classification"),
    path("intelligence/overview/", IntelligenceOverviewView.as_view(), name="intelligence-overview"),
    path("intelligence/assess-batch/", IntelligenceBatchView.as_view(), name="intelligence-assess-batch"),
    path("parts/<uuid:pk>/feasibility/", PartFeasibilityView.as_view(), name="part-feasibility"),
    path("parts/<uuid:pk>/feasibility/assess/", PartFeasibilityAssessView.as_view(), name="part-feasibility-assess"),
    path("parts/<uuid:pk>/feasibility/<uuid:aid>/reviews/", FeasibilityReviewView.as_view(), name="part-feasibility-review"),
    path("intelligence/feasibility/", FeasibilityOverviewView.as_view(), name="feasibility-overview"),
    path("intelligence/feasibility/assess-batch/", FeasibilityBatchView.as_view(), name="feasibility-assess-batch"),
    path("parts/<uuid:pk>/cost-comparisons/", PartCostComparisonsView.as_view(), name="part-cost-comparisons"),
    path("parts/<uuid:pk>/cost-comparisons/calculate/", PartCostPreviewView.as_view(), name="part-cost-preview"),
    path("intelligence/cost-comparisons/", CostComparisonOverviewView.as_view(), name="cost-comparison-overview"),
    path("parts/<uuid:pk>/recommendations/", PartRecommendationsView.as_view(), name="part-recommendations"),
    path("parts/<uuid:pk>/recommendations/<uuid:rid>/reviews/", RecommendationReviewView.as_view(), name="recommendation-review"),
    path("intelligence/recommendations/", RecommendationQueueView.as_view(), name="recommendation-queue"),
    path("intelligence/assessments/", AssessmentRunsView.as_view(), name="assessment-runs"),
    path("intelligence/assessments/<uuid:pk>/", AssessmentRunDetailView.as_view(), name="assessment-run"),
    path("intelligence/assessments/<uuid:pk>/retry/", AssessmentRunActionView.as_view(action_name="retry"), name="assessment-run-retry"),
    path("intelligence/assessments/<uuid:pk>/cancel/", AssessmentRunActionView.as_view(action_name="cancel"), name="assessment-run-cancel"),
    path("intelligence/assessments/<uuid:pk>/report.xlsx", AssessmentReportView.as_view(fmt="xlsx"), name="assessment-report-xlsx"),
    path("intelligence/assessments/<uuid:pk>/report.pdf", AssessmentReportView.as_view(fmt="pdf"), name="assessment-report-pdf"),
    path("intelligence/assessment-schedule/", AssessmentScheduleView.as_view(), name="assessment-schedule"),
    path("admin/assessment-summary/", AdminAssessmentSummaryView.as_view(), name="admin-assessment-summary"),
    # CN-007 role-based AI access (AI_CLIENT_ACCESS_ENABLED)
    path("parts/<uuid:pk>/disclosures/", PartDisclosuresView.as_view(), name="part-disclosures"),
    path("parts/<uuid:pk>/disclosures/<uuid:sid>/share/", DisclosureActionView.as_view(action_name="share"), name="part-disclosure-share"),
    path("parts/<uuid:pk>/disclosures/<uuid:sid>/withdraw/", DisclosureActionView.as_view(action_name="withdraw"), name="part-disclosure-withdraw"),
    path("intelligence/disclosures/", DisclosureQueueView.as_view(), name="disclosure-queue"),
    path("client-intelligence/", ClientIntelligenceView.as_view(), name="client-intelligence"),
    path("client-intelligence/dashboard/", ClientDashboardView.as_view(), name="client-intelligence-dashboard"),
    path("client-intelligence/members/", ClientMembersView.as_view(), name="client-intelligence-members"),
    path("client-intelligence/parts/<uuid:pk>/", ClientPartView.as_view(), name="client-intelligence-part"),
    path("client-intelligence/parts/<uuid:pk>/request/", ClientRequestAssessmentView.as_view(), name="client-intelligence-request"),
    path("client-intelligence/parts/<uuid:pk>/report.pdf", ClientReportView.as_view(), name="client-intelligence-report"),
    path("admin/ai-management/", AdminAIManagementView.as_view(), name="admin-ai-management"),
    path("admin/ai-management/clients/<uuid:pk>/", AdminClientWorkspaceView.as_view(), name="admin-ai-management-client"),
    path("passport-field-options/", PassportFieldOptionsView.as_view(), name="passport-field-options"),
    path("auth/switch/", SwitchView.as_view(), name="auth-switch"),
    path("downloads/<str:token>/", DownloadView.as_view(), name="download"),
    path("operator/overview/", OperatorOverviewView.as_view(), name="operator-overview"),
    path("operator/passport-approvals/", PassportApprovalQueueView.as_view(), name="passport-approvals"),
    path("operator/passport-approvals/<uuid:client_id>/<uuid:passport_id>/", PassportApprovalDetailView.as_view(),
         name="passport-approval-detail"),
    path("notifications/", NotificationListView.as_view(), name="notifications"),
    path("notifications/read-all/", NotificationReadView.as_view(), name="notifications-read-all"),
    path("notifications/<uuid:pk>/read/", NotificationReadView.as_view(), name="notification-read"),
    path("invitation-acceptance/<str:token>/", InvitationAcceptView.as_view(), name="invitation-accept"),
    path("", include(router.urls)),
]
