// Arduino Uno: calibrated pan/tilt motion, I2C face display, passive buzzer.
// Set real pins and limits only after checking the robot. Defaults never attach.
// Protocol at 115200: P -> S enabled pan tilt busy
// M sequence pan tilt beepCount -> D sequence after commanded motion + settle.
// F code -> set face 0..7; answers nothing, needs no servos, and deliberately
// does not feed the servo watchdog so a dead controller still parks the head.
// D is commanded completion, NOT encoder feedback (ordinary servos have none).
#include <Servo.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

const bool ENABLE_SERVOS = false;
const int PAN_PIN = 10;       // Left/right (pan): confirmed Uno pin.
const int TILT_PIN = 9;       // Up/down (tilt): confirmed Uno pin.
const int BUZZER_PIN = 8;     // Passive buzzer; -1 disables sound.
const int SDA_PIN = 18;       // A4. Fixed by the Uno's TWI hardware.
const int SCL_PIN = 19;       // A5. Fixed by the Uno's TWI hardware.
const uint8_t LCD_ADDR = 0x27;  // Backpacks answer at 0x27 or 0x3F; scan first.
const int LCD_COLUMNS = 16, LCD_ROWS = 2;
const int PAN_MIN = 60, PAN_MAX = 120, PAN_HOME = 90;
const int TILT_MIN = 70, TILT_MAX = 110, TILT_HOME = 90;

// CGRAM holds only eight 5x8 glyphs, so they are a parts kit loaded once in
// setup(). Reloading per face would be ~256 I2C bytes and stall the servo step.
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

// Face codes are shared with odi_normal/head_bridge.py. Keep both sides in step.
enum {FACE_SLEEP, FACE_NEUTRAL, FACE_DRIVE, FACE_CURIOUS,
      FACE_HAPPY, FACE_TIRED, FACE_ERROR, FACE_THINK, FACE_COUNT};
// Each face is an eye glyph plus the two mouth cells; composing beats storing
// full rows and keeps the table at 24 bytes of the Uno's 2 KB.
const byte FACES[FACE_COUNT][3] PROGMEM = {
  {EYE_CLOSED, '_', '_'},                 // SLEEP
  {EYE_OPEN, '_', '_'},                   // NEUTRAL
  {EYE_OPEN, MOUTH_LEFT, MOUTH_RIGHT},    // DRIVE
  {EYE_WIDE, 'o', 'o'},                   // CURIOUS
  {EYE_HAPPY, MOUTH_LEFT, MOUTH_RIGHT},   // HAPPY
  {EYE_HALF, '_', '_'},                   // TIRED
  {EYE_X, '/', '\\'},                     // ERROR
  {EYE_OPEN, '.', '.'},                   // THINK
};
const int EYE_LEFT_COLUMN = 4, EYE_RIGHT_COLUMN = 11, MOUTH_COLUMN = 7;

Servo panServo, tiltServo;
LiquidCrystal_I2C lcd(LCD_ADDR, LCD_COLUMNS, LCD_ROWS);
bool enabled = false, active = false, lcdPresent = false;
int panAngle = PAN_HOME, tiltAngle = TILT_HOME;
int targetPan = PAN_HOME, targetTilt = TILT_HOME;
unsigned long sequence = 0, lastContact = 0, lastStep = 0, settledAt = 0;
unsigned long beepAt = 0;
// lastLine tracks any received line so the face can follow the link even when
// ENABLE_SERVOS is false; lastContact stays reserved for the servo watchdog.
unsigned long lastLine = 0, lastFaceStep = 0;
int face = FACE_SLEEP;
byte faceRow = 2;             // Row still to paint; 2 means nothing pending.
int beeps = 0;
bool sounding = false;
char input[80];
byte used = 0;
bool overflowed = false;

void state() {
  Serial.print("S "); Serial.print(enabled ? 1 : 0);
  Serial.print(' '); Serial.print(panAngle);
  Serial.print(' '); Serial.print(tiltAngle);
  Serial.print(' '); Serial.println(active ? 1 : 0);
}
void setFace(int code) {
  if (code == face) return;
  face = code;
  faceRow = 0;  // Repaint by overwrite; lcd.clear() blocks for 2 ms.
}
void drawFaceRow(byte row) {
  byte eye = pgm_read_byte(&FACES[face][0]);
  byte mouthLeft = pgm_read_byte(&FACES[face][1]);
  byte mouthRight = pgm_read_byte(&FACES[face][2]);
  lcd.setCursor(0, row);
  for (int column = 0; column < LCD_COLUMNS; ++column) {
    byte cell = ' ';
    if (row == 0) {
      if (column == EYE_LEFT_COLUMN || column == EYE_RIGHT_COLUMN) cell = eye;
    } else if (column == MOUTH_COLUMN) {
      cell = mouthLeft;
    } else if (column == MOUTH_COLUMN + 1) {
      cell = mouthRight;
    }
    lcd.write(cell);
  }
}
void home() {
  targetPan = PAN_HOME; targetTilt = TILT_HOME;
  active = true; sequence = 0; settledAt = 0;
  beeps = 0; sounding = false;
  if (BUZZER_PIN >= 0) noTone(BUZZER_PIN);
}
void command() {
  lastLine = millis();  // Any line proves the link; only P and a valid M feed
                        // lastContact, which is what parks the head.
  if (strcmp(input, "H") == 0) { home(); return; }
  if (strcmp(input, "P") == 0) {
    lastContact = millis(); state(); return;
  }
  int code;
  char extra;
  if (sscanf(input, "F %d %c", &code, &extra) == 1) {
    if (code < 0 || code >= FACE_COUNT) { Serial.println("E invalid"); return; }
    setFace(code);
    return;
  }
  unsigned long seq;
  int p, t, b;
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
  enabled = ENABLE_SERVOS && PAN_PIN >= 2 && PAN_PIN <= 19 &&
    TILT_PIN >= 2 && TILT_PIN <= 19 && PAN_PIN != TILT_PIN &&
    PAN_PIN != SDA_PIN && PAN_PIN != SCL_PIN &&
    TILT_PIN != SDA_PIN && TILT_PIN != SCL_PIN &&
    PAN_MIN <= PAN_HOME && PAN_HOME <= PAN_MAX &&
    TILT_MIN <= TILT_HOME && TILT_HOME <= TILT_MAX &&
    PAN_MIN >= 0 && PAN_MAX <= 180 && TILT_MIN >= 0 && TILT_MAX <= 180 &&
    (BUZZER_PIN == -1 || (BUZZER_PIN >= 2 && BUZZER_PIN <= 19 &&
                          BUZZER_PIN != PAN_PIN && BUZZER_PIN != TILT_PIN &&
                          BUZZER_PIN != SDA_PIN && BUZZER_PIN != SCL_PIN));
  if (enabled) {
    panServo.write(PAN_HOME); tiltServo.write(TILT_HOME);
    panServo.attach(PAN_PIN); tiltServo.attach(TILT_PIN);
  }
  // A missing display must stay harmless: probe the backpack and skip all LCD
  // work when nothing answers, the way disabled servos never attach.
  Wire.begin();
  Wire.setClock(400000);  // PCF8574 backpacks take 400 kHz; drop to 100000 if
                          // characters come out garbled on the bench.
  Wire.beginTransmission(LCD_ADDR);
  lcdPresent = Wire.endTransmission() == 0;
  if (lcdPresent) {
    lcd.init();
    lcd.backlight();
    for (byte glyph = 0; glyph < 8; ++glyph) {
      byte bitmap[8];
      for (byte row = 0; row < 8; ++row) {
        bitmap[row] = pgm_read_byte(&GLYPHS[glyph][row]);
      }
      lcd.createChar(glyph, bitmap);
    }
    faceRow = 0;  // Paint the boot face now that CGRAM holds the parts kit.
  }
  lastContact = millis(); lastLine = lastContact; state();
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
  // The face sleeps whenever the link goes quiet, with or without servos.
  if (now-lastLine > 2000) setFace(FACE_SLEEP);
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
  // One row per interval. A 16-cell row is ~3 ms of I2C at 400 kHz, and both
  // rows in a single pass would visibly cost the 20 ms servo cadence.
  if (lcdPresent && faceRow < 2 && now-lastFaceStep >= 20) {
    lastFaceStep = now;
    drawFaceRow(faceRow);
    ++faceRow;
  }
  if (BUZZER_PIN >= 0 && now-beepAt >= 130) {
    beepAt = now;
    if (sounding) { noTone(BUZZER_PIN); sounding = false; }
    else if (beeps > 0) { tone(BUZZER_PIN, 1800); sounding = true; --beeps; }
  }
}
