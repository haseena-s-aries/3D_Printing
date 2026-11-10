/**
 * The company profile, shared by public company registration and Aries Admin client creation and editing, so both
 * routes collect the same information with the same rules (backend: apps/tenancy/profile.py).
 */
import { Field } from "./ui";

export type ProfileKey =
  | "name" | "trade_licence_number" | "licence_authority" | "country" | "state" | "city" | "address"
  | "contact_name" | "contact_title" | "contact_email" | "contact_phone";
export type CompanyProfile = Record<ProfileKey, string>;

export const PROFILE_FIELDS: { key: ProfileKey; label: string; section: "company" | "contact"; required: boolean; type?: string; auto?: string; hint?: string }[] = [
  { key: "name", label: "Registered company name", section: "company", required: true, auto: "organization" },
  { key: "trade_licence_number", label: "Trade licence number", section: "company", required: true },
  { key: "licence_authority", label: "Trade licence issuing authority", section: "company", required: true, hint: "e.g. Department of Economic Development, free zone authority" },
  { key: "country", label: "Country", section: "company", required: true, auto: "country-name" },
  { key: "state", label: "Emirate / state", section: "company", required: true, auto: "address-level1" },
  { key: "city", label: "City", section: "company", required: false, auto: "address-level2" },
  { key: "address", label: "Location / address", section: "company", required: true, auto: "street-address" },
  { key: "contact_name", label: "Primary contact name", section: "contact", required: true, auto: "name" },
  { key: "contact_title", label: "Contact designation", section: "contact", required: true, auto: "organization-title" },
  { key: "contact_email", label: "Email address", section: "contact", required: true, type: "email", auto: "email" },
  { key: "contact_phone", label: "Phone number", section: "contact", required: true, type: "tel", auto: "tel" },
];

export const EMPTY_PROFILE: CompanyProfile = Object.fromEntries(PROFILE_FIELDS.map((f) => [f.key, ""])) as CompanyProfile;
export const PROFILE_LABEL = Object.fromEntries(PROFILE_FIELDS.map((f) => [f.key, f.label])) as Record<ProfileKey, string>;

export function CompanyProfileFields({ value, onChange, contactHeading = "Primary contact", emailHint }: {
  value: CompanyProfile; onChange: (next: CompanyProfile) => void; contactHeading?: string; emailHint?: string;
}) {
  const input = (f: (typeof PROFILE_FIELDS)[number]) => (
    <Field key={f.key} label={f.required ? f.label : `${f.label} (optional)`} hint={f.key === "contact_email" ? emailHint : f.hint}>
      <input name={f.key} required={f.required} type={f.type ?? "text"} autoComplete={f.auto}
        placeholder={f.key === "contact_phone" ? "+971 50 123 4567" : undefined}
        value={value[f.key]} onChange={(e) => onChange({ ...value, [f.key]: e.target.value })} />
    </Field>
  );
  return (
    <>
      <h2 className="span-2 form-section">Company</h2>
      {PROFILE_FIELDS.filter((f) => f.section === "company").map(input)}
      <h2 className="span-2 form-section">{contactHeading}</h2>
      {PROFILE_FIELDS.filter((f) => f.section === "contact").map(input)}
    </>
  );
}
