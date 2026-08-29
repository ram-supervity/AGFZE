"use client";

import { useSyncExternalStore } from "react";

import {
  getOfflineState,
  subscribeToOfflineState,
  type OfflineState,
} from "@/lib/offline-state";

const SERVER_STATE: OfflineState = { online: true, cachedAt: null };

/**
 * The connection state, read through `useSyncExternalStore` so the server render and the first
 * client render agree: the server has no connection state to report and always says online, and
 * the real value arrives on the first client tick rather than as a hydration mismatch.
 */
export function useOfflineState(): OfflineState {
  return useSyncExternalStore(subscribeToOfflineState, getOfflineState, () => SERVER_STATE);
}
