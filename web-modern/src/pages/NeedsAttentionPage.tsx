/** The signed-in user's work queue across the application (components/NeedsAttention): what is waiting, by role. */
import { NeedsAttention } from "../components/NeedsAttention";
import { PageHeader } from "../components/ui";

export default function NeedsAttentionPage() {
  return (
    <>
      <PageHeader title="Needs attention" subtitle="Work waiting for you, within your role, company and project scope. Open an item to act on it." />
      <NeedsAttention />
    </>
  );
}
