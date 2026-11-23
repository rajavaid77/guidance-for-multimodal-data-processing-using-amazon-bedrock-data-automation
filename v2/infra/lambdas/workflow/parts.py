"""Record one row per BDA segment of an uploaded file, cutting page-range PDFs for multi-document packs."""

from __future__ import annotations

import io
import logging
from typing import Any

from common import db

from .bda_output import part_name

log = logging.getLogger(__name__)
PACK = "PACK"
PACK_SEGMENT = -1  # segment_index of the container row that represents the whole multi-document file


def _page_range(pages: list[int]) -> tuple[int | None, int | None]:
    return (min(pages), max(pages)) if pages else (None, None)


def _is_pdf(doc: dict[str, Any]) -> bool:
    return (doc.get("content_type") or "").lower() == "application/pdf" or str(doc.get("s3_key", "")).lower().endswith(
        ".pdf"
    )


def _split_pdf(
    claim_id: str, doc: dict[str, Any], segments: list[dict[str, Any]], output_bucket: str, intake_bucket: str, s3: Any
):
    """Return ({segment_index: key}, page_count). Raises on unreadable PDFs; the caller falls back to the original."""
    from pypdf import (
        PdfReader,
        PdfWriter,
    )  # imported here: the layer provides it, unit tests of other paths do not need it

    data = s3.get_object(Bucket=intake_bucket, Key=doc["s3_key"])["Body"].read()
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("encrypted PDF")
    total = len(reader.pages)
    keys: dict[int, str] = {}
    for seg in segments:
        pages = seg["page_indices"]
        if not pages:
            continue  # unknown range: this part keeps the whole original file
        if min(pages) < 1 or max(pages) > total:
            raise ValueError("page index out of range")
        writer = PdfWriter()
        for number in pages:
            writer.add_page(reader.pages[number - 1])
        buffer = io.BytesIO()
        writer.write(buffer)
        key = f"claims/{claim_id}/parts/{doc['document_id']}/{seg['segment_index']:03d}.pdf"
        s3.put_object(Bucket=output_bucket, Key=key, Body=buffer.getvalue(), ContentType="application/pdf")
        keys[seg["segment_index"]] = key
    return keys, total


def record_parts(
    claim_id: str,
    doc: dict[str, Any],
    segments: list[dict[str, Any]],
    output_bucket: str,
    intake_bucket: str,
    s3: Any,
) -> list[dict[str, Any]]:
    """Persist the parts of one source file (idempotent) and update the file row. Returns the part dicts."""
    if not segments:
        return []
    segments = sorted(segments, key=lambda s: s["segment_index"])
    multi = len(segments) > 1
    split_keys: dict[int, str] = {}
    page_count: int | None = None
    if multi and _is_pdf(doc):
        try:
            split_keys, page_count = _split_pdf(claim_id, doc, segments, output_bucket, intake_bucket, s3)
        except Exception as exc:  # noqa: BLE001 - never fail the claim because a pack could not be cut
            log.error("PDF split failed for document %s: %s", doc["document_id"], type(exc).__name__)
            split_keys = {}
    all_pages = [p for s in segments for p in s["page_indices"]]
    if page_count is None and all_pages:
        page_count = max(all_pages)
    parts = []
    for seg in segments:
        start, end = _page_range(seg["page_indices"])
        key = split_keys.get(seg["segment_index"])
        parts.append(
            {
                "claim_id": claim_id,
                "doc": doc["document_id"],
                "batch": doc.get("batch_id"),
                "seg": seg["segment_index"],
                "cls": seg["document_class"],
                "name": part_name(doc["file_name"], seg["document_class"], seg["page_indices"], multi)[:300],
                "ps": start,
                "pe": end,
                "pi": ",".join(map(str, seg["page_indices"]))[:200] or None,
                "conf": seg.get("blueprint_confidence"),
                "kind": "OUTPUT" if key else "INTAKE",
                "key": key or doc["s3_key"],
                "orig": key is None,
                "ct": "application/pdf" if key else doc.get("content_type"),
            }
        )
    if multi:
        # Container row (segment_index PACK_SEGMENT): the whole uploaded file, shown as the parent of its split parts.
        parts.insert(
            0,
            {
                "claim_id": claim_id,
                "doc": doc["document_id"],
                "batch": doc.get("batch_id"),
                "seg": PACK_SEGMENT,
                "cls": PACK,
                "name": doc["file_name"][:300],
                "ps": 1 if page_count else None,
                "pe": page_count,
                "pi": None,
                "conf": None,
                "kind": "INTAKE",
                "key": doc["s3_key"],
                "orig": True,
                "ct": doc.get("content_type"),
            },
        )
    db.execute("DELETE FROM claim_document_parts WHERE document_id = :d", {"d": doc["document_id"]})
    db.execute_many(
        """INSERT INTO claim_document_parts (claim_id, document_id, batch_id, segment_index, document_class,
                  display_name, page_start, page_end, page_indices, blueprint_confidence, s3_bucket_kind, s3_key,
                  is_original, content_type)
           VALUES (:claim_id, :doc, :batch, :seg, :cls, :name, :ps, :pe, :pi, :conf, :kind, :key, :orig, :ct)""",
        parts,
    )
    db.execute(
        """UPDATE claim_documents SET detected_type = :t, segment_count = :n, page_count = :pc
           WHERE document_id = :d""",
        {
            "t": PACK if multi else segments[0]["document_class"],
            "n": len(segments),
            "pc": page_count,
            "d": doc["document_id"],
        },
    )
    return parts
