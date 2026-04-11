from flask import Flask, request, jsonify
from flask_cors import CORS
from fact_checker import run_fact_check

from PIL import Image
import pytesseract
import io

app = Flask(__name__)
CORS(app)

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


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

    try:
        result = run_fact_check(text)
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

    try:
        image_bytes = image_file.read()
        image = Image.open(io.BytesIO(image_bytes))

        extracted_text = pytesseract.image_to_string(image).strip()

        if not extracted_text:
            return jsonify({"error": "No readable text found in image"}), 400

        result = run_fact_check(extracted_text)
        result["extracted_text"] = extracted_text

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


if __name__ == "__main__":
    app.run(debug=True, port=5000)