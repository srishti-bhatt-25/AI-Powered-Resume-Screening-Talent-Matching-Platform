import os
import re
import io
import uuid
import json
import sqlite3
import hashlib
import logging
import sqlite3
from datetime import timedelta
from typing import List, Dict, Set, Any
from flask import Flask, render_template, request, jsonify, redirect, url_for, session

import docx
from pypdf import PdfReader
import bcrypt
import chromadb

from compiler_engine import run_resume_compiler, TargetCodeGenerator
from database_builder import RobustEmbeddingFunction

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "antigravity_secret_key_quantum_mock"
app.permanent_session_lifetime = timedelta(days=30)

DB_FILE = os.path.join(os.path.dirname(__file__), "interview_bank.db")
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db_store")


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():

    conn = get_db()

    cursor = conn.cursor()

    # USERS

    cursor.execute("""

    CREATE TABLE IF NOT EXISTS users (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        username TEXT UNIQUE NOT NULL,

        password_hash TEXT NOT NULL,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

    );

    """)

    # ADD ROLE COLUMN

    try:

        cursor.execute("""

        ALTER TABLE users
        ADD COLUMN role TEXT DEFAULT 'candidate'

        """)

    except:
        pass

    # ADD LINKEDIN COLUMN

    try:

        cursor.execute("""

        ALTER TABLE users
        ADD COLUMN linkedin TEXT

        """)

    except:
        pass

    # RESUMES

    cursor.execute("""

    CREATE TABLE IF NOT EXISTS resumes (

        user_id INTEGER PRIMARY KEY,

        raw_text TEXT NOT NULL,

        parsed_skills TEXT NOT NULL,

        optimized_ir TEXT NOT NULL,

        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE

    );

    """)

    # SESSIONS

    cursor.execute("""

    CREATE TABLE IF NOT EXISTS sessions (

        id TEXT PRIMARY KEY,

        user_id INTEGER NOT NULL,

        role TEXT NOT NULL,

        company TEXT NOT NULL,

        score REAL,

        verdict TEXT,

        feedback TEXT,

        completed INTEGER DEFAULT 0,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE

    );

    """)

    # ASKED QUESTIONS

    cursor.execute("""

    CREATE TABLE IF NOT EXISTS asked_questions (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER NOT NULL,

        question_hash TEXT NOT NULL,

        question_text TEXT NOT NULL,

        asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,

        UNIQUE(user_id, question_hash)

    );

    """)

    # SESSION QUESTIONS

    cursor.execute("""

    CREATE TABLE IF NOT EXISTS session_questions (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        session_id TEXT NOT NULL,

        question_text TEXT NOT NULL,

        user_answer TEXT,

        score INTEGER,

        verdict TEXT,

        feedback_text TEXT,

        follow_up_question TEXT,

        follow_up_answer TEXT,

        follow_up_score INTEGER,

        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE

    );

    """)

    # INTERNSHIPS

    cursor.execute("""

    CREATE TABLE IF NOT EXISTS internships (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        hr_id INTEGER,

        company TEXT NOT NULL,

        role TEXT NOT NULL,

        skills TEXT NOT NULL,

        description TEXT,

        FOREIGN KEY(hr_id) REFERENCES users(id)

    );

    """)

    # APPLICATIONS

    cursor.execute("""

    CREATE TABLE IF NOT EXISTS applications (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER,

        internship_id INTEGER,

        status TEXT DEFAULT 'Pending',

        FOREIGN KEY(user_id) REFERENCES users(id),

        FOREIGN KEY(internship_id) REFERENCES internships(id)

    );

    """)

    conn.commit()

    conn.close()

@app.route("/hr", methods=["GET", "POST"])
def hr_dashboard():

    if "user_id" not in session:

        return redirect(url_for("login_portal"))

    if session.get("role") != "hr":

        return redirect(url_for("dashboard"))

    conn = get_db()

    # POST INTERNSHIP

    if request.method == "POST":

        company = request.form.get("company", "").strip()

        role = request.form.get("role", "").strip()

        skills = request.form.get("skills", "").strip()

        description = request.form.get("description", "").strip()

        if company and role and skills:

            conn.execute("""

            INSERT INTO internships

            (hr_id, company, role, skills, description)

            VALUES (?, ?, ?, ?, ?)

            """, (

                session["user_id"],
                company,
                role,
                skills,
                description

            ))

            conn.commit()

    # INTERNSHIPS

    internships = conn.execute("""

    SELECT *

    FROM internships

    WHERE hr_id = ?

    ORDER BY created_at DESC

    """, (

        session["user_id"],

    )).fetchall()

    # APPLICATIONS

    applications = conn.execute("""

    SELECT

        applications.id,
        applications.status,

        users.username,
        users.linkedin,

        internships.role,
        internships.company

    FROM applications

    JOIN users
    ON applications.user_id = users.id

    JOIN internships
    ON applications.internship_id = internships.id

    WHERE internships.hr_id = ?

    ORDER BY applications.applied_at DESC

    """, (

        session["user_id"],

    )).fetchall()

    conn.close()

    return render_template(

        "hr_dashboard.html",

        internships=internships,

        applications=applications

    )

@app.route("/apply/<int:job_id>")
def apply_internship(job_id):

    if "user_id" not in session:

        return redirect(url_for("login_portal"))

    conn = get_db()

    existing = conn.execute("""

    SELECT *

    FROM applications

    WHERE user_id = ?
    AND internship_id = ?

    """, (

        session["user_id"],
        job_id

    )).fetchone()

    if not existing:

        conn.execute("""

        INSERT INTO applications

        (user_id, internship_id, status)

        VALUES (?, ?, ?)

        """, (

            session["user_id"],
            job_id,
            "Pending"

        ))

        conn.commit()

    conn.close()

    return jsonify({
        "success": True
    })

@app.route("/update_application/<int:app_id>/<status>")
def update_application(app_id, status):

    if "user_id" not in session:

        return redirect(url_for("login_portal"))

    if session.get("role") != "hr":

        return redirect(url_for("dashboard"))

    conn = get_db()

    conn.execute("""

    UPDATE applications

    SET status = ?

    WHERE id = ?

    """, (

        status,
        app_id

    ))

    conn.commit()

    conn.close()

    return redirect(url_for("hr_dashboard"))
def heuristic_evaluation(role, company, question, answer, skills):
    expected_paradigms = {
        "sql": ["table", "schema", "relation", "join", "query", "acid", "row", "structured", "key", "foreign", "normalize"],
        "nosql": ["document", "schema-less", "sharding", "collection", "key-value", "json", "scalability", "horizontal"],
        "mongodb": ["document", "collection", "bson", "json", "aggregate", "schema-less", "sharding"],
        "postgresql": ["acid", "relation", "sql", "join", "transaction", "index", "mvcc"],
        "react": ["reconciliation", "diff", "virtual dom", "state", "props", "hook", "render", "component"],
        "dom": ["reconciliation", "diff", "virtual dom", "state", "props", "hook", "render", "component"],
        "virtual": ["reconciliation", "diff", "virtual dom", "state", "props", "hook", "render", "component"],
        "reconciliation": ["virtual dom", "fiber", "diff", "state", "patch", "tree", "props", "update"],
        "gradient": ["residual", "backpropagation", "activation", "sigmoid", "relu", "resnet", "layer", "weights", "skip connection"],
        "vanishing": ["residual", "backpropagation", "activation", "sigmoid", "relu", "resnet", "layer", "weights", "skip connection"],
        "bagging": ["bootstrap", "aggregation", "ensemble", "parallel", "variance", "random forest", "overfitting"],
        "boosting": ["sequential", "weight", "bias", "xgboost", "weak learner", "gradient", "adaboost"],
        "rag": ["retrieval", "vector", "embedding", "hallucination", "knowledge base", "context", "prompt", "llm"],
        "url": ["hash", "base62", "key generation", "kgs", "unique", "redirect", "base64", "database"],
        "shortening": ["hash", "base62", "key generation", "kgs", "unique", "redirect", "base64", "database"],
        "cap": ["consistency", "availability", "partition", "tolerance", "network", "distributed", "ap", "cp"],
        "rolling": ["zero-downtime", "incremental", "deployment", "kubernetes", "replica", "rollback"],
        "canary": ["subset", "traffic", "monitoring", "routing", "percentage", "metric", "rollback", "deployment"],
        "terraform": ["state", "infrastructure", "declarative", "provider", "plan", "apply", "hcl"],
        "pool": ["reuse", "overhead", "active", "idle", "thread", "close", "timeout"],
        "pooling": ["reuse", "overhead", "active", "idle", "thread", "close", "timeout"],
        "concurrency": ["thread", "process", "lock", "mutex", "deadlock", "race condition", "semaphore", "async", "await", "parallel"],
        "bottlenecks": ["profiling", "latency", "throughput", "memory leak", "cpu", "io", "bandwidth", "caching", "optimization"],
        "scaling": ["horizontal", "vertical", "load balancer", "replication", "sharding", "stateless", "caching", "cdn"],
        "explainable": ["xai", "shap", "lime", "interpretability", "bias", "fairness", "transparency", "feature importance"],
        "microservices": ["gateway", "rest", "grpc", "service discovery", "decentralized", "circuit breaker", "event-driven", "messaging"],
        "availability": ["load balancer", "replication", "redundancy", "failover", "multi-region", "backup", "sla", "clustering", "active-active", "active-passive"],
        "performance": ["latency", "concurrency", "caching", "indexing", "asynchronous", "queue", "rate limit", "load testing", "redis"],
        "security": ["jwt", "oauth", "encryption", "hash", "bcrypt", "ssl", "tls", "cors", "xss", "csrf", "sanitize", "token"],
        "testing": ["unit test", "integration", "mocking", "jest", "pytest", "coverage", "ci/cd", "pipeline"],
        "architecture": ["modular", "scalability", "microservices", "clean architecture", "monolith", "event-driven", "loosely coupled"],
        "optimization": ["caching", "minify", "profiler", "index", "query planner", "batching", "compression", "debounce", "throttle"],
        "leak": ["profile", "profiling", "heap", "garbage collector", "cleanup", "useeffect", "unmount", "listener", "subscription", "allocation"],
        "memory": ["profile", "profiling", "heap", "garbage collector", "cleanup", "useeffect", "unmount", "listener", "subscription", "allocation"]
    }
    
    stopwords = {
        "what", "how", "why", "explain", "difference", "between", "when", "would", "you", "use",
        "is", "are", "the", "a", "an", "of", "to", "for", "in", "with", "on", "at", "by", "from",
        "which", "over", "about", "detail", "design", "service", "like", "focused", "focus", "describe"
    }
    question_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', question.lower()))
    focus_words = question_words - stopwords
    
    answer_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', answer.lower()))
    word_count = len(answer.split())
    
    evasion_phrases = [
        "don't know", "dont know", "do not know", "not sure", "no idea", 
        "not familiar", "haven't worked", "cant explain", "can't explain",
        "hard to say", "never heard"
    ]
    is_evasive = any(phrase in answer.lower() for phrase in evasion_phrases)
    
    cleaned_question = re.sub(r'[^\w\s]', '', question.lower()).strip()
    cleaned_answer = re.sub(r'[^\w\s]', '', answer.lower()).strip()
    
    unique_new_words = answer_words - question_words
    content_new_words = unique_new_words - stopwords
    
    is_copy_paste = (cleaned_answer in cleaned_question) or (
        len(content_new_words) < 3 and 
        len(answer_words.intersection(question_words)) >= 3 and
        len(answer_words.intersection(question_words)) / len(question_words) > 0.5
    )
    
    matched_focus = focus_words.intersection(answer_words)
    alignment_ratio = len(matched_focus) / len(focus_words) if focus_words else 1.0
    
    paradigm_matches = set()
    for focus in focus_words:
        if focus in expected_paradigms:
            for keyword in expected_paradigms[focus]:
                if keyword in answer.lower():
                    paradigm_matches.add(keyword)
                    
    log.info(f"Technical Answer Diagnostics - Focus Words: {list(focus_words)}, Alignment Ratio: {alignment_ratio:.2f}, Production Keywords matched: {list(paradigm_matches)}")
    
    if is_evasive:
        score = 1
        verdict = "Strong No"
        strong_points = "None."
        weak_points = "Evasive response. The candidate explicitly stated they do not know or are unsure about this core technical concept."
        follow_up = "Let's step back. Can you describe any basic aspects or high-level goals of this technology?"
        
    elif is_copy_paste:
        score = 1
        verdict = "Strong No"
        strong_points = "None."
        weak_points = "Invalid response. The candidate repeated or copy-pasted the question text instead of providing an answer."
        follow_up = "Let's reset. Please describe the technical mechanism in your own words."
        
    elif word_count < 6:
        if len(matched_focus) > 0:
            score = 2
            verdict = "Strong No"
            strong_points = f"Briefly mentioned question focus: {', '.join(list(matched_focus))}."
            weak_points = "The response is extremely brief and lacks any technical explanation, structural definitions, or architectural context."
            follow_up = "Could you expand on that definition and explain its operational mechanism in a couple of sentences?"
        else:
            score = 1
            verdict = "Strong No"
            strong_points = "None."
            weak_points = "The response is extremely brief and does not address the question topic at all."
            follow_up = "Please provide a complete explanation of this technical concept."
            
    elif alignment_ratio == 0.0:
        score = 1
        verdict = "Strong No"
        strong_points = "None."
        weak_points = f"Completely off-topic! Your answer does not address the question topics at all: {', '.join(list(focus_words)[:3])}."
        follow_up = "Let's reset. Could you address the specific question asked and explain its core technical definitions?"
        
    elif len(paradigm_matches) == 0 and alignment_ratio < 0.25:
        score = 2
        verdict = "Strong No"
        strong_points = "None."
        weak_points = "Highly superficial. Your response contains general words but does not address the core mechanisms or paradigms of the question."
        follow_up = "Could you explain the specific components, architectures, or structural definitions of this topic?"
        
    elif len(paradigm_matches) == 0:
        score = 4
        verdict = "No"
        strong_points = f"Coherent sentence structure aligned with the topic: {', '.join(list(matched_focus)[:2])}."
        weak_points = "The response is shallow. It lacks concrete technical keywords (e.g., specific indexing, skip connections, virtual dom trees, or clustering protocols) required to demonstrate engineering expertise."
        follow_up = "What are the specific technical metrics, architectures, or protocols involved in this setup?"
        
    else:
        score_base = 5
        score_base += min(3, len(paradigm_matches))
        if alignment_ratio >= 0.5:
            score_base += 2
        elif alignment_ratio >= 0.25:
            score_base += 1
            
        rambling_penalty = 0
        technical_term_count = len(matched_focus) + len(paradigm_matches)
        density = technical_term_count / word_count if word_count > 0 else 0
        
        if word_count > 40:
            if density < 0.05:
                rambling_penalty = 4
            elif density < 0.10:
                rambling_penalty = 3
            elif density < 0.15:
                rambling_penalty = 2
                
        structural_intent_met = True
        question_intent_words = {"how", "why", "explain", "describe"}
        if question_words.intersection(question_intent_words):
            mechanism_connectives = {
                "because", "by", "using", "through", "via", "creates", "enables", 
                "prevents", "mitigates", "reduces", "avoids", "since", "allows"
            }
            if not answer_words.intersection(mechanism_connectives):
                structural_intent_met = False
                
        score = score_base - rambling_penalty
        if word_count > 45 and density < 0.10:
            score = min(5, score)
            
        if not structural_intent_met:
            score = min(7, score)
            
        score = max(1, min(10, score))
        
        if score >= 9:
            verdict = "Strong Yes"
            strong_points = f"Superb technical depth! Directly aligned with the question focus ({', '.join(list(matched_focus)[:3])}) and correctly explained core paradigms: {', '.join(list(paradigm_matches)[:4])}."
            weak_points = "None. A highly competitive, technically precise, and well-structured answer."
            follow_up = ""
        elif score >= 7:
            verdict = "Yes"
            strong_points = f"Solid understanding! Directly addressed the topic and correctly integrated technical keywords: {', '.join(list(paradigm_matches)[:3])}."
            weak_points = "Could improve by detailing concrete caching strategies, distributed failover flows, or concrete optimization metrics."
            follow_up = "How would you optimize this setup to maintain high availability and performance under heavy load?"
        else:
            verdict = "No" if score < 6 else "Yes"
            strong_points = "Good conceptual baseline. Demonstrated accurate awareness of the topic."
            weak_points = "Somewhat high-level or overly verbose. Missing concrete engineering metrics, locking structures, or structural definitions."
            follow_up = "What are the primary memory, compute, or network overheads associated with this setup?"

    return {
        "score": score,
        "verdict": verdict,
        "strong_points": strong_points,
        "weak_points": weak_points,
        "follow_up_question": follow_up
    }

def evaluate_answer_via_ai(role: str, company: str, question: str, answer: str, skills: List[str]):
    import requests
    ollama_running = False
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            ollama_running = True
    except Exception:
        pass

    if not ollama_running:
        log.info("Ollama offline. Grading via local technical heuristic scorer.")
        return heuristic_evaluation(role, company, question, answer, skills)
        
    try:
        import ollama
        prompt = TargetCodeGenerator.generate_evaluator_prompt(role, company, question, answer)
        
        response = ollama.chat(
            model='llama3.1:8b',
            messages=[{'role': 'user', 'content': prompt}],
            format='json',
            options={'temperature': 0.1}
        )
        
        eval_data = json.loads(response['message']['content'])
        for key in ["score", "verdict", "strong_points", "weak_points", "follow_up_question"]:
            if key not in eval_data:
                eval_data[key] = ""
        eval_data["score"] = int(eval_data["score"])
        return eval_data
        
    except Exception as e:
        log.error(f"Ollama chat evaluation error: {e}. Falling back to heuristics.")
        return heuristic_evaluation(role, company, question, answer, skills)

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login_portal"))

@app.route("/login", methods=["GET", "POST"])
def login_portal():

    if request.method == "POST":

        username = request.form.get("username", "").strip()

        password = request.form.get("password", "")

        remember = request.form.get("remember")

        if not username or not password:

            return render_template(
                "login.html",
                error="Please fill in all credentials."
            )

        conn = get_db()

        user = conn.execute(

            "SELECT * FROM users WHERE username = ?",

            (username,)

        ).fetchone()

        conn.close()

        if user and bcrypt.checkpw(

            password.encode('utf-8'),

            user['password_hash'].encode('utf-8')

        ):

            session.clear()

            session["user_id"] = user["id"]

            session["username"] = user["username"]

            session["role"] = user["role"]

            session["linkedin"] = user["linkedin"]

            if remember:

                session.permanent = True

            # HR LOGIN

            if user["role"] == "Candidate":

                return redirect(url_for("dashboard"))

            # CANDIDATE LOGIN

            return redirect(url_for("hr_dashboard"))

        else:

            return render_template(
                "login.html",
                error="Invalid username or password."
            )

    return render_template("login.html")
@app.route("/register", methods=["POST"])
def register():

    username = request.form.get("username", "").strip()

    password = request.form.get("password", "")

    confirm_password = request.form.get("confirm_password", "")

    role = request.form.get("role", "candidate")

    linkedin = request.form.get("linkedin", "").strip()

    if not username or not password or not confirm_password:

        return render_template(
            "login.html",
            error="All registration fields are required."
        )

    if password != confirm_password:

        return render_template(
            "login.html",
            error="Passwords do not match."
        )

    hashed = bcrypt.hashpw(

        password.encode('utf-8'),

        bcrypt.gensalt()

    ).decode('utf-8')

    conn = get_db()

    try:

        conn.execute("""

        INSERT INTO users
        (
            username,
            password_hash,
            role,
            linkedin
        )

        VALUES (?, ?, ?, ?)

        """, (

            username,
            hashed,
            role,
            linkedin

        ))

        conn.commit()

        conn.close()

        return render_template(
            "login.html",
            message="Account created successfully! Please sign in."
        )

    except sqlite3.IntegrityError:

        conn.close()

        return render_template(
            "login.html",
            error="Username already exists."
        )

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_portal"))
@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:

        return redirect(url_for("login_portal"))

    user_id = session["user_id"]

    conn = get_db()

    resume_row = conn.execute(

        "SELECT * FROM resumes WHERE user_id = ?",

        (user_id,)

    ).fetchone()

    parsed_skills = []

    warnings = ""

    recommended_jobs = []

    if resume_row:

        parsed_skills = json.loads(

            resume_row["parsed_skills"]

        )

        opt_ir = json.loads(

            resume_row["optimized_ir"]

        )

        if "warnings" in opt_ir and opt_ir["warnings"]:

            warnings = ", ".join([

                w.split("'")[3]

                for w in opt_ir["warnings"]

                if "'" in w

            ])

        # =========================
        # INTERNSHIP MATCHING
        # =========================

        candidate_dsl = " ".join([

            skill.lower()

            for skill in parsed_skills

        ])

        internships = conn.execute("""

        SELECT *

        FROM internships

        ORDER BY id DESC

        """).fetchall()

        for job in internships:

            job_skills = job["skills"].lower()

            candidate_words = set(

                candidate_dsl.split()

            )

            job_words = set(

                job_skills.split()

            )

            score = len(

                candidate_words & job_words

            )

            if score > 0:

                recommended_jobs.append(job)

    # =========================
    # APPLICATION STATUS
    # =========================

    applied_jobs = conn.execute("""

    SELECT *

    FROM applications

    WHERE user_id = ?

    """, (

        user_id,

    )).fetchall()

    # =========================
    # INTERVIEW HISTORY
    # =========================

    history_rows = conn.execute("""

        SELECT * FROM sessions

        WHERE user_id = ?
        AND completed = 1

        ORDER BY created_at DESC

    """, (

        user_id,

    )).fetchall()

    history = []

    completed_count = len(history_rows)

    total_score = 0

    for sess in history_rows:

        q_rows = conn.execute("""

            SELECT *

            FROM session_questions

            WHERE session_id = ?

        """, (

            sess["id"],

        )).fetchall()

        questions_list = []

        for q in q_rows:

            questions_list.append({

                "question_text":
                q["question_text"],

                "user_answer":
                q["user_answer"],

                "score":
                q["score"],

                "verdict":
                q["verdict"],

                "feedback_text":
                q["feedback_text"],

                "follow_up_question":
                q["follow_up_question"],

                "follow_up_answer":
                q["follow_up_answer"],

                "follow_up_score":
                q["follow_up_score"]

            })

        total_score += sess["score"]

        history.append({

            "id":
            sess["id"],

            "role":
            sess["role"],

            "company":
            sess["company"],

            "score":
            sess["score"],

            "verdict":
            sess["verdict"],

            "feedback":
            sess["feedback"],

            "created_at":
            sess["created_at"].split()[0],

            "questions":
            questions_list

        })

    avg_score = (

        total_score / completed_count

    ) if completed_count > 0 else 0

    conn.close()

    return render_template(

        "dashboard.html",

        username=session["username"],

        parsed_skills=parsed_skills,

        warnings=warnings,

        history=history,

        completed_count=completed_count,

        avg_score=avg_score,

        recommended_jobs=recommended_jobs,

        applied_jobs=applied_jobs

    )
def extract_text_from_file(file_bytes, filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.txt':
        return file_bytes.decode('utf-8', errors='ignore')
    elif ext == '.pdf':
        pdf_file = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_file)
        text_list = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_list.append(text)
        return "\n".join(text_list)
    elif ext in ('.docx', '.doc'):
        docx_file = io.BytesIO(file_bytes)
        doc = docx.Document(docx_file)
        text_list = []
        for para in doc.paragraphs:
            text_list.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    text_list.append(cell.text)
        return "\n".join(text_list)
    else:
        raise ValueError(f"Unsupported file format: {ext}. Please upload a PDF, DOCX, or TXT file.")

@app.route("/api/upload_resume", methods=["POST"])
def upload_resume():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    resume_text = ""
    if request.is_json:
        data = request.get_json()
        resume_text = data.get("resume_text", "").strip()
    elif 'resume_file' in request.files:
        file = request.files['resume_file']
        filename = file.filename
        if filename != '':
            try:
                file_bytes = file.read()
                resume_text = extract_text_from_file(file_bytes, filename).strip()
            except Exception as fe:
                return jsonify({"error": f"Failed to extract file text: {str(fe)}"}), 400
                
    if not resume_text:
        return jsonify({"error": "No resume text or file provided"}), 400
        
    user_id = session["user_id"]
    
    try:
        comp_res = run_resume_compiler(resume_text)
        
        parsed_skills = json.dumps(comp_res["skills"])
        optimized_ir = json.dumps({
            "email": comp_res["email"],
            "phone": comp_res["phone"],
            "warnings": comp_res["warnings"],
            "tokens_count": comp_res["raw_tokens_count"],
            "ast": comp_res["ast"]
        })
        
        conn = get_db()
        conn.execute("""
            INSERT INTO resumes (user_id, raw_text, parsed_skills, optimized_ir, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                raw_text=excluded.raw_text,
                parsed_skills=excluded.parsed_skills,
                optimized_ir=excluded.optimized_ir,
                updated_at=CURRENT_TIMESTAMP
        """, (user_id, resume_text, parsed_skills, optimized_ir))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": "Resume successfully compiled",
            "skills": comp_res["skills"],
            "warnings": comp_res["warnings"]
        })
        
    except Exception as e:
        log.error(f"Resume compiling failed: {e}")
        return jsonify({"error": f"Compilation failed: {str(e)}"}), 500

@app.route("/start_interview", methods=["POST"])
def start_interview():
    if "user_id" not in session:
        return redirect(url_for("login_portal"))
        
    user_id = session["user_id"]
    role = request.form.get("role", "Backend Developer")
    company = request.form.get("company", "FAANG").strip()
    
    conn = get_db()
    resume_row = conn.execute("SELECT * FROM resumes WHERE user_id = ?", (user_id,)).fetchone()
    
    if not resume_row:
        conn.close()
        return redirect(url_for("dashboard"))
        
    skills = json.loads(resume_row["parsed_skills"])
    
    asked_rows = conn.execute("SELECT question_hash FROM asked_questions WHERE user_id = ?", (user_id,)).fetchall()
    asked_hashes = {row["question_hash"] for row in asked_rows}
    
    retrieved_docs = []
    try:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        ef = RobustEmbeddingFunction(model_name="nomic-embed-text", url="http://localhost:11434/api/embeddings")
        collection = client.get_collection(name="interview_bank", embedding_function=ef)
        search_query = TargetCodeGenerator.generate_rag_query(role, company, skills)
        results = collection.query(query_texts=[search_query], n_results=12)
        if results and results['documents'] and results['documents'][0]:
            retrieved_docs = results['documents'][0]
    except Exception as e:
        log.error(f"ChromaDB retrieval error: {e}")
        
    if not retrieved_docs:
        retrieved_docs = [
            f"Explain how you design a modular system architecture for a {role} at {company}?",
            f"What are the major performance bottlenecks in a {role} pipeline, and how do you profile them?",
            f"How do you manage concurrency, scheduling, and error handling in your active projects?"
        ]

    selected_questions = []
    for doc in retrieved_docs:
        q_hash = hashlib.md5(doc.lower().encode()).hexdigest()
        if q_hash not in asked_hashes:
            selected_questions.append((doc, q_hash))
        if len(selected_questions) == 3:
            break
            
    if len(selected_questions) < 3:
        log.warning("User has been asked all database questions. Re-using older questions.")
        for doc in retrieved_docs:
            q_hash = hashlib.md5(doc.lower().encode()).hexdigest()
            if not any(x[1] == q_hash for x in selected_questions):
                selected_questions.append((doc, q_hash))
            if len(selected_questions) == 3:
                break
                
    session_id = str(uuid.uuid4())
    
    conn.execute("""
        INSERT INTO sessions (id, user_id, role, company, score, verdict, feedback, completed)
        VALUES (?, ?, ?, ?, NULL, NULL, NULL, 0)
    """, (session_id, user_id, role, company))
    
    for idx, (q_text, q_hash) in enumerate(selected_questions):
        conn.execute("""
            INSERT INTO session_questions (session_id, question_text, user_answer, score, verdict, feedback_text)
            VALUES (?, ?, NULL, NULL, NULL, NULL)
        """, (session_id, q_text))
        
        try:
            conn.execute("""
                INSERT INTO asked_questions (user_id, question_hash, question_text)
                VALUES (?, ?, ?)
            """, (user_id, q_hash, q_text))
        except sqlite3.IntegrityError:
            pass
            
    conn.commit()
    conn.close()
    
    return redirect(url_for("interview_console", session_id=session_id))

@app.route("/interview/<session_id>")
def interview_console(session_id):
    if "user_id" not in session:
        return redirect(url_for("login_portal"))
        
    user_id = session["user_id"]
    conn = get_db()
    
    sess = conn.execute("SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    if not sess:
        conn.close()
        return redirect(url_for("dashboard"))
        
    q_rows = conn.execute("SELECT question_text FROM session_questions WHERE session_id = ?", (session_id,)).fetchall()
    questions = [q["question_text"] for q in q_rows]
    conn.close()
    
    return render_template(
        "interview.html",
        session_id=session_id,
        role=sess["role"],
        company=sess["company"],
        questions_json=json.dumps(questions)
    )

@app.route("/api/submit_answer", methods=["POST"])
def submit_answer():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    user_id = session["user_id"]
    data = request.get_json()
    
    session_id = data.get("session_id")
    q_index = data.get("question_index")
    question_text = data.get("question")
    answer = data.get("answer", "").strip()
    is_follow_up = data.get("is_follow_up", False)
    
    if not session_id or q_index is None or not question_text or not answer:
        return jsonify({"error": "Invalid payload"}), 400
        
    conn = get_db()
    sess = conn.execute("SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    if not sess:
        conn.close()
        return jsonify({"error": "Session not found"}), 404
        
    resume_row = conn.execute("SELECT parsed_skills FROM resumes WHERE user_id = ?", (user_id,)).fetchone()
    skills = json.loads(resume_row["parsed_skills"]) if resume_row else []
    
    log.info(f"Grading response for session {session_id}, Question index: {q_index}")
    eval_data = evaluate_answer_via_ai(sess["role"], sess["company"], question_text, answer, skills)
    
    if is_follow_up:
        q_rows = conn.execute("SELECT id FROM session_questions WHERE session_id = ?", (session_id,)).fetchall()
        target_id = q_rows[q_index]["id"]
        
        conn.execute("""
            UPDATE session_questions 
            SET follow_up_answer = ?, follow_up_score = ?
            WHERE id = ?
        """, (answer, eval_data["score"], target_id))
    else:
        q_rows = conn.execute("SELECT id FROM session_questions WHERE session_id = ?", (session_id,)).fetchall()
        target_id = q_rows[q_index]["id"]
        
        combined_feedback = f"{eval_data['strong_points']} | {eval_data['weak_points']}"
        
        conn.execute("""
            UPDATE session_questions 
            SET user_answer = ?, score = ?, verdict = ?, feedback_text = ?, follow_up_question = ?
            WHERE id = ?
        """, (answer, eval_data["score"], eval_data["verdict"], combined_feedback, eval_data["follow_up_question"], target_id))
        
    conn.commit()
    conn.close()
    
    return jsonify(eval_data)

@app.route("/api/session_summary/<session_id>")
def session_summary(session_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    user_id = session["user_id"]
    conn = get_db()
    
    sess = conn.execute("SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    if not sess:
        conn.close()
        return jsonify({"error": "Session not found"}), 404
        
    q_rows = conn.execute("SELECT * FROM session_questions WHERE session_id = ?", (session_id,)).fetchall()
    
    scores = []
    strengths = []
    gaps = []
    
    for row in q_rows:
        if row["score"] is not None:
            scores.append(row["score"])
        if row["follow_up_score"] is not None:
            scores.append(row["follow_up_score"])
            
        feedback_parts = row["feedback_text"].split(" | ") if row["feedback_text"] else ["", ""]
        if feedback_parts[0]:
            strengths.append(feedback_parts[0])
        if len(feedback_parts) > 1 and feedback_parts[1]:
            gaps.append(feedback_parts[1])
            
    final_avg = sum(scores) / len(scores) if scores else 0
    
    if final_avg >= 8:
        verdict = "Strong Yes"
        overall_feedback = f"The candidate demonstrated exceptional command over technical core features, and architectural trade-offs for {sess['role']}. Strengths include: " + " ".join(strengths[:2])
    elif final_avg >= 6:
        verdict = "Yes"
        overall_feedback = f"Solid performance. The candidate understands core requirements but could expand on database locking, edge cases, or distributed scaling layers. Notable gap: " + " ".join(gaps[:1])
    else:
        verdict = "No"
        overall_feedback = "The candidate struggled to provide technical depth and production-ready implementations. Conceptual clarity and structural explanations need revision."
        
    conn.execute("""
        UPDATE sessions 
        SET score = ?, verdict = ?, feedback = ?, completed = 1
        WHERE id = ?
    """, (final_avg, verdict, overall_feedback, session_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        "score": final_avg,
        "verdict": verdict,
        "feedback": overall_feedback
    })

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
