// Host regression of actual sketch logic, not an AVR electrical/Servo test.
#include "firmware_stubs/Servo.h"
#include <cassert>
unsigned long fakeTime=0;
SerialFake Serial;
#include "../firmware/odi_head/odi_head.ino"
int main() {
  setup();
  assert(enabled);
  assert(lcd.glyphs==8);
  enabled=false;
  Serial.incoming="M 1 90 100 0\n"; loop();
  assert(Serial.output.find("E invalid") != std::string::npos);
  enabled=true; // Exercise protocol without attaching physical servos.
  Serial.incoming="M 2 90 100 0\n"; loop();
  for(fakeTime=20;fakeTime<1200;fakeTime+=20) loop();
  assert(tiltAngle==100);
  assert(Serial.output.find("D 2") != std::string::npos);
  Serial.incoming="M 3 90 180 0\n"; loop(); // Firmware limit, not host clamp.
  assert(targetTilt==100);
  for(;fakeTime<3000;fakeTime+=20) loop(); // No heartbeat: return to neutral.
  assert(tiltAngle==TILT_HOME && panAngle==PAN_HOME);
  assert(Serial.output.find("D 3") == std::string::npos);
  Serial.incoming=std::string(120,'x')+"M 4 90 100 0\n"; loop();
  assert(targetTilt==TILT_HOME); // Overflow line cannot execute a suffix command.
  Serial.incoming="L 4\n"; loop();
  assert(lcd.rows[0][4]==EYE_HAPPY && lcd.rows[0][11]==EYE_HAPPY);
  int firstRowWrites=lcd.writes;
  fakeTime+=20; loop();
  assert(lcd.writes-firstRowWrites==16);
  assert(lcd.rows[1][7]==MOUTH_LEFT && lcd.rows[1][8]==MOUTH_RIGHT);
  int writes=lcd.writes;
  Serial.incoming="L 4\n"; loop();
  assert(lcd.writes==writes); // Same face does not flash/rewrite LCD.
  fakeTime+=20; Serial.incoming="L 1\n"; loop();
  fakeTime+=20; loop();
  assert(lcd.rows[1]=="       __       "); // Old mouth removed.
  Serial.incoming="L 10\n"; loop();
  assert(face==1);
  unsigned long contact=lastContact;
  Serial.incoming="L 3\n"; loop();
  assert(lastContact==contact); // LCD must not refresh motion lease.
  fakeTime+=3100; loop();
  assert(face==6 && lcd.rows[0][4]==EYE_X);
  lcd.fail=true;
  fakeTime+=20; Serial.incoming="L 0\n"; loop();
  assert(!lcdReady);
  Serial.incoming="M 9 84 65 2\n"; loop();
  assert(sequence==9 && beeps==2); // Missing LCD cannot disable servos/buzzer.
}
