"use client";

import { useEffect } from "react";

import { registerServiceWorker } from "@/lib/pwa";
import { setOnline } from "@/lib/offline-state";

/**
 * Registers the service worker, and keeps the application's idea of "online" honest.
 *
 * Mounted in the root layout so it also covers `/offline` and the sign-in screens - a browser
 * that lost its connection on the way to signing in should still get the offline page rather than
 * the browser's own error.
 *
 * Registration happens in production builds only. `registerServiceWorker` enforces that and, in
 * development, actively unregisters anything a previous production build left on this origin.
 */
export function ServiceWorkerRegistrar() {
  useEffect(() => {
    void registerServiceWorker();

    setOnline(navigator.onLine);
    const online = () => setOnline(true);
    const offline = () => setOnline(false);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);

  return null;
}
