"""Merging a transaction's documents into the one file that goes to the DMS.

This is the whole of what `DocumentPack` adds over what already exists. Step 5 generates draft
contracts and invoices as `Document` rows and this module does not generate anything: it gathers
documents already on the transaction - received ones and the drafts the platform wrote itself -
and merges them into one PDF under the naming convention the desk already uses.

Two decisions in here are worth stating plainly.

**A Step 5 draft is an input, never a duplicate.** The sales pack's contract is whatever
`draft_contract` document the sales module produced. It is read, listed and merged where its
format allows; nothing re-generates it and no second copy of it is created under a new name.

**A document that cannot be merged is still filed, and said so.** The drafts are DOCX, and no
PDF library merges DOCX. Rather than silently dropping them - which would produce a pack that
looks complete and is not - every pack opens with a real contents page listing every source
document, whether its pages were merged in or whether the file has to be attached separately.
A person filing this pack can see exactly what is in their hands and what is not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import pymupdf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.enums import DocumentPackType, DocumentType
from app.models.intake import Document
from app.models.integration import DocumentPack
from app.models.transactions import TradeTransaction
from app.services.audit_service import ActorType, record_audit_event
from app.services.rules.values import format_decimal
from app.services.storage import ObjectNotFoundError, get_storage_service

logger = get_logger(__name__)

PDF_CONTENT_TYPE = "application/pdf"

# What goes into each pack, in the order it is filed. Read as a document-type ordering rather
# than a set, because a bank expects the invoice on top and the supporting paper behind it.
#
# The purchase file is the buying side's evidence pack; the sales pack is what goes to the bank
# under a CAD or LC settlement, so it leads with the sales invoice and the finalised contract -
# which, on a transaction that went through Step 5, are the generated drafts.
PACK_DOCUMENT_TYPES: dict[str, tuple[str, ...]] = {
    DocumentPackType.PURCHASE_FILE.value: (
        DocumentType.INVOICE.value,
        DocumentType.CONTRACT.value,
        DocumentType.BL.value,
        DocumentType.SHIPPING_DOCUMENT.value,
        DocumentType.APPROVAL_EVIDENCE.value,
        DocumentType.FA_DOCUMENT.value,
    ),
    DocumentPackType.SALES_BANK_DOCS.value: (
        DocumentType.DRAFT_INVOICE.value,
        DocumentType.INVOICE.value,
        DocumentType.DRAFT_CONTRACT.value,
        DocumentType.CONTRACT.value,
        DocumentType.BL.value,
        DocumentType.SHIPPING_DOCUMENT.value,
        DocumentType.APPROVAL_EVIDENCE.value,
    ),
}

# Formats PyMuPDF can genuinely open and append. Anything else is listed on the contents page
# and filed alongside, rather than being quietly left out of a pack that claims to be complete.
MERGEABLE_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/tiff",
    }
)


class AuditEvent:
    PACK_COMPILED = "integration.document_pack.compiled"


@dataclass
class PackSource:
    document: Document
    merged: bool = False
    reason: str | None = None


@dataclass
class CompilationResult:
    pack: DocumentPack
    sources: list[PackSource] = field(default_factory=list)

    @property
    def merged_ids(self) -> list[str]:
        return [str(row.document.id) for row in self.sources if row.merged]

    @property
    def attached_separately(self) -> list[str]:
        return [row.document.filename for row in self.sources if not row.merged]


def pack_types_for(transaction: TradeTransaction) -> list[str]:
    """Which packs this transaction actually has.

    A transaction that was bought and sold has both: the purchase file is the buying desk's
    evidence and the bank pack is what the sale is settled against. Neither is invented for a
    transaction that has no leg to build it from.
    """
    types: list[str] = []
    if transaction.purchase_leg is not None or getattr(transaction, "fa_leg", None) is not None:
        types.append(DocumentPackType.PURCHASE_FILE.value)
    if transaction.sales_leg is not None:
        types.append(DocumentPackType.SALES_BANK_DOCS.value)
    return types


def pack_filename(transaction: TradeTransaction, pack_type: str) -> str:
    """The existing naming convention, unchanged.

    `ADV-{contract}-{qty}-{status}` for the purchase file and `SO-{batch}-{qty}-{Final|Prov}` for
    the sales pack - the same convention Step 5 gives its generated drafts, because a person
    sorting a folder should not have to learn a second one.
    """
    quantity = format_decimal(transaction.quantity_mt) or "0"
    if pack_type == DocumentPackType.SALES_BANK_DOCS.value:
        sales = transaction.sales_leg
        final = sales is not None and sales.customer_fixation_status == "fixed"
        return f"SO-{transaction.batch_number}-{quantity}-{'Final' if final else 'Prov'}.pdf"

    purchase = transaction.purchase_leg
    fa = getattr(transaction, "fa_leg", None)
    contract = (
        (purchase.contract_number if purchase else None)
        or (fa.fa_contract_reference if fa else None)
        or transaction.batch_number
    )
    status = purchase.invoice_status if purchase else transaction.status
    return f"ADV-{contract}-{quantity}-{status}.pdf"


def storage_key_for(pack_id: UUID, filename: str) -> str:
    """A UUID-derived key, so the readable name never decides where the bytes live."""
    return f"documents/packs/{pack_id}/{filename}"


async def pack_documents(
    session: AsyncSession, transaction: TradeTransaction, pack_type: str
) -> list[Document]:
    """The transaction's documents for one pack, in filing order.

    Ordered by the pack's own document-type sequence and then by age, so a re-compilation after
    a corrected invoice arrives produces the same pack with the newer paper in it rather than a
    differently-shuffled one.
    """
    wanted = PACK_DOCUMENT_TYPES[pack_type]
    rows = list(
        (
            await session.scalars(
                select(Document)
                .where(
                    Document.transaction_id == transaction.id,
                    Document.document_type.in_(wanted),
                )
                .order_by(Document.created_at)
            )
        ).all()
    )
    order = {document_type: index for index, document_type in enumerate(wanted)}
    return sorted(rows, key=lambda row: (order.get(row.document_type or "", len(order)),))


def _contents_page(
    transaction: TradeTransaction, pack_type: str, filename: str, sources: list[PackSource]
) -> bytes:
    """A real contents page: what is in this pack, and what had to travel beside it."""
    document = pymupdf.open()
    page = document.new_page()
    lines: list[str] = [
        "AGFZE Command Centre",
        f"Document pack: {pack_type.replace('_', ' ')}",
        "",
        f"Batch: {transaction.batch_number}",
        f"File: {filename}",
        f"Compiled: {utcnow().isoformat(timespec='seconds')}",
        "",
        "Contents",
        "",
    ]
    for position, source in enumerate(sources, start=1):
        state = (
            "merged into this file" if source.merged else (source.reason or "attached separately")
        )
        lines.append(
            f"{position}. {source.document.filename}"
            f"  [{source.document.document_type or 'unclassified'}]  - {state}"
        )
    if not sources:
        lines.append("No documents are on this transaction yet.")
    if any(not source.merged for source in sources):
        lines.extend(
            [
                "",
                "The items marked 'attached separately' are not PDFs and could not be merged into",
                "this file. They are on the transaction in the platform and must be filed "
                "alongside",
                "this pack.",
            ]
        )
    page.insert_text((56, 72), "\n".join(lines), fontsize=10, fontname="helv")
    rendered = document.tobytes()
    document.close()
    return bytes(rendered)


def _append(target: pymupdf.Document, data: bytes, content_type: str) -> None:
    """Append one source document's pages. Raises rather than producing an empty section."""
    if content_type == PDF_CONTENT_TYPE:
        with pymupdf.open(stream=data, filetype="pdf") as source:
            target.insert_pdf(source)
        return
    # An image is turned into a single page carrying it, which is what a scanned certificate
    # actually is. PyMuPDF does the conversion; nothing is re-encoded by hand.
    with (
        pymupdf.open(stream=data, filetype=content_type.rsplit("/", 1)[-1]) as image,
        pymupdf.open(stream=image.convert_to_pdf(), filetype="pdf") as converted,
    ):
        target.insert_pdf(converted)


async def compile_pack(
    session: AsyncSession,
    transaction: TradeTransaction,
    pack_type: str,
    *,
    actor_id: UUID | None = None,
) -> CompilationResult:
    """Merge one pack and store it, replacing the previous compilation of the same pack.

    Recompiling rewrites the existing row rather than leaving two packs behind: a transaction has
    one purchase file, and two of them differing by a document nobody can identify is worse than
    none.
    """
    storage = get_storage_service()
    documents = await pack_documents(session, transaction, pack_type)
    sources = [PackSource(document=row) for row in documents]

    filename = pack_filename(transaction, pack_type)
    merged = pymupdf.open()
    try:
        for source in sources:
            content_type = (source.document.content_type or "").split(";")[0].strip().lower()
            if content_type not in MERGEABLE_CONTENT_TYPES:
                source.reason = "attached separately - not a PDF"
                continue
            try:
                data = await storage.download(source.document.storage_ref)
                _append(merged, data, content_type)
            except (ObjectNotFoundError, RuntimeError, ValueError) as exc:
                # A source this platform cannot read is listed honestly rather than skipped in
                # silence. The pack still compiles; the contents page says what is missing.
                logger.warning(
                    "document_pack_source_unreadable",
                    extra={
                        "document_id": str(source.document.id),
                        "reason": type(exc).__name__,
                    },
                )
                source.reason = "attached separately - the stored file could not be read"
                continue
            source.merged = True

        contents = pymupdf.open(
            stream=_contents_page(transaction, pack_type, filename, sources), filetype="pdf"
        )
        # A pack whose sources were all unmergeable - or a transaction with no documents on it
        # yet - is still a real pack: the contents page alone, saying so. Appending an empty
        # document is not a no-op in PyMuPDF, so the guard is the difference between that honest
        # single page and a hard failure.
        if merged.page_count:
            contents.insert_pdf(merged)
        content = bytes(contents.tobytes())
        contents.close()
    finally:
        merged.close()

    pack = await session.scalar(
        select(DocumentPack).where(
            DocumentPack.transaction_id == transaction.id,
            DocumentPack.pack_type == pack_type,
        )
    )
    # The identifier is minted before the row exists, so the bytes are stored under their final
    # key and the row is only written once, complete. A half-written pack pointing at nothing is
    # the one state this table must never hold.
    pack_id = pack.id if pack is not None else uuid.uuid4()
    key = storage_key_for(pack_id, filename)
    await storage.upload(key, content, PDF_CONTENT_TYPE)

    if pack is None:
        pack = DocumentPack(id=pack_id, transaction_id=transaction.id, pack_type=pack_type)
        session.add(pack)
    pack.filename = filename
    pack.storage_ref = key
    pack.byte_size = len(content)
    pack.source_document_ids = [str(row.document.id) for row in sources]
    pack.generated_at = utcnow()
    await session.flush()

    result = CompilationResult(pack=pack, sources=sources)
    await record_audit_event(
        session,
        event_type=AuditEvent.PACK_COMPILED,
        entity_type="document_pack",
        entity_id=pack.id,
        actor_id=actor_id,
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        metadata={
            "transaction_id": str(transaction.id),
            "batch_number": transaction.batch_number,
            "pack_type": pack_type,
            "filename": filename,
            "storage_ref": key,
            "byte_size": len(content),
            "documents_merged": result.merged_ids,
            "documents_attached_separately": result.attached_separately,
        },
    )
    return result


async def compile_packs(
    session: AsyncSession, transaction: TradeTransaction, *, actor_id: UUID | None = None
) -> list[CompilationResult]:
    """Every pack this transaction has, compiled. Usually one; two where it was bought and sold."""
    return [
        await compile_pack(session, transaction, pack_type, actor_id=actor_id)
        for pack_type in pack_types_for(transaction)
    ]


async def packs_for(session: AsyncSession, transaction_id: UUID) -> list[DocumentPack]:
    return list(
        (
            await session.scalars(
                select(DocumentPack)
                .where(DocumentPack.transaction_id == transaction_id)
                .order_by(DocumentPack.pack_type)
            )
        ).all()
    )


async def mark_filed(
    session: AsyncSession,
    packs: list[DocumentPack],
    *,
    dms_document_id: str,
    filed_at: datetime | None = None,
) -> None:
    """Record that the DMS holds these packs, whether a call filed them or a person did."""
    moment = filed_at or utcnow()
    for pack in packs:
        pack.dms_document_id = dms_document_id
        pack.dms_uploaded_at = moment
    await session.flush()
