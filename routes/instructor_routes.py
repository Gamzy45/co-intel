from datetime import datetime

from flask import Blueprint, jsonify, render_template, redirect, request, session, url_for
from flask_login import current_user
from extensions import db
import json

from models.models import (
    Assignment, AssessmentScore, Course, Grade, InstructorFeedback, Output,
    PromptExchange, Reflection, ReflectionConfig, SessionSummary, Student,
)
from services.ai_service import score_engagement, analyze_assignment_authorship
from services.archetype_service import generate_session_summary
from config import MODALITY_SECTIONS, DEFAULT_REFLECTION_QUESTIONS

instructor_bp = Blueprint("instructor", __name__, url_prefix="/instructor")


@instructor_bp.before_request
def require_instructor_role():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    if current_user.role not in ("instructor", "dev"):
        return redirect(url_for("student.prompting"))


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

    output = Output.query.filter_by(student_id=student.id, assignment_id=assignment.id).first()
    reflection = Reflection.query.filter_by(student_id=student.id, assignment_id=assignment.id).first()
    grade = Grade.query.filter_by(student_id=student.id, assignment_id=assignment.id).first()

    if output and output.is_reopened:
        output_status = "reopened"
    elif output and output.is_submitted:
        output_status = "submitted"
    else:
        output_status = "not_submitted"

    if reflection and reflection.is_reopened:
        reflection_status = "reopened"
    elif reflection and reflection.is_submitted:
        reflection_status = "submitted"
    else:
        reflection_status = "not_submitted"

    if grade and grade.is_published:
        grade_status = "published"
    elif grade and grade.feedback:
        grade_status = "draft"
    else:
        grade_status = "no_feedback"

    return {
        "student": student,
        "exchange_count": len(exchanges),
        "concepts_count": len(all_concepts),
        "overall_score": overall,
        "depth_label": _depth_label(overall),
        "initials": "".join(p[0].upper() for p in student.name.split()[:2]),
        "has_feedback": has_feedback,
        "output_status": output_status,
        "reflection_status": reflection_status,
        "grade_status": grade_status,
    }


def _get_reflection_config(assignment_id):
    """Return reflection questions as a dict, reading from Assignment model."""
    assignment = Assignment.query.get(assignment_id)
    if assignment:
        return {
            "question_1": getattr(assignment, "reflection_q1", None) or DEFAULT_REFLECTION_QUESTIONS["question_1"],
            "question_2": getattr(assignment, "reflection_q2", None) or DEFAULT_REFLECTION_QUESTIONS["question_2"],
            "question_3": getattr(assignment, "reflection_q3", None) or DEFAULT_REFLECTION_QUESTIONS["question_3"],
        }
    return {
        "question_1": DEFAULT_REFLECTION_QUESTIONS["question_1"],
        "question_2": DEFAULT_REFLECTION_QUESTIONS["question_2"],
        "question_3": DEFAULT_REFLECTION_QUESTIONS["question_3"],
    }


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

    return render_template(
        "instructor/dashboard.html",
        course=course,
        assignment=assignment,
        rows=rows,
        active_count=active_count,
        avg_exchanges=avg_exchanges,
        deep_count=deep_count,
        reflection_count=reflection_count,
    )


@instructor_bp.route("/assignment/<int:assignment_id>/save-brief", methods=["POST"])
def save_brief(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    data = request.get_json(silent=True) or {}
    assignment.instructions = data.get("instructions", "").strip()
    modality = data.get("modality", "").strip()
    if modality:
        assignment.modality = modality
    try:
        max_score = float(data.get("max_score", 100))
        if max_score <= 0:
            max_score = 100
    except (TypeError, ValueError):
        max_score = 100
    assignment.max_score = max_score
    db.session.commit()
    return jsonify({"success": True, "message": "Assignment brief saved"})


@instructor_bp.route("/assignment/<int:assignment_id>/save-ai-config", methods=["POST"])
def save_ai_config(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    data = request.get_json(silent=True) or {}
    intensity = data.get("intensity", "balanced")
    if intensity not in ("supportive", "balanced", "demanding"):
        intensity = "balanced"
    assignment.intensity = intensity
    try:
        assignment.phase_1_end = int(data.get("phase_1_end", 3))
    except (TypeError, ValueError):
        assignment.phase_1_end = 3
    try:
        assignment.phase_2_end = int(data.get("phase_2_end", 6))
    except (TypeError, ValueError):
        assignment.phase_2_end = 6
    assignment.phase_3_end = assignment.phase_2_end + 3
    assignment.supplementary_instructions = data.get("supplementary_instructions", "").strip()
    db.session.commit()
    return jsonify({"success": True, "message": "AI configuration saved"})


@instructor_bp.route("/assignment/<int:assignment_id>/save-reflection-questions", methods=["POST"])
def save_reflection_questions(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    data = request.get_json(silent=True) or {}
    q1 = data.get("reflection_q1", "").strip()
    q2 = data.get("reflection_q2", "").strip()
    q3 = data.get("reflection_q3", "").strip()
    if not q1 or not q2 or not q3:
        return jsonify({"error": "All three questions are required."}), 400
    db.session.expire(assignment)
    assignment = Assignment.query.get(assignment_id)
    assignment.reflection_q1 = q1
    assignment.reflection_q2 = q2
    assignment.reflection_q3 = q3
    db.session.commit()
    return jsonify({"success": True, "message": "Reflection questions saved"})


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

    intensity = data.get("intensity", "balanced")
    if intensity not in ("supportive", "balanced", "demanding"):
        intensity = "balanced"
    assignment.intensity = intensity
    try:
        assignment.phase_1_end = int(data.get("phase_1_end", 3))
    except (TypeError, ValueError):
        assignment.phase_1_end = 3
    try:
        assignment.phase_2_end = int(data.get("phase_2_end", 6))
    except (TypeError, ValueError):
        assignment.phase_2_end = 6
    assignment.phase_3_end = assignment.phase_2_end + 3
    assignment.supplementary_instructions = data.get("supplementary_instructions", "").strip()

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

    grade = Grade.query.filter_by(student_id=student_id, assignment_id=assignment.id).first()

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
        grade=grade,
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

    grade = Grade.query.filter_by(student_id=student_id, assignment_id=assignment.id).first()

    return render_template(
        "instructor/reflection.html",
        course=course,
        assignment=assignment,
        student=student,
        reflection=reflection,
        questions=questions,
        grade=grade,
    )


@instructor_bp.route("/student/<int:student_id>/assessment")
def assessment(student_id):
    student = Student.query.get_or_404(student_id)
    course, assignment = _get_base_for_student(student)

    print(f"[assessment] student_id={student_id} assignment_id={assignment.id}")

    score_rec = AssessmentScore.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()
    summary_rec = SessionSummary.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()

    print(f"[assessment] score_rec found: {score_rec is not None}")
    print(f"[assessment] summary_rec found: {summary_rec is not None}")
    if summary_rec:
        print(f"[assessment] summary_json (first 200): {(summary_rec.summary_json or '')[:200]}")

    # Generate session summary synchronously if missing so the tab renders immediately
    if summary_rec is None:
        print(f"[assessment] no summary found — generating synchronously")
        try:
            generate_session_summary(student_id, assignment.id)
            summary_rec = SessionSummary.query.filter_by(
                student_id=student_id, assignment_id=assignment.id
            ).first()
            print(f"[assessment] generation complete, record found: {summary_rec is not None}")
        except Exception as exc:
            print(f"[assessment] session summary generation error: {exc}")

    session_summary = json.loads(summary_rec.summary_json) if summary_rec else None
    feedback = InstructorFeedback.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()

    return render_template(
        "instructor/assessment.html",
        course=course,
        assignment=assignment,
        student=student,
        score=score_rec,
        session_summary=session_summary,
        generating=(score_rec is None),
        feedback=feedback,
    )


@instructor_bp.route("/student/<int:student_id>/assessment/generate", methods=["POST"])
def assessment_generate(student_id):
    student = Student.query.get_or_404(student_id)
    course, assignment = _get_base_for_student(student)

    existing_score = AssessmentScore.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()
    if existing_score:
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


@instructor_bp.route("/student/<int:student_id>/assessment/regenerate-summary", methods=["POST"])
def regenerate_summary(student_id):
    student = Student.query.get_or_404(student_id)
    _, assignment = _get_base_for_student(student)

    existing = SessionSummary.query.filter_by(
        student_id=student_id, assignment_id=assignment.id
    ).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()

    try:
        generate_session_summary(student_id, assignment.id)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


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


# ---------------------------------------------------------------------------
# Grading endpoints
# ---------------------------------------------------------------------------

@instructor_bp.route("/student/<int:student_id>/grade/save", methods=["POST"])
def grade_save(student_id):
    student = Student.query.get_or_404(student_id)
    _, assignment = _get_base_for_student(student)
    data = request.get_json(silent=True) or {}

    try:
        score = float(data["score"]) if data.get("score") not in (None, "", "null") else None
    except (TypeError, ValueError):
        score = None
    feedback = data.get("feedback", "").strip() or None

    grade = Grade.query.filter_by(student_id=student_id, assignment_id=assignment.id).first()
    now = datetime.utcnow()
    if grade:
        grade.score = score
        grade.feedback = feedback
        grade.max_score = assignment.max_score or 100
        grade.updated_at = now
    else:
        grade = Grade(
            student_id=student_id,
            assignment_id=assignment.id,
            score=score,
            max_score=assignment.max_score or 100,
            feedback=feedback,
            updated_at=now,
        )
        db.session.add(grade)
    db.session.commit()
    return jsonify({"success": True, "saved_at": now.strftime("%b %d at %H:%M")})


@instructor_bp.route("/student/<int:student_id>/grade/publish", methods=["POST"])
def grade_publish(student_id):
    student = Student.query.get_or_404(student_id)
    _, assignment = _get_base_for_student(student)

    grade = Grade.query.filter_by(student_id=student_id, assignment_id=assignment.id).first()
    if not grade:
        return jsonify({"error": "No grade record found. Save a draft first."}), 404

    now = datetime.utcnow()
    grade.is_published = True
    grade.published_at = now
    grade.updated_at = now
    db.session.commit()
    return jsonify({"success": True, "published_at": now.strftime("%b %d at %H:%M")})


@instructor_bp.route("/student/<int:student_id>/grade/unpublish", methods=["POST"])
def grade_unpublish(student_id):
    student = Student.query.get_or_404(student_id)
    _, assignment = _get_base_for_student(student)

    grade = Grade.query.filter_by(student_id=student_id, assignment_id=assignment.id).first()
    if grade:
        grade.is_published = False
        grade.published_at = None
        grade.updated_at = datetime.utcnow()
        db.session.commit()
    return jsonify({"success": True})


@instructor_bp.route("/student/<int:student_id>/assignment/reopen", methods=["POST"])
def assignment_reopen(student_id):
    student = Student.query.get_or_404(student_id)
    _, assignment = _get_base_for_student(student)

    output = Output.query.filter_by(student_id=student_id, assignment_id=assignment.id).first()
    if not output or not output.is_submitted:
        return jsonify({"error": "No submitted assignment found."}), 404

    output.is_reopened = True
    output.reopened_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True})


@instructor_bp.route("/student/<int:student_id>/reflection/reopen", methods=["POST"])
def reflection_reopen(student_id):
    student = Student.query.get_or_404(student_id)
    _, assignment = _get_base_for_student(student)

    reflection = Reflection.query.filter_by(student_id=student_id, assignment_id=assignment.id).first()
    if not reflection or not reflection.is_submitted:
        return jsonify({"error": "No submitted reflection found."}), 404

    reflection.is_reopened = True
    reflection.reopened_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Access codes
# ---------------------------------------------------------------------------

@instructor_bp.route("/access-codes")
def access_codes():
    from models.models import AccessCode
    course, _ = _get_base()
    codes = (
        AccessCode.query
        .filter_by(course_id=course.id)
        .order_by(AccessCode.created_at.desc())
        .all()
    )
    claimed = sum(1 for c in codes if c.is_claimed)
    unclaimed = len(codes) - claimed
    return render_template(
        "instructor/access_codes.html",
        course=course,
        codes=codes,
        claimed=claimed,
        unclaimed=unclaimed,
    )


@instructor_bp.route("/access-codes/generate", methods=["POST"])
def access_codes_generate():
    import random as _random
    from models.models import AccessCode
    course, _ = _get_base()
    data = request.get_json(silent=True) or {}
    try:
        count = max(1, min(50, int(data.get("count", 1))))
    except (TypeError, ValueError):
        count = 1

    existing = {ac.code for ac in AccessCode.query.with_entities(AccessCode.code).all()}
    generated = []
    attempts = 0
    while len(generated) < count and attempts < 1000:
        attempts += 1
        code = f"{_random.randint(0, 999999):06d}"
        if code not in existing:
            existing.add(code)
            generated.append(AccessCode(code=code, course_id=course.id))

    db.session.add_all(generated)
    db.session.commit()
    return jsonify({"success": True, "count": len(generated)})
