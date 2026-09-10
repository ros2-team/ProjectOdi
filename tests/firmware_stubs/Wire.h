#pragma once
// Host stub for the Uno TWI bus. Tests flip devicePresent to decide whether the
// LCD backpack acknowledges, and read byteCount to assert how much bus traffic
// one loop() iteration causes.
#include <cstdint>

struct WireFake {
  bool devicePresent = true;   // Does the addressed device ACK?
  int byteCount = 0;           // Bytes handed to the bus; the test resets this.
  unsigned long clock = 0;
  uint8_t address = 0;
  void begin() {}
  void setClock(unsigned long hz) {clock = hz;}
  void beginTransmission(uint8_t addr) {address = addr;}
  uint8_t endTransmission() {return devicePresent ? 0 : 2;}
  void write(uint8_t) {++byteCount;}
};
inline WireFake Wire;
