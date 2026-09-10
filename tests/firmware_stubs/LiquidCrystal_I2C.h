#pragma once
// Host stub for a PCF8574-backed 16x2 character LCD. It records the glass
// contents so tests can assert which face is drawn, and counts written cells so
// they can assert the sketch never paints both rows inside one servo tick.
#include <cstdint>
#include <string>

#include "Wire.h"

struct LiquidCrystal_I2C {
  std::string screen[2];
  uint8_t glyphs[8][8] = {};
  int glyphsLoaded = 0;
  int cellsWritten = 0;        // The test resets this between loop() calls.
  int columns;
  uint8_t address;
  int cursorColumn = 0, cursorRow = 0;
  bool initialized = false, backlit = false;

  LiquidCrystal_I2C(uint8_t addr, int cols, int rows)
      : columns(cols), address(addr) {
    for (int row = 0; row < rows && row < 2; ++row) {
      screen[row] = std::string(static_cast<size_t>(cols), ' ');
    }
  }
  void init() {initialized = true;}
  void backlight() {backlit = true;}
  void createChar(uint8_t code, uint8_t bitmap[8]) {
    if (code < 8) {
      for (int row = 0; row < 8; ++row) glyphs[code][row] = bitmap[row];
    }
    ++glyphsLoaded;
  }
  void setCursor(int column, int row) {cursorColumn = column; cursorRow = row;}
  void write(uint8_t value) {
    if (cursorRow >= 0 && cursorRow < 2 &&
        cursorColumn >= 0 && cursorColumn < columns) {
      screen[cursorRow][static_cast<size_t>(cursorColumn)] =
          static_cast<char>(value);
    }
    ++cursorColumn;
    ++cellsWritten;
    Wire.write(value);
  }
};
