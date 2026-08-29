/**
 * What the application currently knows about its own connection, in one small store.
 *
 * It answers two questions and no others: are we online, and is what is on screen a cached copy?
 * The second is answered by the service worker, which stamps every response it serves out of
 * storage with the moment it was stored - so the banner can say "cached at 09:14" as a fact
 * rather than as a guess.
 *
 * Deliberately not a context provider: this is read by a banner, by a button and by an error
 * path, none of which share a tree, and none of which should re-render the application when the
 * connection blinks.
 */

export const CACHED_AT_HEADER = "x-agfze-cached-at";

export interface OfflineState {
  online: boolean;
  /** ISO timestamp of the newest cached response served, or null when everything is live. */
  cachedAt: string | null;
}

let state: OfflineState = { online: true, cachedAt: null };
const listeners = new Set<() => void>();

function publish(next: OfflineState): void {
  if (next.online === state.online && next.cachedAt === state.cachedAt) return;
  state = next;
  for (const listener of listeners) listener();
}

export function getOfflineState(): OfflineState {
  return state;
}

export function subscribeToOfflineState(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setOnline(online: boolean): void {
  // Coming back online clears the stale marker: the next read is live, and leaving the banner up
  // would be its own small lie.
  publish({ online, cachedAt: online ? null : state.cachedAt });
}

/** Called for every API response the browser receives. */
export function noteResponse(headers: Headers | null | undefined): void {
  const cachedAt = headers?.get(CACHED_AT_HEADER) ?? null;
  publish({ online: state.online, cachedAt });
}

export function resetOfflineState(): void {
  state = { online: true, cachedAt: null };
  for (const listener of listeners) listener();
}
