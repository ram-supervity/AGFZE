import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PushPrompt } from "@/components/pwa/push-prompt";
import { OfflineBanner } from "@/components/pwa/offline-banner";
import { ApiError, apiFetch } from "@/lib/api-client";
import { noteResponse, resetOfflineState, setOnline } from "@/lib/offline-state";
import { clearApplicationCaches } from "@/lib/pwa";
import { disablePush } from "@/lib/push";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: { accessToken: "test-token" }, status: "authenticated" }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

const fetchNotifications = vi.fn();
const removePushSubscription = vi.fn();

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    fetchNotifications: (...args: unknown[]) => fetchNotifications(...args),
    removePushSubscription: (...args: unknown[]) => removePushSubscription(...args),
  };
});

beforeEach(() => {
  window.localStorage.clear();
  resetOfflineState();
  fetchNotifications.mockReset();
  removePushSubscription.mockReset();
  removePushSubscription.mockResolvedValue({ removed: 1 });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the contextual push prompt", () => {
  function grantable() {
    // A browser that supports push and has not been asked yet.
    Object.defineProperty(window, "Notification", {
      configurable: true,
      writable: true,
      value: Object.assign(vi.fn(), { permission: "default", requestPermission: vi.fn() }),
    });
    Object.defineProperty(window, "PushManager", { configurable: true, writable: true, value: {} });
    Object.defineProperty(window.navigator, "serviceWorker", {
      configurable: true,
      writable: true,
      value: { getRegistration: vi.fn() },
    });
  }

  it("is not shown on initial page load", () => {
    grantable();
    fetchNotifications.mockResolvedValue({
      items: [{ id: "1", notification_type: "approval.requested", message: "x", link: null, is_read: false, created_at: "" }],
      page: { page: 1, page_size: 10, total: 1, total_pages: 1 },
      unread_count: 1,
    });

    render(<PushPrompt />);

    // Nothing on screen, and - more to the point - the browser has not been asked anything.
    expect(screen.queryByText(/be told the moment/i)).not.toBeInTheDocument();
    expect(fetchNotifications).not.toHaveBeenCalled();
  });

  it("appears only once an approval or an exception has actually reached this person", async () => {
    vi.useFakeTimers();
    grantable();
    fetchNotifications.mockResolvedValue({
      items: [
        {
          id: "1",
          notification_type: "approval.requested",
          message: "I2626-B1 is awaiting a decision.",
          link: "/approvals/1",
          is_read: false,
          created_at: "2026-08-28T09:00:00Z",
        },
      ],
      page: { page: 1, page_size: 10, total: 1, total_pages: 1 },
      unread_count: 1,
    });

    render(<PushPrompt />);
    await vi.advanceTimersByTimeAsync(9_000);
    vi.useRealTimers();

    await waitFor(() =>
      expect(screen.getByText(/be told the moment a decision is waiting/i)).toBeInTheDocument(),
    );
  });

  it("stays away when nothing is waiting on this person", async () => {
    vi.useFakeTimers();
    grantable();
    fetchNotifications.mockResolvedValue({
      items: [
        {
          id: "1",
          notification_type: "report.ready",
          message: "A report is ready.",
          link: "/reports/1",
          is_read: false,
          created_at: "2026-08-28T09:00:00Z",
        },
      ],
      page: { page: 1, page_size: 10, total: 1, total_pages: 1 },
      unread_count: 1,
    });

    render(<PushPrompt />);
    await vi.advanceTimersByTimeAsync(9_000);
    vi.useRealTimers();

    expect(screen.queryByText(/be told the moment/i)).not.toBeInTheDocument();
  });

  it("never asks a browser that has already refused", async () => {
    vi.useFakeTimers();
    grantable();
    (window.Notification as unknown as { permission: string }).permission = "denied";

    render(<PushPrompt />);
    await vi.advanceTimersByTimeAsync(9_000);
    vi.useRealTimers();

    expect(fetchNotifications).not.toHaveBeenCalled();
  });
});

describe("the offline banner", () => {
  it("says nothing at all while everything is live", () => {
    const { container } = render(<OfflineBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says how old cached data is rather than reporting an error", async () => {
    noteResponse(new Headers({ "x-agfze-cached-at": new Date(Date.now() - 5 * 60_000).toISOString() }));
    render(<OfflineBanner />);
    await waitFor(() =>
      expect(screen.getByText(/you’re viewing cached data from 5m ago/i)).toBeInTheDocument(),
    );
  });

  it("says plainly that nothing can be changed while the connection is gone", async () => {
    setOnline(false);
    render(<OfflineBanner />);
    await waitFor(() =>
      expect(
        screen.getByText(/nothing can be submitted, approved or changed/i),
      ).toBeInTheDocument(),
    );
  });
});

describe("a mutating request made offline", () => {
  it("is refused before it is attempted, and never reported as a success", async () => {
    const originalFetch = globalThis.fetch;
    const spy = vi.fn();
    globalThis.fetch = spy as unknown as typeof fetch;
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });

    await expect(
      apiFetch("/approvals/1/decide", { method: "POST", accessToken: "t", body: {} }),
    ).rejects.toMatchObject({ code: "offline" });
    // Not attempted at all: there is no queue behind it, so a request that cannot arrive must
    // not be started and must not look like it worked.
    expect(spy).not.toHaveBeenCalled();

    const error = await apiFetch("/approvals/1/decide", {
      method: "POST",
      accessToken: "t",
      body: {},
    }).catch((thrown) => thrown as ApiError);
    expect(error.message).toMatch(/needs a connection/i);
    expect(error.message).toMatch(/nothing has been saved/i);

    globalThis.fetch = originalFetch;
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
  });
});

describe("signing out", () => {
  it("deletes every cache on the origin, not only the ones this build named", async () => {
    const deleted: string[] = [];
    Object.defineProperty(globalThis, "caches", {
      configurable: true,
      writable: true,
      value: {
        keys: async () => ["agfze-runtime-1", "agfze-precache-1", "a-cache-an-older-build-made"],
        delete: async (name: string) => {
          deleted.push(name);
          return true;
        },
      },
    });

    await expect(clearApplicationCaches()).resolves.toBe(3);
    expect(deleted.sort()).toEqual(
      ["a-cache-an-older-build-made", "agfze-precache-1", "agfze-runtime-1"].sort(),
    );
  });

  it("unsubscribes this browser and forgets it on the server", async () => {
    const unsubscribe = vi.fn(async () => true);
    Object.defineProperty(window, "PushManager", { configurable: true, writable: true, value: {} });
    Object.defineProperty(window, "Notification", {
      configurable: true,
      writable: true,
      value: Object.assign(vi.fn(), { permission: "granted" }),
    });
    Object.defineProperty(window.navigator, "serviceWorker", {
      configurable: true,
      writable: true,
      value: {
        getRegistration: async () => ({
          pushManager: {
            getSubscription: async () => ({
              endpoint: "https://push.test/endpoint/this-browser",
              unsubscribe,
            }),
          },
        }),
      },
    });

    await disablePush("test-token");

    expect(unsubscribe).toHaveBeenCalled();
    expect(removePushSubscription).toHaveBeenCalledWith(
      "test-token",
      "https://push.test/endpoint/this-browser",
    );
  });

  it("still completes when there is nothing to unsubscribe and the API refuses", async () => {
    removePushSubscription.mockRejectedValue(new Error("offline"));
    Object.defineProperty(window.navigator, "serviceWorker", {
      configurable: true,
      writable: true,
      value: { getRegistration: async () => undefined },
    });

    // A sign-out that could fail because a tidy-up failed would leave a device signed in.
    await expect(disablePush("test-token")).resolves.toBeUndefined();
  });
});
