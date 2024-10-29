from flask import Flask, render_template, request, session, redirect
from flask_session import Session
import spacy
from rapidfuzz import fuzz
import PyPDF2
import docx
import secrets
import logging

app = Flask(__name__)

app.config['SESSION_TYPE'] = 'filesystem'
app.config['SECRET_KEY'] = secrets.token_hex(16)
Session(app)
nlp = spacy.load("en_core_web_md")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt'}


def is_allowed_file(filename: str) -> bool:
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_file(file) -> str:
    """Extract text content from PDF, Word, or text files."""
    if file.filename.lower().endswith('.pdf'):
        try:
            pdf_reader = PyPDF2.PdfReader(file)
            text = "".join(page.extract_text() for page in pdf_reader.pages)
            return text
        except Exception as e:
            logger.error(f"Error reading PDF file {file.filename}: {e}")
            return ""
    elif file.filename.lower().endswith(('.docx', '.doc')):
        try:
            doc_content = docx.Document(file)
            text = "\n".join([para.text for para in doc_content.paragraphs])
            return text
        except Exception as e:
            logger.error(f"Error reading Word file {file.filename}: {e}")
            return ""
    else:
        try:
            return file.read().decode("utf-8")
        except UnicodeDecodeError:
            logger.error(f"Error decoding file {file.filename}")
            return ""


def extract_candidate_name(text: str) -> str:
    """Extract the candidate's name from the resume text."""
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            return ent.text
    return "Unknown"


def extract_skills_and_experience(text: str, skill_keywords: list) -> tuple:
    """Extract skills and relevant experience sentences from the resume text."""
    doc = nlp(text)
    skills = {token.text for token in doc if token.text.lower()
              in skill_keywords}
    experience = [sent.text for sent in doc.sents if "years" in sent.text.lower(
    ) or "experience" in sent.text.lower()]
    return list(skills), experience


def calculate_skill_match(job_description: str, candidate_skills: list) -> dict:
    """Calculate a match score for each candidate skill against the job description."""
    return {skill: fuzz.partial_ratio(skill.lower(), job_description.lower()) for skill in candidate_skills}


def rank_candidates(job_description: str, resumes: list, skill_keywords: list) -> list:
    """Rank candidates based on the relevance of their skills to the job description."""
    rankings = []

    for idx, resume in enumerate(resumes):
        name = extract_candidate_name(resume["content"])
        skills, experience = extract_skills_and_experience(
            resume["content"], skill_keywords)
        match_scores = calculate_skill_match(job_description, skills)
        total_score = sum(match_scores.values()) / \
            len(match_scores) if match_scores else 0

        rankings.append({
            "id": idx,
            "name": name,
            "score": round(total_score, 2),
            "skills": skills,
            "experience": experience
        })

    rankings.sort(key=lambda x: x["score"], reverse=True)
    return rankings


@app.route("/", methods=["GET", "POST"])
def index():
    """Handle the main index route for rendering the form and processing candidate screening."""
    session.setdefault('candidates', [])
    session.setdefault('job_description', '')
    session.setdefault('skills', '')

    if request.method == "POST":
        job_description = request.form["job_description"]
        session['job_description'] = job_description
        skills_input = request.form["skills"]
        session['skills'] = skills_input

        skill_keywords = [skill.strip().lower()
                          for skill in skills_input.split(',') if skill.strip()]
        resumes = request.files.getlist("resumes")
        resume_data = [
            {"name": file.filename, "content": extract_text_from_file(file)}
            for file in resumes if is_allowed_file(file.filename)
        ]

        new_candidates = rank_candidates(
            job_description, resume_data, skill_keywords)
        session['candidates'].extend(new_candidates)
        session.modified = True

        for candidate in session['candidates']:
            candidate_skills = candidate['skills']
            match_scores = calculate_skill_match(
                job_description, candidate_skills)
            total_score = sum(match_scores.values()) / \
                len(match_scores) if match_scores else 0
            candidate['score'] = round(total_score, 2)

        session['candidates'].sort(key=lambda x: x['score'], reverse=True)

    return render_template("index.html", candidates=session.get('candidates', []),
                           job_description=session.get('job_description', ''),
                           skills=session.get('skills', ''))


@app.route("/clear", methods=["POST"])
def clear_candidates():
    """Clear the session data for candidates, job description, and skills."""
    session.pop('candidates', None)
    session.pop('job_description', None)
    session.pop('skills', None)
    return redirect('/')


if __name__ == "__main__":
    app.run(debug=True)
