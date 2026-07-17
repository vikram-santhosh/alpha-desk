import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchLatestDeploymentPlan } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function stubFetch(impl: () => Promise<unknown>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

// fetchLatestDeploymentPlan routes through fetchWithTimeout, so it exercises the
// shared error mapping that every cockpit request relies on.
describe("api fetch error mapping", () => {
  it("turns an aborted/timed-out request into a clear, actionable message", async () => {
    stubFetch(() => Promise.reject(new DOMException("Timed out after 15s", "TimeoutError")));
    await expect(fetchLatestDeploymentPlan()).rejects.toThrow(/timed out after \d+s/i);
  });

  it("never leaks the opaque 'signal is aborted without reason' message", async () => {
    stubFetch(() => Promise.reject(new DOMException("signal is aborted without reason", "AbortError")));
    await expect(fetchLatestDeploymentPlan()).rejects.toThrow(/is the backend running/i);
    await expect(fetchLatestDeploymentPlan()).rejects.not.toThrow(/aborted without reason/i);
  });

  it("reports an unreachable backend on a network failure", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    await expect(fetchLatestDeploymentPlan()).rejects.toThrow(/could not reach the backend/i);
  });

  it("returns null on 404 (no saved run) without throwing", async () => {
    stubFetch(() => Promise.resolve({ status: 404, ok: false } as Response));
    await expect(fetchLatestDeploymentPlan()).resolves.toBeNull();
  });
});
