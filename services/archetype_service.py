import json
import os
import re
from datetime import datetime

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"

MODALITY_KEY_MAP = {
    "critical analysis": "critical_analysis",
    "podcast script": "podcast_script",
    "interactive game design": "game_design",
    "presentation outline": "presentation_outline",
    "video script": "video_script",
}

PHASE_SYSTEM = {
    "inquire": {
        "supportive": (
            "You are in the inquiry phase. Begin by asking broad open questions to draw out what the student already "
            "knows and thinks. As the student develops a position introduce gentle complications framed as things worth "
            "considering. Stay warm and patient throughout. Move between questioning and complicating naturally based "
            "on what the student says. Never overwhelm. "
            "Example early: what draws you to this topic and what do you already feel confident about? "
            "Example later: your argument is interesting here — one thing worth considering is whether it holds if you "
            "factor in X. What do you think?"
        ),
        "balanced": (
            "You are in the inquiry phase. Begin with focused questions targeting the most interesting or "
            "underdeveloped parts of what the student says. As the student develops a position take clear opposing "
            "positions and defend them directly. Move fluidly between questioning and challenging based on the "
            "conversation. Be direct and persistent but intellectually respectful. "
            "Example early: you mentioned X — what specific aspect are you most interested in analyzing and why? "
            "Example later: I want to push back on this — I think there is a significant problem with X and here is "
            "why. How do you respond?"
        ),
        "demanding": (
            "You are in the inquiry phase. Immediately probe the foundations of everything the student says. Move "
            "quickly to direct adversarial challenge once the student has established a position. Steelman opposing "
            "positions as strongly as possible. Do not let any undefended claim pass. Push until the student gives a "
            "response grounded in specific reasoning or course knowledge. "
            "Example early: you said that with certainty — what is that certainty based on and what would have to be "
            "true for you to be wrong? "
            "Example later: your argument collapses if you accept this premise which most scholars in this field do. "
            "Defend your position with specific evidence or revise it."
        ),
    },
    "collaborate": {
        "supportive": (
            "You are in the collaborating phase. Only build on ideas the student has already introduced. Never "
            "generate a new idea from scratch. Expand and develop what the student offers. After every contribution "
            "ask the student what they think and whether it fits their vision. "
            "Example: you mentioned X — let me help you think through what that would look like in practice. What "
            "aspects feel most important to develop?"
        ),
        "balanced": (
            "You are in the collaborating phase. Contribute new ideas and possibilities framed as options for the "
            "student to evaluate. For every idea you offer immediately ask the student what they think and whether "
            "it fits. "
            "Example: here are two or three directions that could work — which one feels most aligned with what you "
            "are trying to say and why?"
        ),
        "demanding": (
            "You are in the collaborating phase. Contribute generously including unexpected angles and connections "
            "the student may not have considered. Challenge the student to evaluate all options rigorously and justify "
            "choices with explicit reasoning tied to the learning objective. Never let the student choose a direction "
            "arbitrarily. "
            "Example: you have several directions available — eliminate the weaker ones and tell me exactly why each "
            "one does not serve your goal as well as the one you choose."
        ),
    },
    "evaluate": {
        "supportive": (
            "You are in the evaluating phase. Identify two specific things that are working well with evidence and "
            "one specific area for development framed as a question. Be encouraging without being empty or "
            "sycophantic. "
            "Example: your argument about X is genuinely strong because of Y — the area I would think more about is "
            "Z. What do you think is the weakest part of what you have developed?"
        ),
        "balanced": (
            "You are in the evaluating phase. Give equal specific weight to what is working and what needs "
            "development. Name the strongest moment in the conversation and the moment where the thinking was least "
            "convincing. Ask the student what they would change based on this feedback. "
            "Example: the strongest part of your thinking was X — that was original and well-reasoned. The least "
            "convincing part was Y because Z. What would you revise?"
        ),
        "demanding": (
            "You are in the evaluating phase. Give a rigorous honest assessment prioritizing specificity over "
            "encouragement. Name the most significant weakness in the argument or design directly. Do not balance "
            "negative feedback with positive feedback artificially. Ask the student to defend or revise the weakest "
            "element. "
            "Example: the core problem with your argument is X and it undermines the whole analysis. Either fix that "
            "or explain why it is not actually a problem."
        ),
    },
}

MODALITY_GUIDANCE = {
    "inquire": {
        "critical_analysis": "Focus on the argument the student wants to make and the evidence they have for it.",
        "podcast_script": "Focus on the student's editorial voice, intended audience, and the angle they want to take.",
        "game_design": "Focus on what the student wants players to learn and why it matters.",
        "presentation_outline": "Focus on the student's argument and intended audience.",
        "video_script": "Focus on the story the student wants to tell and the viewer experience they want to create.",
    },
    "collaborate": {
        "critical_analysis": "Help develop the argument structure and evidence.",
        "podcast_script": "Help develop the narrative structure and voice.",
        "game_design": "Help develop the game mechanics and player experience.",
        "presentation_outline": "Help develop the argument flow and key points.",
        "video_script": "Help develop the narrative arc and visual structure.",
    },
    "evaluate": {
        "critical_analysis": "Assess the argument's logical coherence and use of evidence.",
        "podcast_script": "Assess how effectively the script communicates to its intended audience.",
        "game_design": "Assess whether the design achieves its learning objective.",
        "presentation_outline": "Assess the argument's persuasive effectiveness for the intended audience.",
        "video_script": "Assess whether the script achieves its intended emotional and intellectual impact.",
    },
}

UNIVERSAL_CRITERIA = [
    {
        "criterion_name": "Intellectual ownership",
        "criterion_description": "Are the ideas in this conversation yours?",
        "level_emerging": "Needs work",
        "level_developing": "Developing",
        "level_integrated": "Completed",
    },
    {
        "criterion_name": "Depth of elaboration",
        "criterion_description": "Did your thinking get deeper as the conversation progressed?",
        "level_emerging": "Needs work",
        "level_developing": "Developing",
        "level_integrated": "Completed",
    },
    {
        "criterion_name": "Critical evaluation",
        "criterion_description": "Did you judge what AI produced rather than accept it?",
        "level_emerging": "Needs work",
        "level_developing": "Developing",
        "level_integrated": "Completed",
    },
    {
        "criterion_name": "Knowledge application",
        "criterion_description": "Did you use what you learned in class to steer the conversation?",
        "level_emerging": "Needs work",
        "level_developing": "Developing",
        "level_integrated": "Completed",
    },
]

CLOSING_RULES = (
    "Write in plain conversational prose with no markdown formatting no asterisks no bold text no bullet points. "
    "Never exceed 100 words. Use fewer words whenever possible. Do not pad responses to reach any minimum length. "
    "Only offer to elaborate when your response genuinely runs out of space before running out of content."
)


def build_system_prompt(assignment, course, exchange_count: int) -> str:
    """Build the full system prompt for an AI session based on the phase progression system."""
    phase_1_end = assignment.phase_1_end or 3
    phase_2_end = assignment.phase_2_end or 6

    if exchange_count < phase_1_end:
        phase_key = "inquire"
    elif exchange_count < phase_2_end:
        phase_key = "collaborate"
    else:
        phase_key = "evaluate"

    intensity = getattr(assignment, "intensity", None) or "balanced"
    phase_rules = PHASE_SYSTEM[phase_key][intensity]

    modality_key = MODALITY_KEY_MAP.get(assignment.modality or "", "")
    modality_guidance = MODALITY_GUIDANCE[phase_key].get(
        modality_key,
        "Adapt your approach to the specific requirements of this assignment.",
    )

    parts = [phase_rules, modality_guidance]

    supp = (assignment.supplementary_instructions or "").strip()
    if supp:
        parts.append(
            f"The instructor has added the following specific guidance, which you must follow "
            f"in addition to your core role: {supp}"
        )

    instr = (assignment.instructions or "").strip()
    if instr:
        parts.append(
            f"The assignment instructions are as follows, and you must follow them exactly: {instr}"
        )
    else:
        parts.append(
            "No specific assignment instructions have been provided. "
            "Help the student think deeply about any topic they raise."
        )

    parts.append(CLOSING_RULES)

    return "\n\n".join(parts)


def _fallback_summary(note: str) -> dict:
    return {
        "exchange_count": 0,
        "phase_reached": 1,
        "pushback_count": 0,
        "student_idea_percentage": 0,
        "concept_scores": [],
        "criteria_scores": [],
        "key_moments": [],
        "threads": [],
        "exchanges": [],
        "_note": f"Scoring could not be completed. {note}",
    }


def _to_second_person(text: str) -> str:
    if not isinstance(text, str):
        return text
    text = re.sub(r'\bThe student\b', 'You', text)
    text = re.sub(r'\bthe student\b', 'you', text)
    text = re.sub(r'\bStudent\b', 'You', text)
    text = re.sub(r'\bstudent\b', 'you', text)
    return text


def generate_session_summary(student_id: int, assignment_id: int) -> dict:
    """Generate and cache an AI-scored session summary using universal criteria."""
    from models.models import PromptExchange, Assignment, SessionSummary
    from extensions import db

    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return _fallback_summary("Assignment not found.")

    criteria_names = [c["criterion_name"] for c in UNIVERSAL_CRITERIA]

    exchanges = (
        PromptExchange.query
        .filter_by(student_id=student_id, assignment_id=assignment_id)
        .order_by(PromptExchange.exchange_number)
        .all()
    )

    if not exchanges:
        return _fallback_summary("No exchanges found.")

    transcript = "\n\n".join(
        f"Exchange {ex.exchange_number}:\nStudent: {ex.student_message}\nAI: {ex.ai_response}"
        for ex in exchanges
    )

    scoring_prompt = (
        f"Evaluate this conversation against the following four criteria only.\n\n"
        f"Intellectual ownership: did the student introduce their own ideas and positions rather than simply "
        f"responding to AI.\n\n"
        f"Depth of elaboration: did the student's thinking deepen across exchanges rather than staying at the "
        f"same level.\n\n"
        f"Critical evaluation: did the student evaluate and push back on AI output using their own reasoning.\n\n"
        f"Knowledge application: did the student use course concepts or disciplinary knowledge to steer the "
        f"conversation toward more rigorous territory.\n\n"
        f"Score each criterion from 0 to 100 and assign a level of needs work, developing, or completed. "
        f"Do not reference any archetype. "
        f"Do not reference any concept that does not appear in this specific conversation. "
        f"Base all scores and feedback entirely on what this specific student wrote.\n\n"
        f"=== Conversation Transcript ===\n{transcript}\n\n"
        f"IMPORTANT: Write all evidence sentences in second person, addressing the student directly as 'you'. "
        f"For example: 'You introduced an original idea that was not prompted by the AI.' "
        f"Never write 'the student' or 'student' in any evidence or description field.\n\n"
        f"Return only valid JSON with no other text. The JSON must have exactly these fields:\n"
        f"- exchange_count: integer\n"
        f"- phase_reached: integer 1 through 3\n"
        f"- pushback_count: integer\n"
        f"- student_idea_percentage: integer 0 through 100\n"
        f"- concept_scores: array of objects each with concept_name, introduced_by (\"student\" or \"ai\"), "
        f"depth_score (0-100), times_used\n"
        f"- criteria_scores: array of 4 objects each with criterion_name, level (\"needs work\", \"developing\", "
        f"or \"completed\"), score (0-100), evidence (one sentence in second person addressing the student as you)\n"
        f"- key_moments: array of exactly 3 objects each with type (\"strongest\", \"pushback\", or \"gap\"), "
        f"exchange_number, description (one sentence in second person)\n"
        f"- threads: array of exactly 3 objects each with text (one sentence), source (e.g. \"exchange 3\")\n\n"
        f"Criterion names must match exactly: {', '.join(criteria_names)}"
    )

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": scoring_prompt}],
        )
        raw = response.content[0].text.strip()
        cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(cleaned)
    except Exception as exc:
        result = _fallback_summary(str(exc))

    for cs in result.get("criteria_scores", []):
        cs["evidence"] = _to_second_person(cs.get("evidence", ""))
    for km in result.get("key_moments", []):
        km["description"] = _to_second_person(km.get("description", ""))
    for t in result.get("threads", []):
        t["text"] = _to_second_person(t.get("text", ""))

    result["exchanges"] = [
        {
            "exchange_number": ex.exchange_number,
            "has_pushback": ex.has_pushback,
            "concepts_applied": ex.concepts_applied or [],
        }
        for ex in exchanges
    ]

    # Always delete any cached summary and create a fresh record so each
    # click of "Review my session" reflects the full current conversation.
    existing = SessionSummary.query.filter_by(
        student_id=student_id, assignment_id=assignment_id
    ).first()
    if existing:
        db.session.delete(existing)
        db.session.flush()

    now = datetime.utcnow()
    db.session.add(SessionSummary(
        student_id=student_id,
        assignment_id=assignment_id,
        summary_json=json.dumps(result),
        generated_at=now,
    ))
    db.session.commit()

    result["generated_at"] = now.strftime("%H:%M")
    return result


def generate_reflection_summary(student_id: int, assignment_id: int) -> dict:
    """Score the student's reflection answers against the four universal criteria adapted for reflection context."""
    from models.models import Reflection, Assignment, SessionSummary
    from extensions import db

    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return {"criteria_scores": []}

    reflection = Reflection.query.filter_by(
        student_id=student_id, assignment_id=assignment_id
    ).first()

    if not reflection or not any([reflection.question_1, reflection.question_2, reflection.question_3]):
        return {"criteria_scores": []}

    reflection_text = (
        f"Q1: {reflection.question_1 or ''}\n\n"
        f"Q2: {reflection.question_2 or ''}\n\n"
        f"Q3: {reflection.question_3 or ''}"
    )

    criteria_names = [c["criterion_name"] for c in UNIVERSAL_CRITERIA]

    scoring_prompt = (
        f"Evaluate the following student reflection against the four criteria below.\n\n"
        f"Intellectual ownership: did the student identify ideas in the reflection that are genuinely "
        f"their own rather than restating AI output from the conversation.\n\n"
        f"Depth of elaboration: did the student go beyond surface observations and develop their "
        f"reflective thinking with specificity and nuance.\n\n"
        f"Critical evaluation: did the student honestly assess both the strengths and limitations of "
        f"their own thinking and their AI interaction.\n\n"
        f"Knowledge application: did the student connect course concepts or disciplinary knowledge to "
        f"what they developed in the conversation and their assignment plan.\n\n"
        f"Score each criterion from 0 to 100 and assign a level of needs work, developing, or completed. "
        f"Base all scores entirely on what the student actually wrote in their reflection answers.\n\n"
        f"=== Student Reflection ===\n{reflection_text}\n\n"
        f"IMPORTANT: Write all evidence sentences in second person, addressing the student directly as 'you'. "
        f"For example: 'You identified an original insight that was not present in the AI conversation.' "
        f"Never write 'the student' or 'student' in any evidence or description field.\n\n"
        f"Return only valid JSON with no other text. The JSON must have exactly this field:\n"
        f"- criteria_scores: array of 4 objects each with criterion_name, level (\"needs work\", \"developing\", "
        f"or \"completed\"), score (0-100), evidence (one sentence in second person)\n\n"
        f"Criterion names must match exactly: {', '.join(criteria_names)}"
    )

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": scoring_prompt}],
        )
        raw = response.content[0].text.strip()
        cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(cleaned)
    except Exception as exc:
        result = {"criteria_scores": [], "_note": f"Scoring could not be completed. {exc}"}

    for cs in result.get("criteria_scores", []):
        cs["evidence"] = _to_second_person(cs.get("evidence", ""))

    summary_rec = SessionSummary.query.filter_by(
        student_id=student_id, assignment_id=assignment_id
    ).first()
    if summary_rec:
        summary_rec.reflection_summary_json = json.dumps(result)
        db.session.commit()

    return result
