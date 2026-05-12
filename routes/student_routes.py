from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from extensions import db
from models.models import Assignment, Course, InstructorFeedback, Output, PromptExchange, Reflection, ReflectionConfig, Student
from services.ai_service import detect_concept_usage, get_ai_response, suggest_discussion_points
from config import MODALITY_SECTIONS, DEFAULT_REFLECTION_QUESTIONS

student_bp = Blueprint("student", __name__, url_prefix="/student")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_context():
    """Return the demo student, assignment and course based on session course_id."""
    course_id = session.get("course_id")
    if course_id:
        course = Course.query.get(course_id)
    else:
        course = Course.query.first()
        if course:
            session["course_id"] = course.id

    if not course:
        return None, None, None

    student = Student.query.filter_by(name="Alex M.", course_id=course.id).first()
    assignment = Assignment.query.filter_by(course_id=course.id).first()
    return student, assignment, course


def _build_history(exchanges):
    history = []
    for ex in exchanges:
        history.append({"role": "user", "content": ex.student_message})
        history.append({"role": "assistant", "content": ex.ai_response})
    return history


def _get_sections(assignment):
    """Return the sections list for an assignment, using sections_config if set."""
    if assignment.sections_config:
        return assignment.sections_config
    return MODALITY_SECTIONS.get(assignment.modality or "critical analysis", [])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@student_bp.route("/")
def index():
    return redirect(url_for("student.prompting"))


@student_bp.route("/prompting", methods=["GET", "POST"])
def prompting():
    student, assignment, course = _get_context()

    if student is None or assignment is None:
        return "Seed data not found. Please restart the app to seed the database.", 500

    exchanges = (
        PromptExchange.query
        .filter_by(student_id=student.id, assignment_id=assignment.id)
        .order_by(PromptExchange.exchange_number)
        .all()
    )

    if request.method == "POST":
        try:
            payload = request.get_json(silent=True) or {}
            student_message = payload.get("student_message", "").strip()
            if not student_message:
                return jsonify({"error": "Message cannot be empty."}), 400

            # Force SQLAlchemy to reload all objects from DB — prevents stale cache
            db.session.expire_all()
            # Re-fetch assignment and course fresh from DB on every POST
            fresh_assignment = Assignment.query.get(assignment.id)
            fresh_course = Course.query.get(course.id)

            print("--- CO-INTEL DEBUG ---", flush=True)
            print("ASSIGNMENT TITLE:", fresh_assignment.title, flush=True)
            print("INSTRUCTIONS:", fresh_assignment.instructions, flush=True)
            print("CONCEPTS:", fresh_course.required_concepts, flush=True)
            print("OBJECTIVE:", fresh_course.learning_objective, flush=True)
            print("----------------------", flush=True)

            detection = detect_concept_usage(student_message, fresh_course.required_concepts)
            concepts_applied = detection.get("concepts_applied", [])
            has_pushback = bool(detection.get("has_pushback", False))

            history = _build_history(exchanges)

            ai_text = get_ai_response(
                student_message=student_message,
                conversation_history=history,
                course_concepts=fresh_course.required_concepts,
                learning_objective=fresh_course.learning_objective,
                assignment_title=fresh_assignment.title,
                instructions=fresh_assignment.instructions or "",
            )

            exchange_number = len(exchanges) + 1
            exchange = PromptExchange(
                student_id=student.id,
                assignment_id=assignment.id,
                student_message=student_message,
                ai_response=ai_text,
                concepts_applied=concepts_applied,
                has_pushback=has_pushback,
                exchange_number=exchange_number,
                timestamp=datetime.utcnow(),
            )
            db.session.add(exchange)
            db.session.commit()

            return jsonify({
                "ai_response": ai_text,
                "concepts_applied": concepts_applied,
                "has_pushback": has_pushback,
                "exchange_number": exchange_number,
            })

        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    # GET — aggregate progress stats
    all_concepts_used = set()
    pushback_count = 0
    for ex in exchanges:
        all_concepts_used.update(ex.concepts_applied or [])
        if ex.has_pushback:
            pushback_count += 1

    has_output = Output.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first() is not None

    has_reflection = Reflection.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first() is not None

    feedback = InstructorFeedback.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first()

    return render_template(
        "student/prompting.html",
        student=student,
        assignment=assignment,
        course=course,
        exchanges=exchanges,
        required_concepts=course.required_concepts,
        concepts_used=sorted(all_concepts_used),
        exchange_count=len(exchanges),
        pushback_count=pushback_count,
        min_exchanges=course.min_exchanges,
        has_output=has_output,
        has_reflection=has_reflection,
        feedback=feedback,
    )


@student_bp.route("/assignment", methods=["GET", "POST"])
def assignment():
    student, assignment, course = _get_context()

    exchange_count = PromptExchange.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).count()

    existing_output = Output.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first()

    sections = _get_sections(assignment)

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        raw_sections = data.get("sections", {})

        # Validate at least one section has content
        if not any(v.strip() for v in raw_sections.values()):
            return jsonify({"error": "Please write at least one section before saving."}), 400

        modality = assignment.modality or ""
        joined_content = "\n\n".join(
            f"{s['title']}\n{raw_sections.get(s['id'], '')}"
            for s in sections
            if raw_sections.get(s["id"], "").strip()
        )

        if existing_output:
            existing_output.modality = modality
            existing_output.content = joined_content
            existing_output.content_sections = raw_sections
            existing_output.submitted_at = datetime.utcnow()
            # Invalidate cached analysis when content changes
            existing_output.analysis_json = None
            existing_output.analysis_generated_at = None
        else:
            existing_output = Output(
                student_id=student.id,
                assignment_id=assignment.id,
                modality=modality,
                content=joined_content,
                content_sections=raw_sections,
                submitted_at=datetime.utcnow(),
            )
            db.session.add(existing_output)

        db.session.commit()
        return jsonify({"success": True})

    return render_template(
        "student/assignment.html",
        student=student,
        assignment=assignment,
        course=course,
        existing_output=existing_output,
        sections=sections,
        exchange_count=exchange_count,
        min_exchanges=course.min_exchanges,
        unlocked=exchange_count >= course.min_exchanges,
    )


@student_bp.route("/assignment/suggestions")
def assignment_suggestions():
    student, assignment, course = _get_context()
    if student is None:
        return jsonify({"suggestions": []})

    exchanges = (
        PromptExchange.query
        .filter_by(student_id=student.id, assignment_id=assignment.id)
        .order_by(PromptExchange.exchange_number)
        .all()
    )

    if len(exchanges) < 2:
        return jsonify({"suggestions": []})

    exchanges_data = [
        {
            "exchange_number": ex.exchange_number,
            "student_message": ex.student_message,
            "concepts_applied": ex.concepts_applied or [],
            "has_pushback": ex.has_pushback,
        }
        for ex in exchanges
    ]

    try:
        result = suggest_discussion_points(exchanges_data, course.required_concepts)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc), "suggestions": []}), 502


@student_bp.route("/reflection", methods=["GET", "POST"])
def reflection():
    student, assignment, course = _get_context()

    existing = Reflection.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first()

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        q1 = data.get("question_1", "").strip()
        q2 = data.get("question_2", "").strip()
        q3 = data.get("question_3", "").strip()

        if not q1 or not q2 or not q3:
            return jsonify({"error": "All three questions must be answered."}), 400

        if existing:
            existing.question_1 = q1
            existing.question_2 = q2
            existing.question_3 = q3
            existing.submitted_at = datetime.utcnow()
        else:
            existing = Reflection(
                student_id=student.id,
                assignment_id=assignment.id,
                question_1=q1,
                question_2=q2,
                question_3=q3,
                submitted_at=datetime.utcnow(),
            )
            db.session.add(existing)

        db.session.commit()
        return jsonify({"success": True})

    cfg = ReflectionConfig.query.filter_by(assignment_id=assignment.id).first()
    if cfg:
        questions = {
            "question_1": cfg.question_1,
            "question_2": cfg.question_2,
            "question_3": cfg.question_3,
            "hint_1": cfg.hint_1 or "",
            "hint_2": cfg.hint_2 or "",
            "hint_3": cfg.hint_3 or "",
        }
    else:
        questions = {k: (v or "") for k, v in DEFAULT_REFLECTION_QUESTIONS.items()}

    return render_template(
        "student/reflection.html",
        student=student,
        assignment=assignment,
        course=course,
        existing=existing,
        questions=questions,
    )
