import os
from dotenv import load_dotenv

# MUST be called FIRST before importing config or router
load_dotenv()

from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from datetime import datetime

from config import SECRET_KEY, DEBUG, HOST, PORT
from agent.router import AgentRouter
from handlers.file_handler import process_uploaded_file
from utils.text_cleaner import clean_response
from utils.date_parser import detect_appointment_from_text

app = Flask(__name__)
app.secret_key = SECRET_KEY or os.getenv('SECRET_KEY', 'default_secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app)

db = SQLAlchemy(app)
agent = AgentRouter()

# ──────────────────────────────────────────────────────────────────────────────
# STRICT MEDICAL BOUNDARY RULES (Applied to ALL AI modules globally)
# ──────────────────────────────────────────────────────────────────────────────
STRICT_MEDICAL_RULES = (
    "IMPORTANT RULES:\n"
    "1. You MUST ONLY respond to health-related questions (symptoms, diseases, medications, treatments, nutrition, exercise, workouts, recipes, mental wellness, sleep, etc.).\n"
    "2. If the user asks about movies, general sports, entertainment, politics, or any non-health topic, politely decline and say: 'I am a health assistant and can only help with health-related questions. Please ask me about your well-being.'\n"
    "3. CLARIFICATION: Routine automation requests for 'wellness plans', 'workouts', 'exercises', 'recipes', 'mental wellness tips', or 'sleep tips' ARE valid health queries. Do not block them.\n"
    "4. For health-related questions, provide a detailed, thoughtful response (at least 7-15 sentences). Use proper formatting:\n"
    "   - You MUST place the medical disclaimer at the VERY TOP of your response, starting with the warning symbol '⚠️ Medical Disclaimer:'. Never put it at the bottom.\n"
    "   - Use normal case for headings (e.g., 'Key Findings' not 'KEY FINDINGS').\n"
    "   - After each heading, start the content on a new line.\n"
    "   - Use the bullet symbol '●' for list items.\n"
    "   - Do not use all caps words except for standard abbreviations.\n"
    "5. For non-medical greetings (e.g., 'hi', 'hey', 'my name is'), respond briefly in 1-2 sentences without a disclaimer.\n"
    "6. ALIGNMENT RULE: You MUST cross-reference all advice (especially workouts, diets, and wellness strategies) with the CURRENT PATIENT PROFILE context. You must adapt your guidance around ANY active condition, symptom, or injury listed.\n"
    "7. PERSONALIZATION RULE: Always address the user by their name if available. Tailor every recommendation specifically to their BMI, gender, age, and active medical conditions.\n"
    "8. FORMATTING RULE: Use clear section headers like 'Dietary Recommendations', 'Exercise Guidelines', 'Mental Wellness Strategies', etc. Each section must have at least 3 bullet points.\n"
    "Be empathetic, thorough, and professional when giving health advice."
)

# ──────────────────────────────────────────────────────────────────────────────
# DATABASE HELPER: INJECT PATIENT PROFILE INTO AI MEMORY
# ──────────────────────────────────────────────────────────────────────────────
def build_ai_patient_context(user_id):
    """Fetches user metrics and medical history from PostgreSQL to prompt the AI"""
    if not user_id:
        return "No specific patient data available. Provide general, safe health advice."

    assessment = db.session.execute(
        text("SELECT height_cm, weight_kg, gender, bmi FROM health_assessments WHERE user_id = :uid"),
        {"uid": user_id}
    ).fetchone()
    
    illnesses = db.session.execute(
        text("SELECT DISTINCT symptom_or_illness FROM patient_illnesses WHERE user_id = :uid"),
        {"uid": user_id}
    ).fetchall()
    
    user = db.session.execute(
        text("SELECT full_name FROM users WHERE id = :uid"),
        {"uid": user_id}
    ).fetchone()
    
    context = "### CURRENT PATIENT PROFILE BACKGROUND CONTEXT:\n"
    if user:
        context += f"- Patient Name: {user[0]}\n"
    else:
        context += "- Patient Name: Not provided\n"
        
    if assessment:
        context += (
            f"- Demographic Info: Gender identity is {assessment.gender}.\n"
            f"- Metrics: Height measures {assessment.height_cm} cm, Weight measures {assessment.weight_kg} kg.\n"
            f"- Calculated BMI Tier: {assessment.bmi}.\n"
        )
    else:
        context += "- Physical assessment criteria unsubmitted or blank.\n"
        
    if illnesses:
        issue_list = [row[0] for row in illnesses]
        context += f"- Chronic Illness/Active Documented Issues: {', '.join(issue_list)}.\n"
    else:
        context += "- No specialized critical historical illnesses flagged in file systems.\n"
        
    return context

# ──────────────────────────────────────────────────────────────────────────────
# SPA ROUTING (CATCH-ALL)
# ──────────────────────────────────────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_spa(path):
    if path.startswith('api/'):
        return jsonify({"error": "API endpoint not found"}), 404
    return render_template('index.html')

# ──────────────────────────────────────────────────────────────────────────────
# AUTHENTICATION ENDPOINTS
# ──────────────────────────────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    try:
        user = db.session.execute(
            text("SELECT id, full_name, email, password_hash FROM users WHERE email = :email"),
            {"email": email}
        ).fetchone()
        
        if user and user[3] == password:  
            session['user_id'] = user[0]
            return jsonify({
                "success": True,
                "user": {"id": user[0], "full_name": user[1], "email": user[2]}
            })
        return jsonify({"success": False, "error": "Invalid email or password"}), 401
    except Exception as e:
        print(f"Login Error: {e}")
        return jsonify({"success": False, "error": "Database error"}), 500

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    try:
        result = db.session.execute(
            text("INSERT INTO users (full_name, email, password_hash) VALUES (:name, :email, :pass) RETURNING id"),
            {"name": data.get('full_name'), "email": data.get('email'), "pass": data.get('password')}
        )
        user_id = result.fetchone()[0] 
        db.session.commit()
        
        session['user_id'] = user_id
        return jsonify({
            "success": True, 
            "user": {"id": user_id, "full_name": data.get('full_name'), "email": data.get('email')}
        })
    except Exception as e:
        db.session.rollback()
        print(f"Registration Error: {e}") 
        return jsonify({"error": "Email already exists or missing fields"}), 400

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({"success": True})

@app.route('/api/me')
def me():
    user_id = session.get('user_id')
    if user_id:
        query = text("""
            SELECT u.id, u.full_name, u.email, h.height_cm, h.weight_kg, h.gender, h.bmi 
            FROM users u 
            LEFT JOIN health_assessments h ON u.id = h.user_id 
            WHERE u.id = :uid
        """)
        result = db.session.execute(query, {"uid": user_id}).fetchone()
        
        if result:
            return jsonify({"user": {
                "id": result[0], 
                "full_name": result[1], 
                "email": result[2],
                "height": result[3],
                "weight": result[4],
                "gender": result[5],
                "bmi": result[6]
            }})
    return jsonify({"user": None}), 401

@app.route('/api/update-profile', methods=['POST'])
def update_profile():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json()
    full_name = data.get('full_name')
    h = float(data.get('height') or 0)
    w = float(data.get('weight') or 0)
    g = data.get('gender', 'other')
    bmi = float(data.get('bmi') or 0)
    
    if full_name:
        db.session.execute(
            text("UPDATE users SET full_name = :name WHERE id = :uid"),
            {"name": full_name, "uid": user_id}
        )
    
    db.session.execute(
        text("""
            INSERT INTO health_assessments (user_id, height_cm, weight_kg, gender, bmi) 
            VALUES (:uid, :h, :w, :g, :bmi) 
            ON CONFLICT (user_id) DO UPDATE SET 
            height_cm = EXCLUDED.height_cm, 
            weight_kg = EXCLUDED.weight_kg, 
            gender = EXCLUDED.gender, 
            bmi = EXCLUDED.bmi, 
            updated_at = CURRENT_TIMESTAMP
        """),
        {"uid": user_id, "h": h, "w": w, "g": g, "bmi": bmi}
    )
    db.session.commit()
    return jsonify({"success": True})

# ──────────────────────────────────────────────────────────────────────────────
# CHAT ENDPOINTS (Expanded Smart Symptom & Recovery Tracker)
# ──────────────────────────────────────────────────────────────────────────────
@app.route('/api/chat', methods=['POST'])
def chat():
    user_id = session.get('user_id')
    data = request.get_json()
    user_message = data.get('message', '')
    system_prompt = data.get('system_prompt', '')
    history = data.get('history', [])

    if user_id:
        msg_lower = user_message.lower()
        
        symptom_map = {
            "leg": "Lower Body/Leg Injury", "calf": "Lower Body/Leg Injury", "thigh": "Lower Body/Leg Injury",
            "hamstring": "Lower Body/Leg Injury", "quad": "Lower Body/Leg Injury", "ankle": "Lower Body/Leg Injury",
            "foot": "Lower Body/Leg Injury", "feet": "Lower Body/Leg Injury", "toe": "Lower Body/Leg Injury",
            "knee": "Knee Injury", "meniscus": "Knee Injury", "patella": "Knee Injury",
            "back": "Back/Neck Pain", "spine": "Back/Neck Pain", "lumbar": "Back/Neck Pain", "neck": "Back/Neck Pain",
            "shoulder": "Upper Body/Arm Injury", "arm": "Upper Body/Arm Injury", "elbow": "Upper Body/Arm Injury",
            "wrist": "Upper Body/Arm Injury", "hand": "Upper Body/Arm Injury", "finger": "Upper Body/Arm Injury",
            "bicep": "Upper Body/Arm Injury", "tricep": "Upper Body/Arm Injury",
            "fever": "Fever", "temperature": "Fever", "hot": "Fever",
            "headache": "Headache/Migraine", "migraine": "Headache/Migraine", "head": "Headache/Migraine",
            "cold": "Cold/Flu Symptoms", "flu": "Cold/Flu Symptoms", "cough": "Cold/Flu Symptoms",
            "sneeze": "Cold/Flu Symptoms", "congest": "Cold/Flu Symptoms", "runny nose": "Cold/Flu Symptoms",
            "sore throat": "Cold/Flu Symptoms", "throat": "Cold/Flu Symptoms",
            "nausea": "Stomach/Digestive Issue", "stomach": "Stomach/Digestive Issue", "tummy": "Stomach/Digestive Issue",
            "belly": "Stomach/Digestive Issue", "vomit": "Stomach/Digestive Issue", "throw up": "Stomach/Digestive Issue",
            "throwing up": "Stomach/Digestive Issue", "diarrhea": "Stomach/Digestive Issue", "gut": "Stomach/Digestive Issue",
            "food poison": "Stomach/Digestive Issue",
            "chest": "Chest/Breathing Issue", "breath": "Chest/Breathing Issue", "lung": "Chest/Breathing Issue",
            "heart": "Chest/Breathing Issue",
            "fatigue": "Severe Fatigue", "tired": "Severe Fatigue", "exhausted": "Severe Fatigue",
            "dizzy": "Dizziness/Vertigo", "vertigo": "Dizziness/Vertigo", "faint": "Dizziness/Vertigo"
        }

        recovery_words = [
            "free from", "recovered", "healed", "better", "no more", "gone", "cured", "no longer",
            "fine now", "all good", "100%", "back to normal", "fixed", "okay now", "perfectly fine",
            "cleared up", "disappeared", "over it"
        ]
        is_recovery = any(word in msg_lower for word in recovery_words)
        
        trigger_words = [
            "injur", "pain", "hurt", "sprain", "broken", "fever", "headache", "cold", "cough",
            "flu", "sick", "nausea", "ache", "sore", "swollen", "fracture", "ill", "vomit",
            "stiff", "bleeding", "bruis", "torn", "twist", "pulled", "strain", "cramp"
        ]
        is_symptom = any(word in msg_lower for word in trigger_words)

        matched_conditions = set()
        for key, value in symptom_map.items():
            if key in msg_lower:
                matched_conditions.add(value)

        try:
            if is_recovery:
                if "all" in msg_lower or len(matched_conditions) == 0:
                    db.session.execute(
                        text("DELETE FROM patient_illnesses WHERE user_id = :uid"),
                        {"uid": user_id}
                    )
                else:
                    for condition in matched_conditions:
                        db.session.execute(
                            text("DELETE FROM patient_illnesses WHERE user_id = :uid AND symptom_or_illness = :symptom"),
                            {"uid": user_id, "symptom": condition}
                        )
            
            elif is_symptom and matched_conditions:
                for condition in matched_conditions:
                    existing = db.session.execute(
                        text("SELECT 1 FROM patient_illnesses WHERE user_id = :uid AND symptom_or_illness = :symptom"),
                        {"uid": user_id, "symptom": condition}
                    ).fetchone()
                    
                    if not existing:
                        db.session.execute(
                            text("INSERT INTO patient_illnesses (user_id, symptom_or_illness) VALUES (:uid, :symptom)"),
                            {"uid": user_id, "symptom": condition}
                        )
                        
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error updating conditions: {e}")

    patient_context = build_ai_patient_context(user_id)
    messages = []
    
    if system_prompt:
        messages.append({"role": "system", "content": f"{system_prompt}\n\n{patient_context}\n\n{STRICT_MEDICAL_RULES}"})
    else:
        messages.append({
            "role": "system",
            "content": f"You are MedGuide AI, a caring and knowledgeable healthcare assistant.\n\n{patient_context}\n\n{STRICT_MEDICAL_RULES}"
        })
        
    for msg in history[-10:]:
        messages.append({"role": msg['role'], "content": msg['content']})

    framed_user_message = (
        f"{user_message}\n\n"
        f"(System Note: Generate your response by aligning STRICTLY with ALL the active injuries, "
        f"illnesses, gender identity, and physical metrics listed in my Patient Profile Context. "
        f"Address me by name if available. Use clear section headers and bullet points for each recommendation.)"
    )
    messages.append({"role": "user", "content": framed_user_message})

    response = agent.handle_chat(messages)
    response = clean_response(response)

    return jsonify({"response": response})

# ──────────────────────────────────────────────────────────────────────────────
# PERSONALIZED WELLNESS ENDPOINTS (All dynamically linked to Patient Context)
# ──────────────────────────────────────────────────────────────────────────────
@app.route('/api/health-tips', methods=['GET'])
def health_tips():
    user_id = session.get('user_id')
    context = build_ai_patient_context(user_id)
    
    prompt = (
        f"{context}\n\n{STRICT_MEDICAL_RULES}\n"
        f"Patient Medical Request: Provide a daily health tip. "
        f"Generate a practical, actionable health tip for today. "
        f"The tip must be personalized based on my BMI, gender, and ANY active conditions listed in my profile. "
        f"Format the tip as a structured list using the bullet symbol '●'. Each bullet point MUST start on a new line."
    )
    messages = [{"role": "user", "content": prompt}]
    tip = clean_response(agent.handle_chat(messages))
    return jsonify({"tip": tip})

@app.route('/api/wellness-plan', methods=['POST'])
def wellness_plan():
    user_id = session.get('user_id')
    context = build_ai_patient_context(user_id)
    
    user_name = "Patient"
    if user_id:
        user_row = db.session.execute(
            text("SELECT full_name FROM users WHERE id = :uid"), {"uid": user_id}
        ).fetchone()
        if user_row:
            user_name = user_row[0]

    prompt = (
        f"{context}\n\n{STRICT_MEDICAL_RULES}\n"
        f"Patient Medical Request: I am {user_name}. Please generate a highly detailed personalized wellness plan "
        f"tailored explicitly to my recorded physical background context including my Name, Height, Weight, Gender, calculated BMI tier, and ANY active illnesses or injuries. "
        f"Make sure to design actionable nutritional strategies and routines calibrated directly for my body profile metrics. "
        f"Structure your response with these clear sections:\n"
        f"● Dietary Recommendations\n"
        f"● Exercise Guidelines\n"
        f"● Lifestyle Modifications\n"
        f"● Monitoring & Progress Tracking\n"
        f"Use normal case headings, newlines after headings, and ● for bullet points. "
        f"No special characters like *, #, @. At least 10 sentences."
    )
    messages = [{"role": "user", "content": prompt}]
    plan = clean_response(agent.handle_chat(messages))
    return jsonify({"plan": plan})

@app.route('/api/recipes', methods=['GET'])
def recipes():
    user_id = session.get('user_id')
    context = build_ai_patient_context(user_id)
    prompt = (
        f"{context}\n\n{STRICT_MEDICAL_RULES}\n"
        f"Patient Medical Request: Provide structured meal advice. "
        f"Generate 2-3 healthy dietary recipes tailored strictly to my current physical background context, ANY active illnesses or conditions, and BMI targets. "
        f"For each recipe, include:\n"
        f"● Recipe Name\n"
        f"● Ingredients List\n"
        f"● Preparation Steps\n"
        f"● Nutritional Benefits\n"
        f"● Why this recipe suits my profile\n"
        f"Use normal case headings, newlines, and ● for bullets. No special characters."
    )
    messages = [{"role": "user", "content": prompt}]
    recipe = clean_response(agent.handle_chat(messages))
    return jsonify({"recipes": recipe})

@app.route('/api/workouts', methods=['POST'])
def workouts():
    data = request.get_json() or {}
    level = data.get('level', 'beginner')
    user_id = session.get('user_id')
    context = build_ai_patient_context(user_id)
    prompt = (
        f"{context}\n\n{STRICT_MEDICAL_RULES}\n"
        f"Patient Medical Request: Provide functional exercise plans. "
        f"Create a detailed {level} adaptive workout plan safely tailored to my physical capacity, BMI tier, and ALL active recorded injuries or conditions. "
        f"IMPORTANT: You must review my Patient Profile Context. If I have ANY documented injury (whether it is a leg, back, arm, gut issue, or fever), you must explicitly avoid exercises that stress or aggravate that specific area, and provide safe alternatives. "
        f"Structure your workout plan with these sections:\n"
        f"● Warm-up Exercises\n"
        f"● Main Workout (with sets, reps, and rest periods)\n"
        f"● Cool-down Exercises\n"
        f"● Safety Precautions specific to my active conditions\n"
        f"Use normal case headings, newlines, and ● for bullets. No special characters."
    )
    messages = [{"role": "user", "content": prompt}]
    workout = clean_response(agent.handle_chat(messages))
    return jsonify({"workout": workout})

@app.route('/api/mental-wellness', methods=['GET'])
def mental_wellness():
    user_id = session.get('user_id')
    context = build_ai_patient_context(user_id)
    prompt = (
        f"{context}\n\n{STRICT_MEDICAL_RULES}\n"
        f"Patient Medical Request: Provide structured mental health strategies. "
        f"Provide detailed mental wellness, mindfulness, and stress-reduction techniques tailored seamlessly around my physical profile and ANY active medical conditions or physical injuries causing stress. "
        f"Structure your response with these sections:\n"
        f"● Daily Mindfulness Practices\n"
        f"● Stress Management Techniques\n"
        f"● Emotional Well-being Strategies\n"
        f"● When to Seek Professional Help\n"
        f"Use normal case headings, newlines, and ● for bullets. No special characters."
    )
    messages = [{"role": "user", "content": prompt}]
    tips = clean_response(agent.handle_chat(messages))
    return jsonify({"tips": tips})

@app.route('/api/sleep-optimization', methods=['GET'])
def sleep_optimization():
    user_id = session.get('user_id')
    context = build_ai_patient_context(user_id)
    prompt = (
        f"{context}\n\n{STRICT_MEDICAL_RULES}\n"
        f"Patient Medical Request: Provide physiological optimization advice. "
        f"Provide personalized sleep optimization recommendations and behavioral guidelines calculated dynamically based on my physical profile, BMI parameters, and ANY active injuries or illnesses that might disrupt my sleep. "
        f"Structure your response with these sections:\n"
        f"● Sleep Environment Optimization\n"
        f"● Bedtime Routine Recommendations\n"
        f"● Lifestyle Factors Affecting Sleep\n"
        f"● Sleep Tracking & Monitoring\n"
        f"Use normal case headings, newlines, and ● for bullets. No special characters."
    )
    messages = [{"role": "user", "content": prompt}]
    tips = clean_response(agent.handle_chat(messages))
    return jsonify({"tips": tips})

# ──────────────────────────────────────────────────────────────────────────────
# FILE UPLOAD ENDPOINT
# ──────────────────────────────────────────────────────────────────────────────
from handlers.file_handler import process_file

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['file']
    try:
        result = process_file(file)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    
# Automatically create database tables using raw SQL on startup
with app.app_context():
    create_tables_query = text("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            full_name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL
        );

        CREATE TABLE IF NOT EXISTS health_assessments (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            height_cm FLOAT,
            weight_kg FLOAT,
            gender VARCHAR(50),
            bmi FLOAT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS patient_illnesses (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            symptom_or_illness VARCHAR(255) NOT NULL
        );

        CREATE TABLE IF NOT EXISTS generated_features (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            feature_type VARCHAR(255),
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    try:
        db.session.execute(create_tables_query)
        db.session.commit()
        print("✅ Database tables explicitly verified/created using raw SQL!")
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error creating tables: {e}")

if __name__ == '__main__':
    app.run(host=HOST, port=PORT, debug=DEBUG)