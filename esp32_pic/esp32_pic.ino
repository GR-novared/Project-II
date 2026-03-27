#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>

// ================= CAMERA MODEL =================
#define CAMERA_MODEL_AI_THINKER
#include "camera_pins.h"

// ================= CONFIG =================
#define CAM_ID "cam2"   // 👈 อีกตัวใช้ cam1

// ================= WIFI =================
#define WIFI_SSID     "Boat"
#define WIFI_PASSWORD "klahan2546*"

// ================= SERVER =================
const char* serverUrl = "http://10.122.218.249:5000/upload";

// =================================================

void connectWiFi();
void captureAndUpload();

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n🚀 ESP32-CAM AI Thinker | OV2640");

  // ================= CAMERA CONFIG =================
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;

  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;

  config.pin_xclk  = XCLK_GPIO_NUM;
  config.pin_pclk  = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href  = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn  = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  // 🔥 ค่าที่ ESP32-CAM รับไหวจริง
  config.frame_size   = FRAMESIZE_UXGA;   // แนะนำ VGA / SVGA
  config.jpeg_quality = 12;              // 10–15 กำลังดี
  config.fb_count     = 1;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("❌ Camera init failed: 0x%x\n", err);
    while (true);
  }

  Serial.println("📷 Camera INIT OK");

  // ================= SENSOR CONFIG =================
  sensor_t *s = esp_camera_sensor_get();
  s->set_framesize(s, FRAMESIZE_VGA);
  s->set_quality(s, 12);

  s->set_hmirror(s, 0);
  s->set_vflip(s, 0);

  Serial.println("🛠 Sensor configured");

  connectWiFi();
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    captureAndUpload();
  } else {
    connectWiFi();
  }
  delay(2000);   // ปรับถี่ได้ แต่ ESP32-CAM อย่าถี่เกิน
}

// =================================================

void connectWiFi() {
  Serial.println("\n📡 Connecting WiFi...");
  WiFi.disconnect(true);
  delay(300);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\n✅ WiFi Connected");
  Serial.println(WiFi.localIP());
}

void captureAndUpload() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("❌ Capture failed");
    return;
  }

  Serial.printf("📸 [%s] %dx%d | %d bytes\n",
                CAM_ID, fb->width, fb->height, fb->len);

  WiFiClient client;
  HTTPClient http;

  http.begin(client, serverUrl);
  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("X-Cam-ID", CAM_ID);
  http.addHeader("X-Frame-ID", String(millis()));

  int code = http.POST(fb->buf, fb->len);
  Serial.printf("🌐 HTTP Response: %d\n", code);

  http.end();
  esp_camera_fb_return(fb);
}
