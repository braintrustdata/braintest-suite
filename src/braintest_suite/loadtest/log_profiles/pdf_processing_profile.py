import random
import textwrap
from io import BytesIO
from typing import Any
from uuid import uuid4

from braintrust import Attachment, current_span, start_span, traced
from faker import Faker

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError(
        "The PDF processing log profile requires the optional 'pdf' dependency. "
        "Install it with `uv sync --extra pdf` or run with `uv run --extra pdf`."
    ) from exc

fake = Faker()


def _render_pdf(title: str, sentences: list[str]) -> tuple[bytes, int]:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    page_width, page_height = letter
    pdf.setTitle(title)
    pdf.setAuthor("Braintest synthetic document profile")

    lines = []
    for sentence in sentences:
        lines.extend(textwrap.wrap(sentence, width=92) or [""])

    page_count = 0
    line_index = 0
    while line_index < len(lines) or page_count == 0:
        page_count += 1
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(54, page_height - 54, title)
        pdf.setFont("Helvetica", 9)
        pdf.drawRightString(
            page_width - 54,
            page_height - 54,
            f"Synthetic page {page_count}",
        )

        text = pdf.beginText(54, page_height - 82)
        text.setFont("Helvetica", 10)
        for _ in range(48):
            if line_index >= len(lines):
                break
            text.textLine(lines[line_index])
            line_index += 1
        pdf.drawText(text)
        pdf.showPage()

    pdf.save()
    return buffer.getvalue(), page_count


def _build_document_pool(pool_size: int, max_tokens: int) -> list[dict[str, Any]]:
    sentence_count = max(12, max_tokens // 20)
    documents = []

    for index in range(pool_size):
        title = f"{fake.catch_phrase()} — Processing Sample {index + 1}"
        sentences = fake.sentences(nb=sentence_count)
        pdf_bytes, page_count = _render_pdf(title, sentences)
        word_count = sum(len(sentence.split()) for sentence in sentences)

        documents.append(
            {
                "document_id": f"synthetic-document-{index + 1:04d}",
                "filename": f"document-{index + 1:04d}.pdf",
                "title": title,
                "pdf_bytes": pdf_bytes,
                "pdf_size_bytes": len(pdf_bytes),
                "page_count": page_count,
                "word_count": word_count,
                "text_preview": " ".join(sentences[:3]),
                "summary": " ".join(sentences[:5]),
                "document_type": random.choice(["invoice", "contract", "policy", "research_report"]),
                "entities": [
                    {"type": "organization", "value": fake.company()},
                    {"type": "person", "value": fake.name()},
                    {"type": "date", "value": fake.date()},
                    {"type": "amount", "value": f"${fake.random_int(100, 50000):,}"},
                ],
                "table": [
                    {
                        "line_item": fake.bs(),
                        "quantity": fake.random_int(1, 20),
                        "unit_price": round(random.uniform(10, 500), 2),
                    }
                    for _ in range(4)
                ],
            }
        )

    return documents


def _leaf_span(
    name: str,
    *,
    span_type: str = "function",
    input_data: Any = None,
    output_data: Any = None,
    metadata: dict[str, Any] | None = None,
    metrics: dict[str, float | int] | None = None,
) -> None:
    event: dict[str, Any] = {
        "input": input_data,
        "output": output_data,
    }
    if metadata:
        event["metadata"] = metadata
    if metrics:
        event["metrics"] = metrics

    with start_span(name, type=span_type) as span:
        span.log(**event)


def _process_document(document: dict[str, Any]) -> dict[str, Any]:
    processing_run_id = str(uuid4())
    root_span = current_span()
    root_span.log(
        input={
            "document_id": document["document_id"],
            "filename": document["filename"],
            "content_type": "application/pdf",
            "size_bytes": document["pdf_size_bytes"],
        },
        metadata={
            "profile": "mock_document_processing",
            "processing_run_id": processing_run_id,
        },
    )

    source_pdf = Attachment(
        data=document["pdf_bytes"],
        filename=document["filename"],
        content_type="application/pdf",
    )
    processed_pdf = Attachment(
        data=document["pdf_bytes"],
        filename=f"processed-{document['filename']}",
        content_type="application/pdf",
    )

    with start_span("document_intake", type="task") as intake_span:
        _leaf_span(
            "validate_upload",
            input_data={"filename": document["filename"]},
            output_data={"valid": True, "rejection_reasons": []},
        )
        _leaf_span(
            "detect_mime_type",
            input_data={"header": "%PDF"},
            output_data={"mime_type": "application/pdf", "confidence": 0.999},
            span_type="classifier",
        )
        _leaf_span(
            "persist_source_document",
            input_data={"document_id": document["document_id"]},
            output_data={"source_pdf": source_pdf},
            span_type="tool",
        )
        intake_span.log(output={"status": "accepted", "size_bytes": document["pdf_size_bytes"]})

    with start_span("extract_document", type="task") as extraction_span:
        with start_span("parse_pdf", type="tool") as parser_span:
            _leaf_span(
                "extract_pages",
                input_data={"page_count": document["page_count"]},
                output_data={
                    "pages_extracted": document["page_count"],
                    "word_count": document["word_count"],
                    "preview": document["text_preview"],
                },
            )
            _leaf_span(
                "detect_layout",
                input_data={"pages": document["page_count"]},
                output_data={
                    "blocks": document["page_count"] * 7,
                    "reading_order_confidence": 0.97,
                },
                span_type="classifier",
            )
            _leaf_span(
                "extract_tables",
                input_data={"strategy": "rule_based"},
                output_data={"tables_found": 1, "rows": document["table"]},
            )
            parser_span.log(output={"status": "parsed", "pages": document["page_count"]})

        _leaf_span(
            "route_ocr_fallback",
            input_data={"native_text_words": document["word_count"]},
            output_data={"ocr_required": False, "reason": "native_text_available"},
            span_type="classifier",
        )
        extraction_span.log(output={"characters_extracted": document["word_count"] * 6})

    with start_span("analyze_document", type="task") as analysis_span:
        _leaf_span(
            "classify_document",
            span_type="llm",
            input_data={"text": document["text_preview"]},
            output_data={
                "document_type": document["document_type"],
                "confidence": 0.94,
            },
            metadata={"model": "mock-document-classifier-v1"},
            metrics={"prompt_tokens": 420, "completion_tokens": 32, "tokens": 452},
        )

        with start_span("extract_entities", type="llm") as entity_span:
            _leaf_span(
                "detect_entity_candidates",
                input_data={"text": document["text_preview"]},
                output_data={"candidates": document["entities"]},
                span_type="classifier",
            )
            _leaf_span(
                "normalize_entities",
                input_data=document["entities"],
                output_data={"entities": document["entities"], "deduplicated": 0},
            )
            entity_span.log(
                output={"entities": document["entities"]},
                metadata={"model": "mock-entity-extractor-v2"},
                metrics={"prompt_tokens": 650, "completion_tokens": 120, "tokens": 770},
            )

        _leaf_span(
            "summarize_document",
            span_type="llm",
            input_data={"word_count": document["word_count"]},
            output_data={"summary": document["summary"]},
            metadata={"model": "mock-summarizer-v1"},
            metrics={"prompt_tokens": 800, "completion_tokens": 180, "tokens": 980},
        )
        analysis_span.log(
            output={
                "document_type": document["document_type"],
                "entity_count": len(document["entities"]),
            }
        )

    with start_span("quality_assurance", type="review") as quality_span:
        _leaf_span(
            "validate_required_fields",
            input_data={"document_type": document["document_type"]},
            output_data={"valid": True, "missing_fields": []},
        )
        _leaf_span(
            "score_extraction_confidence",
            input_data={"entities": document["entities"]},
            output_data={"confidence": 0.96, "requires_human_review": False},
            span_type="score",
        )
        quality_span.log(output={"passed": True, "confidence": 0.96})

    with start_span("index_document", type="task") as index_span:
        with start_span("chunk_document", type="preprocessor") as chunk_span:
            chunk_count = max(1, document["word_count"] // 250)
            _leaf_span(
                "generate_embeddings",
                span_type="llm",
                input_data={"chunk_count": chunk_count},
                output_data={"vectors_created": chunk_count, "dimensions": 1536},
                metadata={"model": "mock-embedding-model-v1"},
                metrics={"prompt_tokens": document["word_count"], "tokens": document["word_count"]},
            )
            chunk_span.log(output={"chunk_count": chunk_count, "overlap_tokens": 40})

        _leaf_span(
            "write_search_index",
            span_type="tool",
            input_data={"document_id": document["document_id"]},
            output_data={"indexed": True, "index": "synthetic-documents"},
        )
        index_span.log(output={"status": "indexed"})

    with start_span("finalize_document", type="task") as finalize_span:
        _leaf_span(
            "attach_processed_pdf",
            span_type="tool",
            input_data={"document_id": document["document_id"]},
            output_data={"processed_pdf": processed_pdf},
        )
        result = {
            "document_id": document["document_id"],
            "processing_run_id": processing_run_id,
            "status": "completed",
            "page_count": document["page_count"],
            "document_type": document["document_type"],
            "entity_count": len(document["entities"]),
        }
        finalize_span.log(output=result)

    root_span.log(output=result)
    return result


def create_profile(config: dict):
    options = config["loadtest"]["log_profile"]["options"]
    pool_size = options["faker_pool_size"]
    max_tokens = options["max_tokens"]

    print(f"Building synthetic PDF document pool ({pool_size} documents, target size based on {max_tokens} tokens)")
    document_pool = _build_document_pool(pool_size, max_tokens)
    total_bytes = sum(document["pdf_size_bytes"] for document in document_pool)
    print(f"Synthetic PDF document pool generated ({total_bytes / (1024 * 1024):.2f} MiB)")

    @traced(name="process_document", type="task", notrace_io=True)
    def emit_trace():
        document = random.choice(document_pool)
        return _process_document(document)

    return emit_trace
