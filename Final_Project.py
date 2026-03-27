import serial
import time
import threading
import requests
import cv2
import numpy as np
from flask import Flask, Response, jsonify
from picamera2 import Picamera2

# ===============================
# CONFIG & GPS SETUP
# ===============================
FRAME_WIDTH = 700
ZONE_LEFT_RATIO = 0.55
ZONE_RIGHT_RATIO = 0.65
TRACK_TIMEOUT = 4
MAX_TRACK_DIST = 100
MIN_AREA_RATIO = 0.01

SERVER_URL = "http://10.122.218.249:8000/update"
SEND_INTERVAL = 1 

# --- เพิ่มการตั้งค่า GPS ---
try:
    ser_gps = serial.Serial("/dev/serial0", baudrate=9600, timeout=2)
    print("GPS Serial connected.")
except Exception as e:
    print(f"GPS Error: {e}")
    ser_gps = None

# ===============================
# GLOBAL VARIABLES
# ===============================
countIn = 0
countOut = 0
current_lat = 0.0
current_lon = 0.0
data_lock = threading.Lock()

tracks, trackLife, lastSide, inZone, counted = [], [], [], [], []

# ===============================
# GPS HELPER FUNCTION
# ===============================
def parse_gps(line):
    """แปลง NMEA $GPRMC เป็น Decimal Degrees"""
    try:
        if line.startswith('$GPRMC'):
            parts = line.split(',')
            if parts[2] == 'A':  # Status Active
                # แปลง Latitude
                lat_raw = parts[3]
                lat_dir = parts[4]
                lat_deg = float(lat_raw[:2]) + (float(lat_raw[2:]) / 60)
                if lat_dir == 'S': lat_deg = -lat_deg
                
                # แปลง Longitude
                lon_raw = parts[5]
                lon_dir = parts[6]
                lon_deg = float(lon_raw[:3]) + (float(lon_raw[3:]) / 60)
                if lon_dir == 'W': lon_deg = -lon_deg
                
                return round(lat_deg, 6), round(lon_deg, 6)
    except:
        pass
    return None, None

# ===============================
# SEND DATA + GPS LOOP
# ===============================
def send_data_loop():
    global countIn, countOut, current_lat, current_lon

    while True:
        # 1. อ่านค่าจาก GPS ก่อนส่ง
        if ser_gps:
            try:
                # อ่าน buffer ที่ค้างอยู่ออกให้หมดเพื่อให้ได้ค่าล่าสุดจริงๆ
                while ser_gps.in_waiting:
                    line = ser_gps.readline().decode('utf-8', errors='replace').strip()
                    lat, lon = parse_gps(line)
                    if lat and lon:
                        with data_lock:
                            current_lat, current_lon = lat, lon
            except Exception as e:
                print(f"GPS Read Error: {e}")

        # 2. ส่งข้อมูลไปยัง Server
        try:
            with data_lock:
                data = {
                    "in": countIn,
                    "out": countOut,
                    "current_people": max(0, countIn - countOut),
                    "lat": current_lat,
                    "lon": current_lon,
                    "timestamp": time.time()
                }

            requests.post(SERVER_URL, json=data, timeout=1)
            print(f"Sent -> IN:{data['in']} OUT:{data['out']} | Pos:{data['lat']},{data['lon']}")

        except Exception as e:
            print(f"Network Error: {e}")

        time.sleep(SEND_INTERVAL)

# ===============================
# PICAMERA2 & CV (ส่วนเดิม)
# ===============================
picam2 = Picamera2()
config = picam2.create_video_configuration(main={"size": (640, 480), "format": "RGB888"})
picam2.configure(config)
picam2.start()

fgbg = cv2.createBackgroundSubtractorMOG2(history=4000, varThreshold=50, detectShadows=False)
app = Flask(__name__)

def center_of(rect):
    x, y, w, h = rect
    return int(x + w/2), int(y + h/2)

def distance(r1, r2):
    c1, c2 = center_of(r1), center_of(r2)
    return np.linalg.norm(np.array(c1) - np.array(c2))

def resize_keep_ratio(frame, width):
    h, w = frame.shape[:2]
    return cv2.resize(frame, (width, int(h * (width / w))))

def gen_frames():
    global countIn, countOut
    while True:
        frame_raw = picam2.capture_array("main")
        frame = cv2.cvtColor(frame_raw, cv2.COLOR_RGB2BGR)
        frame = resize_keep_ratio(frame, FRAME_WIDTH)
        h, w = frame.shape[:2]
        zoneL, zoneR = int(w * ZONE_LEFT_RATIO), int(w * ZONE_RIGHT_RATIO)

        # Process Image
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fgmask = fgbg.apply(cv2.GaussianBlur(gray, (9, 9), 0))
        _, fgmask = cv2.threshold(fgmask, 200, 255, cv2.THRESH_BINARY)
        cnts, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        active_rects = [cv2.boundingRect(c) for c in cnts if cv2.contourArea(c) > (w * h * MIN_AREA_RATIO)]

        # Tracking Logic
        for rect in active_rects:
            cx, cy = center_of(rect)
            matchIdx = -1
            for i in range(len(tracks)):
                if distance(tracks[i][-1], rect) < MAX_TRACK_DIST:
                    matchIdx = i; break

            if matchIdx == -1:
                tracks.append([rect]); trackLife.append(TRACK_TIMEOUT)
                lastSide.append(0 if cx < zoneL else 1); inZone.append(False); counted.append(False)
            else:
                tracks[matchIdx].append(rect); trackLife[matchIdx] = TRACK_TIMEOUT
                if zoneL <= cx <= zoneR: inZone[matchIdx] = True
                if inZone[matchIdx] and not counted[matchIdx]:
                    with data_lock:
                        if lastSide[matchIdx] == 1 and cx < zoneL: countIn += 1; counted[matchIdx] = True
                        elif lastSide[matchIdx] == 0 and cx > zoneR: countOut += 1; counted[matchIdx] = True

        # Cleanup Tracks
        i = 0
        while i < len(trackLife):
            trackLife[i] -= 1
            if trackLife[i] <= 0:
                for lst in [tracks, trackLife, lastSide, inZone, counted]: lst.pop(i)
            else: i += 1

        # Drawing
        cv2.line(frame, (zoneL, 0), (zoneL, h), (255, 0, 0), 2)
        cv2.line(frame, (zoneR, 0), (zoneR, h), (0, 0, 255), 2)
        cv2.putText(frame, f"IN: {countIn} OUT: {countOut} | GPS: {current_lat},{current_lon}", 
                    (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        ret, buffer = cv2.imencode(".jpg", frame)
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")

@app.route("/video")
def video():
    return Response(gen_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    threading.Thread(target=send_data_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
