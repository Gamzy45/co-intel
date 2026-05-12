import os
import re
from datetime import datetime, timedelta
from flask import Flask, redirect, request, session, url_for
from dotenv import load_dotenv
from extensions import db

load_dotenv()


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///co_intel.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from routes.student_routes import student_bp
    from routes.instructor_routes import instructor_bp

    app.register_blueprint(student_bp)
    app.register_blueprint(instructor_bp)

    @app.route("/")
    def index():
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        from flask import render_template
        if request.method == "POST":
            email = request.form.get("email", "").lower()
            if "instructor" in email or "professor" in email:
                return redirect(url_for("instructor.dashboard"))
            return redirect(url_for("student.prompting"))
        return render_template("login.html")

    @app.route("/course/switch/<int:course_id>")
    def switch_course(course_id):
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
    ]
    with db.engine.connect() as conn:
        for table, col, col_def in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                conn.commit()
            except Exception:
                pass  # Column already exists

        # Clear instructions for Deep Dive with AI (NMS assignment only)
        try:
            conn.execute(text(
                "UPDATE assignments SET instructions = '' "
                "WHERE title = 'Deep Dive with AI' AND (instructions IS NOT NULL AND instructions != '')"
            ))
            conn.commit()
        except Exception:
            pass

        # Backfill NULL values in archetype columns so existing rows are never NULL
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


def _seed():
    from models.models import (
        Course, Assignment, Student,
        Reflection, Output, ReflectionConfig,
    )
    from config import DEFAULT_REFLECTION_QUESTIONS

    from models.models import SessionSummary

    if Course.query.count() > 0:
        return

    now = datetime.utcnow()

    # ------------------------------------------------------------------ Course 1: New Media Society
    nms = Course(
        name="New Media Society",
        color="#E8602A",
        color_light="#FDF0EA",
        color_text="#C04E1E",
        color_hover="#d4521f",
        learning_objective=(
            "Students will analyze contemporary media events by applying "
            "agenda-setting theory and framing theory, identifying how media "
            "organizations shape public perception through selective emphasis, "
            "framing choices, and confirmation bias in coverage."
        ),
        required_concepts=[
            "framing theory",
            "confirmation bias",
            "agenda-setting theory",
            "selective framing",
        ],
        output_modalities=[
            "critical analysis",
            "podcast script",
            "interactive game design",
            "presentation outline",
            "video script",
        ],
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
        modality="critical analysis",
        instructions="",
        concepts_required=False,
        required_concepts=[],
        archetype="challenger",
        contribution_level="thinking_partner",
        phase_1_end=3,
        phase_2_end=6,
        behavioral_emphasis="balanced",
        supplementary_instructions="",
    )
    db.session.add(nms_assignment)
    db.session.flush()

    nms_alex = Student(name="Alex M.", email="alex.m@cointel.edu", course_id=nms.id)
    nms_jamie = Student(name="Jamie L.", email="jamie.l@cointel.edu", course_id=nms.id)
    nms_riley = Student(name="Riley K.", email="riley.k@cointel.edu", course_id=nms.id)
    db.session.add_all([nms_alex, nms_jamie, nms_riley])
    db.session.flush()

    # No pre-seeded exchanges, reflections, or outputs — students start completely fresh

    # ------------------------------------------------------------------ Course 2: Intercultural Communication
    ic = Course(
        name="Intercultural Communication",
        color="#0D9488",
        color_light="#E6F4F3",
        color_text="#0A7A6E",
        color_hover="#0b8078",
        learning_objective=(
            "Students develop an intercultural training game using AI as a co-design partner, "
            "applying course concepts to direct and evaluate AI output throughout the design process."
        ),
        required_concepts=[
            "cultural identity",
            "intercultural competence",
            "high context and low context communication",
            "stereotypes and bias",
            "positionality",
            "ethnocentrism",
        ],
        output_modalities=[
            "interactive game design",
            "critical analysis",
            "podcast script",
            "presentation outline",
            "video script",
        ],
        min_exchanges=5,
    )
    db.session.add(ic)
    db.session.flush()

    ic_assignment = Assignment(
        course_id=ic.id,
        title="Human-AI Game Design",
        description=(
            "Design an educational game that teaches players about intercultural communication. "
            "Use AI as a co-design partner, applying course concepts to direct and evaluate AI output. "
            "Your game should celebrate cultural diversity and help players distinguish between "
            "personal and social identity."
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
        concepts_required=False,
        required_concepts=[],
        archetype="design_thinker",
        contribution_level="thinking_partner",
        phase_1_end=3,
        phase_2_end=6,
        behavioral_emphasis="balanced",
        supplementary_instructions="",
    )
    db.session.add(ic_assignment)
    db.session.flush()

    ic_alex = Student(name="Alex M.", email="alex.m.ic@cointel.edu", course_id=ic.id)
    ic_jamie = Student(name="Jamie L.", email="jamie.l.ic@cointel.edu", course_id=ic.id)
    ic_riley = Student(name="Riley K.", email="riley.k.ic@cointel.edu", course_id=ic.id)
    db.session.add_all([ic_alex, ic_jamie, ic_riley])
    db.session.flush()

    # ReflectionConfig for both assignments
    nms_rq = ReflectionConfig(
        assignment_id=nms_assignment.id,
        question_1=DEFAULT_REFLECTION_QUESTIONS["question_1"],
        question_2=DEFAULT_REFLECTION_QUESTIONS["question_2"],
        question_3=DEFAULT_REFLECTION_QUESTIONS["question_3"],
        hint_1=DEFAULT_REFLECTION_QUESTIONS["hint_1"],
        hint_2=DEFAULT_REFLECTION_QUESTIONS["hint_2"],
        hint_3=DEFAULT_REFLECTION_QUESTIONS["hint_3"],
    )
    ic_rq = ReflectionConfig(
        assignment_id=ic_assignment.id,
        question_1=DEFAULT_REFLECTION_QUESTIONS["question_1"],
        question_2=DEFAULT_REFLECTION_QUESTIONS["question_2"],
        question_3=DEFAULT_REFLECTION_QUESTIONS["question_3"],
        hint_1=DEFAULT_REFLECTION_QUESTIONS["hint_1"],
        hint_2=DEFAULT_REFLECTION_QUESTIONS["hint_2"],
        hint_3=DEFAULT_REFLECTION_QUESTIONS["hint_3"],
    )
    db.session.add_all([nms_rq, ic_rq])

    db.session.commit()


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
