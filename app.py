import logging
import os
import random
import re
from datetime import datetime, timedelta
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from dotenv import load_dotenv
from extensions import db, login_manager
from flask_login import login_user, logout_user, current_user
from flask_talisman import Talisman

load_dotenv()

INSTRUCTOR_CODE = "TEACH-2026"
DEV_CODE = "DEV-0000"

_IS_PRODUCTION = os.getenv("FLASK_ENV", "development") == "production"


def _check_env() -> None:
    """Raise on missing SECRET_KEY; warn on missing ANTHROPIC_API_KEY."""
    secret = os.getenv("SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "SECRET_KEY is not set. Add it to .env before starting the app."
        )
    weak = {"dev-secret", "change-this-secret-key", "secret", ""}
    if secret in weak:
        raise RuntimeError(
            "SECRET_KEY looks like a placeholder. "
            "Generate a real key with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    if not os.getenv("ANTHROPIC_API_KEY", ""):
        logging.warning(
            "ANTHROPIC_API_KEY is not set — AI features will not work."
        )


def create_app():
    _check_env()

    app = Flask(__name__)

    # ---- Security: secret key (never falls back to a hardcoded value) ----
    app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///co_intel.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ---- Security: session cookie hardening ----
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = _IS_PRODUCTION

    db.init_app(app)
    login_manager.init_app(app)

    # ---- Security: HTTP headers via Talisman ----
    Talisman(
        app,
        force_https=_IS_PRODUCTION,
        content_security_policy=False,   # disabled — app uses inline styles/scripts
        x_frame_options="DENY",
    )

    from models.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from routes.student_routes import student_bp
    from routes.instructor_routes import instructor_bp

    app.register_blueprint(student_bp)
    app.register_blueprint(instructor_bp)

    # ------------------------------------------------------------------
    # App-level routes
    # ------------------------------------------------------------------

    @app.route("/")
    def index():
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET"])
    def login():
        if current_user.is_authenticated:
            if current_user.role in ("instructor", "dev"):
                return redirect(url_for("instructor.dashboard"))
            return redirect(url_for("student.prompting"))
        return render_template("login.html")

    @app.route("/login/check", methods=["POST"])
    def login_check():
        from models.models import AccessCode
        from services.audit import log_login_success, log_login_failed

        data = request.get_json(silent=True) or {}
        code = data.get("code", "").strip().upper()

        if not code:
            return jsonify({"status": "invalid", "message": "Please enter your access code."})

        # Instructor special code
        if code == INSTRUCTOR_CODE:
            user = User.query.filter_by(role="instructor").first()
            if user:
                login_user(user)
                log_login_success(user.id, user.role)
                return jsonify({"status": "redirect", "url": url_for("instructor.dashboard")})

        # Dev special code
        if code == DEV_CODE:
            user = User.query.filter_by(role="dev").first()
            if user:
                login_user(user)
                log_login_success(user.id, user.role)
                return jsonify({"status": "redirect", "url": url_for("instructor.dashboard")})

        # Student access codes
        ac = AccessCode.query.filter_by(code=code).first()
        if ac is None:
            log_login_failed(code)
            return jsonify({"status": "invalid",
                            "message": "Invalid access code. Please check your code and try again."})
        if ac.is_claimed:
            return jsonify({"status": "returning", "code": code})

        return jsonify({"status": "unclaimed", "code": code})

    @app.route("/login/register", methods=["POST"])
    def login_register():
        from models.models import AccessCode, Student
        from services.audit import log_login_success

        data = request.get_json(silent=True) or {}
        code = data.get("code", "").strip().upper()
        first_name = data.get("first_name", "").strip()
        last_initial = data.get("last_initial", "").strip().upper()

        if not first_name:
            return jsonify({"status": "error", "message": "First name is required."})
        if len(last_initial) != 1 or not last_initial.isalpha():
            return jsonify({"status": "error", "message": "Last initial must be a single letter."})

        ac = AccessCode.query.filter_by(code=code, is_claimed=False).first()
        if ac is None:
            return jsonify({"status": "error",
                            "message": "This code is no longer valid. Please try again."})

        display_name = f"{first_name} {last_initial}."

        user = User(role="student", display_name=display_name, is_dev=False)
        db.session.add(user)
        db.session.flush()

        email_slug = re.sub(r"[^a-z0-9]", "", display_name.lower())
        email = f"{email_slug}.{user.id}@cointel.edu"
        student = Student(
            name=display_name,
            email=email,
            course_id=ac.course_id,
            user_id=user.id,
        )
        db.session.add(student)

        ac.student_id = user.id
        ac.is_claimed = True
        db.session.commit()

        login_user(user)
        log_login_success(user.id, user.role)
        return jsonify({
            "status": "success",
            "display_name": display_name,
            "redirect": url_for("student.prompting"),
        })

    @app.route("/login/signin", methods=["POST"])
    def login_signin():
        from models.models import AccessCode
        from services.audit import log_login_success, log_login_failed

        data = request.get_json(silent=True) or {}
        code = data.get("code", "").strip().upper()
        first_name = data.get("first_name", "").strip()
        last_initial = data.get("last_initial", "").strip().upper()

        if not first_name:
            return jsonify({"status": "error", "message": "First name is required."})
        if len(last_initial) != 1 or not last_initial.isalpha():
            return jsonify({"status": "error", "message": "Last initial must be a single letter."})

        ac = AccessCode.query.filter_by(code=code, is_claimed=True).first()
        if ac is None:
            log_login_failed(code)
            return jsonify({"status": "error", "message": "Code not found. Please try again."})

        user = User.query.get(ac.student_id)
        if user is None:
            return jsonify({"status": "error", "message": "Account not found. Contact your instructor."})

        expected = f"{first_name} {last_initial}.".lower()
        if user.display_name.lower() != expected:
            log_login_failed(code)
            return jsonify({"status": "error",
                            "message": "The name you entered does not match the name registered to this code. Contact your instructor if you need help."})

        login_user(user)
        log_login_success(user.id, user.role)
        return jsonify({
            "status": "success",
            "display_name": user.display_name,
            "redirect": url_for("student.prompting"),
        })

    @app.route("/logout")
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/dev/reset", methods=["POST"])
    def dev_reset():
        from services.audit import log_dev_reset
        if not current_user.is_authenticated or not current_user.is_dev:
            return jsonify({"error": "Unauthorized"}), 403
        from models.models import Student
        from sqlalchemy import text
        demo_students = Student.query.filter_by(user_id=None).all()
        demo_ids = [s.id for s in demo_students]
        if demo_ids:
            id_list = ",".join(str(i) for i in demo_ids)
            with db.engine.connect() as conn:
                conn.execute(text(f"DELETE FROM prompt_exchanges WHERE student_id IN ({id_list})"))
                conn.execute(text(f"DELETE FROM reflections WHERE student_id IN ({id_list})"))
                conn.execute(text(f"DELETE FROM outputs WHERE student_id IN ({id_list})"))
                conn.execute(text(f"DELETE FROM session_summaries WHERE student_id IN ({id_list})"))
                conn.execute(text(f"DELETE FROM assessment_scores WHERE student_id IN ({id_list})"))
                conn.commit()
        log_dev_reset(current_user.id)
        return jsonify({"success": True})

    @app.route("/course/switch/<int:course_id>")
    def switch_course(course_id):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        session["course_id"] = course_id
        referer = request.referrer or ""
        if re.search(r"/instructor/student/\d+", referer):
            return redirect(url_for("instructor.dashboard"))
        if "/student" in referer:
            return redirect(url_for("student.prompting"))
        return redirect(url_for("instructor.dashboard"))

    @app.context_processor
    def inject_global_context():
        from models.models import Course
        try:
            all_courses = Course.query.order_by(Course.id).all()
            current_course = None
            if all_courses:
                valid_ids = {c.id for c in all_courses}
                if session.get("course_id") not in valid_ids:
                    session["course_id"] = all_courses[0].id
                current_course = next(
                    (c for c in all_courses if c.id == session.get("course_id")),
                    all_courses[0],
                )
            return {
                "all_courses": all_courses,
                "current_course_id": session.get("course_id"),
                "course_color":       (current_course.color       if current_course else "#E8602A"),
                "course_color_light": (current_course.color_light if current_course else "#FDF0EA"),
                "course_color_text":  (current_course.color_text  if current_course else "#C04E1E"),
                "course_color_hover": (current_course.color_hover if current_course else "#d4521f"),
            }
        except Exception:
            return {
                "all_courses": [], "current_course_id": None,
                "course_color": "#E8602A", "course_color_light": "#FDF0EA",
                "course_color_text": "#C04E1E", "course_color_hover": "#d4521f",
            }

    with app.app_context():
        db.create_all()
        _migrate()
        _seed()

    return app


def _migrate():
    """Add new columns to existing tables without deleting data."""
    from sqlalchemy import text

    new_cols = [
        ("assignments", "concepts_required", "BOOLEAN NOT NULL DEFAULT 0"),
        ("assignments", "required_concepts",  "TEXT NOT NULL DEFAULT '[]'"),
        ("assignments", "archetype",           "VARCHAR(50) NOT NULL DEFAULT 'challenger'"),
        ("assignments", "contribution_level",  "VARCHAR(50) NOT NULL DEFAULT 'thinking_partner'"),
        ("assignments", "phase_1_end",         "INTEGER NOT NULL DEFAULT 3"),
        ("assignments", "phase_2_end",         "INTEGER NOT NULL DEFAULT 6"),
        ("assignments", "sidebar_mode",        "VARCHAR(50) NOT NULL DEFAULT 'prescriptive'"),
        ("assignments", "behavioral_emphasis", "VARCHAR(50) NOT NULL DEFAULT 'balanced'"),
        ("assignments", "supplementary_instructions", "TEXT NOT NULL DEFAULT ''"),
        ("students",    "user_id",             "INTEGER REFERENCES users(id)"),
    ]
    with db.engine.connect() as conn:
        for table, col, col_def in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                conn.commit()
            except Exception:
                pass

        try:
            conn.execute(text(
                "UPDATE assignments SET instructions = '' "
                "WHERE title = 'Deep Dive with AI' AND (instructions IS NOT NULL AND instructions != '')"
            ))
            conn.commit()
        except Exception:
            pass

        backfills = [
            ("assignments", "archetype",           "'challenger'"),
            ("assignments", "contribution_level",  "'thinking_partner'"),
            ("assignments", "phase_1_end",         "3"),
            ("assignments", "phase_2_end",         "6"),
            ("assignments", "sidebar_mode",        "'prescriptive'"),
            ("assignments", "behavioral_emphasis", "'balanced'"),
        ]
        for table, col, default in backfills:
            try:
                conn.execute(text(f"UPDATE {table} SET {col} = {default} WHERE {col} IS NULL OR {col} = ''"))
                conn.commit()
            except Exception:
                pass

        try:
            conn.execute(text(
                "DELETE FROM session_summaries "
                "WHERE summary_json LIKE '%\"emerging\"%' OR summary_json LIKE '%\"integrated\"%'"
            ))
            conn.commit()
        except Exception:
            pass


def _seed():
    from models.models import (
        Course, Assignment, Student, User, AccessCode,
        Reflection, Output, ReflectionConfig,
    )
    from config import DEFAULT_REFLECTION_QUESTIONS

    if User.query.count() == 0:
        instructor = User(role="instructor", display_name="Gamze Y.", is_dev=False)
        dev = User(role="dev", display_name="Dev Account", is_dev=True)
        db.session.add_all([instructor, dev])
        db.session.commit()

    if Course.query.count() > 0:
        _seed_access_codes()
        return

    now = datetime.utcnow()

    nms = Course(
        name="New Media Society",
        color="#E8602A", color_light="#FDF0EA",
        color_text="#C04E1E", color_hover="#d4521f",
        learning_objective=(
            "Students will analyze contemporary media events by applying "
            "agenda-setting theory and framing theory, identifying how media "
            "organizations shape public perception through selective emphasis, "
            "framing choices, and confirmation bias in coverage."
        ),
        required_concepts=["framing theory", "confirmation bias", "agenda-setting theory", "selective framing"],
        output_modalities=["critical analysis", "podcast script", "interactive game design", "presentation outline", "video script"],
        min_exchanges=5,
    )
    db.session.add(nms)
    db.session.flush()

    nms_assignment = Assignment(
        course_id=nms.id,
        title="Deep Dive with AI",
        description=(
            "Select a recent media event and engage in a structured AI dialogue "
            "to unpack how it was framed across different outlets. Push back on at "
            "least one AI response, and produce a final output in your chosen modality."
        ),
        due_date=now + timedelta(days=14),
        modality="critical analysis", instructions="",
        concepts_required=False, required_concepts=[],
        archetype="challenger", contribution_level="thinking_partner",
        phase_1_end=3, phase_2_end=6, behavioral_emphasis="balanced",
        supplementary_instructions="",
    )
    db.session.add(nms_assignment)
    db.session.flush()

    for name, email in [("Alex M.", "alex.m@cointel.edu"), ("Jamie L.", "jamie.l@cointel.edu"), ("Riley K.", "riley.k@cointel.edu")]:
        db.session.add(Student(name=name, email=email, course_id=nms.id))

    ic = Course(
        name="Intercultural Communication",
        color="#0D9488", color_light="#E6F4F3",
        color_text="#0A7A6E", color_hover="#0b8078",
        learning_objective=(
            "Students develop an intercultural training game using AI as a co-design partner, "
            "applying course concepts to direct and evaluate AI output throughout the design process."
        ),
        required_concepts=["cultural identity", "intercultural competence", "high context and low context communication", "stereotypes and bias", "positionality", "ethnocentrism"],
        output_modalities=["interactive game design", "critical analysis", "podcast script", "presentation outline", "video script"],
        min_exchanges=5,
    )
    db.session.add(ic)
    db.session.flush()

    ic_assignment = Assignment(
        course_id=ic.id,
        title="Human-AI Game Design",
        description=(
            "Design an educational game that teaches players about intercultural communication. "
            "Use AI as a co-design partner, applying course concepts to direct and evaluate AI output."
        ),
        due_date=now + timedelta(days=21),
        modality="interactive game design",
        instructions=(
            "Work with AI to design an educational game that teaches players about intercultural "
            "communication. You must apply course concepts to direct and evaluate AI output throughout "
            "the design process. Your game should celebrate cultural diversity and help players "
            "distinguish between personal and social identity. Document your creative decisions and "
            "be prepared to present your game design to the class."
        ),
        concepts_required=False, required_concepts=[],
        archetype="design_thinker", contribution_level="thinking_partner",
        phase_1_end=3, phase_2_end=6, behavioral_emphasis="balanced",
        supplementary_instructions="",
    )
    db.session.add(ic_assignment)
    db.session.flush()

    for name, email in [("Alex M.", "alex.m.ic@cointel.edu"), ("Jamie L.", "jamie.l.ic@cointel.edu"), ("Riley K.", "riley.k.ic@cointel.edu")]:
        db.session.add(Student(name=name, email=email, course_id=ic.id))

    for assignment_id in [nms_assignment.id, ic_assignment.id]:
        db.session.add(ReflectionConfig(
            assignment_id=assignment_id,
            question_1=DEFAULT_REFLECTION_QUESTIONS["question_1"],
            question_2=DEFAULT_REFLECTION_QUESTIONS["question_2"],
            question_3=DEFAULT_REFLECTION_QUESTIONS["question_3"],
            hint_1=DEFAULT_REFLECTION_QUESTIONS["hint_1"],
            hint_2=DEFAULT_REFLECTION_QUESTIONS["hint_2"],
            hint_3=DEFAULT_REFLECTION_QUESTIONS["hint_3"],
        ))

    db.session.commit()
    _seed_access_codes()


def _seed_access_codes():
    from models.models import AccessCode, Course
    if AccessCode.query.count() > 0:
        return
    existing_codes = set()
    courses = Course.query.all()
    for course in courses:
        for _ in range(10):
            while True:
                code = f"{random.randint(0, 999999):06d}"
                if code not in existing_codes:
                    existing_codes.add(code)
                    break
            db.session.add(AccessCode(code=code, course_id=course.id))
    db.session.commit()


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
