#include <WiFi.h>
#include <HTTPClient.h>
#include <math.h>

// ================= WIFI =================
#define WIFI_SSID     "Boat"
#define WIFI_PASSWORD "klahan2546*"

// ================= SERVER =================
const char* serverUrl = "http://10.122.218.249:5000/update";

// -------- PIN CONFIG --------
#define IR_A  1
#define IR_B  2

// -------- THRESHOLD --------
#define THRESHOLD_A 60
#define THRESHOLD_B 60
#define DEAD_BAND   5
#define TIMEOUT     3000

// -------- FILTER CONFIG --------
#define AVG_SAMPLES 5

// -------- VARIABLES --------
int peopleCount = 0;
int lastSentCount = -1;

// pending queue
int pendingA = 0;
int pendingB = 0;

// time stamp
unsigned long timeA = 0;
unsigned long timeB = 0;

// filter
float bufA[AVG_SAMPLES];
float bufB[AVG_SAMPLES];
int idx = 0;
bool bufferFilled = false;

// edge detect
bool prevBlockA = false;
bool prevBlockB = false;

// -------- FreeRTOS Send Task --------
TaskHandle_t sendTaskHandle = NULL;
volatile bool needSend = false;
volatile int sendValue = 0;

// --------------------------------------------------

void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting WiFi");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nConnected!");
  Serial.println(WiFi.localIP());
}

// --------------------------------------------------
// 🔥 HTTP Task (วิ่งอีก Core ไม่บล็อก loop)

void sendTask(void *parameter) {

  for (;;) {

    if (needSend) {

      if (WiFi.status() == WL_CONNECTED) {

        HTTPClient http;
        http.begin(serverUrl);
        http.addHeader("Content-Type", "application/json");
        http.setTimeout(500);

        String payload = "{\"people\":" + String(sendValue) + "}";

        int code = http.POST(payload);

        Serial.print("HTTP Code: ");
        Serial.println(code);

        http.end();
      }

      needSend = false;
    }

    vTaskDelay(10 / portTICK_PERIOD_MS);
  }
}

// --------------------------------------------------

float convertToDistance(int raw) {
  if (raw < 1) raw = 1;

  float voltage = (raw / 4095.0) * 3.3;
  float d = 60.0 * pow(voltage, -1.10);

  if (d < 5) d = 5;
  if (d > 150) d = 150;

  return d;
}

float movingAverage(float *buf) {
  float sum = 0;
  for (int i = 0; i < AVG_SAMPLES; i++) sum += buf[i];
  return sum / AVG_SAMPLES;
}

bool isBlocked(float d, float th) {
  return d < (th - DEAD_BAND);
}

// --------------------------------------------------

void setup() {

  Serial.begin(115200);

  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  for (int i = 0; i < AVG_SAMPLES; i++) {
    bufA[i] = 150;
    bufB[i] = 150;
  }

  connectWiFi();

  // 🔥 สร้าง Task บน Core 0
  xTaskCreatePinnedToCore(
    sendTask,
    "SendTask",
    5000,
    NULL,
    1,
    &sendTaskHandle,
    0
  );
}

// --------------------------------------------------

void loop() {

  // ---- read ----
  float distA = convertToDistance(analogRead(IR_A));
  float distB = convertToDistance(analogRead(IR_B));

  bufA[idx] = distA;
  bufB[idx] = distB;
  idx++;

  if (idx >= AVG_SAMPLES) {
    idx = 0;
    bufferFilled = true;
  }

  if (!bufferFilled) return;

  float avgA = movingAverage(bufA);
  float avgB = movingAverage(bufB);

  bool blockA = isBlocked(avgA, THRESHOLD_A);
  bool blockB = isBlocked(avgB, THRESHOLD_B);

  // ---- EVENT DETECT ----
  if (blockA && !prevBlockA) {
    pendingA++;
    timeA = millis();
  }

  if (blockB && !prevBlockB) {
    pendingB++;
    timeB = millis();
  }

  prevBlockA = blockA;
  prevBlockB = blockB;

  // ---- MATCH EVENTS ----
  while (pendingA > 0 && pendingB > 0) {

    if (timeA < timeB) {
      peopleCount++;
    } else {
      peopleCount--;
      if (peopleCount < 0) peopleCount = 0;
    }

    pendingA--;
    pendingB--;
  }

  // ---- TIMEOUT CLEAN ----
  if (pendingA > 0 && millis() - timeA > TIMEOUT) pendingA = 0;
  if (pendingB > 0 && millis() - timeB > TIMEOUT) pendingB = 0;

  // ---- SEND WHEN CHANGED (ไม่บล็อกแล้ว) ----
  if (peopleCount != lastSentCount) {
    sendValue = peopleCount;
    needSend = true;
    lastSentCount = peopleCount;
  }

  // ---- DEBUG ----
  Serial.print("A=");
  Serial.print(avgA);
  Serial.print(" B=");
  Serial.print(avgB);
  Serial.print(" | People=");
  Serial.println(peopleCount);

  delay(100);
}