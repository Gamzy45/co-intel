import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 1000


def _client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
    return anthropic.Anthropic(api_key=api_key)


def get_ai_response(
    student_message: str,
    conversation_history: list[dict],
    course_concepts: list[str],
    learning_objective: str,
    assignment_title: str = "",
    instructions: str = "",
) -> str:
    """
    Send the current student message (with full conversation history) to Claude
    and return the assistant's text reply. All parameters are passed fresh from
    the database on every call so instructor changes take effect immediately.
    """
    if instructions.strip():
        instructions_block = (
            f"Instructor instructions: {instructions}\n"
            f"Learning objective: {learning_objective}\n"
            f"Your role is to help the student think more deeply about their chosen topic. "
            f"Follow the instructor instructions exactly. "
            f"Do not add requirements or constraints that are not in the instructor instructions. "
            f"Do not reference specific theories or frameworks unless the student brings them up first. "
            f"Ask follow-up questions that help the student develop their own argument. "
            f"Never write the assignment for them."
        )
    else:
        instructions_block = (
            f"No specific assignment instructions have been provided yet. "
            f"Help the student think deeply about any topic they raise. "
            f"Ask follow-up questions that encourage them to apply their own knowledge and challenge assumptions. "
            f"Never write for the student."
        )

    system = (
        f"You are a co-intelligence partner helping a student complete the following assignment.\n"
        f"Assignment: {assignment_title}\n"
        f"{instructions_block} "
        f"Keep responses to three to four sentences in plain conversational prose with no markdown "
        f"formatting, no asterisks, no bold text, no bullet points."
    )

    print("SYSTEM PROMPT:", system, flush=True)

    # Build messages: history + new student turn
    messages = list(conversation_history) + [
        {"role": "user", "content": student_message}
    ]

    response = _client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=messages,
    )
    return response.content[0].text


def detect_concept_usage(student_message: str, required_concepts: list[str]) -> dict:
    """
    Ask Claude to detect which required concepts appear in the student message,
    whether the message pushes back on a prior AI response, and whether the
    student is passively accepting the AI's output.

    Returns a dict with keys:
        concepts_applied  – list of matched concept strings
        has_pushback      – bool
        passive_acceptance – bool
    """
    concepts_str = ", ".join(f'"{c}"' for c in required_concepts)
    prompt = (
        f"Analyze the following student message and return ONLY valid JSON with no "
        f"extra text, markdown, or code fences.\n\n"
        f"Required concepts to check for: [{concepts_str}]\n\n"
        f"Student message:\n{student_message}\n\n"
        f"Return exactly this JSON structure:\n"
        f'{{"concepts_applied": ["<matched concept>", ...], '
        f'"has_pushback": true or false, '
        f'"passive_acceptance": true or false}}\n\n'
        f"Rules:\n"
        f"- Only include a concept in concepts_applied if the student demonstrably "
        f"uses or references it (paraphrasing counts).\n"
        f"- has_pushback is true if the student challenges, questions, or disagrees "
        f"with something the AI said in a prior turn.\n"
        f"- passive_acceptance is true if the student simply agrees with, summarises, "
        f"or echoes the AI without adding their own analysis."
    )

    response = _client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Best-effort: strip accidental markdown fences and retry
        cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {
                "concepts_applied": [],
                "has_pushback": False,
                "passive_acceptance": False,
            }


def suggest_discussion_points(
    exchanges: list[dict],
    required_concepts: list[str],
) -> dict:
    """
    Analyze student exchanges and return 3 discussion point suggestions grounded
    in what the STUDENT wrote or challenged — not AI output.

    Returns {"suggestions": [{"title": str, "suggestion": str}]}
    """
    if not exchanges:
        return {"suggestions": []}

    exchanges_text = "\n\n".join(
        f"Exchange {e.get('exchange_number', i + 1)}:\n"
        f"  Student wrote: {e['student_message']}\n"
        f"  Concepts applied: {e.get('concepts_applied', [])}\n"
        f"  Had pushback: {e.get('has_pushback', False)}"
        for i, e in enumerate(exchanges)
    )

    prompt = (
        f"You are helping a student identify threads from their own thinking to develop in a final assignment. "
        f"Analyze ONLY what the student wrote (not AI responses) and identify 3 discussion points or argument "
        f"threads the student introduced. Suggest how they could develop each one further in their own words.\n\n"
        f"Required course concepts: {', '.join(required_concepts)}\n\n"
        f"=== Student exchanges (student messages only) ===\n{exchanges_text}\n\n"
        f"Return ONLY valid JSON, no markdown, no code fences.\n"
        f"Return exactly this structure with exactly 3 suggestions:\n"
        f'{{"suggestions": ['
        f'{{"title": "5 words max", "suggestion": "1-2 sentences max, framed as a starting point not a conclusion"}}'
        f"]}}\n\n"
        f"Rules:\n"
        f"- Only reference ideas the student themselves introduced or challenged\n"
        f"- Do NOT suggest copying AI output\n"
        f"- Frame each as a question or unfinished thought, not a completed argument\n"
        f"- Each suggestion must be under 40 words"
    )

    response = _client().messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"suggestions": []}


def analyze_assignment_authorship(
    assignment_text: str,
    exchanges: list[dict],
    required_concepts: list[str],
) -> dict:
    """
    Analyze the student's final assignment against the prompting exchange log.
    Identifies which phrases are student-original, concept applications, AI-derived,
    AI-sourced, or reflect student pushback.

    Returns a dict with 'segments' (list) and four score/feedback pairs.
    """
    exchanges_text = "\n\n".join(
        f"Exchange {e.get('exchange_number', i + 1)}:\n"
        f"  Student: {e['student_message']}\n"
        f"  AI: {e['ai_response']}"
        for i, e in enumerate(exchanges)
    )

    prompt = (
        f"You are analyzing a student's final assignment to identify the origin of their ideas.\n\n"
        f"Required course concepts: {', '.join(required_concepts)}\n\n"
        f"=== Prompt Exchange Log ===\n{exchanges_text}\n\n"
        f"=== Student Final Assignment ===\n{assignment_text}\n\n"
        f"Return ONLY valid JSON with no extra text, markdown, or code fences.\n\n"
        f"Find 8–15 key phrases or sentences in the assignment and classify each as one of:\n"
        f"- 'student_original': original idea with no parallel in the AI responses\n"
        f"- 'student_concept': course concept correctly applied by the student\n"
        f"- 'ai_idea': idea that closely mirrors AI output without student elaboration\n"
        f"- 'ai_source': source, citation, or claim that originated from the AI\n"
        f"- 'student_pushback': writing that reflects a pushback the student made during prompting\n\n"
        f"Also score the student on four dimensions (integers 0–100) with one sentence of feedback each:\n"
        f"- originality_score: proportion of ideas that are student-originated\n"
        f"- new_info_score: new information added beyond what the AI produced\n"
        f"- elaboration_score: depth of expansion vs mere restatement of AI ideas\n"
        f"- concept_score: quality of course concept integration\n\n"
        f"Return exactly this JSON structure:\n"
        f'{{"segments": [{{"text": "exact substring from assignment", "type": "type_name", "explanation": "brief reason"}}, ...],'
        f'"originality_score": 0-100, "originality_feedback": "one sentence",'
        f'"new_info_score": 0-100, "new_info_feedback": "one sentence",'
        f'"elaboration_score": 0-100, "elaboration_feedback": "one sentence",'
        f'"concept_score": 0-100, "concept_feedback": "one sentence"}}\n\n'
        f"CRITICAL: every 'text' value must be an exact character-for-character substring of the "
        f"student assignment above. Copy the text precisely with no modifications."
    )

    response = _client().messages.create(
        model=MODEL,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {
                "segments": [],
                "originality_score": None, "originality_feedback": "Could not parse analysis.",
                "new_info_score": None, "new_info_feedback": "Could not parse analysis.",
                "elaboration_score": None, "elaboration_feedback": "Could not parse analysis.",
                "concept_score": None, "concept_feedback": "Could not parse analysis.",
            }


def score_engagement(
    prompt_exchanges: list[dict],
    reflection: dict,
    required_concepts: list[str],
) -> dict:
    """
    Score a student's full engagement session.

    prompt_exchanges – list of dicts with keys: student_message, ai_response,
                       concepts_applied, has_pushback, exchange_number
    reflection       – dict with keys: question_1, question_2, question_3
    required_concepts – list of concept strings from the course

    Returns a dict with scores (0-100) and feedback strings:
        concept_score, concept_feedback
        depth_score, depth_feedback
        pushback_score, pushback_feedback
        reflection_q1_score, reflection_q1_feedback
        reflection_q2_score, reflection_q2_feedback
        reflection_q3_score, reflection_q3_feedback
        overall_score, overall_feedback
    """
    exchanges_text = "\n\n".join(
        f"Exchange {e['exchange_number']}:\n"
        f"  Student: {e['student_message']}\n"
        f"  AI: {e['ai_response']}\n"
        f"  Concepts applied: {e.get('concepts_applied', [])}\n"
        f"  Has pushback: {e.get('has_pushback', False)}"
        for e in prompt_exchanges
    )

    prompt = (
        f"You are an assessment engine for a university course. "
        f"Evaluate the student's AI dialogue and reflection. "
        f"Return ONLY valid JSON with no extra text, markdown, or code fences.\n\n"
        f"Required course concepts: {', '.join(required_concepts)}\n\n"
        f"=== Prompt Exchanges ===\n{exchanges_text}\n\n"
        f"=== Reflection ===\n"
        f"Q1: {reflection.get('question_1', '')}\n"
        f"Q2: {reflection.get('question_2', '')}\n"
        f"Q3: {reflection.get('question_3', '')}\n\n"
        f"Return exactly this JSON structure (all scores are integers 0-100, "
        f"all feedback fields are concise strings of 1-2 sentences):\n"
        f'{{'
        f'"concept_score": 0-100, "concept_feedback": "...", '
        f'"depth_score": 0-100, "depth_feedback": "...", '
        f'"pushback_score": 0-100, "pushback_feedback": "...", '
        f'"reflection_q1_score": 0-100, "reflection_q1_feedback": "...", '
        f'"reflection_q2_score": 0-100, "reflection_q2_feedback": "...", '
        f'"reflection_q3_score": 0-100, "reflection_q3_feedback": "...", '
        f'"overall_score": 0-100, "overall_feedback": "..."'
        f'}}\n\n'
        f"Scoring rubric:\n"
        f"- concept_score: breadth and accuracy of required concept usage across exchanges.\n"
        f"- depth_score: analytical depth; does the student build on ideas or stay surface-level?\n"
        f"- pushback_score: quality of critical engagement; did the student challenge the AI "
        f"meaningfully at least once?\n"
        f"- reflection_q1/q2/q3_score: insight, specificity, and self-awareness in each "
        f"reflection answer.\n"
        f"- overall_score: holistic judgment weighting all dimensions."
    )

    response = _client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {
                "concept_score": None, "concept_feedback": "Could not parse assessment.",
                "depth_score": None, "depth_feedback": "Could not parse assessment.",
                "pushback_score": None, "pushback_feedback": "Could not parse assessment.",
                "reflection_q1_score": None, "reflection_q1_feedback": "Could not parse assessment.",
                "reflection_q2_score": None, "reflection_q2_feedback": "Could not parse assessment.",
                "reflection_q3_score": None, "reflection_q3_feedback": "Could not parse assessment.",
                "overall_score": None, "overall_feedback": "Could not parse assessment.",
            }
