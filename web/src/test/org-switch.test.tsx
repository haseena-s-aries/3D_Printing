/** Switching organisation: every data hook reloads, previous data is cleared and late responses are dropped. */
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

let sessionKey = "membership-maritime";
vi.mock("../auth/AuthContext", () => ({ useSessionKey: () => sessionKey }));

import * as client from "../api/client";
import { useApi } from "../api/useApi";

afterEach(() => vi.restoreAllMocks());

describe("organisation switch", () => {
  it("reloads, clears the previous organisation's data and ignores its late response", async () => {
    const pending: ((v: unknown) => void)[] = [];
    vi.spyOn(client, "api").mockImplementation((() => new Promise((resolve) => pending.push(resolve))) as never);
    const { result, rerender } = renderHook(() => useApi<string>("/dashboard/summary/"));
    pending[0]("maritime totals");
    await waitFor(() => expect(result.current.data).toBe("maritime totals"));

    // the user switches organisation (same page, same request path)
    pending.length = 0;
    sessionKey = "membership-energy";
    vi.spyOn(client, "api").mockImplementation((() => new Promise((resolve) => pending.push(resolve))) as never);
    rerender();
    await waitFor(() => expect(result.current.data).toBeNull()); // old organisation's data is not shown under the new name
    await waitFor(() => expect(pending.length).toBeGreaterThan(0)); // reloaded for the new organisation
    pending[pending.length - 1]("energy totals");
    await waitFor(() => expect(result.current.data).toBe("energy totals"));
  });

  it("drops a response that was started before the switch", async () => {
    sessionKey = "membership-a";
    const resolvers: ((v: unknown) => void)[] = [];
    vi.spyOn(client, "api").mockImplementation((() => new Promise((resolve) => resolvers.push(resolve))) as never);
    const { result, rerender } = renderHook(() => useApi<string>("/parts/"));
    const beforeSwitch = resolvers[0];
    sessionKey = "membership-b";
    rerender();
    await waitFor(() => expect(resolvers.length).toBeGreaterThan(1));
    resolvers[resolvers.length - 1]("b parts");
    await waitFor(() => expect(result.current.data).toBe("b parts"));
    beforeSwitch("a parts arriving late");
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.data).toBe("b parts");
  });
});
