from __future__ import annotations
from aivan.schemas.requirement import BuyerRequirement
from aivan.llm.gateway import llm_complete_json
from aivan.llm.prompts import CLARIFICATION_SYSTEM
from aivan.utils.language import detect_language

ZH_TEMPLATE = """已收到您的询盘，感谢！为了帮您准确询价，还需要确认以下信息：

{questions}

请回复以上信息，我们将立即为您跟进。谢谢！"""

EN_TEMPLATE = """Thank you for your inquiry! To provide an accurate quote, we need a few more details:

{questions}

Please reply with the above information and we'll follow up immediately. Thank you!"""

def generate_clarification_message(
    requirement: BuyerRequirement,
    language: str | None = None,
) -> str | None:
    """Generate a clarification message for missing fields. Returns None if no clarification needed."""
    if not requirement.missing_fields:
        return None

    if language is None:
        language = requirement.language or detect_language(requirement.raw_text)

    user_prompt = f"""Missing fields for requirement:
Product: {requirement.product_type or 'unknown'}
Customer language: {language}

Missing fields:
{chr(10).join(f'- {mf.field_name}: {mf.question}' for mf in requirement.missing_fields)}

Generate a polite clarification message in {language} asking for these fields."""

    try:
        result = llm_complete_json("missing_field_clarification", CLARIFICATION_SYSTEM, user_prompt)
        message_text = result.get("message_text", "")
        if message_text:
            return message_text
    except Exception:
        pass

    questions = "\n".join(f"{i+1}. {mf.question}" for i, mf in enumerate(requirement.missing_fields))

    if language == "zh":
        return ZH_TEMPLATE.format(questions=questions)
    else:
        return EN_TEMPLATE.format(questions=questions)
