/**
 * Mirrors the backend `NotificationType` vocabulary.
 *
 * Three channels deliver from Step 10 and they are independent of one another: in-app always,
 * for everybody; email additionally, by the preference below; push additionally, by a browser
 * subscription that no preference here can grant or revoke.
 */
export const NOTIFICATION_TYPES = [
  "exception.opened",
  "approval.requested",
  "approval.decided",
  "integration.attention",
  "report.ready",
] as const;

export type NotificationType = (typeof NOTIFICATION_TYPES)[number];

export const NOTIFICATION_LABELS: Record<NotificationType, string> = {
  "exception.opened": "Exception",
  "approval.requested": "Approval",
  "approval.decided": "Decision",
  "integration.attention": "Integration",
  "report.ready": "Report",
};

export const NOTIFICATION_CHIP: Record<NotificationType, string> = {
  "exception.opened": "border-pill-amber-border bg-pill-amber-bg text-pill-amber-text",
  "approval.requested": "border-border bg-muted text-muted-foreground",
  "approval.decided": "border-pill-green-border bg-pill-green-bg text-pill-green-text",
  "integration.attention": "border-pill-red-border bg-pill-red-bg text-pill-red-text",
  "report.ready": "border-border bg-muted text-muted-foreground",
};

export function notificationLabel(type: string): string {
  return NOTIFICATION_LABELS[type as NotificationType] ?? type.replace(/[._]/g, " ");
}

export function notificationChip(type: string): string {
  return (
    NOTIFICATION_CHIP[type as NotificationType] ?? "border-border bg-muted text-muted-foreground"
  );
}

/** What the badge shows. Above this it stops counting and says so, rather than growing. */
export const MAX_BADGE_COUNT = 99;

export function badgeCount(unread: number): string {
  return unread > MAX_BADGE_COUNT ? `${MAX_BADGE_COUNT}+` : String(unread);
}

/**
 * What `users.notification_channel` actually governs, now that all three channels deliver.
 *
 * It governs email, and only email. In-app is created for every notification and every user
 * regardless of what is stored here - it is the platform's durable record rather than a channel
 * somebody can switch off - and push is gated solely on whether this browser holds a
 * subscription, which is a browser permission and not a database value.
 *
 * `push` remains a value the API accepts so that anything stored before Step 10 still validates.
 * It grants nothing, and the settings page never writes it: enabling push is a browser permission
 * interaction with its own control beside this one.
 */
export const EMAIL_CHANNEL = "email";
export const IN_APP_CHANNEL = "in_app";

export type NotificationChannel = "in_app" | "email" | "push";

/** Whether a stored channel value means "also send me an email". */
export function emailIsEnabled(channel: string): boolean {
  return channel === EMAIL_CHANNEL;
}

/** What to store when the email toggle is turned on or off. */
export function channelForEmail(enabled: boolean): NotificationChannel {
  return enabled ? EMAIL_CHANNEL : IN_APP_CHANNEL;
}

/**
 * The three channels, for the settings page's own explanatory list. `governedBy` is the honest
 * answer to "how do I change this", and it is a different answer for each of them.
 */
export const NOTIFICATION_CHANNELS = [
  {
    value: "in_app",
    label: "In-app",
    governedBy: "always" as const,
    note: "Always on. Every notification is written to your notification centre and counted by the bell in the header - it is the platform's record, not a setting.",
  },
  {
    value: "email",
    label: "Email",
    governedBy: "preference" as const,
    note: "A copy of every notification, sent to your work address with a link into the screen it is about.",
  },
  {
    value: "push",
    label: "Push",
    governedBy: "browser" as const,
    note: "A notification from your browser the moment something needs you, even with the tab closed. Enabled per browser, by permission.",
  },
] as const;

/** Relative age, computed against a caller-supplied `now` so a render stays deterministic. */
export function relativeAge(iso: string, now: Date): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.max(0, Math.floor((now.getTime() - then) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return days < 30 ? `${days}d ago` : `${Math.floor(days / 30)}mo ago`;
}
