import base64
from pathlib import Path

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.models.schemas import VlmExtractionResult

settings = get_settings()
CLIENT = OpenAI(
    base_url=settings.OPENROUTER_API_URL, api_key=settings.OPENROUTER_API_KEY
)

SYSTEM_PROMPT = """You are an expert OCR and document extraction assistant for receipts and invoices.

Your task: analyze the provided image and return a single JSON object with exactly two top-level keys:
- "raw_text": string — full plain-text transcription of everything visible on the document (preserve original language, layout order, line breaks where helpful).
- "structured_data": object — normalized fields extracted from the document.

Rules:
- Output valid JSON only. No markdown, no code fences, no commentary.
- If a field is missing or illegible, use null (not empty string) for optional fields.
- For numbers, use JSON numbers (float), not strings with currency symbols.
- "structured_data.items": array of line items; empty array [] if no line items visible; null only if the entire items section cannot be determined.
- Each item may include: item_name, quantity, unit_price, total_price (all optional per item except use null when unknown).
- Detect currency when possible (e.g. PLN, EUR) and set structured_data.currency; otherwise null.
- Include buyer, seller, date, totals (total_net, total_vat, total_gross) when present on the document.

Do not invent data. Only extract what is visible on the image."""

USER_PROMPT = (
    "Extract all text and structured invoice/receipt fields from this image. "
    "Return JSON matching the required schema."
)

MIME_BY_SUFFIX = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=15),
    retry=retry_if_exception_type(
        (APIConnectionError, APITimeoutError, RateLimitError)
    ),
)
def extract_structured_data(upload_path: Path, suffix: str) -> VlmExtractionResult:
    mime = MIME_BY_SUFFIX.get(suffix)

    with upload_path.open("rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")

    system_prompt: ChatCompletionMessageParam = {
        "role": "system",
        "content": SYSTEM_PROMPT,
    }
    user_prompt: ChatCompletionMessageParam = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": USER_PROMPT,
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_base64}"},
            },
        ],
    }

    response = CLIENT.chat.completions.create(
        model=settings.VLM_MODEL_NAME,
        messages=[system_prompt, user_prompt],
        temperature=0.0,
        timeout=60,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "vlm_extraction_result",
                "schema": VlmExtractionResult.model_json_schema(),
                # "strict": True,  # remove if validation fails
            },
        },
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("No content returned from VLM model")
    return VlmExtractionResult.model_validate_json(content)
