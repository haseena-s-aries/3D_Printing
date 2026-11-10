import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { SubmissionForm } from "../components/PartSubmission";
import { BackLink, Card, PageHeader } from "../components/ui";

/** Client spare-part submission (Client Administrator: company record; other client users: proposal). */
export default function PartSubmissionPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const isAdmin = session?.membership.role === "client_admin";
  return (
    <>
      <BackLink to="/parts">Digital inventory</BackLink>
      <PageHeader
        title={isAdmin ? "Add a spare part" : "Propose a new spare part"}
        subtitle="Fields marked * are required. Mark anything you do not know as Unknown / not available; Aries can ask for more later."
      />
      <Card>
        <SubmissionForm isAdmin={isAdmin} onDone={(p) => navigate(`/parts/${p.id}?submitted=1`)} />
      </Card>
    </>
  );
}
