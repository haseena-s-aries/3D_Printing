/** P1 visual catalog: cards show stored states honestly and offer no manufacturing or approval action. */
import type { Part } from "@passport/api-types";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Eligibility, PartCard } from "../components/catalog";

const base = {
  id: "p1", part_number: "DME-1001", name: "Sea-water pump impeller", project_name: "Pump refit", dimensions: "Ø165 x 44 mm",
  criticality: "critical", passport_id: "pp1", passport_number: "DP-2026-00001", revision: { number: 1, status: "draft" },
  publication_state: "draft", evidence_level: "none", manufacturing_eligibility: "not_eligible", data_captured: "rl3",
  documents: { total: 3, step: 1, dwg: 0, pdf: 1, image: 1 }, has_3d: true, thumbnail: null,
} as unknown as Part;

const card = (p: Partial<Part>) =>
  render(<MemoryRouter><PartCard part={{ ...base, ...p } as Part} onQuickView={vi.fn()} /></MemoryRouter>);

describe("catalog part card", () => {
  it("marks a draft part as in digitisation and shows its stored eligibility", () => {
    card({});
    expect(screen.getByText("In digitisation · not manufacturing-ready")).toBeInTheDocument();
    expect(screen.getByText("Not eligible for manufacturing")).toBeInTheDocument();
    expect(screen.getByText("R-L1–R-L3 data complete")).toBeInTheDocument(); // data completeness, not eligibility
    expect(screen.getByRole("link", { name: "DME-1001" })).toHaveAttribute("href", "/parts/p1");
  });

  it("offers no manufacturing, approval or ordering action", () => {
    card({ publication_state: "published", manufacturing_eligibility: "eligible" });
    expect(screen.getByText("Published")).toBeInTheDocument();
    expect(screen.getByText("Eligible for manufacturing")).toBeInTheDocument();
    const actions = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    expect(actions.join(" ")).not.toMatch(/request|order|approve|release/i);
    expect(screen.queryByText(/price|lead time/i)).toBeNull();
  });

  it("shows a part without a passport as not manufacturing-ready", () => {
    card({ passport_id: null, passport_number: null, publication_state: null, manufacturing_eligibility: null, data_captured: null } as Partial<Part>);
    expect(screen.getByText("No passport")).toBeInTheDocument();
    expect(screen.getByText("In digitisation · not manufacturing-ready")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open part" })).toBeInTheDocument();
  });

  it("keeps one primary action on the card face and the secondary ones in an accessible menu", () => {
    const onRequest = vi.fn();
    render(<MemoryRouter><PartCard part={base} onQuickView={vi.fn()} onRequest={onRequest} cloneable /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Open passport" })).toHaveAttribute("href", "/passports/pp1");
    expect(screen.queryByRole("menuitem")).toBeNull();
    const more = screen.getByRole("button", { name: "More actions for DME-1001" });
    expect(more).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitem", { name: "Clone part DME-1001" })).toHaveAttribute("href", "/parts/p1/clone");
    expect(screen.getByRole("menuitem", { name: "Open part record" })).toHaveAttribute("href", "/parts/p1");
    expect(screen.getByRole("menuitem", { name: "Request" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(more).toHaveFocus();
    fireEvent.click(more);
    fireEvent.click(screen.getByRole("menuitem", { name: "Request" }));
    expect(onRequest).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /approve|release|order/i })).toBeNull();
  });

  it("labels every stored eligibility state", () => {
    const { rerender } = render(<Eligibility value="eligible_subject_to_authorisation" />);
    expect(screen.getByText("Eligible, subject to authorisation")).toBeInTheDocument();
    rerender(<Eligibility value="suspended" />);
    expect(screen.getByText("Manufacturing suspended")).toBeInTheDocument();
  });
});
