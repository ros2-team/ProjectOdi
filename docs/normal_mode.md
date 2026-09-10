# 일반모드 첫 버전

현재 동작하는 탐험 빌드는 `assamblybackup` (51e4f73581a840563db26872b93249fa473f61a6)에
보존했습니다. 일반모드 변경은 `feature/normal_mode`에만 반영합니다.
`test/assambly`에는 아직 합치지 않습니다.

## 구현 범위

웹에서 **일반모드 시작** → Uno 연결·정지 확인 → 카메라 정면 복귀 →
8초 대기 → 가까운 안전한 목표 한 곳(직선거리 0.5~1.2m)으로 이동 → 반복합니다.
경로 길이는 장애물 우회에 따라 더 길 수 있습니다. 일반모드는 현재 SLAM 지도를
그대로 사용하며, 탐험모드를 새로 시작할 때만 기존의 새 지도 준비 절차를 실행합니다.

안정적으로 감지된 지정 물체를 발견하면 이동 액션의 종료와 실제 정지 상태를
확인한 뒤 카메라로 바라보고 작게 끄덕인 후 정면으로 돌아옵니다.
기본 대상은 bottle, backpack, cup, 신뢰도 0.6 이상, 화면 면적 2% 이상,
연속 3회 감지입니다. 관심 표현 후 같은 클래스에는 60초 동안 반응하지 않습니다.
이 클래스 단위 제한은 단순한 첫 버전이며 서로 다른 병도 잠시 제외될 수 있습니다.
화면 크기 기준은 거리 측정이나 쓰레기 판정이 아닙니다.

물체를 놓치거나 6초 안에 정렬하지 못하면 끄덕임 없이 정면으로 복귀합니다.
일반모드는 사진·OpenAI 분석·일기·DB 미션을 만들지 않습니다.
부저가 없어도 팬틸트 동작을 수행하며, 선택적으로 연결하면 짧은 비프음을 냅니다.
치워 달라고 의미를 판단하거나 물체가 치워질 때까지 기다리는 기능은 포함하지 않습니다.

모드 변경은 **일반모드 종료 → 실제 IDLE 확인 → 탐험 시작** 순서입니다.
이동 목표가 늦게 수락되어도 해당 목표를 취소하고 Nav2의 최종 결과를 기다립니다.
취소 응답만으로 정지 완료라고 처리하지 않습니다.
카메라는 일반모드에서 본체가 정지한 동안만 움직입니다.

## 구성

- 메인 PC: `odi_normal/normal_node` — 행동 상태, YOLO 화면 중심 추종, 종료 처리.
- 메인 PC: 기존 `odi_exploration`의 `SHORT_ROAM` — 가까운 목표 한 곳으로 이동.
- Raspberry Pi: `odi_normal/head_bridge` — ROS와 Uno USB 시리얼 연결.
- Uno: `firmware/odi_head/odi_head.ino` — 제한된 각도로 서서히 이동, 완료 응답,
  2초 통신 watchdog, 부저, I2C 16x2 LCD 표정.
- 웹: 일반모드 시작/종료 버튼, 행동 상태와 카메라 영상.

기존 perception/tracker 테스트 브랜치는 수정하지 않습니다.
이번 화면 중심 추종은 새 패키지의 `attention.py`에 구현했습니다.

| 통신 | 내용 |
|---|---|
| `/mission/command` | 기존 START/STOP/RESET, 새 NORMAL/NORMAL_STOP |
| `/mission/state` | 기존 상태 + NORMAL/NORMAL_STOPPING |
| `/normal/status` | JSON: session_id, stage, detail |
| `/normal/event` | 세션에 해당하는 FAULT/STOPPED |
| `/head/command` | JSON: id, session_id, pan, tilt, beep |
| `/head/state` | ready, session_id, pan, tilt, busy, done |

Uno 시리얼(115200)은 다음과 같습니다.

| 명령 | 방향 | 내용 |
|---|---|---|
| `P` | → Uno | 하트비트. `S enabled pan tilt busy`로 응답 |
| `M seq pan tilt beep` | → Uno | 이동. 완료 후 `D seq` |
| `H` | → Uno | 즉시 정면 복귀 |
| `F code` | → Uno | 표정 0~7. 응답 없음 |
| `E invalid` | Uno → | 거부된 명령 |
| `BOOT` | Uno → | 리셋됨. 호스트는 표정을 다시 보냄 |

표정은 `head_bridge`가 `/mission/state`와 `/normal/status`의 stage에서 계산해
바뀔 때만 보냅니다. 코드는 0 SLEEP, 1 NEUTRAL, 2 DRIVE, 3 CURIOUS, 4 HAPPY,
5 TIRED, 6 ERROR, 7 THINK이며 `.ino`의 enum과 짝을 맞춰야 합니다.
`F`는 서보 watchdog을 갱신하지 않습니다. 제어 노드가 죽으면 표정과 무관하게
2초 뒤 머리가 정면으로 돌아가야 하기 때문입니다.

## 로봇을 확인하기 전

확인된 Uno 핀 연결은 **PAN_PIN=10(좌우), TILT_PIN=9(상하)**이며 펌웨어에 반영했습니다.
부저는 **디지털 8번(수동 부저)**, LCD는 **A4(SDA)/A5(SCL)** 입니다.
정면 각도와 회전 범위 확인 전이므로 **ENABLE_SERVOS=false**를 유지합니다.
이 상태로는 서보가 구동되지 않고 일반모드도 출발하지 않습니다.
LCD 표정은 서보와 무관하므로 이 상태에서도 확인할 수 있습니다.
서보 전원은 별도로 공급하되 Uno와 서보 전원의 GND를 공통으로 연결합니다.

LCD는 없으면 없는 대로 동작합니다. `setup()`이 I2C 주소에 응답이 있는지 확인해
없으면 이후 LCD 작업을 전부 건너뜁니다. **LCD를 붙이기 전에 Arduino IDE의
I2C 스캐너 예제로 백팩 주소를 읽고 `LCD_ADDR`을 맞추세요.** 흔한 값은 0x27과 0x3F입니다.
글자가 깨지면 `Wire.setClock(400000)`을 `100000`으로 낮춥니다.

로봇을 확인하면 다음을 맞추세요.

1. 반영된 핀 설정(PAN_PIN=10, TILT_PIN=9, BUZZER_PIN=8)과 실제 배선이
   일치하는지 확인합니다. 부저를 A4/A5에 꽂으면 I2C와 충돌하며 펌웨어가 거부합니다.
3. 장착 방향과 기구 간섭을 확인하고 PAN_HOME/TILT_HOME 및 MIN/MAX를 설정합니다.
   90도는 예시값이며 실제 정면을 보장하지 않습니다.
4. 물리적으로 제한 범위가 안전함을 확인한 뒤 ENABLE_SERVOS=true로 바꿉니다.
5. Arduino IDE에서 보드 Arduino Uno와 해당 USB 포트를 선택하고
   Servo 라이브러리가 설치된 환경에서 업로드합니다.
6. 같은 정면·허용 각도를 `Odi_ws/src/odi_bringup/config/odi.yaml`의
   normal_node 설정에도 맞춥니다. 추종이 반대로 움직이면 해당 pan_sign 또는
   tilt_sign을 반전합니다.

일반 서보에는 각도 피드백이 없으므로 펌웨어의 D 응답은 **명령한 보간 이동과
350ms 대기 완료**를 의미합니다. 모터 걸림이나 실제 카메라 정면을 측정한 결과가 아닙니다.
정면과 제한 각도는 실제 장착 상태에서 확인해야 합니다.

## 메인 PC 빌드

작업 중인 변경을 먼저 정리한 뒤 새 worktree를 권장합니다.

```bash
cd ~/ProjectOdi_assembly
git fetch origin
git worktree add -b feature/normal_mode ../ProjectOdi_normal origin/feature/normal_mode

cd ~/ProjectOdi_normal/Odi_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

로컬에 feature/normal_mode가 이미 있으면 새로 만들지 말고 그 worktree를 사용하세요.
기존 프로젝트의 OpenAI·DB 환경변수 설정은 그대로 필요합니다.
새 경로의 웹을 실행하려면 메인 PC의 실행 터미널에 다음을 설정합니다.

```bash
export ODI_PROJECT_ROOT="$HOME/ProjectOdi_normal"
```

## Raspberry Pi 준비

Raspberry Pi에도 이 브랜치의 소스를 가져오고 해당 ROS 워크스페이스에서:

```bash
source /opt/ros/humble/setup.bash
sudo apt install python3-serial
colcon build --symlink-install --packages-up-to odi_normal
source install/setup.bash
```

Uno USB 포트를 확인해 `/dev/serial/by-id/...`처럼 장치를 구분하는 경로를 사용하세요.
OpenCR 포트 `/dev/odi_opencr`를 사용하면 안 됩니다.
사용자에게 해당 시리얼 장치 접근 권한도 필요합니다.

처음 연결 확인 시에는 SBC에서 직접 실행할 수 있습니다.

```bash
ros2 run odi_normal head_bridge --ros-args \
  -p enabled:=true \
  -p port:=/dev/serial/by-id/실제_Uno_장치
```

`ros2 topic echo /head/state`에서 ready가 true인지 확인합니다.
enabled=false는 연결 기능을 꺼 두는 설정이며 더미 성공을 만들지 않습니다.
펌웨어 ENABLE_SERVOS=false 또는 USB 연결 문제가 있으면 ready는 true가 되지 않습니다.

## 기존 두 터미널로 실행

SBC 준비가 끝나면 메인 PC **터미널 1**에서:

```bash
source ~/ProjectOdi_normal/Odi_ws/install/setup.bash
export ODI_PROJECT_ROOT="$HOME/ProjectOdi_normal"
# 아래는 Raspberry Pi에 있는 실제 install/setup.bash 절대 경로입니다.
export ODI_HEAD_SETUP=/home/team4/ProjectOdi_normal/Odi_ws/install/setup.bash
export ODI_HEAD_PORT=/dev/serial/by-id/실제_Uno_장치
ros2 run odi_bringup odi_robot_start
```

ODI_HEAD_SETUP을 설정하면 기존 SBC tmux 세션에 head 창이 함께 생성됩니다.
이 환경변수를 설정하지 않으면 이전처럼 브링업·카메라만 실행합니다.
이미 떠 있는 odi_robot 세션에는 창을 추가하지 않으므로 처음 적용 시 기존 세션을
정상 종료하고 다시 켜세요. 직접 실행한 head_bridge와 자동 실행을 중복하지 마세요.

**터미널 2**에서는 기존 DB·OpenAI 환경 설정을 불러온 뒤:

```bash
source ~/ProjectOdi_normal/Odi_ws/install/setup.bash
export ODI_PROJECT_ROOT="$HOME/ProjectOdi_normal"
ros2 run odi_bringup odi_project_start
```

웹을 새로고침하고 일반모드를 선택합니다.
종료 버튼을 누르면 현재 위치에서 멈추고 카메라를 정면으로 돌립니다.
일반모드 종료는 집으로 돌아가기나 일기 작성이 아닙니다.

## 실제 로봇 검증 순서

1. 처음에는 rest_sec를 충분히 크게 설정하고, 가까운 병 하나로 정렬 방향과
   끄덕임을 확인합니다. 크롭/추종 화면은 기본 320x240에 맞춰져 있습니다.
2. 정면 복귀가 맞는지 확인한 뒤 rest_sec=8.0으로 짧은 이동을 확인합니다.
3. 이동 중 발견, 물체가 사라지는 경우, 반복 감지 제한을 확인합니다.
4. 일반모드 종료 → IDLE → 탐험 시작을 확인합니다.
5. Uno 연결을 끊으면 이동 취소 후 연결 복구·정면 복귀를 기다리는지 확인합니다.
   이미 팬틸트를 움직인 경우에는 복귀 확인 없이 모드를 전환하지 않습니다.
6. 마지막으로 기존 탐험→관찰→복귀→웹 일기 흐름을 회귀 테스트합니다.

Nav2 결과가 오지 않거나 Uno 복귀 응답이 없으면 종료를 완료하지 않습니다.
복구할 수 없다면 로봇을 정지시키고 두 터미널을 다시 시작하세요.
일반모드 제어 노드의 heartbeat가 사라지면 SHORT_ROAM도 취소합니다.
배터리 메시지가 충전 중 또는 15% 이하를 보고하면 일반모드는 중단합니다.

## 오프라인 검증

```bash
python3 -m unittest discover -s tests -q
g++ -std=c++17 -Wall -Wextra -I tests/firmware_stubs \
  tests/test_head_firmware.cpp -o /tmp/odi_head_test
/tmp/odi_head_test
node --check web_ws/static/js/exploring.js
```

HTTP 테스트에는 Flask, flask-sock, PyMySQL이 필요합니다.
검증 당시 Python 테스트 66개 통과, 실제 스케치 로직을 포함한 C++ 호스트 테스트 통과.
ROS2 Humble 빌드, AVR 툴체인 컴파일, 전기적 연결, 실물 서보 동작은 아직 검증하지 않았습니다.
PC용 Servo/Serial/Wire/LCD 스텁은 실제 하드웨어 피드백을 검증하지 않습니다.
특히 LCD 스텁은 I2C 타이밍을 재현하지 않으므로, LCD 갱신이 서보 움직임을
끊지 않는지는 실물에서 확인해야 합니다.

참고한 공식 API:
[Arduino Servo](https://docs.arduino.cc/libraries/servo/),
[ROS2 Humble 액션](https://docs.ros.org/en/humble/Concepts/Basic/About-Actions.html).

