import cv2
from ultralytics import YOLO
import threading
import time
import torch


# =============================
# 1. Video Stream Thread
# =============================
class VideoStream:
    def __init__(self, url):
        self.cap = cv2.VideoCapture(url)
        self.ret, self.frame = self.cap.read()
        self.stopped = False
        threading.Thread(target=self.update, daemon=True).start()

    def update(self):
        while not self.stopped:
            if not self.cap.isOpened():
                self.stopped = True
                break

            ret, frame = self.cap.read()
            if ret:
                self.frame = frame
            else:
                self.stopped = True

    def read(self):
        return self.frame

    def stop(self):
        self.stopped = True
        self.cap.release()


# =============================
# 2. Passenger Counter YOLO
# =============================
class PassengerCounterYOLO:
    def __init__(self, stream_url, output_path="counting_result.mp4"):
        print("🚀 โหลด YOLO Model...")
        self.model = YOLO("yolov8n.pt")

        print(f"🔗 เชื่อมต่อ Stream: {stream_url}")
        self.vs = VideoStream(stream_url)
        time.sleep(2)

        frame = self.vs.read()
        if frame is None:
            raise RuntimeError("❌ ดึงภาพจาก Stream ไม่ได้")

        self.h, self.w = frame.shape[:2]

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.out = cv2.VideoWriter(
            output_path,
            fourcc,
            20.0,
            (self.w, self.h)
        )

        # =============================
        # Counter Variables
        # =============================
        self.in_count = 0
        self.out_count = 0
        self.current_passengers = 0

        self.track_state = {}
        self.counted_ids = set()

        # =============================
        # Single Count Line
        # =============================
        self.line_center = int(self.w * 0.5)
        self.buffer = 30

    def process(self):
        cv2.namedWindow("AI Passenger Counter", cv2.WINDOW_NORMAL)

        device = "0" if torch.cuda.is_available() else "cpu"
        print(f"✅ ใช้อุปกรณ์: {device}")

        while not self.vs.stopped:
            frame = self.vs.read()
            if frame is None:
                continue

            results = self.model.track(
                frame,
                persist=True,
                classes=[0],
                imgsz=320,
                device=device,
                verbose=False
            )

            if results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                ids = results[0].boxes.id.cpu().numpy().astype(int)

                for box, obj_id in zip(boxes, ids):
                    x1, y1, x2, y2 = box
                    cx = int((x1 + x2) / 2)

                    if cx > self.line_center + self.buffer:
                        zone = "OUTSIDE"
                    elif cx < self.line_center - self.buffer:
                        zone = "INSIDE"
                    else:
                        zone = None

                    if obj_id not in self.track_state:
                        if zone:
                            self.track_state[obj_id] = zone
                    else:
                        if obj_id not in self.counted_ids:
                            # ---------- IN ----------
                            if (
                                self.track_state[obj_id] == "OUTSIDE"
                                and zone == "INSIDE"
                            ):
                                self.in_count += 1
                                self.current_passengers += 1
                                self.counted_ids.add(obj_id)
                                print(f"➕ เข้า | บนรถ: {self.current_passengers}")

                            # ---------- OUT ----------
                            elif (
                                self.track_state[obj_id] == "INSIDE"
                                and zone == "OUTSIDE"
                            ):
                                self.out_count += 1
                                self.current_passengers = max(
                                    0, self.current_passengers - 1
                                )
                                self.counted_ids.add(obj_id)
                                print(f"➖ ออก | บนรถ: {self.current_passengers}")

                    color = (
                        (0, 255, 0)
                        if obj_id in self.counted_ids
                        else (255, 150, 0)
                    )

                    cv2.rectangle(
                        frame,
                        (int(x1), int(y1)),
                        (int(x2), int(y2)),
                        color,
                        2
                    )

            # =============================
            # Draw Count Line
            # =============================
            cv2.line(
                frame,
                (self.line_center, 0),
                (self.line_center, self.h),
                (255, 255, 255),
                2
            )

            cv2.putText(
                frame,
                f"ON BUS: {self.current_passengers}",
                (20, 120),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 255),
                3
            )

            cv2.imshow("AI Passenger Counter", frame)
            self.out.write(frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        self.vs.stop()
        self.out.release()
        cv2.destroyAllWindows()
        print("✅ ปิดระบบเรียบร้อย")


# =============================
# Main
# =============================
if __name__ == "__main__":
    URL = "http://192.168.3.16:5000/video_feed"
    PassengerCounterYOLO(URL).process()