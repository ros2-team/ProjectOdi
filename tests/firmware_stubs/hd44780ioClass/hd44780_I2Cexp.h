#pragma once
#include <string>
class hd44780_I2Cexp {
 public:
  std::string rows[2] = {std::string(16, ' '), std::string(16, ' ')};
  int row=0, col=0, writes=0;
  bool fail=false;
  explicit hd44780_I2Cexp(int) {}
  int begin(int, int) {return 0;}
  int setCursor(int c, int r) {col=c; row=r; return 0;}
  int write(char c) {if(fail) return 0; rows[row][col++]=c; ++writes; return 1;}
};
