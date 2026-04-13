# libraries
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from fact_checker import run_fact_check

from PIL import Image
import pytesseract
import io
import os
from datetime import datetime

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret")

CORS(
    app,
    supports_credentials=True,
    origins=["http://127.0.0.1:5173", "http://localhost:5173"]
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# -----------------------------
# Temporary in-memory storage
# -----------------------------
USERS = {}
FACT_CHECKS = []
NEXT_CHECK_ID = 1


def serialize_check(row):
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "claim": row["claim"],
        "verdict": row["verdict"],
        "confidence": row["confidence"],
        "explanation": row["explanation"],
        "extracted_text": row["extracted_text"],
        "created_at": row["created_at"],
        "sources": row["sources"],
    }


def save_fact_check(claim, result, user_id=None, extracted_text=None):
    global NEXT_CHECK_ID

    row = {
        "id": NEXT_CHECK_ID,
        "user_id": user_id,
        "claim": claim,
        "verdict": result.get("verdict"),
        "confidence": result.get("confidence", 0.0),
        "explanation": result.get("explanation", ""),
        "extracted_text": extracted_text,
        "created_at": datetime.now().isoformat(),
        "sources": result.get("sources", []),
    }

    FACT_CHECKS.append(row)
    NEXT_CHECK_ID += 1
    return row["id"], row["created_at"]


@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "FactLens backend is running"})


@app.route("/check", methods=["POST"])
def check_fact():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No JSON data received"}), 400

    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "No text provided"}), 400

    user_id = session.get("user_id")

    try:
        result = run_fact_check(text)
        fact_check_id, created_at = save_fact_check(text, result, user_id=user_id)

        result["id"] = fact_check_id
        result["claim"] = text
        result["created_at"] = created_at
        result["user_id"] = user_id

        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            "verdict": "Error",
            "confidence": 0.0,
            "explanation": str(e),
            "sources": [],
            "images": []
        }), 500


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
            extracted_text=extracted_text
        )

        result["id"] = fact_check_id
        result["claim"] = extracted_text
        result["extracted_text"] = extracted_text
        result["created_at"] = created_at
        result["user_id"] = user_id

        return jsonify(result), 200

    except Exception as e:
        return jsonify({
            "verdict": "Error",
            "confidence": 0.0,
            "explanation": str(e),
            "sources": [],
            "images": [],
            "extracted_text": ""
        }), 500


@app.route("/fact-checks", methods=["GET"])
def get_fact_checks():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    user_checks = [
        {
            "id": row["id"],
            "claim": row["claim"],
            "verdict": row["verdict"],
            "confidence": row["confidence"],
            "explanation": row["explanation"],
            "extracted_text": row["extracted_text"],
            "created_at": row["created_at"],
        }
        for row in reversed(FACT_CHECKS)
        if row["user_id"] == user_id
    ]

    return jsonify(user_checks), 200


@app.route("/fact-checks/<int:check_id>", methods=["GET"])
def get_fact_check_detail(check_id):
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    for row in FACT_CHECKS:
        if row["id"] == check_id and row["user_id"] == user_id:
            return jsonify(serialize_check(row)), 200

    return jsonify({"error": "Fact check not found"}), 404


@app.route("/me", methods=["GET"])
def me():
    user_id = session.get("user_id")

    if not user_id or user_id not in USERS:
        return jsonify({"logged_in": False}), 401

    return jsonify({
        "logged_in": True,
        "user": USERS[user_id]
    }), 200


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/auth/google", methods=["POST"])
def auth_google():
    data = request.get_json() or {}
    credential = data.get("credential", "").strip()

    if not credential:
        return jsonify({
            "success": False,
            "error": "Missing Google credential"
        }), 400

    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            os.getenv("GOOGLE_CLIENT_ID")
        )

        google_sub = idinfo["sub"]
        email = idinfo.get("email")
        name = idinfo.get("name", "Google User")
        picture_url = idinfo.get("picture")

        if not email:
            return jsonify({
                "success": False,
                "error": "Google account email not found"
            }), 400

        user = {
            "id": google_sub,
            "name": name,
            "email": email,
            "picture_url": picture_url,
            "created_at": datetime.now().isoformat()
        }

        USERS[google_sub] = user

        session["user_id"] = google_sub
        session["user_email"] = email
        session["user_name"] = name

        return jsonify({
            "success": True,
            "message": "Login successful",
            "user": user
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 401


if __name__ == "__main__":
    app.run(debug=True, port=5000)