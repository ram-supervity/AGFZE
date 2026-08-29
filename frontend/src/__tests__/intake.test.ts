import { describe, expect, it } from "vitest";

import {
  BAND_BORDER,
  CATEGORY_LABELS,
  DOCUMENT_TYPES,
  DOCUMENT_TYPE_LABELS,
  MAX_UPLOAD_BYTES,
  REQUEST_CATEGORIES,
  canCorrect,
  confidenceBand,
  formatConfidence,
  labelFor,
  validateFileClientSide,
} from "@/lib/intake";

function file(name: string, size: number): File {
  const handle = new File([""], name);
  Object.defineProperty(handle, "size", { value: size });
  return handle;
}

describe("confidenceBand", () => {
  it("bands a score into the traffic-light triad at 0.9 and 0.7", () => {
    expect(confidenceBand(1)).toBe("confident");
    expect(confidenceBand(0.9)).toBe("confident");
    expect(confidenceBand(0.899)).toBe("review");
    expect(confidenceBand(0.7)).toBe("review");
    expect(confidenceBand(0.699)).toBe("blocked");
    expect(confidenceBand(0)).toBe("blocked");
  });

  it("treats an absent score as the weakest band rather than assuming the best", () => {
    expect(confidenceBand(null)).toBe("blocked");
    expect(confidenceBand(undefined)).toBe("blocked");
  });

  it("maps every band onto a signal token, and only onto a signal token", () => {
    for (const className of Object.values(BAND_BORDER)) {
      expect(className).toMatch(/^border-l-signal-(confident|review|blocked)$/);
    }
  });
});

describe("formatConfidence", () => {
  it("renders a score as a whole percentage", () => {
    expect(formatConfidence(0.934)).toBe("93%");
    expect(formatConfidence(1)).toBe("100%");
  });

  it("says so plainly when there is no score, rather than showing a zero", () => {
    expect(formatConfidence(null)).toBe("No score");
    expect(formatConfidence(undefined)).toBe("No score");
  });
});

describe("canCorrect", () => {
  it("admits the desks that own the work", () => {
    expect(canCorrect(["purchase_user"])).toBe(true);
    expect(canCorrect(["sales_user"])).toBe(true);
    expect(canCorrect(["fa_user"])).toBe(true);
    expect(canCorrect(["logistics_user"])).toBe(true);
    expect(canCorrect(["admin"])).toBe(true);
  });

  it("keeps the approver and the auditor out of the correcting seat", () => {
    expect(canCorrect(["approver_hod"])).toBe(false);
    expect(canCorrect(["auditor"])).toBe(false);
    expect(canCorrect(["finance_user"])).toBe(false);
    expect(canCorrect([])).toBe(false);
  });

  it("admits an account that also holds a correcting role", () => {
    expect(canCorrect(["approver_hod", "purchase_user"])).toBe(true);
  });
});

describe("validateFileClientSide", () => {
  it("accepts every whitelisted extension", () => {
    for (const name of ["a.pdf", "b.docx", "c.xlsx", "d.xls", "e.csv", "f.jpg", "g.png"]) {
      expect(validateFileClientSide(file(name, 1024)), name).toBeNull();
    }
  });

  it("refuses a type that is not on the whitelist", () => {
    expect(validateFileClientSide(file("payload.exe", 1024))).toMatch(/only pdf/i);
    expect(validateFileClientSide(file("archive.zip", 1024))).toMatch(/only pdf/i);
  });

  it("refuses an empty file and one over the 25 MB limit", () => {
    expect(validateFileClientSide(file("empty.pdf", 0))).toMatch(/empty/i);
    expect(validateFileClientSide(file("huge.pdf", MAX_UPLOAD_BYTES + 1))).toMatch(/25 MB/);
    expect(validateFileClientSide(file("exact.pdf", MAX_UPLOAD_BYTES))).toBeNull();
  });
});

describe("vocabularies", () => {
  it("labels every category and document type the backend can send", () => {
    for (const category of REQUEST_CATEGORIES) {
      expect(CATEGORY_LABELS[category], category).toBeTruthy();
    }
    for (const type of DOCUMENT_TYPES) {
      expect(DOCUMENT_TYPE_LABELS[type], type).toBeTruthy();
    }
  });

  it("falls back to the raw value rather than showing nothing for an unknown one", () => {
    expect(labelFor(CATEGORY_LABELS, "purchase")).toBe("Purchase");
    expect(labelFor(CATEGORY_LABELS, "something_new")).toBe("something_new");
    expect(labelFor(CATEGORY_LABELS, null)).toBe("-");
  });
});
