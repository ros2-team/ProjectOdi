// Arduino Uno: calibrated pan/tilt motion, optional passive buzzer.
// Pins and motion limits calibrated on Odi; upload moves the head to 84/65.
// Protocol at 115200: P -> S enabled pan tilt busy
// M sequence pan tilt beepCount -> D sequence after commanded motion + settle.
// D is commanded completion, NOT encoder feedback (ordinary servos have none).
#include <Servo.h>
#include <avr/pgmspace.h>
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
// Glyph artwork adapted from feature/head_lcd (5936aa9).
enum {EYE_OPEN, EYE_CLOSED, EYE_HAPPY, EYE_WIDE, EYE_X, EYE_HALF,
      MOUTH_LEFT, MOUTH_RIGHT};
const byte GLYPHS[8][8] PROGMEM = {
  {0x00, 0x0E, 0x1F, 0x1F, 0x1F, 0x0E, 0x00, 0x00},  // EYE_OPEN
  {0x00, 0x00, 0x00, 0x1F, 0x1F, 0x00, 0x00, 0x00},  // EYE_CLOSED
  {0x00, 0x00, 0x04, 0x0E, 0x1B, 0x00, 0x00, 0x00},  // EYE_HAPPY
  {0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E, 0x00},  // EYE_WIDE
  {0x00, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x00, 0x00},  // EYE_X
  {0x00, 0x00, 0x1F, 0x1F, 0x0E, 0x00, 0x00, 0x00},  // EYE_HALF
  {0x00, 0x00, 0x00, 0x00, 0x10, 0x08, 0x07, 0x00},  // MOUTH_LEFT
  {0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x1C, 0x00},  // MOUTH_RIGHT
};


enum {FACE_READY, FACE_REST, FACE_WALK, FACE_CURIOUS, FACE_HAPPY,
      FACE_STOPPING, FACE_ERROR, FACE_EXPLORE, FACE_SLEEP, FACE_THINK, FACE_COUNT};
// Preserve L 0..7 meanings; append sleep and thinking at 8 and 9.
const byte FACES[FACE_COUNT][3] PROGMEM = {
  {EYE_OPEN, '_', '_'}, {EYE_HALF, '_', '_'},
  {EYE_OPEN, MOUTH_LEFT, MOUTH_RIGHT}, {EYE_WIDE, 'o', 'o'},
  {EYE_HAPPY, MOUTH_LEFT, MOUTH_RIGHT}, {EYE_HALF, '_', '_'},
  {EYE_X, '/', '\\'}, {EYE_OPEN, MOUTH_LEFT, MOUTH_RIGHT},
  {EYE_CLOSED, '_', '_'}, {EYE_OPEN, '.', '.'}
};
int face = FACE_READY, drawingFace = -1;
byte faceRow = 2;
unsigned long faceAt = 0, lastFaceStep = 0;

void drawFace() {
  if (!lcdReady) return;
  if (drawingFace != face) { drawingFace = face; faceRow = 0; }
  if (faceRow >= 2 || millis()-lastFaceStep < 20) return;
  lastFaceStep = millis();
  // Only one row per tick, after servo servicing, at standard 100 kHz.
  if (lcd.setCursor(0, faceRow) != 0) {
    lcdReady = false; Serial.println("E lcd_io"); return;
  }
  for (byte col = 0; col < 16; ++col) {
    byte cell = ' ';
    if (faceRow == 0 && (col == 4 || col == 11))
      cell = pgm_read_byte(&FACES[face][0]);
    else if (faceRow == 1 && (col == 7 || col == 8))
      cell = pgm_read_byte(&FACES[face][col-6]);
    if (lcd.write(cell) != 1) {
      lcdReady = false; Serial.println("E lcd_io"); return;
    }
  }
  ++faceRow;
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
    if (sscanf(input, "L %d %c", &requested, &tail) != 1 || requested < 0 || requested >= FACE_COUNT) {
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
  Wire.setClock(100000);
  // Arduino AVR Boards 1.8.6: bound I2C bus faults as well as normal writes.
  Wire.setWireTimeout(3000, true);
  lcdReady = lcd.begin(16, 2) == 0;
  if (!lcdReady) Serial.println("E lcd_init");
  for (byte glyph = 0; lcdReady && glyph < 8; ++glyph) {
    byte bitmap[8];
    for (byte row = 0; row < 8; ++row) bitmap[row] = pgm_read_byte(&GLYPHS[glyph][row]);
    if (lcd.createChar(glyph, bitmap) != 0) {
      lcdReady = false; Serial.println("E lcd_glyph");
    }
  }
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
  drawFace();
  if (BUZZER_PIN >= 0 && now-beepAt >= 130) {
    beepAt = now;
    if (sounding) { noTone(BUZZER_PIN); sounding = false; }
    else if (beeps > 0) { tone(BUZZER_PIN, 1800); sounding = true; --beeps; }
  }
}
