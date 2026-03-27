from flask import Flask, Response, jsonify
import cv2
import numpy as np
import time
import threading
import requests
from picamera2 import Picamera2

# ===============================
# CONFIG
# ===============================
FRAME_WIDTH = 700 
ZONE_LEFT_RATIO  = 0.45
ZONE_RIGHT_RATIO = 0.55
TRACK_TIMEOUT = 4
MAX_TRACK_DIST = 200
MIN_AREA_RATIO = 0.03

SERVER_URL = "http://10.122.218.249:8000/update"
SEND_INTERVAL = 1

# ===============================
# GLOBAL VARIABLES & LOCK
# ===============================
countIn = 0
countOut = 0
current_frame = None  # สำหรับเก็บเฟรมล่าสุดเพื่อส่งให้ Flask
data_lock = threading.Lock()
frame_lock = threading.Lock() # Lock สำหรับแชร์เฟรม

# Tracking state
tracks, trackLife, lastSide, inZone, counted = [], [], [], [], []

# ===============================
# INIT PICAMERA2 & MOG2
# ===============================
picam2 = Picamera2()
#config = picam2.create_video_configuration(
#    main={"size": (640, 480), "format": "RGB888"},
#    controls={"FrameRate": 30}
#)

config = picam2.create_video_configuration(
    main={"size": (320, 240), "format": "RGB888"}, # ลดขนาดลงเพื่อเช็คว่าหายไหม
    controls={"FrameRate": 20}
)
picam2.configure(config)
picam2.start()

fgbg = cv2.createBackgroundSubtractorMOG2(history=4000, varThreshold=100, detectShadows=False)
app = Flask(__name__)

# ===============================
# HELPERS
# ===============================
def center_of(rect):
    x, y, w, h = rect
    return int(x + w/2), int(y + h/2)

def distance(r1, r2):
    c1, c2 = center_of(r1), center_of(r2)
    return np.linalg.norm(np.array(c1) - np.array(c2))

def resize_keep_ratio(frame, width):
    h, w = frame.shape[:2]
    return cv2.resize(frame, (width, int(h * (width / w))))

# ===============================
# MAIN PROCESSING LOOP (รันตลอดเวลา)
# ===============================
def process_camera_loop():
    global countIn, countOut, current_frame, tracks, trackLife, lastSide, inZone, counted
    
    while True:
        # 1. Capture & Pre-process
        raw_frame = picam2.capture_array("main")
        frame = cv2.cvtColor(raw_frame, cv2.COLOR_RGB2BGR)
        frame = resize_keep_ratio(frame, FRAME_WIDTH)
        h, w = frame.shape[:2]
        zoneL, zoneR = int(w * ZONE_LEFT_RATIO), int(w * ZONE_RIGHT_RATIO)

        # 2. Image Processing (MOG2)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fgmask = fgbg.apply(cv2.GaussianBlur(gray, (9, 9), 0))
        _, fgmask = cv2.threshold(fgmask, 200, 255, cv2.THRESH_BINARY)
        fgmask = cv2.erode(fgmask, None, iterations=2)
        fgmask = cv2.dilate(fgmask, None, iterations=2)

        cnts, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        active_rects = [cv2.boundingRect(c) for c in cnts if cv2.contourArea(c) > (w * h * MIN_AREA_RATIO)]

        # 3. Tracking & Counting
        for rect in active_rects:
            cx, cy = center_of(rect)
            matchIdx = -1
            minDist = 9999

            for i in range(len(tracks)):
                d = distance(tracks[i][-1], rect)
                if d < minDist and d < MAX_TRACK_DIST:
                    minDist = d
                    matchIdx = i

            if matchIdx == -1:
                tracks.append([rect])
                trackLife.append(TRACK_TIMEOUT)
                lastSide.append(0 if cx < zoneL else 1)
                inZone.append(False)
                counted.append(False)
            else:
                tracks[matchIdx].append(rect)
                trackLife[matchIdx] = TRACK_TIMEOUT
                if zoneL <= cx <= zoneR:
                    inZone[matchIdx] = True

                if inZone[matchIdx] and not counted[matchIdx]:
                    with data_lock:
                        if lastSide[matchIdx] == 1 and cx < zoneL:
                            countIn += 1
                            counted[matchIdx] = True
                        elif lastSide[matchIdx] == 0 and cx > zoneR:
                            countOut += 1
                            counted[matchIdx] = True

        # Cleanup Tracks
        idx = 0
        while idx < len(trackLife):
            trackLife[idx] -= 1
            if trackLife[idx] <= 0:
                for lst in [tracks, trackLife, lastSide, inZone, counted]: lst.pop(idx)
            else: idx += 1

        # 4. Drawing
        cv2.line(frame, (zoneL, 0), (zoneL, h), (255, 0, 0), 2)
        cv2.line(frame, (zoneR, 0), (zoneR, h), (0, 0, 255), 2)
        for rect in active_rects:
            rx, ry, rw, rh = rect
            cv2.rectangle(frame, (rx, ry), (rx+rw, ry+rh), (0, 255, 255), 2)
        cv2.putText(frame, f"IN: {countIn} OUT: {countOut}", (10, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # 5. Update Global Frame (สำหรับส่งให้ Flask)
        with frame_lock:
            ret, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            current_frame = buffer.tobytes()

# ===============================
# SEND DATA LOOP
# ===============================
def send_data_loop():
    global countIn, countOut
    while True:
        try:
            with data_lock:
                current_p = max(0, countIn - countOut)
                payload = {
                    "current_people": current_p,
                    "lat": 13.7563,
                    "lon": 100.5018
                }
            requests.post(SERVER_URL, json=payload, timeout=0.8)
        except:
            pass
        time.sleep(SEND_INTERVAL)

# ===============================
# FLASK ROUTES
# ===============================
def gen_frames():
    while True:
        with frame_lock:
            if current_frame is None:
                continue
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + current_frame + b"\r\n")
        time.sleep(0.03) # กัน Loop ทำงานหนักเกินไป

@app.route("/video")
def video():
    return Response(gen_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/status")
def status():
    with data_lock:
        return jsonify({"in": countIn, "out": countOut})

if __name__ == "__main__":
    # เริ่มต้น Thread ประมวลผลภาพ (ตัวหลัก)
    threading.Thread(target=process_camera_loop, daemon=True).start()
    # เริ่มต้น Thread ส่งข้อมูลไป Server
    threading.Thread(target=send_data_loop, daemon=True).start()
    
    # รัน Flask
    app.run(host="0.0.0.0", port=5000, threaded=True)
