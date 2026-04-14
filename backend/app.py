from flask import Flask, request, jsonify, session
from flask_cors import CORS
from fact_checker import run_fact_check

from PIL import Image
import pytesseract
import io
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY is not set")

CORS(
    app,
    supports_credentials=True,
    origins=["http://localhost:5173", "http://127.0.0.1:5173"],
)

is_production = os.getenv("ENV") == "production"

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = is_production

tesseract_cmd = os.getenv("TESSERACT_CMD")
if tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def get_connection():
    db_name = os.getenv("DB_NAME")
    db_password = os.getenv("DB_PASSWORD")

    if not db_name or not db_password:
        raise ValueError("Database environment variables are missing")

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=db_name,
        user=os.getenv("DB_USER", "postgres"),
        password=db_password,
    )


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # users table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            google_sub TEXT UNIQUE,
            picture_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    # fact_checks table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS fact_checks (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            claim TEXT NOT NULL,
            verdict TEXT,
            confidence FLOAT,
            explanation TEXT,
            extracted_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    # sources table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sources (
            id SERIAL PRIMARY KEY,
            fact_check_id INTEGER REFERENCES fact_checks(id) ON DELETE CASCADE,
            title TEXT,
            url TEXT
        );
        """
    )

    # Make old databases compatible with new code
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub TEXT;")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS picture_url TEXT;")
    cur.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
    )

    cur.execute("ALTER TABLE fact_checks ADD COLUMN IF NOT EXISTS user_id INTEGER;")
    cur.execute("ALTER TABLE fact_checks ADD COLUMN IF NOT EXISTS claim TEXT;")
    cur.execute("ALTER TABLE fact_checks ADD COLUMN IF NOT EXISTS verdict TEXT;")
    cur.execute("ALTER TABLE fact_checks ADD COLUMN IF NOT EXISTS confidence FLOAT;")
    cur.execute("ALTER TABLE fact_checks ADD COLUMN IF NOT EXISTS explanation TEXT;")
    cur.execute("ALTER TABLE fact_checks ADD COLUMN IF NOT EXISTS extracted_text TEXT;")
    cur.execute(
        "ALTER TABLE fact_checks ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
    )

    # Old schema support: if old column "reason" exists, copy it into explanation
    cur.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'fact_checks' AND column_name = 'reason'
            ) THEN
                UPDATE fact_checks
                SET explanation = reason
                WHERE explanation IS NULL;
            END IF;
        END$$;
        """
    )

    conn.commit()
    cur.close()
    conn.close()


def save_fact_check(claim, result, user_id=None, extracted_text=None):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO fact_checks (user_id, claim, verdict, confidence, explanation, extracted_text)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, created_at;
        """,
        (
            user_id,
            claim,
            result.get("verdict"),
            result.get("confidence"),
            result.get("explanation"),
            extracted_text,
        ),
    )

    fact_check_row = cur.fetchone()
    fact_check_id = fact_check_row[0]
    created_at = fact_check_row[1]

    for source in result.get("sources", []):
        cur.execute(
            """
            INSERT INTO sources (fact_check_id, title, url)
            VALUES (%s, %s, %s);
            """,
            (
                fact_check_id,
                source.get("title"),
                source.get("url"),
            ),
        )

    conn.commit()
    cur.close()
    conn.close()

    return fact_check_id, created_at


def get_or_create_google_user(google_sub, name, email, picture_url=None):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(
        """
        SELECT id, name, email, password_hash, google_sub, picture_url, created_at
        FROM users
        WHERE google_sub = %s;
        """,
        (google_sub,),
    )
    user = cur.fetchone()

    if user:
        cur.close()
        conn.close()
        return user

    cur.execute(
        """
        SELECT id, name, email, password_hash, google_sub, picture_url, created_at
        FROM users
        WHERE email = %s;
        """,
        (email,),
    )
    user = cur.fetchone()

    if user:
        cur.execute(
            """
            UPDATE users
            SET google_sub = %s,
                picture_url = %s,
                name = %s
            WHERE id = %s
            RETURNING id, name, email, password_hash, google_sub, picture_url, created_at;
            """,
            (google_sub, picture_url, name, user["id"]),
        )
        user = cur.fetchone()
    else:
        cur.execute(
            """
            INSERT INTO users (name, email, password_hash, google_sub, picture_url)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, name, email, password_hash, google_sub, picture_url, created_at;
            """,
            (name, email, None, google_sub, picture_url),
        )
        user = cur.fetchone()

    conn.commit()
    cur.close()
    conn.close()
    return user


@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "FactLens backend is running"})


@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json() or {}

    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not name or not email or not password:
        return jsonify(
            {
                "success": False,
                "error": "Name, email, and password are required",
            }
        ), 400

    password_hash = generate_password_hash(password)

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT id FROM users WHERE email = %s;", (email,))
        existing_user = cur.fetchone()

        if existing_user:
            cur.close()
            conn.close()
            return jsonify(
                {
                    "success": False,
                    "error": "Email already registered",
                }
            ), 400

        cur.execute(
            """
            INSERT INTO users (name, email, password_hash)
            VALUES (%s, %s, %s)
            RETURNING id, name, email, picture_url, created_at;
            """,
            (name, email, password_hash),
        )

        user = cur.fetchone()
        conn.commit()

        session["user_id"] = user["id"]
        session["user_email"] = user["email"]
        session["user_name"] = user["name"]

        user["created_at"] = user["created_at"].isoformat()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "message": "Signup successful",
                "user": user,
            }
        ), 201

    except Exception as e:
        return jsonify(
            {
                "success": False,
                "error": str(e),
            }
        ), 500


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify(
            {
                "success": False,
                "error": "Email and password are required",
            }
        ), 400

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT id, name, email, password_hash, google_sub, picture_url, created_at
            FROM users
            WHERE email = %s;
            """,
            (email,),
        )
        user = cur.fetchone()

        cur.close()
        conn.close()

        if not user or not user["password_hash"] or not check_password_hash(
            user["password_hash"], password
        ):
            return jsonify(
                {
                    "success": False,
                    "error": "Invalid email or password",
                }
            ), 401

        session["user_id"] = user["id"]
        session["user_email"] = user["email"]
        session["user_name"] = user["name"]

        user["created_at"] = user["created_at"].isoformat()
        del user["password_hash"]

        return jsonify(
            {
                "success": True,
                "message": "Login successful",
                "user": user,
            }
        )

    except Exception as e:
        return jsonify(
            {
                "success": False,
                "error": str(e),
            }
        ), 500


@app.route("/auth/google", methods=["POST"])
def auth_google():
    data = request.get_json() or {}
    credential = data.get("credential", "").strip()

    if not credential:
        return jsonify(
            {
                "success": False,
                "error": "Missing Google credential",
            }
        ), 400

    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            os.getenv("GOOGLE_CLIENT_ID"),
        )

        google_sub = idinfo["sub"]
        email = idinfo.get("email")
        name = idinfo.get("name", "Google User")
        picture_url = idinfo.get("picture")

        if not email:
            return jsonify(
                {
                    "success": False,
                    "error": "Google account email not found",
                }
            ), 400

        user = get_or_create_google_user(
            google_sub=google_sub,
            name=name,
            email=email,
            picture_url=picture_url,
        )

        session["user_id"] = user["id"]
        session["user_email"] = user["email"]
        session["user_name"] = user["name"]

        if user.get("created_at"):
            user["created_at"] = user["created_at"].isoformat()

        if "password_hash" in user:
            del user["password_hash"]

        return jsonify(
            {
                "success": True,
                "message": "Login successful",
                "user": user,
            }
        )

    except Exception as e:
        return jsonify(
            {
                "success": False,
                "error": str(e),
            }
        ), 401


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify(
        {
            "success": True,
            "message": "Logged out successfully",
        }
    )


@app.route("/me", methods=["GET"])
def me():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"logged_in": False}), 401

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT id, name, email, picture_url, created_at
            FROM users
            WHERE id = %s;
            """,
            (user_id,),
        )

        user = cur.fetchone()

        cur.close()
        conn.close()

        if not user:
            session.clear()
            return jsonify({"logged_in": False}), 401

        user["created_at"] = user["created_at"].isoformat()

        return jsonify(
            {
                "logged_in": True,
                "user": user,
            }
        )

    except Exception as e:
        return jsonify(
            {
                "logged_in": False,
                "error": str(e),
            }
        ), 500


@app.route("/check", methods=["POST"])
def check_fact():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No JSON data received"}), 400

    text = data.get("text", "").strip()

    MAX_TEXT_LENGTH = 2000
    if len(text) > MAX_TEXT_LENGTH:
        return jsonify({"error": f"Text too long. Max {MAX_TEXT_LENGTH} characters allowed"}), 400

    if not text:
        return jsonify({"error": "No text provided"}), 400

    user_id = session.get("user_id")

    try:
        result = run_fact_check(text)
        fact_check_id, created_at = save_fact_check(text, result, user_id=user_id)

        result["id"] = fact_check_id
        result["claim"] = text
        result["created_at"] = created_at.isoformat() if created_at else None
        result["user_id"] = user_id

        return jsonify(result), 200

    except Exception as e:
        return jsonify(
            {
                "verdict": "Error",
                "confidence": 0.0,
                "explanation": str(e),
                "sources": [],
                "images": [],
            }
        ), 500


@app.route("/check-image", methods=["POST"])
def check_image():
    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    image_file = request.files["image"]

    if image_file.filename == "":
        return jsonify({"error": "Empty file name"}), 400

    user_id = session.get("user_id")

    try:
        image_bytes = image_file.read()
        image = Image.open(io.BytesIO(image_bytes))

        extracted_text = pytesseract.image_to_string(image).strip()

        if not extracted_text:
            return jsonify({"error": "No readable text found in image"}), 400

        result = run_fact_check(extracted_text)
        fact_check_id, created_at = save_fact_check(
            extracted_text,
            result,
            user_id=user_id,
            extracted_text=extracted_text,
        )

        result["id"] = fact_check_id
        result["claim"] = extracted_text
        result["extracted_text"] = extracted_text
        result["created_at"] = created_at.isoformat() if created_at else None
        result["user_id"] = user_id

        return jsonify(result), 200

    except Exception as e:
        return jsonify(
            {
                "verdict": "Error",
                "confidence": 0.0,
                "explanation": str(e),
                "sources": [],
                "images": [],
                "extracted_text": "",
            }
        ), 500


@app.route("/fact-checks", methods=["GET"])
def get_fact_checks():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT id, claim, verdict, confidence, explanation, extracted_text, created_at
            FROM fact_checks
            WHERE user_id = %s
            ORDER BY created_at DESC;
            """,
            (user_id,),
        )

        rows = cur.fetchall()

        cur.close()
        conn.close()

        for row in rows:
            if row["created_at"]:
                row["created_at"] = row["created_at"].isoformat()

        return jsonify(rows)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/fact-checks/<int:fact_check_id>", methods=["GET"])
def get_fact_check_detail(fact_check_id):
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT id, user_id, claim, verdict, confidence, explanation, extracted_text, created_at
            FROM fact_checks
            WHERE id = %s AND user_id = %s;
            """,
            (fact_check_id, user_id),
        )

        fact_check = cur.fetchone()

        if not fact_check:
            cur.close()
            conn.close()
            return jsonify({"error": "Fact check not found"}), 404

        cur.execute(
            """
            SELECT id, fact_check_id, title, url
            FROM sources
            WHERE fact_check_id = %s
            ORDER BY id ASC;
            """,
            (fact_check_id,),
        )

        sources = cur.fetchall()

        cur.close()
        conn.close()

        if fact_check["created_at"]:
            fact_check["created_at"] = fact_check["created_at"].isoformat()

        fact_check["sources"] = sources

        return jsonify(fact_check)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)