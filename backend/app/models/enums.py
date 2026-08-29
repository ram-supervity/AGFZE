"""Vocabularies shared by the intake models, the API schemas and the AI prompts.

Every value is stored as a plain string column guarded by a check constraint rather than a
PostgreSQL enum, matching the pattern `background_jobs.status` established in : a later
 adds a state without a type-altering migration.
"""

from __future__ import annotations

from enum import Enum


class RequestSource(str, Enum):
    EMAIL = "email"
    PORTAL = "portal"


class RequestCategory(str, Enum):
    PURCHASE = "purchase"
    SALES = "sales"
    FA = "fa"
    LOGISTICS = "logistics"
    APPROVAL = "approval"
    FOLLOW_UP = "follow_up"
    INFORMATIONAL = "informational"
    EXCEPTION = "exception"


class BusinessStream(str, Enum):
    SCRAP = "scrap"
    FA = "fa"


class RequestStatus(str, Enum):
    """ owns exactly these four states.

    `Matched`, `Validation Pending`, `Approval Pending`, `Committed` and the rest of the
    lifecycle are introduced from  onwards and must not be referenced here.
    """

    RECEIVED = "received"
    CLASSIFIED = "classified"
    EXTRACTION_PENDING = "extraction_pending"
    EXTRACTED = "extracted"


class TransactionStatus(str, Enum):
    """The trade transaction lifecycle.

    The first four mirror the request states  owns, so a transaction created straight off a
    confirmed extraction carries the same vocabulary its request does.  added the three that
    follow and  added `APPROVED`, which was where the lifecycle stopped for exactly as long
    as there was nothing downstream of it.

     adds the two states that make an approval mean something outside this platform.
    `INTEGRATION_PENDING` is set the moment a transaction's three integration jobs are created,
    and `COMMITTED` only once all three are genuinely resolved - by a real automated success or
    by an admin's explicit, reasoned confirmation that they finished the posting by hand.

    `CLOSED` is declared and deliberately unreachable. Closing a deal turns on payment
    confirmation and full documentation and shipment completeness, none of which is concretely
    specified for this platform, so no code path sets it. It is here so the vocabulary is honest
    about the state existing, not so something can quietly move a transaction into it.
    """

    RECEIVED = "received"
    CLASSIFIED = "classified"
    EXTRACTION_PENDING = "extraction_pending"
    EXTRACTED = "extracted"
    MATCHED = "matched"
    VALIDATION_PENDING = "validation_pending"
    APPROVAL_PENDING = "approval_pending"
    APPROVED = "approved"
    INTEGRATION_PENDING = "integration_pending"
    COMMITTED = "committed"
    CLOSED = "closed"


class PriceBasis(str, Enum):
    """How a deal's price is arrived at.

    `THREE_MONTH_LME` is discovery's third sales pricing mechanism, alongside a locked price and a
    straight percentage of the LME: the price is struck against the three-month LME quotation
    taken ahead of ETD/ETA rather than against the cash settlement of a single day.

    The averaged figure itself is *recorded* here, never computed. Discovery is explicit that the
    exchange has no usable feed - "West Metal website (no public API available)... user manually
    enters 3-month LME price for the day" - so this platform holds no daily price series to
    average. Producing an average from data it does not have would be inventing the price, which
    is precisely the class of number this platform exists to stop appearing.
    """

    FIXED = "fixed"
    LME_PERCENT = "lme_percent"
    THREE_MONTH_LME = "three_month_lme"


# The two bases whose price moves with the exchange. A rule that compares a contracted LME
# percentage against the one recorded on a transaction applies to both, and grouping them here
# rather than naming `lme_percent` at each call site is what stops a deal quietly falling out of a
# check by being re-classified from one LME basis to the other.
LME_LINKED_PRICE_BASES: tuple[str, ...] = (
    PriceBasis.LME_PERCENT.value,
    PriceBasis.THREE_MONTH_LME.value,
)


class InvoiceStatus(str, Enum):
    """A batch is commonly invoiced twice: provisionally while unfixed, finally once priced."""

    PROVISIONAL = "provisional"
    FINAL = "final"


class MatchMethod(str, Enum):
    """How a document came to sit on the transaction it sits on."""

    BATCH_NUMBER = "batch_number"
    FUZZY_AUTO = "fuzzy_auto"
    NEW_BATCH = "new_batch"
    SUGGESTION_CONFIRMED = "suggestion_confirmed"
    MANUAL = "manual"
    SUPERSESSION = "supersession"
    DUPLICATE_LINK = "duplicate_link"


class RuleSeverity(str, Enum):
    """What a failing evaluation means for the transaction it belongs to.

    `ACKNOWLEDGEABLE` is the only severity a preparing user can clear on their own, and only
    through an explicit, logged acknowledgement. `HARD` blocks submission until the underlying
    data is corrected, whatever its size.
    """

    HARD = "hard"
    ACKNOWLEDGEABLE = "acknowledgeable"
    INFORMATIONAL = "informational"


class ExceptionCategory(str, Enum):
    """The ten categories of the governing exception matrix.

    All ten are registered from the outset so the queue's structure is complete and needs no
    restructuring later. Three of them were dormant for a while - the container mismatch and the
    stalled shipment until the shipment module arrived, and the integration failure until the
    integration hub did. From  onwards every category has producing code behind it.
    """

    MISSING_MANDATORY_DOCUMENT = "missing_mandatory_document"
    MISMATCHED_CONTAINER_NUMBER = "mismatched_container_number"
    INVOICE_AMOUNT_OUTSIDE_TOLERANCE = "invoice_amount_outside_tolerance"
    QUANTITY_VARIATION_OUTSIDE_TOLERANCE = "quantity_variation_outside_tolerance"
    UNMATCHED_REFERENCE = "unmatched_reference"
    LOW_CONFIDENCE = "low_confidence"
    DUPLICATE_DOCUMENT = "duplicate_document"
    SHIPMENT_STATUS_UNAVAILABLE = "shipment_status_unavailable"
    APPROVAL_NOT_RECEIVED = "approval_not_received"
    INTEGRATION_FAILURE = "integration_failure"


class ExceptionPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalDecision(str, Enum):
    """What an approver did with a transaction that was put to them.

    `REJECTED` and `CHANGES_REQUESTED` are both a return to the workflow, never a dead end: each
    puts the transaction back into `Validation Pending`, editable, with the stated reason on it.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class DocumentType(str, Enum):
    """What a document is.

    `BL_DRAFT` and `BL` are deliberately two values rather than one with a flag: BR-07 turns on
    the difference between a draft bill of lading, which is enough to start preparing a sales
    document, and a final one, which is what a submission actually waits for. A single `bl` value
    with a boolean beside it would put that distinction somewhere the classifier cannot report.

    `DRAFT_CONTRACT` and `DRAFT_INVOICE` are the two documents this platform writes itself. They
    are drafts for a person to read and take forward on paper; nothing sends them anywhere.
    """

    INVOICE = "invoice"
    CONTRACT = "contract"
    BL = "bl"
    BL_DRAFT = "bl_draft"
    SHIPPING_DOCUMENT = "shipping_document"
    TRACKER = "tracker"
    APPROVAL_EVIDENCE = "approval_evidence"
    FA_DOCUMENT = "fa_document"
    DRAFT_CONTRACT = "draft_contract"
    DRAFT_INVOICE = "draft_invoice"
    # The two documents discovery named that the platform could not previously produce.
    #
    # A Performa invoice is the advance, clean invoice raised before the cargo is weighed - its
    # defining property is that there is no weight slip behind it, which is exactly why it cannot
    # share the commercial invoice's draft gate. See `NO_SHIPMENT_EVIDENCE_DRAFT_TYPES`.
    #
    # A bank cover letter is the covering note that accompanies a documentary set to the bank. It
    # states what is enclosed and against which contract; it carries no commercial terms of its own.
    DRAFT_PERFORMA_INVOICE = "draft_performa_invoice"
    DRAFT_BANK_COVER_LETTER = "draft_bank_cover_letter"
    UNKNOWN = "unknown"


# The bill-of-lading family, in the two senses BR-07 has to tell apart. A shipping confirmation
# counts as final evidence that the cargo loaded; a draft B/L explicitly does not.
FINAL_BL_DOCUMENT_TYPES: tuple[str, ...] = ("bl", "shipping_document")
DRAFT_BL_DOCUMENT_TYPES: tuple[str, ...] = ("bl_draft",)

# What the platform generates. Never received, never extracted from.
GENERATED_DOCUMENT_TYPES: tuple[str, ...] = (
    "draft_contract",
    "draft_invoice",
    "draft_performa_invoice",
    "draft_bank_cover_letter",
)

# The generated documents that are not gated on shipment evidence, and why each one is not.
#
# BR-07 holds a draft commercial invoice back until at least a draft bill of lading exists, which
# is correct for a document that states what shipped. It is wrong for both of these:
#
# * a **Performa invoice** is raised *before* the cargo is weighed or loaded - it is the advance
#   invoice, and discovery describes it precisely as the clean invoice with no weight slip. Gating
#   it on shipment evidence would make the platform unable to produce it in the only circumstance
#   it is ever produced in;
# * a **bank cover letter** is a covering note listing an enclosed documentary set. It asserts
#   nothing about the cargo, so shipment evidence is not what makes it correct or incorrect.
#
# This exemption is narrow and deliberate: it is not a way past validation, it is the recognition
# that BR-07 is a rule about one specific document's meaning.
NO_SHIPMENT_EVIDENCE_DRAFT_TYPES: tuple[str, ...] = (
    "draft_performa_invoice",
    "draft_bank_cover_letter",
)


class ShipmentStatus(str, Enum):
    """Where a shipment stands, in the four words the desk actually uses.

    The same four values describe a shipment whose carrier reported them and one a person typed
    in. There is no `manually_tracked` state and there is deliberately not going to be one: how a
    figure was obtained belongs on the audit trail, not in the vocabulary the screen filters on.
    """

    ON_SCHEDULE = "on_schedule"
    DELAYED = "delayed"
    ARRIVED = "arrived"
    EXCEPTION = "exception"


class ShipmentMilestone(str, Enum):
    """The fixed milestone vocabulary a free-text carrier description is parsed down to.

    `UNKNOWN` is the honest state of a shipment nobody has reported on yet, and the state a
    description that could not be understood stays in. Nothing here guesses a milestone forward.
    """

    BOOKED = "booked"
    GATE_IN = "gate_in"
    LOADED = "loaded"
    DEPARTED = "departed"
    IN_TRANSIT = "in_transit"
    TRANSHIPPED = "transhipped"
    ARRIVED = "arrived"
    DISCHARGED = "discharged"
    GATE_OUT = "gate_out"
    DELIVERED = "delivered"
    UNKNOWN = "unknown"


class BillOfLadingType(str, Enum):
    """`SEAWAY` is a final bill in the sense BR-07 cares about; `DRAFT` explicitly is not."""

    ORIGINAL = "original"
    SEAWAY = "seaway"
    DRAFT = "draft"


class ShipmentIssueType(str, Enum):
    QUALITY = "quality"
    DAMAGE = "damage"
    DETENTION = "detention"
    OTHER = "other"


# The bill types that count as a final, non-draft bill of lading for BR-07's submission check.
FINAL_BILL_OF_LADING_TYPES: tuple[str, ...] = ("original", "seaway")


class DocumentSource(str, Enum):
    """How a document came to exist.

    `GENERATED` arrives with the sales module: it is the first document in the platform that
    originates from no intake event at all, because the platform itself wrote it.
    """

    RECEIVED = "received"
    UPLOADED = "uploaded"
    GENERATED = "generated"


class PaymentCondition(str, Enum):
    """Recorded on the sales leg. Nothing is gated on it at this point in the lifecycle."""

    CAD = "CAD"
    TT = "TT"


class FixationStatus(str, Enum):
    """Whether the customer has fixed the price on an LME-linked sale."""

    UNFIXED = "unfixed"
    FIXED = "fixed"


class Territory(str, Enum):
    INDIA = "india"
    CHINA = "china"
    JAPAN = "japan"
    OTHER = "other"


class ExtractionStatus(str, Enum):
    """`NOT_APPLICABLE` is the honest state of a document the platform wrote itself.

    There is nothing to read and understand about a draft this system generated out of its own
    data, so reporting it as `completed` would claim an extraction that never ran.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class IntegrationTargetSystem(str, Enum):
    """The three systems an approved transaction has to reach, and the only three.

    They are listed together but they are not built alike: the tracker has a real, working client
    behind it because Microsoft Graph's Excel API is documented and already integrated with, while
    SAP and the DMS have an adapter with an honest manual fallback because neither endpoint
    contract is confirmed anywhere in this platform's material.
    """

    TRACKER = "tracker"
    SAP = "sap"
    DMS = "dms"


class IntegrationJobStatus(str, Enum):
    """What genuinely happened to one posting, in the only five words that can be true of it.

    `AWAITING_MANUAL_ACTION` is the fifth, and it exists because neither of the other four is
    honest about the SAP and DMS fallback. The platform has done everything it can do - the
    payload is prepared, the document pack is compiled - and a person has to finish the posting
    in a system this platform cannot reach. That is not a success and it is not a failure, and
    reporting it as either would be the one thing this module must never do.
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    AWAITING_MANUAL_ACTION = "awaiting_manual_action"


class DocumentPackType(str, Enum):
    """The two compiled packages, named for what a person calls them.

    A pack is a merge of documents that already exist, never a new document. The drafts 
    generates are inputs to one of these, not a third pack type.
    """

    PURCHASE_FILE = "purchase_file"
    SALES_BANK_DOCS = "sales_bank_docs"


# The job statuses an automatic retry may ever pick up. `AWAITING_MANUAL_ACTION` is absent by
# construction: there is nothing automated left to re-attempt on a job that is waiting for a
# person, and re-running it would only overwrite their work with the same fallback again.
RETRYABLE_JOB_STATUSES: tuple[str, ...] = (
    IntegrationJobStatus.QUEUED.value,
    IntegrationJobStatus.PROCESSING.value,
)


def _values(enum: type[Enum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum)


REQUEST_SOURCES = _values(RequestSource)
REQUEST_CATEGORIES = _values(RequestCategory)
BUSINESS_STREAMS = _values(BusinessStream)
REQUEST_STATUSES = _values(RequestStatus)
DOCUMENT_TYPES = _values(DocumentType)
DOCUMENT_SOURCES = _values(DocumentSource)
PAYMENT_CONDITIONS = _values(PaymentCondition)
FIXATION_STATUSES = _values(FixationStatus)
TERRITORIES = _values(Territory)
EXTRACTION_STATUSES = _values(ExtractionStatus)
TRANSACTION_STATUSES = _values(TransactionStatus)
PRICE_BASES = _values(PriceBasis)
INVOICE_STATUSES = _values(InvoiceStatus)
MATCH_METHODS = _values(MatchMethod)
RULE_SEVERITIES = _values(RuleSeverity)
EXCEPTION_CATEGORIES = _values(ExceptionCategory)
EXCEPTION_PRIORITIES = _values(ExceptionPriority)
APPROVAL_DECISIONS = _values(ApprovalDecision)
SHIPMENT_STATUSES = _values(ShipmentStatus)
SHIPMENT_MILESTONES = _values(ShipmentMilestone)
BILL_OF_LADING_TYPES = _values(BillOfLadingType)
SHIPMENT_ISSUE_TYPES = _values(ShipmentIssueType)
INTEGRATION_TARGET_SYSTEMS = _values(IntegrationTargetSystem)
INTEGRATION_JOB_STATUSES = _values(IntegrationJobStatus)
DOCUMENT_PACK_TYPES = _values(DocumentPackType)


def sql_in_list(values: tuple[str, ...]) -> str:
    """Render a check-constraint membership clause from a vocabulary."""
    return ", ".join(f"'{value}'" for value in values)
