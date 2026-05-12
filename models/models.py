from datetime import datetime
from extensions import db


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

    course = db.relationship("Course", back_populates="assignments")
    exchanges = db.relationship("PromptExchange", back_populates="assignment")
    reflections = db.relationship("Reflection", back_populates="assignment")
    outputs = db.relationship("Output", back_populates="assignment")
    assessment_scores = db.relationship("AssessmentScore", back_populates="assignment")

    def __repr__(self):
        return f"<Assignment {self.title}>"


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)

    course = db.relationship("Course", back_populates="students")
    exchanges = db.relationship("PromptExchange", back_populates="student")
    reflections = db.relationship("Reflection", back_populates="student")
    outputs = db.relationship("Output", back_populates="student")
    assessment_scores = db.relationship("AssessmentScore", back_populates="student")

    def __repr__(self):
        return f"<Student {self.name}>"


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

    student = db.relationship("Student", back_populates="outputs")
    assignment = db.relationship("Assignment", back_populates="outputs")

    def __repr__(self):
        return f"<Output {self.modality} student={self.student_id}>"


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
    reflection_score = db.Column(db.Integer, nullable=True)   # average of q1/q2/q3
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
