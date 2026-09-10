#pragma once
#include <string>
#include <sstream>
#include <cstring>
#include <cstdint>
using byte = unsigned char;
extern unsigned long fakeTime;
inline unsigned long millis() {return fakeTime;}

// PROGMEM keeps tables in AVR flash; on the host they are ordinary memory.
#define PROGMEM
inline byte pgm_read_byte(const byte *address) {return *address;}

// tone()/noTone() record their calls so the buzzer path is assertable.
struct ToneFake {int calls = 0, silences = 0, pin = -1, frequency = 0;};
inline ToneFake Tone;
inline void tone(int pin, int frequency) {
  Tone.pin = pin; Tone.frequency = frequency; ++Tone.calls;
}
inline void noTone(int pin) {Tone.pin = pin; ++Tone.silences;}
class Servo {public: void attach(int) {} void write(int) {}};
struct SerialFake {
  std::string incoming, output;
  void begin(int) {}
  int available() {return incoming.size();}
  char read() {char c=incoming[0]; incoming.erase(0,1); return c;}
  template<class T> void print(T x) {std::ostringstream s; s<<x; output+=s.str();}
  template<class T> void println(T x) {print(x);output+='\n';}
};
extern SerialFake Serial;
