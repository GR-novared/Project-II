from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

import os
import io
import threading
import numpy as np
from PIL import Image

# YOLO
from ultralytics import YOLO

# ===== Firebase Init =====
cred = credentials.Certificate("firebase.json")
firebase_admin.initialize_app(cred)

db = firestore.client()

# ===== Flask =====
app = Flask(__name__)

# ===== CONFIG =====
SAVE_DIR = "received2_images"
os.makedirs(SAVE_DIR, exist_ok=True)

model = YOLO("yolov8l.pt")  # แนะนำ n เร็วกว่า

image_buffer = {}
buffer_lock = threading.Lock()


# =========================================================
# 🚍 1. ROUTE สำหรับ "รถบัสส่งจำนวนคนมาเอง"
# =========================================================
@app.route('/update', methods=['POST'])
def update():

    data = request.json
    people_count = data.get("people")

    print("🚌 Bus sent:", people_count)

    try:
        doc_ref = db.collection("buses").document("ESP32_bus1")

        doc_ref.set({
            "people_count": people_count,
            "timestamp": datetime.utcnow(),
            "source": "bus_sensor"
        }, merge=True)

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)}), 400


# =========================================================
# 📸 2. ROUTE สำหรับ "กล้อง 2 ตัว → YOLO"
# =========================================================
@app.route('/upload', methods=['POST'])
def upload():

    if request.content_type != "image/jpeg":
        return jsonify({"error": "Invalid content type"}), 400

    cam_id = request.headers.get("X-Cam-ID")
    if cam_id not in ["cam1", "cam2"]:
        return jsonify({"error": "Missing or invalid X-Cam-ID"}), 400

    image_bytes = request.data
    if not image_bytes:
        return jsonify({"error": "No image data"}), 400

    with buffer_lock:
        image_buffer[cam_id] = image_bytes

        if "cam1" not in image_buffer or "cam2" not in image_buffer:
            return jsonify({"status": "waiting", "received": cam_id}), 200

        # ===== รวมภาพ =====
        img1 = Image.open(io.BytesIO(image_buffer["cam1"]))
        img2 = Image.open(io.BytesIO(image_buffer["cam2"]))

        h = min(img1.height, img2.height)
        img1 = img1.resize((img1.width, h))
        img2 = img2.resize((img2.width, h))

        merged_img = Image.new("RGB", (img1.width + img2.width, h))
        merged_img.paste(img1, (0, 0))
        merged_img.paste(img2, (img1.width, 0))

        # ===== YOLO =====
        img_np = np.array(merged_img)
        results = model(img_np)

        person_count = 0
        for r in results:
            for box in r.boxes:
                if int(box.cls[0]) == 0:  # person
                    person_count += 1

        print("📸 Camera detected:", person_count)

        # ===== SAVE =====
        filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
        filepath = os.path.join(SAVE_DIR, filename)
        merged_img.save(filepath, "JPEG", quality=90)

        # ===== FIRESTORE =====
        try:
            doc_ref = db.collection("bus_stops").document("esp32_cam_1")

            doc_ref.set({
                "people_count": person_count,
                "timestamp": datetime.utcnow(),
                "image": filename,
                "source": "camera_ai"
            }, merge=True)

            print("🔥 Updated from camera")

        except Exception as e:
            print("Firestore Error:", e)

        image_buffer.clear()

    return jsonify({
        "status": "ok",
        "people": person_count,
        "filename": filename
    }), 200


# ===== RUN =====
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)