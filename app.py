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
        _seed()

    return app


def _seed():
    from models.models import (
        Course, Assignment, Student,
        Reflection, Output, ReflectionConfig,
    )
    from config import DEFAULT_REFLECTION_QUESTIONS

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
            "to unpack how it was framed across different outlets. Apply at least "
            "three required course concepts in your exchanges, push back on at "
            "least one AI response, and produce a final output in your chosen modality."
        ),
        due_date=now + timedelta(days=14),
        modality="critical analysis",
        instructions=(
            "Select any topic related to AI, social media, media and globalization, online dating, "
            "or videogaming. Engage in a structured dialogue with AI to explore how your chosen topic "
            "shapes culture, society, or public perception. Push back on at least one AI response and "
            "produce a final output in your chosen modality."
        ),
    )
    db.session.add(nms_assignment)
    db.session.flush()

    nms_alex = Student(name="Alex M.", email="alex.m@cointel.edu", course_id=nms.id)
    nms_jamie = Student(name="Jamie L.", email="jamie.l@cointel.edu", course_id=nms.id)
    nms_riley = Student(name="Riley K.", email="riley.k@cointel.edu", course_id=nms.id)
    db.session.add_all([nms_alex, nms_jamie, nms_riley])
    db.session.flush()

    nms_reflection = Reflection(
        student_id=nms_alex.id,
        assignment_id=nms_assignment.id,
        question_1=(
            "I was surprised by how much agenda-setting and confirmation bias overlap. "
            "I went in thinking they were separate phenomena but the AI helped me see "
            "they form a feedback loop. That reframing changed how I want to structure "
            "my analysis document."
        ),
        question_2=(
            "I pushed back in exchange 2 and the AI validated my point while adding "
            "nuance about co-presence of mechanisms. It didn't just agree—it gave me "
            "Stroud's research as a way to hold both ideas simultaneously. That felt "
            "like genuine intellectual engagement rather than the AI just confirming me."
        ),
        question_3=(
            "I want to compare three outlets instead of two, and add a section on "
            "audience analytics as evidence of the confirmation bias loop. The selective "
            "framing example with the October jobs report is concrete enough to anchor "
            "the whole document."
        ),
        submitted_at=now - timedelta(minutes=20),
    )
    db.session.add(nms_reflection)

    nms_sections = {
        "intro": (
            "This analysis examines how Fox News and MSNBC covered the 2024 US presidential "
            "election cycle, applying agenda-setting theory and framing theory to understand "
            "how each network constructed a different public reality from the same underlying events."
        ),
        "comparative": (
            "Fox News ranked economic anxiety, immigration, and crime at the top of its salience "
            "hierarchy throughout the cycle. MSNBC foregrounded threats to democratic institutions, "
            "reproductive rights, and climate policy. Neither network invented its agenda—each amplified "
            "concerns already present in its audience—but editorial gatekeeping about story placement, "
            "airtime, and guest selection sharpened those hierarchies over time. The October jobs report "
            "illustrates the divergence most concretely: Fox led with grocery prices and skeptical economists, "
            "treating 254,000 jobs added as a footnote; MSNBC led with the same number as vindication of "
            "economic policy. Entman's four framing functions operated differently on identical source data."
        ),
        "argument": (
            "My central argument is that agenda-setting and confirmation bias form a self-reinforcing "
            "feedback loop that makes divergent coverage commercially rational, not simply ideologically "
            "motivated. This insight came from my own pushback in exchange 2: I initially thought "
            "confirmation bias was purely an audience phenomenon, separate from network agenda-setting. "
            "The AI's response helped me see they are co-constitutive. Networks learn through ratings "
            "which frames generate engagement, intensify those frames, and attract audiences already primed "
            "to respond. Audiences self-select toward confirming environments, generating the metrics that "
            "reward networks for intensification. Neither side causes the other—the loop is the structure."
        ),
        "conclusion": (
            "Agenda-setting theory explains macro-level issue prioritization; framing theory explains "
            "micro-level narrative construction; confirmation bias explains why divergence is economically "
            "sustainable rather than self-correcting. Understanding all three is necessary for media "
            "literacy in a fragmented information environment where audiences can, and do, construct "
            "entirely separate informational realities from the same news cycle."
        ),
    }
    nms_output = Output(
        student_id=nms_alex.id,
        assignment_id=nms_assignment.id,
        modality="critical analysis",
        content="\n\n".join(nms_sections.values()),
        content_sections=nms_sections,
        submitted_at=now - timedelta(minutes=10),
    )
    db.session.add(nms_output)

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
