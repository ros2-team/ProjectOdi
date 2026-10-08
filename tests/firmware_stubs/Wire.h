#pragma once
#define WIRE_HAS_TIMEOUT 1
struct WireFake {
  void begin() {}
  void setClock(unsigned long) {}
  void setWireTimeout(unsigned long, bool) {}
};
inline WireFake Wire;
