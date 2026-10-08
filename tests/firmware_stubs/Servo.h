#pragma once
#include <string>
#include <sstream>
#include <cstring>
#include <cstdint>
#include <vector>
using byte = unsigned char;
extern unsigned long fakeTime;
inline unsigned long millis() {return fakeTime;}
inline std::vector<int> toneFrequencies;
inline bool toneActive=false;
inline void tone(int, int hz) {toneFrequencies.push_back(hz); toneActive=true;}
inline void noTone(int) {toneActive=false;}
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

