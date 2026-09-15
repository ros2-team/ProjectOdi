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
  assert(lcd.rows[0][5]==EYE_HAPPY && lcd.rows[0][10]==EYE_HAPPY);
  int firstRowWrites=lcd.writes;
  fakeTime+=20; loop();
  assert(lcd.writes-firstRowWrites==16);
  assert(lcd.rows[1][7]==MOUTH_LEFT && lcd.rows[1][8]==MOUTH_RIGHT);
  assert(lcd.rows[1][4]=='*' && lcd.rows[1][11]=='*');
  int writes=lcd.writes;
  Serial.incoming="L 4\n"; loop();
  assert(lcd.writes==writes); // Same face does not flash/rewrite LCD.
  fakeTime+=20; Serial.incoming="L 1\n"; loop();
  fakeTime+=20; loop();
  assert(lcd.rows[1][4]==' ' && lcd.rows[1][11]==' '); // Cheeks removed.
  Serial.incoming="L 10\n"; loop();
  assert(face==1);
  unsigned long contact=lastContact;
  Serial.incoming="L 3\n"; loop();
  assert(lastContact==contact); // LCD must not refresh motion lease.
  fakeTime+=3100; loop();
  assert(face==6 && lcd.rows[0][5]==EYE_X);
  fakeTime=8220; Serial.incoming="L 0\n"; loop();
  assert(lcd.rows[0][5]==EYE_OPEN); // No timed blinking.
  fakeTime=8400; loop();
  assert(lcd.rows[0][5]==EYE_OPEN);
  fakeTime+=20; Serial.incoming="L 3\n"; loop();
  fakeTime+=20; loop();
  assert(lcd.rows[1]=="       O        "); // Single uppercase mouth.
  lcd.fail=true;
  fakeTime+=20; Serial.incoming="L 0\n"; loop();
  assert(!lcdReady);
  Serial.incoming="M 9 84 65 3\n"; loop();
  assert(sequence==9 && talksLeft==3); // Missing LCD cannot disable sound.
  for (int i=0; i<15; ++i) {fakeTime+=10; loop();}
  Serial.incoming="M 10 90 65 0\n"; loop();
  assert(talking); // Following movement does not truncate speech.
  for (int i=0; i<100; ++i) {fakeTime+=10; loop();}
  assert(!talking && !toneActive && panAngle==90);
  bool rises=false, falls=false;
  for (size_t i=1; i<toneFrequencies.size(); ++i) {
    assert(toneFrequencies[i]>=500 && toneFrequencies[i]<=840);
    rises |= toneFrequencies[i]>toneFrequencies[i-1];
    falls |= toneFrequencies[i]<toneFrequencies[i-1];
  }
  assert(rises && falls);
  Serial.incoming="M 11 84 65 3\n"; loop();
  Serial.incoming="H\n"; loop();
  assert(!talking && !toneActive);
  Serial.incoming="M 12 90 70 3\n"; loop();
  fakeTime+=2100; loop();
  assert(!talking && targetPan==PAN_HOME); // Watchdog cancels speech too.
  // New sounds are bounded, non-blocking, and preserve the existing M/D protocol.
  toneFrequencies.clear();
  Serial.incoming="M 20 84 65 4\n"; loop();
  assert(soundPreset==4 && talking);
  for (int i=0; i<20; ++i) { fakeTime+=10; loop(); }
  assert(!talking && !toneActive);
  assert(!toneFrequencies.empty());
  assert(toneFrequencies.front() < toneFrequencies.back());
  Serial.incoming="M 21 90 65 5\n"; loop();
  assert(soundPreset==5 && talking);
  for (int i=0; i<40; ++i) { fakeTime+=10; loop(); }
  Serial.incoming="M 22 93 65 0\n"; loop();
  assert(talking); // Silent tracking steps must preserve the hum.
  for (int i=0; i<90; ++i) { fakeTime+=10; loop(); }
  assert(!talking && panAngle==93);
  assert(Serial.output.find("D 22") != std::string::npos);
  Serial.incoming="M 23 84 65 7\n"; loop();
  assert(sequence==22); // Unknown sound cannot start a move.
  Serial.incoming="M 24 84 65 5\n"; loop();
  Serial.incoming="H\n"; loop();
  assert(!talking && !toneActive);
  // Every situation has a different pitch sequence, not just a repeat count.
  std::vector<std::vector<int>> patterns;
  for (int preset : {1, 2, 4, 5, 6}) {
    toneFrequencies.clear();
    Serial.incoming="P\n"; loop();
    startTalk(preset);
    for (int i=0; i<125; ++i) { fakeTime+=10; loop(); }
    assert(!talking && !toneActive);
    assert(!toneFrequencies.empty());
    for (const auto& previous : patterns) assert(previous!=toneFrequencies);
    patterns.push_back(toneFrequencies);
  }
  // Sound-only B must not touch a pending servo command or its watchdog lease.
  Serial.incoming="P\nM 30 100 70 0\n"; loop();
  unsigned long motionContact=lastContact, motionSequence=sequence;
  int motionPan=targetPan, motionTilt=targetTilt;
  bool motionActive=active;
  for (int sound : {1, 4, 5, 6, 7}) {
    fakeTime+=1;
    Serial.incoming="B " + std::to_string(sound) + "\n"; loop();
    assert(lastContact==motionContact && sequence==motionSequence);
    assert(targetPan==motionPan && targetTilt==motionTilt && active==motionActive);
    assert(soundPreset==sound);
  }
  Serial.incoming="B 8\n"; loop();
  assert(Serial.output.find("E sound_invalid") != std::string::npos);
  for (int i=0; i<140; ++i) { fakeTime+=10; loop(); }
  assert(Serial.output.find("D 30") != std::string::npos);
  // Even repeated sound requests cannot extend the motor watchdog.
  fakeTime=motionContact+2101;
  Serial.incoming="B 7\n"; loop();
  assert(targetPan==PAN_HOME && targetTilt==TILT_HOME && !talking);
}


