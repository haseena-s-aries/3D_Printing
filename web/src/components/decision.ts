/** Internal business-decision codes (for example OQ-35) are shown to operator staff only; clients get plain wording. */
import { useAuth } from "../auth/AuthContext";

export function useDecision(): (code: string) => string {
  const { session } = useAuth();
  const operator = !!session?.membership.role.startsWith("operator");
  return (code: string) => (operator ? ` (${code})` : "");
}
