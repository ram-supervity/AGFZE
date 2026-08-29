import type { Metadata } from "next";

import { OfflineView } from "@/components/pwa/offline-view";

export const metadata: Metadata = {
  title: "Offline",
  description: "You are offline. What you have already opened stays readable.",
};

/**
 * The page the service worker serves when a navigation has no network and nothing cached.
 *
 * It sits outside every route group on purpose. The protected layout reads the session on the
 * server and would redirect to the identity provider, which is exactly the request that cannot be
 * made without a connection - so the one page whose whole job is to work offline must not depend
 * on anything the server has to answer.
 *
 * Precached at install time, so it is present before it is ever needed.
 */
export default function OfflinePage() {
  return <OfflineView />;
}
