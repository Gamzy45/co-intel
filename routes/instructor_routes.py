from datetime import datetime

from flask import Blueprint, jsonify, render_template, redirect, request, session, url_for
from extensions import db
from models.models import (
    Assignment, AssessmentScore, Course, InstructorFeedback, Output,
    PromptExchange, Reflection, ReflectionConfig, Student,
)
from services.ai_service import score_engagement, analyze_assignment_authorship
from config import MODALITY_SECTIONS, DEFAULT_REFLECTION_QUESTIONS

instructor_bp = Blueprint("instructor", __name__, url_prefix="/instructor")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _depth_label(score):
    if score is None:
        return "pending"
    if score >= 75:
        return "deep"
    if score >= 45:
        return "moderate"
    return "surface"


def _get_base():
    """Return (course, assignment) based on session course_id."""
    course_id = session.get("course_id")
    if course_id:
        course = Course.query.get(course_id)
    else:
        course = Course.query.first()
        if course:
            session["course_id"] = course.id
    if not course:
        return None, None
    assignment = Assignment.query.filter_by(course_id=course.id).first()
    return course, assignment


def _get_base_for_student(student):
    """Derive course and assignment from a specific student record."""
    course = Course.query.get(student.course_id)
    assignment = Assignment.query.filter_by(course_id=course.id).first()
    return course, assignment


def _get_sections(assignment):
    if assignment.sections_config:
        return assignment.sections_config
    return MODALITY_SECTIONS.get(assignment.modality or "critical analysis", [])


def _student_row(student, assignment):
    exchanges = PromptExchange.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).all()
    all_concepts = set()
    for ex in exchanges:
        all_concepts.update(ex.concepts_applied or [])

    score_rec = AssessmentScore.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first()
    overall = score_rec.overall_score if score_rec else None

    has_feedback = InstructorFeedback.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first() is not None

    return {
        "student": student,
        "exchange_count": len(exchanges),
        "concepts_count": len(all_concepts),
        "overall_score": overall,
        "depth_label": _depth_label(overall),
        "initials": "".join(p[0].upper() for p in student.name.split()[:2]),
        "has_feedback": has_feedback,
    }


def _get_reflection_config(assignment_id):
    """Return reflection config as a dict, falling back to defaults."""
    cfg = ReflectionConfig.query.filter_by(assignment_id=assignment_id).first()
    if cfg:
        return {
            "question_1": cfg.question_1,
            "question_2": cfg.question_2,
            "question_3": cfg.question_3,
            "hint_1": cfg.hint_1 or "",
            "hint_2": cfg.hint_2 or "",
            "hint_3": cfg.hint_3 or "",
        }
    return {k: (v or "") for k, v in DEFAULT_REFLECTION_QUESTIONS.items()}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@instructor_bp.route("/")
def index():
    return redirect(url_for("instructor.dashboard"))


@instructor_bp.route("/dashboard")
def dashboard():
    course, assignment = _get_base()
    students = Student.query.filter_by(course_id=course.id).all()
    rows = [_student_row(s, assignment) for s in students]

    active_count = sum(1 for r in rows if r["exchange_count"] > 0)
    exchange_counts = [r["exchange_count"] for r in rows if r["exchange_count"] > 0]
    avg_exchanges = round(sum(exchange_counts) / len(exchange_counts), 1) if exchange_counts else 0
    deep_count = sum(1 for r in rows if r["depth_label"] == "deep")
    reflection_count = Reflection.query.filter_by(assignment_id=assignment.id).count()

    sections = _get_sections(assignment)
    reflection_config = _get_reflection_config(assignment.id)

    return render_template(
        "instructor/dashboard.html",
        course=course,
        assignment=assignment,
        rows=rows,
        active_count=active_count,
        avg_exchanges=avg_exchanges,
        deep_count=deep_count,
        reflection_count=reflection_count,
        sections=sections,
        sections_defaults=MODALITY_SECTIONS,
        reflection_config=reflection_config,
        default_questions=DEFAULT_REFLECTION_QUESTIONS,
    )


@instructor_bp.route("/assignment-config", methods=["POST"])
def assignment_config():
    _, assignment = _get_base()
    data = request.get_json(silent=True) or {}
    modality = data.get("modality", "").strip()
    instructions = data.get("instructions", "").strip()
    sections_config = data.get("sections_config")

    if not modality:
        return jsonify({"error": "Modality is required."}), 400

    assignment.modality = modality
    assignment.instructions = instructions
    if sections_config is not None:
        assignment.sections_config = sections_config

    db.session.commit()
    return jsonify({"success": True})


@instructor_bp.route("/student/<int:student_id>/log")
def log(student_id):
    student = Student.query.get_or_404(student_id)
    course, assignment = _get_base_for_student(student)
    exchanges = (
        PromptExchange.query
        .filter_by(student_id=student_id, assignment_id=assignment.id)
        .order_by(PromptExchange.exchange_number)
        .all()
    )
    all_concepts = set()
    for ex in exchanges:
        all_concepts.update(ex.concepts_applied or [])

    return render_template(
        "instructor/log.html",
        course=course,
        assignment=assignment,
        student=student,
        exchanges=exchanges,
        exchange_count=len(exchanges),
        concept_count=len(all_concepts),
    )


@instructor_bp.route("/student/<int:student_id>/assignment")
def assignment(student_id):
    student = Student.query.get_or_404(student_id)
    course, assignment = _get_base_for_student(student)

    exchanges = PromptExchange.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).all()
    output = Output.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()

    all_concepts = set()
    pushback_count = 0
    for ex in exchanges:
        all_concepts.update(ex.concepts_applied or [])
        if ex.has_pushback:
            pushback_count += 1

    sections = _get_sections(assignment)

    # Determine analysis state
    if output and output.analysis_json:
        generating_analysis = False
    elif output:
        generating_analysis = True
    else:
        generating_analysis = False

    return render_template(
        "instructor/assignment.html",
        course=course,
        assignment=assignment,
        student=student,
        output=output,
        exchange_count=len(exchanges),
        concepts_count=len(all_concepts),
        pushback_count=pushback_count,
        sections=sections,
        generating_analysis=generating_analysis,
    )


@instructor_bp.route("/student/<int:student_id>/assignment/analyze", methods=["POST"])
def assignment_analyze(student_id):
    student = Student.query.get_or_404(student_id)
    course, assignment = _get_base_for_student(student)

    output = Output.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()

    if not output:
        return jsonify({"error": "No submission found."}), 404

    if output.analysis_json:
        return jsonify({"success": True})  # already cached

    exchanges = (
        PromptExchange.query
        .filter_by(student_id=student_id, assignment_id=assignment.id)
        .order_by(PromptExchange.exchange_number)
        .all()
    )

    # Build full text from sections or legacy content
    sections = _get_sections(assignment)
    if output.content_sections:
        text_parts = []
        for s in sections:
            content = output.content_sections.get(s["id"], "").strip()
            if content:
                text_parts.append(f"{s['title']}\n{content}")
        assignment_text = "\n\n".join(text_parts)
    else:
        assignment_text = output.content or ""

    if not assignment_text.strip():
        return jsonify({"error": "Assignment has no content."}), 400

    exchanges_data = [
        {
            "exchange_number": ex.exchange_number,
            "student_message": ex.student_message,
            "ai_response": ex.ai_response,
        }
        for ex in exchanges
    ]

    try:
        result = analyze_assignment_authorship(assignment_text, exchanges_data, course.required_concepts)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502

    output.analysis_json = result
    output.analysis_generated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"success": True})


@instructor_bp.route("/student/<int:student_id>/reflection")
def reflection(student_id):
    student = Student.query.get_or_404(student_id)
    course, assignment = _get_base_for_student(student)
    reflection = Reflection.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()
    questions = _get_reflection_config(assignment.id)

    return render_template(
        "instructor/reflection.html",
        course=course,
        assignment=assignment,
        student=student,
        reflection=reflection,
        questions=questions,
    )


@instructor_bp.route("/student/<int:student_id>/assessment")
def assessment(student_id):
    student = Student.query.get_or_404(student_id)
    course, assignment = _get_base_for_student(student)

    score_rec = AssessmentScore.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()
    feedback = InstructorFeedback.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()

    return render_template(
        "instructor/assessment.html",
        course=course,
        assignment=assignment,
        student=student,
        score=score_rec,
        generating=(score_rec is None),
        feedback=feedback,
    )


@instructor_bp.route("/student/<int:student_id>/assessment/generate", methods=["POST"])
def assessment_generate(student_id):
    student = Student.query.get_or_404(student_id)
    course, assignment = _get_base_for_student(student)

    existing = AssessmentScore.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()
    if existing:
        return jsonify({"success": True})

    exchanges = (
        PromptExchange.query
        .filter_by(student_id=student_id, assignment_id=assignment.id)
        .order_by(PromptExchange.exchange_number)
        .all()
    )
    reflection = Reflection.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()

    exchanges_data = [
        {
            "exchange_number": ex.exchange_number,
            "student_message": ex.student_message,
            "ai_response": ex.ai_response,
            "concepts_applied": ex.concepts_applied or [],
            "has_pushback": ex.has_pushback,
        }
        for ex in exchanges
    ]
    reflection_data = {
        "question_1": reflection.question_1 if reflection else "",
        "question_2": reflection.question_2 if reflection else "",
        "question_3": reflection.question_3 if reflection else "",
    }

    try:
        result = score_engagement(exchanges_data, reflection_data, course.required_concepts)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502

    q1 = result.get("reflection_q1_score")
    q2 = result.get("reflection_q2_score")
    q3 = result.get("reflection_q3_score")
    scores = [s for s in [q1, q2, q3] if s is not None]
    avg_reflection = round(sum(scores) / len(scores)) if scores else None

    score_rec = AssessmentScore(
        student_id=student_id,
        assignment_id=assignment.id,
        concept_score=result.get("concept_score"),
        depth_score=result.get("depth_score"),
        pushback_score=result.get("pushback_score"),
        reflection_score=avg_reflection,
        reflection_q1_score=q1,
        reflection_q2_score=q2,
        reflection_q3_score=q3,
        overall_score=result.get("overall_score"),
        concept_feedback=result.get("concept_feedback"),
        depth_feedback=result.get("depth_feedback"),
        pushback_feedback=result.get("pushback_feedback"),
        reflection_feedback=result.get("reflection_feedback"),
        reflection_q1_feedback=result.get("reflection_q1_feedback"),
        reflection_q2_feedback=result.get("reflection_q2_feedback"),
        reflection_q3_feedback=result.get("reflection_q3_feedback"),
        overall_feedback=result.get("overall_feedback"),
        generated_at=datetime.utcnow(),
    )
    db.session.add(score_rec)
    db.session.commit()

    return jsonify({"success": True})


@instructor_bp.route("/student/<int:student_id>/assessment/feedback", methods=["POST"])
def assessment_feedback(student_id):
    student = Student.query.get_or_404(student_id)
    _, assignment = _get_base_for_student(student)
    data = request.get_json(silent=True) or {}
    text = data.get("feedback_text", "").strip()

    if not text:
        return jsonify({"error": "Feedback cannot be empty."}), 400

    existing = InstructorFeedback.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()
    if existing:
        existing.feedback_text = text
        existing.updated_at = datetime.utcnow()
    else:
        db.session.add(InstructorFeedback(
            student_id=student_id,
            assignment_id=assignment.id,
            feedback_text=text,
            updated_at=datetime.utcnow(),
        ))
    db.session.commit()
    return jsonify({"success": True})


@instructor_bp.route("/reflection-config", methods=["POST"])
def reflection_config():
    _, assignment = _get_base()
    data = request.get_json(silent=True) or {}

    q1 = data.get("question_1", "").strip()
    q2 = data.get("question_2", "").strip()
    q3 = data.get("question_3", "").strip()
    if not q1 or not q2 or not q3:
        return jsonify({"error": "All three questions are required."}), 400

    existing = ReflectionConfig.query.filter_by(assignment_id=assignment.id).first()
    if existing:
        existing.question_1 = q1
        existing.question_2 = q2
        existing.question_3 = q3
        existing.hint_1 = data.get("hint_1", "").strip() or None
        existing.hint_2 = data.get("hint_2", "").strip() or None
        existing.hint_3 = data.get("hint_3", "").strip() or None
        existing.updated_at = datetime.utcnow()
    else:
        db.session.add(ReflectionConfig(
            assignment_id=assignment.id,
            question_1=q1,
            question_2=q2,
            question_3=q3,
            hint_1=data.get("hint_1", "").strip() or None,
            hint_2=data.get("hint_2", "").strip() or None,
            hint_3=data.get("hint_3", "").strip() or None,
            updated_at=datetime.utcnow(),
        ))
    db.session.commit()
    return jsonify({"success": True})
