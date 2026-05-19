import json
from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user
from extensions import db
from models.models import Assignment, Course, Grade, InstructorFeedback, Output, PromptExchange, Reflection, ReflectionConfig, SessionSummary, Student
from services.ai_service import detect_concept_usage, get_ai_response, suggest_discussion_points
from services.archetype_service import build_system_prompt, generate_session_summary
from config import MODALITY_SECTIONS, DEFAULT_REFLECTION_QUESTIONS

student_bp = Blueprint("student", __name__, url_prefix="/student")


@student_bp.before_request
def require_student_access():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    if current_user.role not in ("student", "instructor", "dev"):
        return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_context():
    """Return (student, assignment, course) for the current user."""
    from flask_login import current_user

    # Real student logged in via access code
    if current_user.is_authenticated and current_user.role == "student":
        student = Student.query.filter_by(user_id=current_user.id).first()
        if student:
            course = Course.query.get(student.course_id)
            assignment = Assignment.query.filter_by(course_id=course.id).first()
            session["course_id"] = course.id
            return student, assignment, course

    # Demo / instructor / dev fallback
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

            # do not cache this query — must be rebuilt fresh on every request
            db.session.expire_all()
            fresh_assignment = Assignment.query.get(assignment.id)
            fresh_course = Course.query.get(course.id)

            detection = detect_concept_usage(student_message, fresh_course.required_concepts)
            concepts_applied = detection.get("concepts_applied", [])
            has_pushback = bool(detection.get("has_pushback", False))

            history = _build_history(exchanges)
            exchange_count_before = len(exchanges)
            system_prompt = build_system_prompt(fresh_assignment, fresh_course, exchange_count_before)

            ai_text = get_ai_response(
                student_message=student_message,
                conversation_history=history,
                system_prompt=system_prompt,
                student_name=student.name if student else None,
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

            # Compute per-phase stats. Guarded in a separate try so a stat
            # failure never blocks the exchange — the commit already succeeded.
            sid = student.id
            aid = assignment.id
            p1  = fresh_assignment.phase_1_end or 3
            p2  = fresh_assignment.phase_2_end or 6

            current_phase                  = 'inquire'
            exchanges_in_current_phase     = 0
            pushback_count_in_phase        = 0
            student_word_count             = len(student_message.split())
            max_student_words_in_phase     = 0
            substantive_responses_in_phase = 0

            try:
                if exchange_number <= p1:
                    current_phase = 'inquire'
                    phase_exchanges = PromptExchange.query.filter(
                        PromptExchange.student_id == sid,
                        PromptExchange.assignment_id == aid,
                        PromptExchange.exchange_number <= p1,
                    ).all()
                elif exchange_number <= p2:
                    current_phase = 'collaborate'
                    phase_exchanges = PromptExchange.query.filter(
                        PromptExchange.student_id == sid,
                        PromptExchange.assignment_id == aid,
                        PromptExchange.exchange_number > p1,
                        PromptExchange.exchange_number <= p2,
                    ).all()
                else:
                    current_phase = 'evaluate'
                    phase_exchanges = PromptExchange.query.filter(
                        PromptExchange.student_id == sid,
                        PromptExchange.assignment_id == aid,
                        PromptExchange.exchange_number > p2,
                    ).all()

                phase_msgs = [
                    ex.student_message for ex in phase_exchanges
                    if ex.student_message
                ]
                exchanges_in_current_phase     = len(phase_exchanges)
                pushback_count_in_phase        = sum(
                    1 for ex in phase_exchanges if ex.has_pushback
                )
                word_counts                    = [len(m.split()) for m in phase_msgs]
                max_student_words_in_phase     = max(word_counts) if word_counts else 0
                substantive_responses_in_phase = sum(
                    1 for w in word_counts if w > 30
                )
            except Exception:
                pass  # stat failure is non-fatal; zeroed defaults returned above

            return jsonify({
                "ai_response": ai_text,
                "concepts_applied": concepts_applied,
                "has_pushback": has_pushback,
                "exchange_number": exchange_number,
                "current_phase": current_phase,
                "exchanges_in_current_phase": exchanges_in_current_phase,
                "pushback_count_in_phase": pushback_count_in_phase,
                "student_word_count": student_word_count,
                "max_student_words_in_phase": max_student_words_in_phase,
                "substantive_responses_in_phase": substantive_responses_in_phase,
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

    exchange_count = len(exchanges)
    phase_1_end = getattr(assignment, "phase_1_end", 3) or 3
    phase_2_end = getattr(assignment, "phase_2_end", 6) or 6
    phase_3_end = getattr(assignment, "phase_3_end", 9) or 9
    if exchange_count < phase_1_end:
        current_phase = 1
    elif exchange_count < phase_2_end:
        current_phase = 2
    else:
        current_phase = 3

    inquire_min     = phase_1_end
    collaborate_min = max(phase_2_end - phase_1_end, 1)
    evaluate_min    = max(phase_3_end - phase_2_end, 1)

    return render_template(
        "student/prompting.html",
        student=student,
        assignment=assignment,
        course=course,
        exchanges=exchanges,
        required_concepts=course.required_concepts,
        concepts_used=sorted(all_concepts_used),
        exchange_count=exchange_count,
        pushback_count=pushback_count,
        min_exchanges=course.min_exchanges,
        has_output=has_output,
        has_reflection=has_reflection,
        feedback=feedback,
        current_phase=current_phase,
        phase_1_end=phase_1_end,
        phase_2_end=phase_2_end,
        inquire_min=inquire_min,
        collaborate_min=collaborate_min,
        evaluate_min=evaluate_min,
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

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        content = data.get("content", "").strip()

        if not content:
            return jsonify({"error": "Please write something before saving."}), 400

        if existing_output and existing_output.is_submitted and not existing_output.is_reopened:
            return jsonify({"error": "Cannot edit a submitted assignment."}), 403

        modality = assignment.modality or ""

        if existing_output:
            existing_output.modality = modality
            existing_output.content = content
            existing_output.content_sections = None
            existing_output.analysis_json = None
            existing_output.analysis_generated_at = None
        else:
            existing_output = Output(
                student_id=student.id,
                assignment_id=assignment.id,
                modality=modality,
                content=content,
            )
            db.session.add(existing_output)

        db.session.commit()
        return jsonify({"success": True})

    grade = Grade.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first()

    return render_template(
        "student/assignment.html",
        student=student,
        assignment=assignment,
        course=course,
        existing_output=existing_output,
        exchange_count=exchange_count,
        min_exchanges=course.min_exchanges,
        unlocked=exchange_count >= course.min_exchanges,
        grade=grade,
    )


@student_bp.route("/session-summary")
def session_summary():
    student, assignment, course = _get_context()
    if student is None:
        return jsonify({"error": "Student not found."}), 404

    # Always regenerate fresh from all current exchanges so students see
    # an up-to-date summary if they continue the conversation after reviewing.
    try:
        result = generate_session_summary(student.id, assignment.id)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


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

        if existing and existing.is_submitted and not existing.is_reopened:
            return jsonify({"error": "Cannot edit a submitted reflection."}), 403

        if existing:
            existing.question_1 = q1
            existing.question_2 = q2
            existing.question_3 = q3
        else:
            existing = Reflection(
                student_id=student.id,
                assignment_id=assignment.id,
                question_1=q1,
                question_2=q2,
                question_3=q3,
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

    grade = Grade.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first()

    return render_template(
        "student/reflection.html",
        student=student,
        assignment=assignment,
        course=course,
        existing=existing,
        questions=questions,
        grade=grade,
    )


@student_bp.route("/assignment/submit", methods=["POST"])
def assignment_submit():
    student, assignment, course = _get_context()
    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()

    output = Output.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first()

    if not content and (not output or not output.content):
        return jsonify({"error": "Please write something before submitting."}), 400

    now = datetime.utcnow()
    if output:
        if content:
            output.content = content
            output.analysis_json = None
            output.analysis_generated_at = None
        output.is_submitted = True
        output.submitted_at = now
        output.is_reopened = False
    else:
        output = Output(
            student_id=student.id,
            assignment_id=assignment.id,
            modality=assignment.modality or "",
            content=content,
            submitted_at=now,
            is_submitted=True,
        )
        db.session.add(output)

    db.session.commit()
    return jsonify({"success": True, "submitted_at": now.strftime("%b %d at %H:%M")})


@student_bp.route("/assignment/resubmit", methods=["POST"])
def assignment_resubmit():
    student, assignment, course = _get_context()
    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()

    output = Output.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first()

    if not output:
        return jsonify({"error": "No assignment found."}), 404

    now = datetime.utcnow()
    if content:
        output.content = content
        output.analysis_json = None
        output.analysis_generated_at = None
    output.is_submitted = True
    output.is_reopened = False
    output.resubmitted_at = now
    output.submitted_at = now
    db.session.commit()
    return jsonify({"success": True, "submitted_at": now.strftime("%b %d at %H:%M")})


@student_bp.route("/reflection/submit", methods=["POST"])
def reflection_submit():
    student, assignment, course = _get_context()
    data = request.get_json(silent=True) or {}
    q1 = data.get("question_1", "").strip()
    q2 = data.get("question_2", "").strip()
    q3 = data.get("question_3", "").strip()

    if not q1 or not q2 or not q3:
        return jsonify({"error": "All three questions must be answered before submitting."}), 400

    existing = Reflection.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first()

    now = datetime.utcnow()
    if existing:
        existing.question_1 = q1
        existing.question_2 = q2
        existing.question_3 = q3
        existing.is_submitted = True
        existing.submitted_at = now
        existing.is_reopened = False
    else:
        existing = Reflection(
            student_id=student.id,
            assignment_id=assignment.id,
            question_1=q1,
            question_2=q2,
            question_3=q3,
            submitted_at=now,
            is_submitted=True,
        )
        db.session.add(existing)

    db.session.commit()
    return jsonify({"success": True, "submitted_at": now.strftime("%b %d at %H:%M")})


@student_bp.route("/reflection/resubmit", methods=["POST"])
def reflection_resubmit():
    student, assignment, course = _get_context()
    data = request.get_json(silent=True) or {}
    q1 = data.get("question_1", "").strip()
    q2 = data.get("question_2", "").strip()
    q3 = data.get("question_3", "").strip()

    existing = Reflection.query.filter_by(
        student_id=student.id, assignment_id=assignment.id
    ).first()

    if not existing:
        return jsonify({"error": "No reflection found."}), 404

    now = datetime.utcnow()
    if q1:
        existing.question_1 = q1
    if q2:
        existing.question_2 = q2
    if q3:
        existing.question_3 = q3
    existing.is_submitted = True
    existing.is_reopened = False
    existing.resubmitted_at = now
    existing.submitted_at = now
    db.session.commit()
    return jsonify({"success": True, "submitted_at": now.strftime("%b %d at %H:%M")})
