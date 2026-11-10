/** Engineers & Access: Aries staff are picked from a searchable list of accounts with the chosen role. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { StaffPicker, filterStaff, staffLabel, type StaffOption } from "../components/StaffPicker";

const STAFF: StaffOption[] = [
  { email: "ravi@aries.test", name: "Ravi Kumar", role: "operator_engineer" },
  { email: "anu@aries.test", name: "Anu Joseph", role: "operator_engineer" },
  { email: "qa@aries.test", name: "Quinn Admin", role: "operator_admin" },
  { email: "noname@aries.test", name: "", role: "operator_engineer" },
];

describe("staff filter", () => {
  it("lists only the chosen role, sorted by name, and searches name or email", () => {
    expect(filterStaff(STAFF, "operator_engineer", "").map(staffLabel)).toEqual(
      ["Anu Joseph (anu@aries.test)", "noname@aries.test", "Ravi Kumar (ravi@aries.test)"]);
    expect(filterStaff(STAFF, "operator_engineer", "ravi").map((o) => o.email)).toEqual(["ravi@aries.test"]);
    expect(filterStaff(STAFF, "operator_engineer", "ANU@").map((o) => o.email)).toEqual(["anu@aries.test"]);
    expect(filterStaff(STAFF, "operator_engineer", "quinn")).toEqual([]);
  });
});

function Harness({ onPick }: { onPick: (email: string) => void }) {
  const [value, setValue] = useState("");
  return <StaffPicker options={STAFF} role="operator_engineer" value={value} roleName="Aries Engineer"
    assigned={new Set(["anu@aries.test"])} onChange={(e) => { setValue(e); onPick(e); }} />;
}

describe("staff picker", () => {
  it("opens the role's accounts on click, filters as you type and picks one", () => {
    const onPick = vi.fn();
    render(<Harness onPick={onPick} />);
    const box = screen.getByRole("combobox");
    fireEvent.focus(box);
    const list = screen.getByRole("listbox");
    expect(within(list).getAllByRole("option")).toHaveLength(3);
    // already assigned: shown, but cannot be picked
    const anu = within(list).getByRole("option", { name: /Anu Joseph/ });
    expect(anu).toHaveAttribute("aria-disabled", "true");
    fireEvent.mouseDown(anu);
    expect(onPick).not.toHaveBeenCalled();
    fireEvent.change(box, { target: { value: "kum" } });
    expect(within(screen.getByRole("listbox")).getAllByRole("option")).toHaveLength(1);
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onPick).toHaveBeenLastCalledWith("ravi@aries.test");
    expect(box).toHaveValue("Ravi Kumar (ravi@aries.test)");
  });

  it("says when nothing matches", () => {
    render(<Harness onPick={() => {}} />);
    const box = screen.getByRole("combobox");
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "zzz" } });
    expect(screen.getByRole("listbox")).toHaveTextContent("No Aries Engineer matches “zzz”.");
  });
});
