import type { PlatformRole } from "@/lib/roles";
import { hasAnyRole } from "@/lib/roles";

/** Admin for the platform, Auditor for the independent oversight the role exists to give. */
export const AUDIT_READ_ROLES: readonly PlatformRole[] = ["admin", "auditor"];

export function canReadAuditTrail(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, AUDIT_READ_ROLES);
}

/**
 * Prose for an event type, derived rather than enumerated.
 *
 * There is deliberately no map of every event type here. Ten  have contributed to this
 * vocabulary and an eleventh will contribute more, so the explorer's filter is populated from the
 * data the API actually holds and each value is rendered by splitting it on its own separators.
 * A hardcoded list would be wrong the day a new event is first recorded.
 */
export function eventTypeLabel(value: string): string {
  const [domain, ...rest] = value.split(".");
  const action = rest.join(" ").replace(/[._]/g, " ");
  const readable = action ? `${domain} — ${action}` : domain.replace(/_/g, " ");
  return readable.charAt(0).toUpperCase() + readable.slice(1);
}

export function entityTypeLabel(value: string): string {
  const readable = value.replace(/_/g, " ");
  return readable.charAt(0).toUpperCase() + readable.slice(1);
}

/** Every actor type the trail permits. `system` is a real actor, not a missing one. */
export const ACTOR_TYPE_LABELS: Record<string, string> = {
  user: "Person",
  system: "Platform",
  agent: "AI agent",
};

export function actorLabel(
  actorType: string,
  actorName: string | null,
  actorEmail: string | null,
): string {
  if (actorName) return actorEmail ? `${actorName} (${actorEmail})` : actorName;
  return ACTOR_TYPE_LABELS[actorType] ?? actorType;
}

/**
 * A one-line rendering of the metadata a row carries.
 *
 * The API has already redacted by key and bounded by length; this only decides what fits on a
 * table row. Nothing here renders document text or a model prompt, because nothing in the payload
 * it is handed contains any — the metadata discipline is upheld at every call site that writes
 * one, and the read layer redacts anything that ever slipped.
 */
export function metadataSummary(metadata: Record<string, unknown>, limit = 4): string {
  const entries = Object.entries(metadata ?? {}).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  );
  if (entries.length === 0) return "No further detail recorded.";
  const shown = entries
    .slice(0, limit)
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${String(value)}`)
    .join(" · ");
  const remaining = entries.length - Math.min(limit, entries.length);
  return remaining > 0 ? `${shown} · +${remaining} more` : shown;
}

/** The filters the explorer offers, and the only ones the API accepts. */
export interface AuditFilters {
  date_from?: string;
  date_to?: string;
  event_type?: string;
  actor_id?: string;
  entity_type?: string;
  search?: string;
}

export function auditQueryString(filters: AuditFilters): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) search.set(key, value);
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : "";
}
