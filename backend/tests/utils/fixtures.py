"""Synthetic documents and synthetic provider responses.

Every byte here is generated, not sampled from a real trade document, and every "AI response" is
a JSON payload a test writes itself. Nothing in the suite requires a live Graph tenant, a live
mailbox or a live Gemini key.
"""

from __future__ import annotations

import io
import json
import zlib
from typing import Any

PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _pdf(objects: list[bytes]) -> bytes:
    """Assemble a minimal but structurally valid PDF with a real xref table."""
    out = io.BytesIO()
    out.write(b"%PDF-1.7\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n".encode())
        out.write(body)
        out.write(b"\nendobj\n")
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    )
    return out.getvalue()


def text_layer_pdf(lines: list[str] | None = None) -> bytes:
    """A digital PDF whose pages carry a real, readable text layer."""
    body_lines = lines or [
        "COMMERCIAL INVOICE",
        "Invoice Number: INV-2026-0451",
        "Contract Reference: AGF-CT-2026-118",
        "Commodity: Copper Millberry 99.9%",
        "Quantity: 24.500 MT",
        "Rate: 8125.00",
        "Currency: USD",
        "Amount: 199062.50",
        "Invoice Date: 2026-08-14",
    ]
    stream_parts = ["BT", "/F1 12 Tf", "50 760 Td", "14 TL"]
    for line in body_lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream_parts.append(f"({escaped}) Tj T*")
    stream_parts.append("ET")
    content = "\n".join(stream_parts).encode("latin-1")

    return _pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
    )


def scanned_pdf() -> bytes:
    """A page that is only a picture: an embedded image and no text operators at all."""
    raw = bytes([255, 255, 255] * 4)
    compressed = zlib.compress(raw)
    return _pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length 44 >>\nstream\nq 595 0 0 842 0 0 cm /Im0 Do Q\nendstream",
            b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceRGB "
            b"/BitsPerComponent 8 /Filter /FlateDecode /Length "
            + str(len(compressed)).encode()
            + b" >>\nstream\n"
            + compressed
            + b"\nendstream",
        ]
    )


def docx_bytes(paragraphs: list[str] | None = None) -> bytes:
    from docx import Document as DocxDocument

    document = DocxDocument()
    for line in paragraphs or ["Sale Contract AGF-CT-2026-118", "Incoterm: CIF Nhava Sheva"]:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Shipments"
    sheet.append(["AGFZE shipment tracker - August 2026"])
    sheet.append([])
    sheet.append(["Batch", "Container", "Commodity", "Quantity"])
    sheet.append(["B-2026-091", "MSKU7781234", "Copper Millberry", "24.500 MT"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def csv_bytes() -> bytes:
    return (
        b"AGFZE tracker export\n\n"
        b"Batch,Container,Commodity,Quantity\n"
        b"B-2026-091,MSKU7781234,Copper Millberry,24.500 MT\n"
    )


def graph_message_payload(message_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": message_id,
        "subject": "Purchase confirmation - Copper Millberry 24.5MT",
        "receivedDateTime": "2026-08-23T09:14:00Z",
        "hasAttachments": False,
        "from": {"emailAddress": {"name": "Broker Desk", "address": "desk@broker.example"}},
        "body": {
            "contentType": "text",
            "content": "Please find our confirmation for 24.5 MT Copper Millberry.",
        },
    }
    payload.update(overrides)
    return payload


def classification_response(
    category: str = "purchase",
    confidence: float = 0.93,
    stream: str | None = "scrap",
) -> str:
    return json.dumps(
        {
            "category": category,
            "confidence": confidence,
            "rationale": "The mail confirms a purchase of copper scrap against a contract.",
            "stream": stream,
        }
    )


def document_classification_response(
    document_type: str = "invoice",
    confidence: float = 0.95,
    territory: str | None = "india",
) -> str:
    return json.dumps(
        {
            "document_type": document_type,
            "confidence": confidence,
            "rationale": "The header reads COMMERCIAL INVOICE and it carries an invoice number.",
            "territory": territory,
        }
    )


def extraction_response(values: dict[str, tuple[str | None, float]]) -> str:
    return json.dumps(
        {
            "fields": [
                {
                    "name": name,
                    "value": value,
                    "confidence": confidence,
                    "rationale": f"Read from the {name.replace('_', ' ')} line.",
                    "page": 1,
                    "paragraph": 2,
                }
                for name, (value, confidence) in values.items()
            ]
        }
    )
