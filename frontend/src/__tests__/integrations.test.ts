import { describe, expect, it } from "vitest";

import {
  INTEGRATION_JOB_STATUSES,
  INTEGRATION_STATUS_CHIP,
  INTEGRATION_STATUS_LABELS,
  INTEGRATION_STATUS_NOTES,
  INTEGRATION_TARGETS,
  INTEGRATION_TARGET_LABELS,
  attemptLabel,
  canCompleteManually,
  canManageIntegrations,
  canRetry,
  successProvenance,
  targetAvailabilityNote,
} from "@/lib/integrations";

describe("the integration vocabulary", () => {
  it("names the three target systems and no others", () => {
    expect(INTEGRATION_TARGETS).toEqual(["tracker", "sap", "dms"]);
    for (const target of INTEGRATION_TARGETS) {
      expect(INTEGRATION_TARGET_LABELS[target]).toBeTruthy();
    }
  });

  it("carries the fifth job status, which is neither a success nor a failure", () => {
    expect(INTEGRATION_JOB_STATUSES).toEqual([
      "queued",
      "processing",
      "succeeded",
      "failed",
      "awaiting_manual_action",
    ]);
  });

  it("gives every status a label, a colour and an explanation", () => {
    for (const status of INTEGRATION_JOB_STATUSES) {
      expect(INTEGRATION_STATUS_LABELS[status], status).toBeTruthy();
      expect(INTEGRATION_STATUS_CHIP[status], status).toBeTruthy();
      expect(INTEGRATION_STATUS_NOTES[status], status).toBeTruthy();
    }
  });

  it("never colours a job waiting on a person the same as a failed one", () => {
    // The two mean entirely different things and call for different actions, so they must not be
    // able to look alike on the monitor.
    expect(INTEGRATION_STATUS_CHIP.awaiting_manual_action).not.toBe(
      INTEGRATION_STATUS_CHIP.failed,
    );
    expect(INTEGRATION_STATUS_LABELS.awaiting_manual_action).not.toBe(
      INTEGRATION_STATUS_LABELS.failed,
    );
    expect(INTEGRATION_STATUS_CHIP.failed).toContain("signal-blocked");
    expect(INTEGRATION_STATUS_CHIP.awaiting_manual_action).toContain("signal-review");
  });
});

describe("the two actions", () => {
  it("offers retry only for a job that genuinely failed", () => {
    expect(canRetry("failed")).toBe(true);
    expect(canRetry("awaiting_manual_action")).toBe(false);
    expect(canRetry("succeeded")).toBe(false);
    expect(canRetry("queued")).toBe(false);
  });

  it("offers manual completion only for a job waiting on a person", () => {
    expect(canCompleteManually("awaiting_manual_action")).toBe(true);
    expect(canCompleteManually("failed")).toBe(false);
    expect(canCompleteManually("succeeded")).toBe(false);
  });

  it("never offers both for the same job", () => {
    for (const status of INTEGRATION_JOB_STATUSES) {
      expect(canRetry(status) && canCompleteManually(status), status).toBe(false);
    }
  });
});

describe("canManageIntegrations", () => {
  it("admits an administrator and nobody else", () => {
    expect(canManageIntegrations(["admin"])).toBe(true);
    expect(canManageIntegrations(["purchase_user"])).toBe(false);
    expect(canManageIntegrations(["approver_hod"])).toBe(false);
    expect(canManageIntegrations(["auditor"])).toBe(false);
    expect(canManageIntegrations([])).toBe(false);
  });
});

describe("successProvenance", () => {
  it("always says when a posting was completed by a person", () => {
    expect(successProvenance(true, "Ayesha Karim")).toContain("by hand");
    expect(successProvenance(true, "Ayesha Karim")).toContain("Ayesha Karim");
    expect(successProvenance(true, null)).toContain("by hand");
  });

  it("describes an automated posting as automated, and never as a person's", () => {
    const automated = successProvenance(false, null);
    expect(automated).toContain("automatically");
    expect(automated).not.toContain("by hand");
  });
});

describe("attemptLabel", () => {
  it("reads plainly before and after the first attempt", () => {
    expect(attemptLabel(0, 5)).toBe("No attempts yet");
    expect(attemptLabel(2, 5)).toBe("Attempt 2 of 5");
  });
});

describe("targetAvailabilityNote", () => {
  it("says an unconfigured target is expected rather than broken", () => {
    const note = targetAvailabilityNote("sap", false);
    expect(note).toContain("SAP");
    expect(note).toContain("not a failure");
  });

  it("says a configured target posts automatically", () => {
    expect(targetAvailabilityNote("dms", true)).toContain("automatically");
  });
});
