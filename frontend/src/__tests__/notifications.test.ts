import { describe, expect, it } from "vitest";

import {
  MAX_BADGE_COUNT,
  NOTIFICATION_CHANNELS,
  NOTIFICATION_TYPES,
  badgeCount,
  channelForEmail,
  emailIsEnabled,
  notificationChip,
  notificationLabel,
  relativeAge,
} from "@/lib/notifications";

describe("NOTIFICATION_CHANNELS", () => {
  it("describes three channels that are governed three different ways", () => {
    // The distinction this step turns on: in-app is not a preference at all, email is the one
    // thing `notification_channel` governs, and push is a browser permission no stored value can
    // grant. Three radio buttons would have been three lies.
    expect(NOTIFICATION_CHANNELS.map((channel) => channel.value)).toEqual([
      "in_app",
      "email",
      "push",
    ]);
    expect(NOTIFICATION_CHANNELS.map((channel) => channel.governedBy)).toEqual([
      "always",
      "preference",
      "browser",
    ]);
  });

  it("never describes a channel as unavailable, because all three now deliver", () => {
    for (const channel of NOTIFICATION_CHANNELS) {
      expect(channel.note.toLowerCase(), channel.value).not.toContain("not built");
      expect(channel.note.toLowerCase(), channel.value).not.toContain("coming soon");
    }
  });
});

describe("the email preference", () => {
  it("reads the stored channel as an email toggle and nothing more", () => {
    expect(emailIsEnabled("email")).toBe(true);
    expect(emailIsEnabled("in_app")).toBe(false);
    // A value stored before Step 10. It grants nothing: push is gated on the subscription.
    expect(emailIsEnabled("push")).toBe(false);
  });

  it("writes only in_app or email, and never push", () => {
    expect(channelForEmail(true)).toBe("email");
    expect(channelForEmail(false)).toBe("in_app");
  });
});

describe("badgeCount", () => {
  it("counts up to the ceiling and then stops counting", () => {
    expect(badgeCount(0)).toBe("0");
    expect(badgeCount(7)).toBe("7");
    expect(badgeCount(MAX_BADGE_COUNT)).toBe(String(MAX_BADGE_COUNT));
    expect(badgeCount(MAX_BADGE_COUNT + 1)).toBe(`${MAX_BADGE_COUNT}+`);
    expect(badgeCount(4000)).toBe(`${MAX_BADGE_COUNT}+`);
  });
});

describe("notification labels", () => {
  it("names every type the backend service can create", () => {
    for (const type of NOTIFICATION_TYPES) {
      expect(notificationLabel(type), type).not.toBe(type);
      expect(notificationChip(type), type).toContain("border-");
    }
  });

  it("renders a type a later step adds without throwing", () => {
    expect(notificationLabel("shipment.delayed")).toBe("shipment delayed");
    expect(notificationChip("shipment.delayed")).toContain("border-border");
  });

  it("gives an integration failure the blocked colour, not the review one", () => {
    // A failed posting and a posting waiting on somebody are different states throughout this
    // platform, and the notification for a failure has to read as a failure.
    expect(notificationChip("integration.attention")).toContain("signal-blocked");
  });
});

describe("relativeAge", () => {
  const now = new Date("2026-08-28T12:00:00Z");

  it("reads in the unit a reader would use", () => {
    expect(relativeAge("2026-08-28T11:59:40Z", now)).toBe("just now");
    expect(relativeAge("2026-08-28T11:35:00Z", now)).toBe("25m ago");
    expect(relativeAge("2026-08-28T06:00:00Z", now)).toBe("6h ago");
    expect(relativeAge("2026-08-25T12:00:00Z", now)).toBe("3d ago");
    expect(relativeAge("2026-05-28T12:00:00Z", now)).toBe("3mo ago");
  });

  it("never reads as being in the future when clocks disagree slightly", () => {
    expect(relativeAge("2026-08-28T12:00:30Z", now)).toBe("just now");
  });

  it("returns nothing for a value it cannot read, rather than NaN", () => {
    expect(relativeAge("not a date", now)).toBe("");
  });
});
