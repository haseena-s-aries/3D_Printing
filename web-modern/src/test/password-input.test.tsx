/** Password fields: the eye button shows and hides the typed password; the label still finds the input. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PasswordInput } from "../components/PasswordInput";
import { Field } from "../components/ui";

describe("password input", () => {
  it("toggles between hidden and shown", () => {
    render(<Field label="Password"><PasswordInput value="Secret-123" onChange={() => {}} /></Field>);
    const input = screen.getByLabelText("Password"); // unambiguous: the eye button is named "Show"/"Hide"
    expect(input).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(input).toHaveAttribute("type", "text");
    const hide = screen.getByRole("button", { name: "Hide" });
    expect(hide).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(hide);
    expect(input).toHaveAttribute("type", "password");
  });
});
