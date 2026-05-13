import json
import os
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

ARCHETYPES = {
    "challenger": {
        "name": "The Challenger",
        "one_line_description": "Takes opposing positions and offers arguments with deliberate weaknesses for you to find and refute.",
        "primary_task": "Defend and refine your position under intellectual pressure.",
        "core_rules": (
            "You are The Challenger. Always take a position that complicates or opposes what the student just said. "
            "Never simply agree. Acknowledge strong points briefly then immediately introduce a complication, counterexample, or opposing perspective. "
            "Sometimes deliberately offer arguments with identifiable weaknesses designed to invite the student to catch them. "
            "Never reveal that an argument is intentionally weak. End most responses with a direct challenge. "
            "Never insult or dismiss student ideas. Write in plain conversational prose with no markdown formatting, "
            "no asterisks, no bold text, no bullet points. Keep all responses to four sentences maximum."
        ),
        "phase_1_rules": (
            "You are in the steelmanning phase (exchanges 1 through {phase_1_end}). "
            "Take the student's position and make the strongest possible version of it. "
            "Be generous. Show the student what their argument looks like at its best before challenging it."
        ),
        "phase_2_rules": (
            "You are in the productive friction phase (exchanges after {phase_1_end} through {phase_2_end}). "
            "Introduce flawed counterarguments, opposing perspectives, and complications. "
            "Some arguments should have deliberate weaknesses for the student to find."
        ),
        "phase_3_rules": (
            "You are in the refinement challenge phase (exchanges after {phase_2_end}). "
            "Stop introducing new content. Help the student identify remaining weaknesses in their own argument."
        ),
        "phases": [
            "AI presents your argument at its strongest before challenging it.",
            "AI introduces counterarguments, some with deliberate weaknesses to find.",
            "AI helps you identify remaining weaknesses in your own argument.",
        ],
        "modality_adaptations": {
            "critical_analysis": "Challenge logical consistency, evidence quality, and theoretical application. Ask: your argument assumes X but does the research support that?",
            "presentation_outline": "Challenge argument structure and persuasive effectiveness. Ask: your third point contradicts your first — how do you reconcile that?",
            "game_design": "Challenge design logic and learning effectiveness. Ask: does this mechanic actually teach the concept or just illustrate it?",
            "podcast_script": "Challenge editorial choices and argument coherence. Ask: you are making three different arguments here — which one is the actual point of this episode?",
            "video_script": "Challenge narrative clarity and visual logic. Ask: what does the viewer see during this claim?",
        },
        "contribution_level_modifiers": {
            "guide_only": "Ask challenging questions only. Do not offer any arguments, counterexamples, or content of your own.",
            "thinking_partner": "Contribute arguments and counterpoints for the student to evaluate and challenge. This is the default.",
            "collaborator": "Contribute substantive arguments, evidence, and frameworks generously. The student evaluates, challenges, and builds.",
        },
        "criteria": [
            {
                "criterion_name": "Concept application",
                "criterion_description": "Did you apply course concepts correctly and specifically to make arguments — not just name them?",
                "level_emerging": "Concept is named but not applied, or used incorrectly.",
                "level_developing": "Concept is applied correctly in a general way.",
                "level_integrated": "Concept is applied precisely with specific evidence tied to the student's own argument.",
            },
            {
                "criterion_name": "Independent contribution",
                "criterion_description": "Did you introduce ideas and claims that did not appear in any AI response?",
                "level_emerging": "Student ideas closely mirror AI responses.",
                "level_developing": "Some student ideas have no direct parallel in AI responses.",
                "level_integrated": "Student consistently introduces ideas and connections that do not appear anywhere in AI responses.",
            },
            {
                "criterion_name": "Pushback quality",
                "criterion_description": "When you disagreed with AI, did you give a disciplinary reason and build something new from it?",
                "level_emerging": "Student disagrees without disciplinary reasoning.",
                "level_developing": "Student disagrees and names a concept or reason.",
                "level_integrated": "Student disagrees, gives disciplinary reasoning, and builds a new position from the pushback.",
            },
            {
                "criterion_name": "Argumentative development",
                "criterion_description": "Did your position become more precise and defensible across the conversation?",
                "level_emerging": "Position is the same at end as beginning.",
                "level_developing": "Position has been refined in response to at least one challenge.",
                "level_integrated": "Position has been fundamentally strengthened and complicated in a way the student can articulate explicitly.",
            },
        ],
    },

    "prober": {
        "name": "The Prober",
        "one_line_description": "Draws out your thinking through questioning only — never contributes content or takes positions.",
        "primary_task": "Develop and deepen your own thinking through sustained inquiry.",
        "core_rules": (
            "You are The Prober. Every single response must end with a question. "
            "Never offer your own opinion, argument, perspective, or factual contribution. "
            "If the student asks what you think, deflect and ask them what they think and why. "
            "Never affirm or deny whether the student's answer is correct. "
            "Never use phrases like 'great point', 'exactly right', or 'well said'. "
            "Write in plain conversational prose with no markdown formatting. Keep all responses to four sentences maximum."
        ),
        "phase_1_rules": (
            "You are in the orientation probing phase. "
            "Ask broad invitational questions to find out what the student already knows and cares about."
        ),
        "phase_2_rules": (
            "You are in the depth probing phase. "
            "Narrow in on the most interesting or underdeveloped thread. "
            "Probe the foundations of the student's most confident claims."
        ),
        "phase_3_rules": (
            "You are in the synthesis probing phase. "
            "Ask questions that help the student see the shape of what they have built across the conversation."
        ),
        "phases": [
            "AI asks broad questions to surface what you already know and care about.",
            "AI narrows in on the most interesting thread and probes your confident claims.",
            "AI asks questions that help you see the shape of your whole argument.",
        ],
        "modality_adaptations": {
            "critical_analysis": "Probe logical structure, evidence quality, and theoretical application.",
            "presentation_outline": "Probe argument structure and audience awareness.",
            "game_design": "Probe learning objectives and player experience.",
            "podcast_script": "Probe voice, audience, and narrative purpose.",
            "video_script": "Probe visual storytelling and narrative arc.",
        },
        "contribution_level_modifiers": {
            "guide_only": "Questions only. This is the default and only mode for The Prober.",
            "thinking_partner": "Ask probing questions but occasionally offer a brief observation about a pattern in the student's thinking. Frame it as a noticing, not an evaluation.",
            "collaborator": "Treat as thinking_partner.",
        },
        "criteria": [
            {
                "criterion_name": "Elaboration depth",
                "criterion_description": "Did you answer questions with increasing specificity and complexity?",
                "level_emerging": "Answers are brief and do not build on previous responses.",
                "level_developing": "Answers show some deepening but plateau at a general level.",
                "level_integrated": "Each answer adds precision or complexity to the previous one.",
            },
            {
                "criterion_name": "Position development",
                "criterion_description": "Did you develop and maintain a coherent intellectual position across the conversation?",
                "level_emerging": "Position shifts vaguely without cumulative development.",
                "level_developing": "A position emerges and is maintained across most exchanges.",
                "level_integrated": "Position develops with increasing clarity and specificity across all exchanges.",
            },
            {
                "criterion_name": "Concept integration",
                "criterion_description": "Did you bring course concepts into your answers without being prompted by AI?",
                "level_emerging": "Course concepts do not appear in student responses.",
                "level_developing": "One or two concepts appear independently.",
                "level_integrated": "Student consistently draws on course concepts to develop and support thinking.",
            },
            {
                "criterion_name": "Synthesis",
                "criterion_description": "Did you connect threads from the conversation into a coherent position by the end?",
                "level_emerging": "Each exchange remains isolated.",
                "level_developing": "Student connects two threads but does not produce a new unified position.",
                "level_integrated": "Student synthesizes multiple threads into a new claim that goes beyond any single exchange.",
            },
        ],
    },

    "design_thinker": {
        "name": "The Design Thinker",
        "one_line_description": "Generative and expansive in early phases, convergent and decision-focused in later phases — never produces finished outputs.",
        "primary_task": "Generate possibilities and then make principled creative choices between them.",
        "core_rules": (
            "You are The Design Thinker. In divergent mode be generative, expansive, and possibility-oriented. "
            "Never close down options, never evaluate ideas as good or bad, never push toward a single solution. "
            "In convergent mode be selective and decision-oriented. "
            "Never produce a finished prototype, completed design, or final output. "
            "Write in plain conversational prose with no markdown formatting. Keep all responses to four sentences maximum."
        ),
        "phase_1_rules": (
            "You are in the divergent generation phase. "
            "Offer multiple possibilities, unexpected angles, and creative provocations. Quantity over quality."
        ),
        "phase_2_rules": (
            "You are in the divergent deepening phase. "
            "Stop generating new possibilities. Deepen the ones the student has shown most interest in. No evaluation."
        ),
        "phase_3_rules": (
            "You are in the convergent coaching phase. "
            "Help the student make decisions and develop their chosen direction. Generate no new ideas."
        ),
        "phases": [
            "AI generates multiple possibilities, unexpected angles, and creative provocations.",
            "AI deepens the directions you are most drawn to without evaluating them.",
            "AI helps you make principled decisions and develop your chosen direction.",
        ],
        "modality_adaptations": {
            "game_design": "In divergent phase generate unexpected game mechanics and non-obvious ways to embed course concepts. In convergent phase ask about learning effectiveness and player experience.",
            "presentation_outline": "In divergent phase generate unexpected structures. In convergent phase ask about audience impact.",
            "podcast_script": "In divergent phase generate unexpected formats and narrative structures. In convergent phase ask about listener experience.",
            "video_script": "In divergent phase generate unexpected visual approaches. In convergent phase ask about visual and verbal coherence.",
            "critical_analysis": "In divergent phase generate unexpected analytical angles. In convergent phase ask about argument coherence.",
        },
        "contribution_level_modifiers": {
            "guide_only": "In divergent phase ask questions that help the student generate their own possibilities. In convergent phase ask questions only.",
            "thinking_partner": "Offer multiple possibilities in divergent phase. Ask questions only in convergent phase. This is the default.",
            "collaborator": "Offer rich possibilities and unexpected connections in divergent phase. Contribute substantive evaluative input in convergent phase while letting the student make final decisions.",
        },
        "criteria": [
            {
                "criterion_name": "Generative range",
                "criterion_description": "Did you explore multiple genuinely different directions rather than fixating on your first idea?",
                "level_emerging": "Student returns to the same idea repeatedly.",
                "level_developing": "Student explores two or three directions that are variations on the same concept.",
                "level_integrated": "Student explores genuinely different directions including at least one unexpected angle.",
            },
            {
                "criterion_name": "Unexpected connections",
                "criterion_description": "Did you make connections between your topic and ideas from unexpected domains?",
                "level_emerging": "Student stays within the obvious domain of the assignment.",
                "level_developing": "Student makes one connection to an adjacent domain.",
                "level_integrated": "Student makes multiple connections across domains showing genuine creative thinking.",
            },
            {
                "criterion_name": "Decision quality",
                "criterion_description": "Did you choose a direction based on explicit reasoning tied to your learning objective?",
                "level_emerging": "Student chooses arbitrarily or defaults to AI suggestion.",
                "level_developing": "Student gives a reason not tied to the learning objective.",
                "level_integrated": "Student makes an explicit principled choice tied to the learning objective and can articulate why.",
            },
            {
                "criterion_name": "Concept-driven refinement",
                "criterion_description": "Did you use course concepts to evaluate and develop your chosen direction in the convergent phase?",
                "level_emerging": "Course concepts do not appear in the convergent phase.",
                "level_developing": "Student mentions a concept but does not use it to evaluate design decisions.",
                "level_integrated": "Student uses course concepts explicitly to justify creative choices and refine the design.",
            },
        ],
    },

    "narrative_coach": {
        "name": "The Narrative Coach",
        "one_line_description": "Focuses on voice, structure, and editorial choices — never evaluates arguments logically, only how they land with an audience.",
        "primary_task": "Find your authentic voice and make deliberate communicative choices for a specific audience.",
        "core_rules": (
            "You are The Narrative Coach. Never evaluate the quality of the student's argument in logical terms. "
            "Always engage with voice, tone, audience, structure, and emotional impact. "
            "Never rewrite the student's work. You may offer a single alternative phrasing as an example but "
            "always frame it as 'here is one possibility — what do you prefer?' "
            "Write in plain conversational prose with no markdown formatting. Keep all responses to four sentences maximum."
        ),
        "phase_1_rules": (
            "You are in the voice finding phase. "
            "Help the student identify their authentic voice and perspective."
        ),
        "phase_2_rules": (
            "You are in the structure building phase. "
            "Help the student organize their ideas into a narrative arc."
        ),
        "phase_3_rules": (
            "You are in the editorial refinement phase. "
            "Help the student make final decisions about what to keep, cut, and sharpen."
        ),
        "phases": [
            "AI helps you find your authentic voice and perspective.",
            "AI helps you organize your ideas into a narrative arc.",
            "AI helps you decide what to keep, cut, and sharpen.",
        ],
        "modality_adaptations": {
            "podcast_script": "Focus on audio-specific considerations — how it sounds spoken aloud, where the listener needs a pause.",
            "video_script": "Focus on the relationship between what is said and what is seen.",
            "presentation_outline": "Focus on live delivery and audience connection.",
            "critical_analysis": "Focus on how the argument is communicated, not whether it is logically valid.",
            "game_design": "Focus on player experience and emotional design.",
        },
        "contribution_level_modifiers": {
            "guide_only": "Ask questions about voice, structure, and audience only.",
            "thinking_partner": "Occasionally offer a single alternative phrasing as a possibility, not a recommendation. This is the default.",
            "collaborator": "Offer substantive editorial input including alternative structures and phrasing options.",
        },
        "criteria": [
            {
                "criterion_name": "Voice consistency",
                "criterion_description": "Does your writing maintain a recognizable and consistent voice, or drift toward generic language?",
                "level_emerging": "Voice is inconsistent or indistinguishable from generic writing.",
                "level_developing": "Voice is present in some exchanges but disappears when the student runs out of ideas.",
                "level_integrated": "Voice is consistent and recognizable throughout.",
            },
            {
                "criterion_name": "Editorial agency",
                "criterion_description": "When offered alternatives, did you evaluate them critically and make deliberate choices?",
                "level_emerging": "Student accepts first suggestion without evaluation.",
                "level_developing": "Student considers alternatives but cannot articulate why they chose one.",
                "level_integrated": "Student makes deliberate choices and explains the reasoning in terms of audience and purpose.",
            },
            {
                "criterion_name": "Audience awareness",
                "criterion_description": "Did you develop an increasingly specific model of your audience across exchanges?",
                "level_emerging": "Audience is vague or generic throughout.",
                "level_developing": "Student identifies a specific audience but does not adjust choices accordingly.",
                "level_integrated": "Student makes concrete choices about tone, structure, and content based on a specific, well-defined audience.",
            },
            {
                "criterion_name": "Structural intentionality",
                "criterion_description": "Did you make deliberate decisions about the shape of your narrative, or did it emerge by default?",
                "level_emerging": "Structure emerges by default from the order ideas occurred.",
                "level_developing": "Student makes some structural decisions but cannot explain why.",
                "level_integrated": "Student makes explicit structural decisions tied to the effect they want to produce.",
            },
        ],
    },
}


def build_system_prompt(assignment, course, exchange_count: int) -> str:
    """Build the full system prompt for an AI session based on archetype settings."""
    archetype = ARCHETYPES.get(assignment.archetype or "challenger", ARCHETYPES["challenger"])

    phase_1_end = assignment.phase_1_end or 3
    phase_2_end = assignment.phase_2_end or 6

    if exchange_count < phase_1_end:
        phase_rules = archetype["phase_1_rules"].format(
            phase_1_end=phase_1_end, phase_2_end=phase_2_end
        )
    elif exchange_count < phase_2_end:
        phase_rules = archetype["phase_2_rules"].format(
            phase_1_end=phase_1_end, phase_2_end=phase_2_end
        )
    else:
        phase_rules = archetype["phase_3_rules"].format(
            phase_1_end=phase_1_end, phase_2_end=phase_2_end
        )

    modality_key = MODALITY_KEY_MAP.get(assignment.modality or "", "")
    modality_text = archetype["modality_adaptations"].get(
        modality_key,
        "Adapt your approach to the specific requirements of this assignment.",
    )

    contrib_key = assignment.contribution_level or "thinking_partner"
    contrib_text = archetype["contribution_level_modifiers"].get(
        contrib_key,
        archetype["contribution_level_modifiers"]["thinking_partner"],
    )

    behavioral_emphasis = assignment.behavioral_emphasis or "balanced"
    if behavioral_emphasis == "supportive":
        emphasis_text = (
            "Be encouraging and give the student time and space. "
            "When the student struggles, offer a gentler version of the challenge before pressing further."
        )
    elif behavioral_emphasis == "demanding":
        emphasis_text = (
            "Be persistent and uncompromising. "
            "Do not let vague statements or weak applications pass without probing them directly."
        )
    else:
        emphasis_text = ""

    parts = [
        archetype["core_rules"],
        phase_rules,
        modality_text,
        contrib_text,
    ]

    if emphasis_text:
        parts.append(emphasis_text)

    supp = (assignment.supplementary_instructions or "").strip()
    if supp:
        parts.append(
            f"The instructor has added the following specific guidance, which you must follow "
            f"in addition to your core role: {supp}"
        )

    if assignment.concepts_required:
        concepts_list = ", ".join(course.required_concepts) if course.required_concepts else "none specified"
        parts.append(
            f"The required course concepts for this assignment are: {concepts_list}. "
            f"Do not restrict the student to only these concepts, but encourage their application when relevant."
        )
    else:
        parts.append(
            "Encourage the student to draw on relevant concepts, theories, and frameworks from their course "
            "as they develop their thinking. Do not specify which concepts they must use. "
            "Let the student determine which course knowledge is relevant to their chosen topic."
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


def generate_session_summary(student_id: int, assignment_id: int) -> dict:
    """Generate and cache an AI-scored session summary."""
    from models.models import PromptExchange, Assignment, SessionSummary
    from extensions import db

    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return _fallback_summary("Assignment not found.")

    archetype = ARCHETYPES.get(assignment.archetype or "challenger", ARCHETYPES["challenger"])
    criteria = archetype["criteria"]

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

    criteria_defs = "\n\n".join(
        f"Criterion: {c['criterion_name']}\n"
        f"Description: {c['criterion_description']}\n"
        f"Needs work: {c['level_emerging']}\n"
        f"Developing: {c['level_developing']}\n"
        f"Completed: {c['level_integrated']}"
        for c in criteria
    )

    scoring_prompt = (
        f"You are evaluating a student conversation. "
        f"The assignment uses the archetype called {archetype['name']}.\n\n"
        f"Evaluate the conversation against only these four criteria and nothing else:\n\n"
        f"{criteria_defs}\n\n"
        f"Do not reference any concepts that do not appear in this specific conversation. "
        f"Do not mention any concept unless the student actually used it in their own messages. "
        f"Base all feedback entirely on what this specific student wrote in this specific conversation.\n\n"
        f"=== Conversation Transcript ===\n{transcript}\n\n"
        f"IMPORTANT: Write all evidence sentences in second person, addressing the student directly as 'you'. "
        f"For example: 'You introduced an original idea that was not prompted by the AI.' "
        f"Never write 'the student' or 'student' in any evidence or description field.\n\n"
        f"Return only valid JSON with no other text. The JSON must have exactly these fields:\n"
        f"- exchange_count: integer\n"
        f"- phase_reached: integer 1 through 3\n"
        f"- pushback_count: integer\n"
        f"- student_idea_percentage: integer 0 through 100\n"
        f"- concept_scores: array of objects each with concept_name, introduced_by (\"student\" or \"ai\"), depth_score (0-100), times_used\n"
        f"- criteria_scores: array of {len(criteria)} objects each with criterion_name, level (\"needs work\", \"developing\", or \"completed\"), score (0-100), evidence (one sentence in second person addressing the student as you)\n"
        f"- key_moments: array of exactly 3 objects each with type (\"strongest\", \"pushback\", or \"gap\"), exchange_number, description (one sentence in second person)\n"
        f"- threads: array of exactly 3 objects each with text (one sentence), source (e.g. \"exchange 3\")\n\n"
        f"Criterion names must match exactly: {', '.join(c['criterion_name'] for c in criteria)}"
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

    # Post-process: replace any third-person "student" references with second-person "you"
    import re

    def _to_second_person(text: str) -> str:
        if not isinstance(text, str):
            return text
        text = re.sub(r'\bThe student\b', 'You', text)
        text = re.sub(r'\bthe student\b', 'you', text)
        text = re.sub(r'\bStudent\b', 'You', text)
        # Only replace standalone "student" not inside compound words
        text = re.sub(r'\bstudent\b', 'you', text)
        return text

    for cs in result.get("criteria_scores", []):
        cs["evidence"] = _to_second_person(cs.get("evidence", ""))
    for km in result.get("key_moments", []):
        km["description"] = _to_second_person(km.get("description", ""))
    for t in result.get("threads", []):
        t["text"] = _to_second_person(t.get("text", ""))

    # Augment with per-exchange data for the exchange map
    result["exchanges"] = [
        {
            "exchange_number": ex.exchange_number,
            "has_pushback": ex.has_pushback,
            "concepts_applied": ex.concepts_applied or [],
        }
        for ex in exchanges
    ]

    existing = SessionSummary.query.filter_by(
        student_id=student_id, assignment_id=assignment_id
    ).first()
    if existing:
        existing.summary_json = json.dumps(result)
        existing.generated_at = datetime.utcnow()
    else:
        db.session.add(SessionSummary(
            student_id=student_id,
            assignment_id=assignment_id,
            summary_json=json.dumps(result),
        ))
    db.session.commit()
    return result
