/** Download links are opened on the web app's own address, even when the backend built them with its internal port. */
import { describe, expect, it } from "vitest";

import { sameOriginUrl } from "../api/client";

describe("sameOriginUrl", () => {
  const origin = window.location.origin;
  it("re-bases API links built with the backend's internal host or port", () => {
    expect(sameOriginUrl("http://139.5.189.155:8030/api/v1/downloads/abc.def:ghi/")).toBe(`${origin}/api/v1/downloads/abc.def:ghi/`);
    expect(sameOriginUrl("http://127.0.0.1:8000/api/v1/downloads/tok/?x=1")).toBe(`${origin}/api/v1/downloads/tok/?x=1`);
    expect(sameOriginUrl("/api/v1/downloads/tok/")).toBe(`${origin}/api/v1/downloads/tok/`);
  });
  it("leaves other URLs alone", () => {
    expect(sameOriginUrl("https://storage.example.test/container/file.glb?sig=1")).toBe("https://storage.example.test/container/file.glb?sig=1");
    expect(sameOriginUrl("blob:http://x/123")).toBe("blob:http://x/123");
  });
});
