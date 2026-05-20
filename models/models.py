from datetime import datetime
from flask_login import UserMixin
from extensions import db


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False, default="student")  # instructor | student | dev
    display_name = db.Column(db.String(100), nullable=False)
    is_dev = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self):
        return f"<User {self.display_name} ({self.role})>"


class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    learning_objective = db.Column(db.Text, nullable=False)
    required_concepts = db.Column(db.JSON, nullable=False, default=list)
    output_modalities = db.Column(db.JSON, nullable=False, default=list)
    min_exchanges = db.Column(db.Integer, nullable=False, default=5)
    color = db.Column(db.String(20), nullable=False, default="#E8602A")
    color_light = db.Column(db.String(20), nullable=False, default="#FDF0EA")
    color_text = db.Column(db.String(20), nullable=False, default="#C04E1E")
    color_hover = db.Column(db.String(20), nullable=False, default="#d4521f")

    assignments = db.relationship("Assignment", back_populates="course")
    students = db.relationship("Student", back_populates="course")

    def __repr__(self):
        return f"<Course {self.name}>"


class Assignment(db.Model):
    __tablename__ = "assignments"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    due_date = db.Column(db.DateTime, nullable=True)
    modality = db.Column(db.String(100), nullable=True)
    instructions = db.Column(db.Text, nullable=True)
    sections_config = db.Column(db.JSON, nullable=True)

    # Phase progression system fields
    concepts_required = db.Column(db.Boolean, nullable=False, default=False)
    required_concepts = db.Column(db.JSON, nullable=False, default=list)
    intensity = db.Column(db.String(50), nullable=False, default="balanced")
    phase_1_end = db.Column(db.Integer, nullable=False, default=3)
    phase_2_end = db.Column(db.Integer, nullable=False, default=6)
    phase_3_end = db.Column(db.Integer, nullable=False, default=9)
    supplementary_instructions = db.Column(db.Text, nullable=False, default="")
    max_score = db.Column(db.Float, nullable=False, default=100)

    reflection_q1 = db.Column(db.Text, nullable=False, default="Looking back at your conversation, what is the most important idea you developed that you want to carry into your assignment?")
    reflection_q2 = db.Column(db.Text, nullable=False, default="Where did your own knowledge or course concepts most change the direction of the conversation?")
    reflection_q3 = db.Column(db.Text, nullable=False, default="What is your plan for the assignment — what will you argue, design, or create? And which specific moment in your conversation most directly shaped that plan?")

    course = db.relationship("Course", back_populates="assignments")
    exchanges = db.relationship("PromptExchange", back_populates="assignment")
    reflections = db.relationship("Reflection", back_populates="assignment")
    outputs = db.relationship("Output", back_populates="assignment")
    assessment_scores = db.relationship("AssessmentScore", back_populates="assignment")
    session_summaries = db.relationship("SessionSummary", back_populates="assignment")

    def __repr__(self):
        return f"<Assignment {self.title}>"


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    course = db.relationship("Course", back_populates="students")
    exchanges = db.relationship("PromptExchange", back_populates="student")
    reflections = db.relationship("Reflection", back_populates="student")
    outputs = db.relationship("Output", back_populates="student")
    assessment_scores = db.relationship("AssessmentScore", back_populates="student")

    def __repr__(self):
        return f"<Student {self.name}>"


class AccessCode(db.Model):
    __tablename__ = "access_codes"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    is_claimed = db.Column(db.Boolean, nullable=False, default=False)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    claimed_user = db.relationship("User", foreign_keys=[student_id])
    course = db.relationship("Course")

    def __repr__(self):
        return f"<AccessCode {self.code} claimed={self.is_claimed}>"


class PromptExchange(db.Model):
    __tablename__ = "prompt_exchanges"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False)
    student_message = db.Column(db.Text, nullable=False)
    ai_response = db.Column(db.Text, nullable=False)
    concepts_applied = db.Column(db.JSON, nullable=False, default=list)
    has_pushback = db.Column(db.Boolean, nullable=False, default=False)
    exchange_number = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("Student", back_populates="exchanges")
    assignment = db.relationship("Assignment", back_populates="exchanges")

    def __repr__(self):
        return f"<PromptExchange #{self.exchange_number} student={self.student_id}>"


class Reflection(db.Model):
    __tablename__ = "reflections"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False)
    question_1 = db.Column(db.Text, nullable=False)
    question_2 = db.Column(db.Text, nullable=False)
    question_3 = db.Column(db.Text, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_submitted = db.Column(db.Boolean, nullable=False, default=False)
    is_reopened = db.Column(db.Boolean, nullable=False, default=False)
    reopened_at = db.Column(db.DateTime, nullable=True)
    resubmitted_at = db.Column(db.DateTime, nullable=True)

    student = db.relationship("Student", back_populates="reflections")
    assignment = db.relationship("Assignment", back_populates="reflections")

    def __repr__(self):
        return f"<Reflection student={self.student_id} assignment={self.assignment_id}>"


class Output(db.Model):
    __tablename__ = "outputs"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False)
    modality = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    content_sections = db.Column(db.JSON, nullable=True)
    analysis_json = db.Column(db.JSON, nullable=True)
    analysis_generated_at = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_submitted = db.Column(db.Boolean, nullable=False, default=False)
    is_reopened = db.Column(db.Boolean, nullable=False, default=False)
    reopened_at = db.Column(db.DateTime, nullable=True)
    resubmitted_at = db.Column(db.DateTime, nullable=True)

    student = db.relationship("Student", back_populates="outputs")
    assignment = db.relationship("Assignment", back_populates="outputs")

    def __repr__(self):
        return f"<Output {self.modality} student={self.student_id}>"


class SessionSummary(db.Model):
    __tablename__ = "session_summaries"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False)
    summary_json = db.Column(db.Text, nullable=True)
    reflection_summary_json = db.Column(db.Text, nullable=True)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("Student")
    assignment = db.relationship("Assignment", back_populates="session_summaries")

    def __repr__(self):
        return f"<SessionSummary student={self.student_id} assignment={self.assignment_id}>"


class InstructorFeedback(db.Model):
    __tablename__ = "instructor_feedback"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False)
    feedback_text = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("Student")
    assignment = db.relationship("Assignment")

    def __repr__(self):
        return f"<InstructorFeedback student={self.student_id}>"


class ReflectionConfig(db.Model):
    __tablename__ = "reflection_configs"

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False, unique=True)
    question_1 = db.Column(db.Text, nullable=False)
    question_2 = db.Column(db.Text, nullable=False)
    question_3 = db.Column(db.Text, nullable=False)
    hint_1 = db.Column(db.Text, nullable=True)
    hint_2 = db.Column(db.Text, nullable=True)
    hint_3 = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    assignment = db.relationship("Assignment")

    def __repr__(self):
        return f"<ReflectionConfig assignment={self.assignment_id}>"


class AssessmentScore(db.Model):
    __tablename__ = "assessment_scores"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False)

    concept_score = db.Column(db.Integer, nullable=True)
    depth_score = db.Column(db.Integer, nullable=True)
    pushback_score = db.Column(db.Integer, nullable=True)
    reflection_score = db.Column(db.Integer, nullable=True)
    reflection_q1_score = db.Column(db.Integer, nullable=True)
    reflection_q2_score = db.Column(db.Integer, nullable=True)
    reflection_q3_score = db.Column(db.Integer, nullable=True)
    overall_score = db.Column(db.Integer, nullable=True)

    concept_feedback = db.Column(db.Text, nullable=True)
    depth_feedback = db.Column(db.Text, nullable=True)
    pushback_feedback = db.Column(db.Text, nullable=True)
    reflection_feedback = db.Column(db.Text, nullable=True)
    reflection_q1_feedback = db.Column(db.Text, nullable=True)
    reflection_q2_feedback = db.Column(db.Text, nullable=True)
    reflection_q3_feedback = db.Column(db.Text, nullable=True)
    overall_feedback = db.Column(db.Text, nullable=True)

    generated_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("Student", back_populates="assessment_scores")
    assignment = db.relationship("Assignment", back_populates="assessment_scores")

    def __repr__(self):
        return f"<AssessmentScore student={self.student_id} overall={self.overall_score}>"


class Grade(db.Model):
    __tablename__ = "grades"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False)
    score = db.Column(db.Float, nullable=True)
    max_score = db.Column(db.Float, nullable=False, default=100)
    feedback = db.Column(db.Text, nullable=True)
    is_published = db.Column(db.Boolean, nullable=False, default=False)
    published_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("Student")
    assignment = db.relationship("Assignment")

    def __repr__(self):
        return f"<Grade student={self.student_id} score={self.score}/{self.max_score}>"
