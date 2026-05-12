# Co-Intelligence

A Flask web application that scaffolds dialogic AI engagement in university courses. Students converse with Claude through structured prompting phases; instructors monitor engagement depth, view submissions, and generate AI-powered assessments.

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd co-intel
```

### 2. Create and activate a virtual environment

```bash
python3.11 -m venv venv
source venv/bin/activate      # macOS / Linux
# venv\Scripts\activate       # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add your API key

Open `.env` and replace the placeholder with your real Anthropic API key:

```
ANTHROPIC_API_KEY=your_key_here
```

Get a key at https://console.anthropic.com

### 5. Run the app

```bash
python app.py
```

The app will be available at **http://localhost:5000**

On first run the database is created and seeded automatically with:
- Two courses: New Media Society and Intercultural Communication
- Three students per course: Alex M., Jamie L., Riley K.
- Alex M. (New Media Society) has 3 existing exchanges, a submitted reflection, and a submitted assignment

---

## Usage

| URL | Description |
|---|---|
| `/student/prompting` | Student chat interface — send prompts, see concept tags |
| `/student/assignment` | Write final assignment in modality-based sections |
| `/student/reflection` | Answer three metacognitive questions |
| `/instructor/dashboard` | Overview of all students with engagement scores |
| `/instructor/student/<id>/log` | Full prompting log for a student |
| `/instructor/student/<id>/assignment` | View submitted assignment with authorship analysis |
| `/instructor/student/<id>/reflection` | View submitted reflection |
| `/instructor/student/<id>/assessment` | AI-generated assessment with scores and feedback |
| `/course/switch/<id>` | Switch active course |

---

## Project structure

```
co-intel/
├── app.py                        # App factory and database seed
├── config.py                     # Modality section definitions
├── extensions.py                 # Shared SQLAlchemy instance
├── requirements.txt
├── .env                          # API key (never commit this)
├── models/
│   └── models.py                 # Course, Assignment, Student, PromptExchange,
│                                 # Reflection, Output, AssessmentScore
├── routes/
│   ├── student_routes.py         # /student/* endpoints
│   └── instructor_routes.py      # /instructor/* endpoints
├── services/
│   └── ai_service.py             # get_ai_response, detect_concept_usage,
│                                 # score_engagement, suggest_discussion_points,
│                                 # analyze_assignment_authorship (Anthropic SDK)
├── static/
│   ├── style.css                 # Full design system
│   └── app.js                   # Shared JS utilities
└── templates/
    ├── base.html                 # Shared layout (topbar, sidebar block, content block)
    ├── _course_nav.html          # Course switcher partial
    ├── student/
    │   ├── prompting.html
    │   ├── assignment.html
    │   └── reflection.html
    └── instructor/
        ├── _student_sidebar.html # Shared student-level sidebar partial
        ├── dashboard.html
        ├── log.html
        ├── assignment.html
        ├── reflection.html
        └── assessment.html
```

## Reset the database

Delete the SQLite file and restart the app to re-seed:

```bash
rm instance/co_intel.db
python app.py
```
