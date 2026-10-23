"""Required supplier questions, not inferred material or execution facts."""
from __future__ import annotations

MATERIAL_CONFIRMATION_QUESTIONS = (
    "Do you manufacture this product in-house? Please identify any outsourced steps.",
    "Do you have the required raw material in stock? Please state available quantity and any shortage or unknown status.",
    "If material is not confirmed, how long will confirmation with the material supplier take?",
    "What is the raw material procurement lead time, and what evidence supports it?",
    "Can the required material be locked or reserved for this inquiry?",
    "How long is that material lock or reservation valid, and what conditions apply?",
    "Is substitute material needed? Please identify the proposed substitute and any approval still required.",
    "Would substitution affect price, quality or lead time? Please describe each effect or state that it is unknown.",
)


def with_material_confirmation_questions(message: str) -> str:
    """Keep the supplied draft and ensure the source-defined questions are asked."""
    if all(question in message for question in MATERIAL_CONFIRMATION_QUESTIONS):
        return message
    questions = "\n".join(
        f"{index}. {question}"
        for index, question in enumerate(MATERIAL_CONFIRMATION_QUESTIONS, start=1)
    )
    section = (
        "Material and execution confirmation (please leave unverified facts unknown):\n"
        + questions
    )
    before, signature, after = message.partition("\nBest regards,")
    return before.rstrip() + "\n\n" + section + ("\n\nBest regards," + after if signature else "")
