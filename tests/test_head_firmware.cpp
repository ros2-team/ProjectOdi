// Host regression of actual sketch logic, not an AVR electrical/Servo test.
#include "firmware_stubs/Servo.h"
#include "firmware_stubs/Wire.h"
#include "firmware_stubs/LiquidCrystal_I2C.h"
#include <cassert>
unsigned long fakeTime=0;
SerialFake Serial;
#include "../firmware/odi_head/odi_head.ino"
int main() {
  setup();
  assert(!enabled);
  assert(lcdPresent && lcd.initialized && lcd.glyphsLoaded==8);
  Serial.incoming="M 1 90 100 0\n"; loop();
  assert(Serial.output.find("E invalid") != std::string::npos);
  enabled=true; // Exercise protocol without attaching physical servos.
  Serial.incoming="M 2 90 100 0\n"; loop();
  for(fakeTime=20;fakeTime<1000;fakeTime+=20) loop();
  assert(tiltAngle==100);
  assert(Serial.output.find("D 2") != std::string::npos);
  assert(Tone.calls==0); // A zero beep count stays silent.
  Serial.incoming="M 3 90 180 0\n"; loop(); // Firmware limit, not host clamp.
  assert(targetTilt==100);
  for(;fakeTime<3000;fakeTime+=20) loop(); // No heartbeat: return to neutral.
  assert(tiltAngle==TILT_HOME && panAngle==PAN_HOME);
  assert(Serial.output.find("D 3") == std::string::npos);
  Serial.incoming=std::string(120,'x')+"M 4 90 100 0\n"; loop();
  assert(targetTilt==TILT_HOME); // Overflow line cannot execute a suffix command.

  // A rejected face code leaves the current expression alone.
  Serial.output.clear();
  fakeTime+=20; Serial.incoming="F 9\n"; loop();
  assert(Serial.output.find("E invalid") != std::string::npos);
  assert(face==FACE_SLEEP);

  // F sets the face, answers nothing, and must not feed the servo watchdog.
  Serial.output.clear();
  unsigned long parked=lastContact;
  lcd.cellsWritten=0;
  fakeTime+=20; Serial.incoming="F 3\n"; loop();
  assert(face==FACE_CURIOUS);
  assert(lastContact==parked);
  assert(Serial.output.empty());
  assert(lcd.cellsWritten==16); // One row per interval, never both at once.
  lcd.cellsWritten=0; fakeTime+=20; loop(); assert(lcd.cellsWritten==16);
  lcd.cellsWritten=0; fakeTime+=20; loop(); assert(lcd.cellsWritten==0);
  assert(lcd.screen[0][EYE_LEFT_COLUMN]==(char)EYE_WIDE);
  assert(lcd.screen[0][EYE_RIGHT_COLUMN]==(char)EYE_WIDE);
  assert(lcd.screen[1][MOUTH_COLUMN]=='o');

  // Expressions survive disabled servos; motion commands still do not.
  enabled=false;
  Serial.output.clear();
  fakeTime+=20; Serial.incoming="F 4\n"; loop();
  assert(face==FACE_HAPPY && Serial.output.empty());
  Serial.incoming="M 5 90 100 0\n"; loop();
  assert(Serial.output.find("E invalid") != std::string::npos);
  enabled=true;

  // A quiet link sleeps the face even though F kept the expression fresh.
  for(unsigned long quiet=fakeTime+2100; fakeTime<quiet; fakeTime+=20) loop();
  assert(face==FACE_SLEEP);

  // The beep count drives the buzzer now that a pin is wired.
  Tone.calls=0;
  Serial.incoming="M 6 90 100 2\n"; loop();
  for(unsigned long beeping=fakeTime+600; fakeTime<beeping; fakeTime+=20) loop();
  assert(Tone.calls==2 && Tone.pin==BUZZER_PIN);

  // A missing backpack must leave the sketch silent on the bus.
  Wire.devicePresent=false;
  setup();
  assert(!lcdPresent);
  Wire.byteCount=0;
  fakeTime+=20; Serial.incoming="F 2\n"; loop();
  fakeTime+=20; loop();
  fakeTime+=20; loop();
  assert(face==FACE_DRIVE && Wire.byteCount==0);
}
