import type { Metadata } from "next";

import { LegalPage } from "@/components/shared/legal-page";

export const metadata: Metadata = { title: "Disclaimer" };

export default function DisclaimerPage() {
  return (
    <LegalPage
      title="Disclaimer"
      version="Version 1.0"
      effectiveNote="effective on first production release, and reviewed at each platform release"
    >
      <div className="space-y-8">
        <section>
          <h2>Scope of this notice</h2>
          <p>
            AGFZE Command Centre is an internal operations platform used by AGFZE staff to coordinate
            trade correspondence, documentation, and approvals. This disclaimer sets out the limits
            of what the platform produces and how its output must be treated. It applies to every
            screen, export, and notification the platform generates, and to every person who signs
            in to it.
          </p>
        </section>

        <section>
          <h2>AI-assisted classification and extraction</h2>
          <p>
            The platform applies automated and AI-assisted processing to trade emails and their
            attachments in order to classify them, associate them with a counterparty and a
            transaction, and extract structured fields such as material grade, quantity, incoterm,
            delivery window, and price basis. That processing is probabilistic. It can misread a
            scanned page, attach a document to the wrong transaction, transpose a figure, or omit a
            field altogether - most often where the source is handwritten, poorly scanned,
            ambiguous, or laid out in a format the platform has not seen before.
          </p>
        </section>

        <section>
          <h2>Every automated output is a proposal</h2>
          <p>
            Anything the platform derives automatically is a proposal for a person to accept,
            correct, or reject. It is not a decision. No extracted value, classification, summary, or
            suggested action carries authority until a competent user has verified it against the
            underlying source document and recorded that verification in the platform. Where a
            confidence indicator is shown, it describes the system’s own certainty about its reading
            of the source. It is not an assurance of commercial or legal correctness, and a high
            confidence indicator never removes the obligation to verify.
          </p>
        </section>

        <section>
          <h2>Not an offer, quotation, or advice</h2>
          <p>
            Nothing presented in the platform constitutes a price quotation, an offer capable of
            acceptance, a binding contract, or financial, legal, tax, or investment advice. Draft
            documents and calculated figures shown on screen are internal working material. AGFZE
            enters into commercial commitments only through its authorised contracting process and
            only through the individuals mandated to make them.
          </p>
        </section>

        <section>
          <h2>Indicative pricing</h2>
          <p>
            Metal price references, including LME-linked values, premiums, and any figure derived
            from them, are indicative. They may be delayed, cached, interpolated, or based on a
            settlement that has since been revised. Confirm them against the authoritative source and
            the applicable contract terms before quoting them to a counterparty, pricing a
            transaction, or relying on them in a valuation.
          </p>
        </section>

        <section>
          <h2>The system of record</h2>
          <p>
            The platform supports the work; it does not replace the record. SAP and the approved,
            executed document set remain the systems of record for financial postings, inventory
            positions, and contractual obligations. Where the platform and the system of record
            disagree, the system of record prevails, and the discrepancy must be raised rather than
            worked around.
          </p>
        </section>

        <section>
          <h2>Release scope and availability</h2>
          <p>
            Functionality is delivered in stages. Modules described in the platform as scheduled are
            not available, and describing them is not a commitment that a capability will be
            delivered in a particular form or on a particular date. The platform is provided for
            internal business use, without warranty of uninterrupted availability or of fitness for
            any purpose beyond the internal workflows it is built to support.
          </p>
        </section>
      </div>
    </LegalPage>
  );
}
