/**
 * The browser half of Web Push: permission, subscription, and telling the API about both.
 *
 * Push on this platform is gated by one thing - whether a subscription exists on the server - so
 * everything here is about creating or removing exactly that. There is no preference to set
 * alongside it, and none of these functions writes one.
 */

import {
  fetchVapidPublicKey,
  removePushSubscription,
  savePushSubscription,
} from "@/lib/api-client";

export type PushPermission = "default" | "granted" | "denied" | "unsupported";

export function pushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function pushPermission(): PushPermission {
  if (!pushSupported()) return "unsupported";
  return Notification.permission as PushPermission;
}

/** The VAPID public key arrives as URL-safe base64 and `pushManager` wants raw bytes. */
export function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normalised = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(normalised);
  const bytes = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
  return bytes;
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const registration = await navigator.serviceWorker.getRegistration();
  if (!registration) return null;
  return registration.pushManager.getSubscription();
}

export interface SubscribeResult {
  ok: boolean;
  reason?: "unsupported" | "denied" | "no-worker" | "not-configured" | "failed";
}

/**
 * Ask for permission, subscribe this browser, and register it with the API.
 *
 * The application server key comes from the API rather than only from the build, so a deployment
 * that rotates it does not need the frontend rebuilt to stop handing out a key the server can no
 * longer sign with.
 */
export async function enablePush(accessToken: string): Promise<SubscribeResult> {
  if (!pushSupported()) return { ok: false, reason: "unsupported" };

  const permission = await Notification.requestPermission();
  if (permission !== "granted") return { ok: false, reason: "denied" };

  const registration = await navigator.serviceWorker.getRegistration();
  // No worker means no push, and this is where the production-only registration rule is felt:
  // push cannot be exercised against `npm run dev`.
  if (!registration) return { ok: false, reason: "no-worker" };

  let key = "";
  try {
    const published = await fetchVapidPublicKey(accessToken);
    key = published.configured ? published.public_key : "";
  } catch {
    key = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY ?? "";
  }
  if (!key) return { ok: false, reason: "not-configured" };

  try {
    const existing = await registration.pushManager.getSubscription();
    const subscription =
      existing ??
      (await registration.pushManager.subscribe({
        // Required by every browser that implements Web Push: a subscription that could deliver
        // a payload the user cannot see is not one this platform asks for.
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key) as BufferSource,
      }));
    const payload = subscription.toJSON() as { endpoint?: string; keys?: Record<string, string> };
    if (!payload.endpoint || !payload.keys?.p256dh || !payload.keys?.auth) {
      return { ok: false, reason: "failed" };
    }
    await savePushSubscription(accessToken, {
      endpoint: payload.endpoint,
      keys: { p256dh: payload.keys.p256dh, auth: payload.keys.auth },
    });
    return { ok: true };
  } catch {
    return { ok: false, reason: "failed" };
  }
}

/**
 * Unsubscribe this browser and forget it on the server.
 *
 * The server call is attempted whatever the browser does, and a failure on either side is not
 * allowed to fail the caller: this runs on the sign-out path, where the worst possible outcome is
 * a sign-out that refuses to complete.
 */
export async function disablePush(accessToken: string | undefined): Promise<void> {
  let endpoint: string | undefined;
  try {
    const subscription = await currentSubscription();
    if (subscription) {
      endpoint = subscription.endpoint;
      await subscription.unsubscribe();
    }
  } catch {
    /* the browser had nothing to unsubscribe */
  }
  if (!accessToken) return;
  try {
    await removePushSubscription(accessToken, endpoint);
  } catch {
    /* the row is orphaned at worst, and the next 410 from the push service removes it */
  }
}
