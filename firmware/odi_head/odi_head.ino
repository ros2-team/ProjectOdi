// Arduino Uno: calibrated pan/tilt motion, optional passive buzzer.
// Pins and motion limits calibrated on Odi; upload moves the head to 84/65.
// Protocol at 115200: P -> S enabled pan tilt busy
// M sequence pan tilt beepCount -> D sequence after commanded motion + settle.
// D is commanded completion, NOT encoder feedback (ordinary servos have none).
#include <Servo.h>
#include <Wire.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

const bool ENABLE_SERVOS = true;
const int PAN_PIN = 10;       // Left/right (pan): confirmed Uno pin.
const int TILT_PIN = 9;       // Up/down (tilt): confirmed Uno pin.
const int BUZZER_PIN = 8;     // Passive buzzer.
const int PAN_MIN = 40, PAN_MAX = 140, PAN_HOME = 84;
const int TILT_MIN = 0, TILT_MAX = 100, TILT_HOME = 65;
Servo panServo, tiltServo;
bool enabled = false, active = false;
int panAngle = PAN_HOME, tiltAngle = TILT_HOME;
int targetPan = PAN_HOME, targetTilt = TILT_HOME;
unsigned long sequence = 0, lastContact = 0, lastStep = 0, settledAt = 0;
unsigned long beepAt = 0;
int beeps = 0;
bool sounding = false;
char input[80];
byte used = 0;
bool overflowed = false;

// Uno SDA=A4 (18), SCL=A5 (19). Library auto-detects backpack pin mapping.
hd44780_I2Cexp lcd(0x27);
bool lcdReady = false;
int face = 0, drawnFace = -1;
unsigned long faceAt = 0;
const char* const faces[] = {"    ( ^_^ )", "    ( -_- )", "    ( o_o )",
  "    ( O_O )", "    ( ^o^ )", "    ( ._. )", "    ( x_x )", "    ( o_o )"};
const char* const labels[] = {"ODI READY", "RESTING", "WALKING", "LOOKING AT YOU",
  "HELLO! BEEP BEEP", "STOPPING", "LINK LOST", "EXPLORING"};

void drawFace() {
  if (!lcdReady || drawnFace == face) return;
  // Pad each row instead of clear() to avoid flashing the whole screen.
  for (byte row = 0; row < 2; ++row) {
    const char* text = row == 0 ? faces[face] : labels[face];
    if (lcd.setCursor(0, row) != 0) {
      lcdReady = false; Serial.println("E lcd_io"); return;
    }
    byte length = strlen(text);
    for (byte col = 0; col < 16; ++col) {
      if (lcd.write(col < length ? text[col] : ' ') != 1) {
        lcdReady = false; Serial.println("E lcd_io"); return;
      }
    }
  }
  drawnFace = face;
}

void state() {
  Serial.print("S "); Serial.print(enabled ? 1 : 0);
  Serial.print(' '); Serial.print(panAngle);
  Serial.print(' '); Serial.print(tiltAngle);
  Serial.print(' '); Serial.println(active ? 1 : 0);
}
void home() {
  targetPan = PAN_HOME; targetTilt = TILT_HOME;
  active = true; sequence = 0; settledAt = 0;
  beeps = 0; sounding = false;
  if (BUZZER_PIN >= 0) noTone(BUZZER_PIN);
}
void command() {
  if (input[0] == 'L') {
    int requested; char tail;
    if (sscanf(input, "L %d %c", &requested, &tail) != 1 || requested < 0 || requested > 7) {
      Serial.println("E lcd_invalid"); return;
    }
    face = requested; faceAt = millis();
    Serial.println(lcdReady ? "L OK" : "L unavailable");
    return; // Display updates must never keep motion watchdog alive.
  }
  if (strcmp(input, "H") == 0) { home(); face = 0; faceAt = millis(); return; }
  if (strcmp(input, "P") == 0) {
    lastContact = millis(); state(); return;
  }
  unsigned long seq;
  int p, t, b;
  char extra;
  if (sscanf(input, "M %lu %d %d %d %c", &seq, &p, &t, &b, &extra) != 4 ||
      !enabled || p < PAN_MIN || p > PAN_MAX || t < TILT_MIN ||
      t > TILT_MAX || b < 0 || b > 3) {
    Serial.println("E invalid"); return;
  }
  lastContact = millis();
  sequence = seq; targetPan = p; targetTilt = t;
  active = true; settledAt = 0;
  beeps = BUZZER_PIN >= 0 ? b : 0; beepAt = millis();
}
void setup() {
  Serial.begin(115200);
  Serial.println("BOOT");
  Wire.begin();
  // Arduino AVR Boards 1.8.6: bound I2C bus faults as well as normal writes.
  Wire.setWireTimeout(3000, true);
  lcdReady = lcd.begin(16, 2) == 0;
  if (!lcdReady) Serial.println("E lcd_init");
  drawFace();
  enabled = ENABLE_SERVOS && PAN_PIN >= 2 && PAN_PIN <= 19 &&
    TILT_PIN >= 2 && TILT_PIN <= 17 && PAN_PIN <= 17 && PAN_PIN != TILT_PIN &&
    PAN_MIN <= PAN_HOME && PAN_HOME <= PAN_MAX &&
    TILT_MIN <= TILT_HOME && TILT_HOME <= TILT_MAX &&
    PAN_MIN >= 0 && PAN_MAX <= 180 && TILT_MIN >= 0 && TILT_MAX <= 180 &&
    (BUZZER_PIN == -1 || (BUZZER_PIN >= 2 && BUZZER_PIN <= 17 &&
                          BUZZER_PIN != PAN_PIN && BUZZER_PIN != TILT_PIN));
  if (enabled) {
    panServo.write(PAN_HOME); tiltServo.write(TILT_HOME);
    panServo.attach(PAN_PIN); tiltServo.attach(TILT_PIN);
  }
  lastContact = millis(); state();
}
void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (!overflowed) { input[used] = 0; command(); }
      used = 0; overflowed = false;
    } else if (c != '\r') {
      if (used < sizeof(input)-1) input[used++] = c;
      else overflowed = true;
    }
  }
  unsigned long now = millis();
  if (now-faceAt > 3000) face = 6;
  drawFace();
  if (enabled && now-lastContact > 2000 &&
      (sequence != 0 || targetPan != PAN_HOME || targetTilt != TILT_HOME)) home();
  if (enabled && now-lastStep >= 20) {
    lastStep = now;
    if (panAngle < targetPan) ++panAngle;
    if (panAngle > targetPan) --panAngle;
    if (tiltAngle < targetTilt) ++tiltAngle;
    if (tiltAngle > targetTilt) --tiltAngle;
    panServo.write(panAngle); tiltServo.write(tiltAngle);
    if (active && panAngle == targetPan && tiltAngle == targetTilt) {
      if (!settledAt) settledAt = now;
      if (now-settledAt >= 350) {
        active = false;
        if (sequence) { Serial.print("D "); Serial.println(sequence); }
        state();
      }
    }
  }
  if (BUZZER_PIN >= 0 && now-beepAt >= 130) {
    beepAt = now;
    if (sounding) { noTone(BUZZER_PIN); sounding = false; }
    else if (beeps > 0) { tone(BUZZER_PIN, 1800); sounding = true; --beeps; }
  }
}
