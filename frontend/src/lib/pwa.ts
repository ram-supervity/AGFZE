/**
 * Installing, registering and - on sign-out - completely forgetting this application.
 *
 * The one rule worth stating at the top: **the service worker is registered in production builds
 * only.** In development it is actively unregistered instead. A worker that holds onto assets
 * while Next.js is hot-reloading them makes a development environment that lies to you, and the
 * hour spent working out why an edit did not appear is worse than not having offline support on
 * localhost. See the README for how to exercise the worker properly (`npm run build && npm start`).
 */

export const SERVICE_WORKER_URL = "/sw.js";

/** Chromium fires this before showing its own install affordance; iOS Safari never does. */
export interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
  prompt(): Promise<void>;
}

export function serviceWorkerSupported(): boolean {
  return typeof navigator !== "undefined" && "serviceWorker" in navigator;
}

/** True only in a production bundle. The single gate on the worker ever being registered. */
export function serviceWorkerEnabled(): boolean {
  return process.env.NODE_ENV === "production" && serviceWorkerSupported();
}

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!serviceWorkerEnabled()) {
    // Development: tear down anything a previous production build on this origin left behind,
    // so `npm run dev` on port 3000 is never served yesterday's cached bundle.
    await unregisterServiceWorkers();
    return null;
  }
  try {
    return await navigator.serviceWorker.register(SERVICE_WORKER_URL, { scope: "/" });
  } catch {
    // An unregistered worker costs offline support and nothing else. The application works.
    return null;
  }
}

export async function unregisterServiceWorkers(): Promise<void> {
  if (!serviceWorkerSupported()) return;
  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
  } catch {
    /* nothing to unregister, or storage is unavailable */
  }
}

/**
 * Delete every cache this origin holds.
 *
 * Not only the caches whose names this build recognises: a cached screen can name a counterparty
 * and quote a price, and on a shared or lost device the correct amount of that left behind after
 * a sign-out is none of it, including anything an older build wrote under a name this one has
 * never heard of.
 */
export async function clearApplicationCaches(): Promise<number> {
  if (typeof caches === "undefined") return 0;
  try {
    const names = await caches.keys();
    await Promise.all(names.map((name) => caches.delete(name)));
    return names.length;
  } catch {
    return 0;
  }
}

/** iOS Safari, which never fires `beforeinstallprompt` and installs from the Share sheet. */
export function isIosSafari(): boolean {
  if (typeof navigator === "undefined") return false;
  const agent = navigator.userAgent;
  const isIos = /iPad|iPhone|iPod/.test(agent) || (agent.includes("Macintosh") && "ontouchend" in document);
  const isSafari = /Safari/.test(agent) && !/CriOS|FxiOS|EdgiOS|OPiOS/.test(agent);
  return isIos && isSafari;
}

/** Whether the app is already running as an installed application. */
export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  const iosStandalone = (window.navigator as Navigator & { standalone?: boolean }).standalone;
  return window.matchMedia?.("(display-mode: standalone)").matches === true || iosStandalone === true;
}
