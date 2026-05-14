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
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per day", "50 per hour"])

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
    csrf.init_app(app)
    limiter.init_app(app)

    # ---- Security: HTTP headers via Talisman ----
    Talisman(
        app,
        force_https=_IS_PRODUCTION,
        content_security_policy=False,
        frame_options="DENY",
    )

    @app.errorhandler(429)
    def ratelimit_handler(e):
        return render_template("429.html"), 429

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
    @limiter.limit("30 per minute")
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
    @csrf.exempt
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
                conn.execute(text(f"DELETE FROM grades WHERE student_id IN ({id_list})"))
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
        _seed_demo_submissions()

    return app


def _migrate():
    """Add new columns to existing tables without deleting data."""
    from sqlalchemy import text

    new_cols = [
        ("assignments", "concepts_required",        "BOOLEAN NOT NULL DEFAULT 0"),
        ("assignments", "required_concepts",         "TEXT NOT NULL DEFAULT '[]'"),
        ("assignments", "phase_1_end",               "INTEGER NOT NULL DEFAULT 3"),
        ("assignments", "phase_2_end",               "INTEGER NOT NULL DEFAULT 6"),
        ("assignments", "supplementary_instructions","TEXT NOT NULL DEFAULT ''"),
        ("assignments", "max_score",                 "FLOAT NOT NULL DEFAULT 100"),
        # Legacy columns kept in DB for safety — not used by new model
        ("assignments", "archetype",                 "VARCHAR(50) NOT NULL DEFAULT 'challenger'"),
        ("assignments", "contribution_level",        "VARCHAR(50) NOT NULL DEFAULT 'thinking_partner'"),
        ("assignments", "sidebar_mode",              "VARCHAR(50) NOT NULL DEFAULT 'prescriptive'"),
        ("assignments", "behavioral_emphasis",       "VARCHAR(50) NOT NULL DEFAULT 'balanced'"),
        # New phase-system columns
        ("assignments", "intensity",                 "VARCHAR(50) NOT NULL DEFAULT 'balanced'"),
        ("assignments", "phase_3_end",               "INTEGER NOT NULL DEFAULT 9"),
        ("students",    "user_id",                   "INTEGER REFERENCES users(id)"),
        ("outputs",     "is_submitted",              "BOOLEAN NOT NULL DEFAULT 0"),
        ("outputs",     "is_reopened",               "BOOLEAN NOT NULL DEFAULT 0"),
        ("outputs",     "reopened_at",               "DATETIME"),
        ("outputs",     "resubmitted_at",            "DATETIME"),
        ("reflections", "is_submitted",              "BOOLEAN NOT NULL DEFAULT 0"),
        ("reflections", "is_reopened",               "BOOLEAN NOT NULL DEFAULT 0"),
        ("reflections", "reopened_at",               "DATETIME"),
        ("reflections", "resubmitted_at",            "DATETIME"),
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

        # Backfill intensity from behavioral_emphasis for existing rows
        try:
            conn.execute(text(
                "UPDATE assignments SET intensity = behavioral_emphasis "
                "WHERE (intensity IS NULL OR intensity = '') AND behavioral_emphasis IS NOT NULL AND behavioral_emphasis != ''"
            ))
            conn.commit()
        except Exception:
            pass

        # Ensure intensity is always a valid value
        try:
            conn.execute(text(
                "UPDATE assignments SET intensity = 'balanced' "
                "WHERE intensity NOT IN ('supportive', 'balanced', 'demanding')"
            ))
            conn.commit()
        except Exception:
            pass

        # Backfill phase_3_end from phase_2_end + 3 for existing rows
        try:
            conn.execute(text(
                "UPDATE assignments SET phase_3_end = phase_2_end + 3 "
                "WHERE phase_3_end IS NULL OR phase_3_end = 0"
            ))
            conn.commit()
        except Exception:
            pass

        # Ensure phase_1_end and phase_2_end have valid values
        backfills = [
            ("assignments", "phase_1_end", "3"),
            ("assignments", "phase_2_end", "6"),
        ]
        for table, col, default in backfills:
            try:
                conn.execute(text(f"UPDATE {table} SET {col} = {default} WHERE {col} IS NULL OR {col} = 0"))
                conn.commit()
            except Exception:
                pass

        # Set canonical intensity values per assignment title (Step 10)
        try:
            conn.execute(text(
                "UPDATE assignments SET intensity = 'balanced', phase_1_end = 3, phase_2_end = 6, phase_3_end = 9 "
                "WHERE title = 'Deep Dive with AI'"
            ))
            conn.execute(text(
                "UPDATE assignments SET intensity = 'supportive', phase_1_end = 3, phase_2_end = 6, phase_3_end = 9 "
                "WHERE title = 'Human-AI Game Design'"
            ))
            conn.commit()
        except Exception:
            pass

        # Delete all existing session summaries so they regenerate with new universal criteria
        try:
            conn.execute(text("DELETE FROM session_summaries"))
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
        intensity="balanced",
        phase_1_end=3, phase_2_end=6, phase_3_end=9,
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
        intensity="supportive",
        phase_1_end=3, phase_2_end=6, phase_3_end=9,
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


def _seed_demo_submissions():
    """Ensure Alex M. (NMS demo student) has realistic submitted data on first launch."""
    from models.models import Course, Student, Assignment, Output, Reflection, Grade, PromptExchange

    nms = Course.query.filter_by(name="New Media Society").first()
    if not nms:
        return
    alex = Student.query.filter_by(name="Alex M.", course_id=nms.id).first()
    assignment = Assignment.query.filter_by(course_id=nms.id).first()
    if not alex or not assignment:
        return

    now = datetime.utcnow()

    # Demo exchanges — AI companions topic analyzed through media framing lens
    demo_exchanges = [
        # Inquire phase (exchanges 1–3)
        (1,
         "I want to analyze how media covers AI companion apps like Replika. My argument is that most coverage "
         "uses a fear-based framing that sensationalizes addiction risks while ignoring genuine use cases like "
         "mental health support for isolated people. I think agenda-setting theory explains why addiction "
         "narratives dominate.",
         "That's a specific claim. What evidence do you have that addiction framing actually dominates — and what "
         "draws you to Replika specifically rather than other AI companion tools?",
         False),
        (2,
         "Looking at Guardian and Wired coverage from 2023, addiction language appears in most articles I "
         "reviewed — terms like 'parasocial obsession' and 'unhealthy attachment' even in pieces that start "
         "sympathetically. Framing theory explains this as a schema journalists apply before they report. "
         "Agenda-setting then determines which frame becomes the dominant public reference point.",
         "I want to push back on the framing theory claim. Journalists applying a pre-existing schema is one "
         "explanation. But the fear frame also generates more engagement — which is an audience behavior "
         "explanation, not a journalistic one. Why does framing theory explain this better than a simple "
         "incentive argument?",
         True),
        (3,
         "Both factors operate together. Confirmation bias in audiences reinforces journalists' incentive to "
         "use fear frames, which then shapes what audiences expect — it's a feedback loop. Agenda-setting "
         "tracks what becomes salient and fear frames position AI companions as a policy crisis rather than "
         "a social technology. That shift in what the story is about is exactly what agenda-setting predicts.",
         "Fair — the multi-causal explanation is more defensible. One thing worth considering: is the fear "
         "framing specific to AI companions or is it a broader pattern in how media covers emerging social "
         "technologies? If it's general, your argument becomes a case study rather than a unique phenomenon. "
         "Does that change your argument or strengthen it?",
         False),
        # Collaborate phase (exchanges 4–6)
        (4,
         "I think it strengthens it. I can show this reproduces a pattern visible with social media, video "
         "games, and celebrity parasocial fandom — the through-line is moral panic theory combined with "
         "agenda-setting. How would you structure an argument that connects all of these?",
         "One structure: open with the pattern across technologies, then zoom into AI companions as the "
         "sharpest current instance. Your core claim becomes that moral panic framing in tech coverage "
         "follows an agenda-setting dynamic that prioritizes risk salience over social nuance. Use Replika "
         "coverage as evidence throughout. Does that architecture match what you want to say?",
         False),
        (5,
         "I want the AI-specific angle as the main focus, not just a case study. My claim is that AI companion "
         "coverage is distinct because the relationship with the technology itself is what gets framed as "
         "pathological — unlike video games where the harm is about time or violence. The intimacy dimension "
         "makes it a different category of moral panic.",
         "That is a stronger and more original claim. You could anchor it in framing theory by showing "
         "journalists consistently apply interpersonal vocabulary — attachment, dependency, longing — and "
         "then pathologize that vocabulary. The implicit frame is: intimacy with a machine is inherently "
         "disordered. Two directions from here: do you want to challenge that frame or just analyze it?",
         False),
        (6,
         "I want to challenge it. My argument is that the pathology frame reveals a cultural assumption that "
         "legitimate intimacy can only occur between humans. That assumption goes unquestioned in the coverage. "
         "Confirmation bias operates at the level of ideology, not just editorial preference. The agenda-setting "
         "effect here is not just about what issues get coverage — it is about which relationships are legible "
         "as valid.",
         "That is genuinely original — you are moving from agenda-setting to a critique of what I would call "
         "legitimacy framing. Ambitious for the scope but defensible. Make sure you can back the cultural "
         "assumption claim with specific textual evidence from articles, not just assertion. Do you have "
         "two or three concrete examples that show this assumption operating in the coverage?",
         False),
        # Evaluate phase (exchange 7)
        (7,
         "Yes — I found three pieces from 2023 where journalists describe Replika users as confusing AI for "
         "real relationships or filling a void that human connection should fill. That language assumes a "
         "clear hierarchy where AI intimacy is substitution, not a valid form on its own terms. I think I "
         "have enough to write a strong analysis.",
         "The strongest part is the legitimacy framing thesis — original and supported by your textual "
         "evidence. The weakest element is the connection to agenda-setting theory: you are using it loosely "
         "to mean what gets covered and how, but the classic theory is more specifically about salience, not "
         "frame content. Either tighten that theoretical application or center your argument on framing theory "
         "alone, which fits your actual analysis better. What would you revise?",
         False),
    ]

    if not PromptExchange.query.filter_by(student_id=alex.id, assignment_id=assignment.id).first():
        for ex_num, student_msg, ai_msg, has_pb in demo_exchanges:
            concepts = ["framing theory", "agenda-setting theory"] if ex_num <= 3 else \
                       ["framing theory"] if ex_num <= 6 else ["framing theory", "confirmation bias"]
            db.session.add(PromptExchange(
                student_id=alex.id,
                assignment_id=assignment.id,
                student_message=student_msg,
                ai_response=ai_msg,
                concepts_applied=concepts,
                has_pushback=has_pb,
                exchange_number=ex_num,
                timestamp=now - timedelta(days=3, hours=2 - ex_num * 0.3),
            ))
        db.session.commit()

    if not Output.query.filter_by(student_id=alex.id, assignment_id=assignment.id).first():
        db.session.add(Output(
            student_id=alex.id,
            assignment_id=assignment.id,
            modality=assignment.modality or "critical analysis",
            content=(
                "The coverage of the Senate climate bill in July 2024 offers a compelling case study "
                "in agenda-setting and selective framing. Mainstream outlets foregrounded economic cost "
                "projections while downplaying long-term environmental data — a pattern consistent with "
                "what agenda-setting theory predicts when coverage follows industry-funded briefings.\n\n"
                "What struck me most in my AI dialogue was how quickly the challenger pushed back on my "
                "initial claim that 'all media is biased.' That pressure forced me to distinguish between "
                "structural bias (built into editorial incentives) and intentional bias (deliberate "
                "distortion). Framing theory helped me see that even neutral-seeming word choices — "
                "'cost' vs 'investment' — carry ideological weight.\n\n"
                "The confirmation bias angle was the most productive thread. Audiences who already "
                "distrust government spending will read 'trillion-dollar bill' as confirmation of waste, "
                "while environmentally-engaged readers see 'historic climate investment.' The same text, "
                "two incompatible readings. This is not simply audience interpretation — it is the "
                "predictable result of framing choices made before publication."
            ),
            submitted_at=now - timedelta(days=2),
            is_submitted=True,
        ))

    if not Reflection.query.filter_by(student_id=alex.id, assignment_id=assignment.id).first():
        db.session.add(Reflection(
            student_id=alex.id,
            assignment_id=assignment.id,
            question_1=(
                "The most surprising moment was when the AI challenged my claim that media bias is "
                "intentional. I had not considered that structural incentives — advertising, audience "
                "retention, editorial inertia — could produce biased framing without anyone intending it. "
                "That distinction changed how I think about accountability in journalism."
            ),
            question_2=(
                "I pushed back on the AI's steelman of the 'marketplace of ideas' argument. The AI "
                "presented it well, but I felt it underweighted the structural advantages that well-funded "
                "voices have in that marketplace. My pushback led to a more nuanced version of the argument "
                "that I used directly in my analysis."
            ),
            question_3=(
                "Next time I would front-load the framing theory angle earlier. I spent three exchanges "
                "on general bias arguments before connecting to the specific course concepts. Starting with "
                "the theoretical frame would have made the AI dialogue more productive from the start."
            ),
            submitted_at=now - timedelta(days=1),
            is_submitted=True,
        ))

    if not Grade.query.filter_by(student_id=alex.id, assignment_id=assignment.id).first():
        db.session.add(Grade(
            student_id=alex.id,
            assignment_id=assignment.id,
            score=87,
            max_score=assignment.max_score or 100,
            feedback=(
                "Strong analytical work overall. Your distinction between structural and intentional bias "
                "was the clearest original contribution — that came through in the pushback exchange and "
                "carried well into the final piece. The framing theory application is precise and grounded "
                "in specific textual evidence rather than broad claims.\n\n"
                "The confirmation bias section is your strongest paragraph. Consider developing the "
                "agenda-setting angle further in revision — you named it but the analysis stays at a "
                "surface level compared to the framing work. One more layer of evidence there would "
                "bring the two theoretical threads into better balance."
            ),
            is_published=True,
            published_at=now - timedelta(hours=6),
            created_at=now - timedelta(hours=8),
            updated_at=now - timedelta(hours=6),
        ))

    db.session.commit()


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
