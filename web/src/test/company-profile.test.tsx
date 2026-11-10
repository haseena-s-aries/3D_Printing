/** One company profile for self-registration and Aries Admin creation; missing fields and unverified contacts are shown as such. */
import type { Client } from "@passport/api-types";
import { render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ClientOverview } from "../components/ClientAdminPanels";
import { CompanyProfileFields, EMPTY_PROFILE, PROFILE_FIELDS, type CompanyProfile } from "../components/CompanyProfileFields";
import { registrationBody } from "../pages/RegisterCompanyPage";

afterEach(() => vi.restoreAllMocks());

const LABELS = ["Registered company name", "Trade licence number", "Trade licence issuing authority", "Country", "Emirate / state",
  "Location / address", "Primary contact name", "Contact designation", "Email address", "Phone number"];

function Harness() {
  const [v, setV] = useState<CompanyProfile>(EMPTY_PROFILE);
  return <form><CompanyProfileFields value={v} onChange={setV} /></form>;
}

describe("shared company profile fields", () => {
  it("collects every required profile field", () => {
    render(<Harness />);
    for (const l of LABELS) expect(screen.getByLabelText(l)).toBeRequired();
    expect(screen.getByLabelText("City (optional)")).not.toBeRequired();
    expect(PROFILE_FIELDS).toHaveLength(11);
  });

  it("maps the profile to the registration API without dropping a field", () => {
    const p = Object.fromEntries(PROFILE_FIELDS.map((f) => [f.key, `v-${f.key}`])) as CompanyProfile;
    const body = registrationBody(p);
    expect(body).toMatchObject({ company_name: "v-name", job_title: "v-contact_title", email: "v-contact_email", phone: "v-contact_phone",
      state: "v-state", address: "v-address", licence_authority: "v-licence_authority" });
    expect(Object.values(body).sort()).toEqual(Object.values(p).sort());
  });
});

describe("client profile in Aries Admin", () => {
  it("marks missing fields and never shows an invited contact as verified", async () => {
    const values = { ...EMPTY_PROFILE, name: "Old Co", country: "Oman" };
    const details = {
      name: "Old Co", slug: "old-co", status: "active", hosting_model: "shared", region_code: "", origin: "aries_admin", created_at: "2026-10-01T00:00:00Z",
      profile: { values, missing: PROFILE_FIELDS.filter((f) => f.required && !values[f.key]).map((f) => f.key), complete: false },
      contact: { state: "invited", email: "c@old.test", email_verified: false, label: "Invited as Client Administrator; awaiting acceptance (email not verified)", verified_at: null },
      registration: null, people: [], aries_staff: [], counts: { projects: 0, parts: 0, passports: 0 },
    };
    render(<ClientOverview client={{ id: "c1", name: "Old Co" } as Client} details={{ data: details as never, loading: false, error: null, reload: () => undefined }}
      onChanged={() => undefined} />);
    const profile = await screen.findByTestId("company-profile");
    expect(within(profile).getAllByText("Missing")).toHaveLength(8);
    expect(within(profile).getByText("Oman")).toBeInTheDocument();
    expect(screen.getByText("Incomplete: 8 missing")).toBeInTheDocument();
    expect(screen.getByTestId("contact-status")).toHaveTextContent("Not verified");
    expect(screen.getByTestId("contact-status")).not.toHaveTextContent("Email verified");
    expect(screen.getByText("Created by Aries Admin")).toBeInTheDocument();
  });
});
