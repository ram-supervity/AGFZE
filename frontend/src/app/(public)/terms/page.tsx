import type { Metadata } from "next";

import { LegalPage } from "@/components/shared/legal-page";

export const metadata: Metadata = { title: "Terms of Use" };

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Use"
      version="Version 1.0"
      effectiveNote="effective on first production release, and reviewed at each platform release"
    >
      <div className="space-y-8">
        <section>
          <h2>1. Scope</h2>
          <p>
            These terms govern the use of AGFZE Command Centre, an internal platform provided by
            AGFZE for the coordination of trade correspondence, documentation, and approvals. Signing
            in confirms your acceptance of them. They apply to every user, in every role, on every
            device used to reach the platform.
          </p>
        </section>

        <section>
          <h2>2. Authorised users and credentials</h2>
          <p>
            The platform is for authorised AGFZE staff and supervised contractors only. Your account
            is personal to you. Do not share your credentials, do not let another person work under
            your session, and do not sign in on behalf of a colleague — including where doing so
            would be quicker or a colleague is absent. If you believe your credentials have been
            exposed, report it to the IT service desk immediately. Access ends when your engagement
            with AGFZE ends.
          </p>
        </section>

        <section>
          <h2>3. Act within your role</h2>
          <p>
            Roles define what you may see and do. Work within the role assigned to you, and do not
            attempt to reach data or functions outside it, whether by manipulating a link, an
            identifier, an export, or an integration. If you need broader access to do your job,
            request it through the role assignment process rather than working around the controls.
          </p>
        </section>

        <section>
          <h2>4. Four-eyes principle for approvals</h2>
          <p>
            Approvals require two people. The person who prepares or submits a transaction may not
            also approve it, and an approver may not approve their own submission through a
            delegated or shared account. Where an approval is delegated during absence, the
            delegation is recorded, and the delegate approves in their own name. Circumventing this
            separation is a breach of these terms regardless of the commercial urgency.
          </p>
        </section>

        <section>
          <h2>5. Accuracy remains your responsibility</h2>
          <p>
            The platform proposes; people decide. Automated classification and extraction are aids,
            and the responsibility for the accuracy of a record stays with the user who submits it
            and with the user who approves it. Verify proposed values against the source document
            before you accept them. An error in an approved record is not excused by the fact that
            the platform suggested it.
          </p>
        </section>

        <section>
          <h2>6. Acceptable use</h2>
          <p>
            Use the platform only for AGFZE business. Do not upload material unrelated to a
            transaction, malicious files, or content you are not entitled to hold. Do not probe,
            scan, or attempt to bypass the platform’s security controls, and do not connect
            unapproved tools, scripts, or automation to it. Do not copy platform data into personal
            accounts, personal devices, or unapproved third-party services, including general-purpose
            AI tools.
          </p>
        </section>

        <section>
          <h2>7. Monitoring</h2>
          <p>
            Use of the platform is logged and monitored for security, service reliability, and audit
            purposes. Actions taken in the platform are recorded against the acting account in an
            append-only audit trail that no user can edit or delete. Monitoring is proportionate and
            is carried out under AGFZE’s IT and employment policies.
          </p>
        </section>

        <section>
          <h2>8. Confidentiality</h2>
          <p>
            Counterparty identities, negotiated prices, premiums, contract terms, volumes, and
            shipment details are confidential business information. Do not disclose them outside
            AGFZE, or inside AGFZE to colleagues who have no business need to know. Take particular
            care with screenshots, forwarded email, and exports — the platform’s access controls do
            not follow a file once it leaves the platform. Confidentiality obligations continue after
            your access ends.
          </p>
        </section>

        <section>
          <h2>9. Availability and change</h2>
          <p>
            The platform is delivered in stages and is provided without a guarantee of uninterrupted
            availability. AGFZE may add, change, restrict, or withdraw functionality, and may suspend
            access for maintenance or for security reasons. Where a change materially affects how you
            work, it is communicated in advance where it is practical to do so.
          </p>
        </section>

        <section>
          <h2>10. Consequences of misuse</h2>
          <p>
            Breach of these terms may lead to suspension or withdrawal of access, disciplinary action
            under AGFZE’s employment policies, termination of a contractor engagement, and — where
            the conduct warrants it — referral to the relevant authorities and recovery of loss.
            Suspected breaches are investigated by the platform team together with the responsible
            business owner.
          </p>
        </section>

        <section>
          <h2>11. Relationship to other policies</h2>
          <p>
            These terms sit beneath AGFZE’s employment, IT acceptable use, information security, and
            data protection policies and do not replace them. Where a conflict arises, the broader
            AGFZE policy prevails. The platform’s Disclaimer and Privacy Notice are read together
            with these terms.
          </p>
        </section>
      </div>
    </LegalPage>
  );
}
