# Uno 16×2 LCD 테스트

브랜치: `feature/normal_mode`. 펌웨어: `firmware/odi_head/odi_head.ino`.

| 장치 | 연결 / 설정 |
|---|---|
| 좌우 서보 | D10, 40~140도, 정면 84도 |
| 상하 서보 | D9, 0~100도, 정면 65도 |
| 수동형 부저 | D8 |
| LCD SDA / SCL | A4(18) / A5(19) |
| LCD | I²C 0x27, 16열 × 2행 |

Uno와 서보 외부 전원의 GND는 공통이어야 합니다. 현재 펌웨어는 서보가 활성화되어
업로드/재부팅 시 정면 84/65로 이동합니다.

## 설치와 업로드

1. 최신 `feature/normal_mode`를 받습니다. 로컬 수정이 있으면 먼저 diff를 확인해
   보존하고, `git pull --ff-only`로 갱신합니다.
2. Arduino IDE 라이브러리 관리자에서 **hd44780 — Bill Perry**를 설치합니다.
   Servo도 필요합니다. LiquidCrystal_I2C가 아닌 hd44780을 사용합니다.
   [라이브러리 설치 안내](https://github.com/duinoWitchery/hd44780#installation)
3. 보드 관리자에서 Arduino AVR Boards 1.8.6 이상을 사용합니다.
   보드 Arduino Uno, 해당 USB 포트를 선택하고 위 스케치를 업로드합니다.
4. 시리얼 모니터는 **115200 baud**, 줄바꿈(Newline)으로 설정합니다.

라이브러리가 0x27의 백팩 핀 배치를 자동 판별합니다. Wire 타임아웃을 3ms로
설정합니다. LCD 초기화 실패는 `E lcd_init`,
표시 중 오류는 `E lcd_io`로 보고하며 LCD 표시만 중단합니다. 배선을 수정한 뒤
Uno를 재시작합니다. LCD 오류가 서보 완료 응답을 대신하거나 성공으로 위장하지 않습니다.

## LCD만 먼저 확인

다음 명령을 한 줄씩 보냅니다. L 명령은 모터나 부저를 움직이지 않습니다.

| 명령 | 첫 줄 표정 | 둘째 줄 |
|---|---|---|
| `L 0` | `( ^_^ )` | ODI READY |
| `L 1` | `( -_- )` | RESTING |
| `L 2` | `( o_o )` | WALKING |
| `L 3` | `( O_O )` | LOOKING AT YOU |
| `L 4` | `( ^o^ )` | HELLO! BEEP BEEP |
| `L 5` | `( ._. )` | STOPPING |
| `L 6` | `( x_x )` | LINK LOST |
| `L 7` | `( o_o )` | EXPLORING |

정상 응답은 `L OK`입니다. LCD가 없으면 `L unavailable`입니다.
수동 테스트에서 3초 동안 새 L 명령이 없으면 LINK LOST로 바뀌는 것이 정상입니다.
ROS 브리지는 상태가 같아도 1초마다 갱신하지만 LCD 자체는 변경된 화면만 씁니다.
16×2 문자 LCD이므로 이번 버전은 문자 표정과 영문 문구를 사용합니다.

부저 테스트는 `M 30 84 65 2`입니다. 정면에서 두 번 소리가 나야 합니다.
`L 4`는 표정만 바꾸며 소리를 내지 않습니다. 일반모드의 끄덕임 단계에서만
기존 M 명령의 beep=2로 비프음을 함께 냅니다.

## ROS 연동

메인 PC와 Raspberry Pi에서 최신 소스를 받고 각 Odi_ws에서 실행합니다.

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select odi_normal
source install/setup.bash
```

시리얼 모니터를 닫고 Uno를 Pi USB에 연결합니다. 기존 두 터미널 실행 구성에서
head_bridge가 새 빌드로 재시작되도록 로봇 준비와 프로젝트를 다시 시작합니다.
`ODI_HEAD_SETUP`은 Pi의 새 install/setup.bash, `ODI_HEAD_PORT`는 Uno 포트여야 합니다.

웹 일반모드에서 대기 → 이동 → 물체 관찰 → 끄덕임/비프 → 대기의 표정 변화를
확인하고, 종료 시 STOPPING → ODI READY를 확인합니다.
미션/일반모드 상태가 3초 넘게 끊기면 LINK LOST가 표시됩니다.
L 명령은 기존 2초 서보 watchdog을 연장하지 않습니다.

화면이 밝지만 문자가 안 보이면 LCD 백팩의 대비 가변저항을 조절합니다.
초기화 오류가 나면 주소·SDA/SCL·전원을 확인하고 라이브러리 예제
`hd44780 → ioClass → hd44780_I2Cexp → I2CexpDiag`로 진단할 수 있습니다.

## 검증 범위

호스트 C++ 테스트는 실제 스케치를 가짜 Servo/Wire/LCD와 함께 실행해 명령 파싱,
표시 변경, 잔상 제거, LCD 오류 격리, watchdog을 검사합니다. Python 테스트는
ROS 상태별 표정 선택과 다른 세션의 메시지 배제를 검사합니다.
실제 Uno 컴파일·업로드, LCD 배선과 실물 표시 확인은 장비에서 수행해야 합니다.
