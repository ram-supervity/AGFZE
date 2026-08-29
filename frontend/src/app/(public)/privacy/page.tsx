import type { Metadata } from "next";

import { LegalPage } from "@/components/shared/legal-page";

export const metadata: Metadata = { title: "Privacy Notice" };

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Notice"
      version="Version 1.0"
      effectiveNote="effective on first production release, and reviewed at each platform release"
    >
      <div className="space-y-8">
        <section>
          <h2>Who this notice is for</h2>
          <p>
            AGFZE Command Centre is an internal platform, available only to AGFZE staff and to
            contractors working under AGFZE supervision. This notice explains what the platform
            processes, why, who can see it, how long it is kept, and how to raise a question about
            it. AGFZE is the controller of the information described here.
          </p>
        </section>

        <section>
          <h2>What the platform processes</h2>
          <p>
            <span className="font-medium">Corporate identity.</span> Your name, work email address,
            the identifiers issued to your account, the platform roles assigned to you, and the time
            of your most recent sign-in. Identity is supplied by Microsoft Entra ID and brokered
            through Keycloak; the platform never receives or stores your password.
          </p>
          <p>
            <span className="font-medium">Trade correspondence and attachments.</span> Email routed
            to platform mailboxes, including sender and recipient addresses, subject lines, message
            bodies, and attached documents such as enquiries, offers, contracts, invoices, packing
            lists, and transport documents. Business correspondence routinely contains the names and
            contact details of counterparty staff, and those details are processed with it.
          </p>
          <p>
            <span className="font-medium">Actions and audit trail.</span> A record of what was done
            in the platform: which record was opened, changed, submitted, approved, or rejected, by
            whom, and when, together with the technical request identifier that ties the action to a
            server log entry.
          </p>
          <p>
            <span className="font-medium">Operational logs.</span> Request metadata and diagnostic
            information used to keep the service running and to investigate faults.
          </p>
        </section>

        <section>
          <h2>Why it is processed</h2>
          <p>
            Processing is carried out in AGFZE’s legitimate business interest in operating,
            supervising, and auditing its trading operations, and where it is necessary to perform or
            prepare a contract with a counterparty. Retention of commercial records is also required
            to meet AGFZE’s accounting, tax, and regulatory obligations. Staff use of the platform is
            processed in the context of the employment or engagement relationship.
          </p>
        </section>

        <section>
          <h2>Who can see what</h2>
          <p>
            Access is granted by role, on a least-privilege basis. A role determines which modules
            you can open and which records within them you can read or act on. Auditors receive
            read-only visibility for assurance purposes. Administrators can manage accounts and
            configuration; they do not receive an exemption from the audit trail, and their actions
            are recorded in the same way as everyone else’s.
          </p>
        </section>

        <section>
          <h2>Where it is held and who processes it</h2>
          <p>
            Platform data is held in managed cloud infrastructure operated by AGFZE’s hosting
            provider in the regions AGFZE selects for the deployment. Two categories of sub-processor
            are engaged: the cloud hosting and managed database provider, and the provider of the AI
            extraction service used to read documents. Both act only on AGFZE’s documented
            instructions under a written processing agreement. Content submitted to the AI extraction
            service is not used to train that provider’s models.
          </p>
        </section>

        <section>
          <h2>How long it is kept</h2>
          <p>
            Transaction records, correspondence, and the documents attached to them are retained for
            the period required for commercial records under the law and free zone regulations
            applicable to AGFZE, and for any longer period required by an open dispute, audit, or
            legal hold. Operational logs are kept for a substantially shorter period, sufficient to
            investigate incidents and monitor service health. Identity records are removed once an
            account is closed and the retention period for the actions attributed to it has passed.
          </p>
          <p>
            The audit trail is append-only. No user, of any role, can edit or delete an audit entry
            through the platform, and no interface for doing so is exposed.
          </p>
        </section>

        <section>
          <h2>Your rights and how to ask</h2>
          <p>
            You may ask what the platform holds about you, ask for an inaccuracy in your identity or
            role assignment to be corrected, and object to a specific processing activity. Requests
            about your own record, and any question about this notice, go to the IT service desk,
            which will route them to the data protection contact. Requests are answered within the
            period set by AGFZE’s internal policy; where a record must be retained for a legal or
            regulatory reason, that reason is explained rather than the record being deleted.
          </p>
        </section>
      </div>
    </LegalPage>
  );
}
