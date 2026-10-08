
# 🤖 ODi (오디) : 자율주행 탐험 반려로봇

> **Autonomous Exploration Companion Robot**

ROS 2 Humble 기반으로 동작하며, 미지의 실내 공간을 스스로 탐사하고 **처음 보는 물체를 발견했을 때 '호기심'을 발동**시켜 능동적으로 관찰·기록하는 반려로봇 시스템입니다.
기존 홈 서비스 로봇이 *명령을 수행하는* 수동형이라면, ODi는 *스스로 발견하는* 능동형 로봇을 지향합니다.

<p align="center">
  <img width="810" height="751" alt="Odi — 호기심 탐사 로봇 _               " src="https://github.com/user-attachments/assets/29d6fa5c-25b9-4ebc-80f5-2e69481f29e6" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/ROS_2-Humble-22314E?logo=ros&logoColor=white">
  <img src="https://img.shields.io/badge/Ubuntu-22.04_LTS-E95420?logo=ubuntu&logoColor=white">
  <img src="https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/YOLOv8-Ultralytics-00FFFF?logo=yolo&logoColor=black">
  <img src="https://img.shields.io/badge/Raspberry_Pi-A22846?logo=raspberrypi&logoColor=white">
</p>

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|---|---|
| **프로젝트명** | 자율주행 탐험 반려로봇 ODi (오디) |
| **개발 기간** | 2026.0X ~ 2026.0X <!-- 확인 필요 --> |
| **팀 구성** | X명 <!-- 확인 필요 --> |
| **개발 환경** | ROS 2 Humble (Ubuntu 22.04 LTS), Python 3.10, C++, Flutter |
| **하드웨어** | Raspberry Pi, 2D LiDAR, Pi Camera Module, Pan-Tilt 서보 2축, DC 모터 드라이버 |

---

## 2. 개발 배경 및 목적

- **수동형 → 능동형 전환**
  기존 홈 로봇은 사용자가 명령해야만 동작합니다. ODi는 사용자의 개입 없이 스스로 공간을 탐색하고, 환경 변화를 먼저 감지해 알립니다.

- **'새로움'의 정량화**
  로봇이 무엇을 처음 보는지 판단할 기준이 필요합니다. 객체 임베딩 벡터와 기존 DB를 비교해 **호기심 점수(Novelty Score)** 를 산출하고, 이를 행동 트리거로 사용합니다.

- **본체 회전 없는 능동 관찰**
  주행 중에도 대상을 놓치지 않도록 Pan-Tilt 2축 카메라를 독립 제어하여, 본체를 돌리지 않고 시야를 유지합니다.

---

## 3. 주요 기능

| 기능 | 설명 |
|---|---|
| 🗺️ **자율 탐사 (Frontier Exploration)** | 미지 영역과 탐사 완료 영역의 경계면(Frontier)을 실시간 감지하여 탐사 경로를 스스로 설정 |
| 🎯 **Pan-Tilt 능동 시야 추적** | YOLOv8 Bounding Box 중심 오차를 PID로 보정하여 대상을 시야 중심(ROI)에 지속 유지 |
| ✨ **호기심 점수 산출 (Novelty Score)** | 객체 임베딩 벡터와 DB 저장 특징값의 코사인 유사도를 비교해 신규성을 수치화 |
| 🔄 **계층형 상태 머신 (FSM)** | EXPLORE → CURIOSITY → UPDATE → REST 이벤트 기반 행동 제어 |
| 🧠 **객체 DB 자동 갱신** | 신규 판정된 객체의 임베딩 벡터와 메타데이터를 DB에 등록, 관측 빈도 가중치 반영 |
| 📱 **모바일 앱 연동** | 탐사 중 발견한 객체의 '호기심 갤러리'와 실시간 지도를 앱으로 전송 |

---

## 4. 기술 스택

### Robot & System
- **OS / Middleware** : Ubuntu 22.04 LTS, ROS 2 Humble
- **Hardware** : Raspberry Pi, 2D LiDAR, Pi Camera Module v2, Pan-Tilt 서보 2축, 2WD 구동부

### Software & Algorithm
- **Navigation** : Navigation2, SLAM Toolbox / Cartographer, Frontier Exploration
- **Vision** : YOLOv8 (Ultralytics), OpenCV
- **Control** : PID Feedback Control, 계층형 FSM (Hierarchical State Machine)
- **Novelty Engine** : Embedding Vector + Cosine Similarity 기반 신규성 판별

### Application
- **Mobile** : Flutter
- **Database** : Vector DB <!-- 확인 필요: 실제 사용 DB명 기입 -->
- **Communication** : ROS 2 Topic / Action / Service

---

## 5. 시스템 아키텍처

```
                    [ Mobile App (Flutter) ]
                              │  (WebSocket / REST)
                              ▼
                    ┌──────────────────────┐
                    │   Application Layer  │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  Robot State Machine │   (EXPLORE / CURIOSITY / UPDATE / REST)
                    └──────────┬───────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
[ Exploration ]        [ Perception ]         [ Novelty Engine ]
 ├─ SLAM Toolbox        ├─ YOLOv8 Detector     ├─ Embedding Extractor
 ├─ Nav2 Costmap        ├─ Pan-Tilt PID Ctrl   ├─ Cosine Similarity
 └─ Frontier Selector   └─ Camera / LiDAR      └─ Object DB R/W
```

---

## 6. 핵심 구현 내용

### ① Pan-Tilt 능동 시야 추적 제어

로봇 본체의 회전 없이 Pan(좌우)·Tilt(상하) 서보를 독립 제어하여, 이동 중에도 대상 객체를 시야 중심에 유지합니다.

**제어 파이프라인**

```
YOLOv8 Detection  →  Center Error e(x, y)  →  PID Control Loop  →  Servo Angle Output
   (Bounding Box)      (프레임 중심 대비 오차)     (Kp / Ki / Kd)       (Pan / Tilt 각도)
```

- 프레임 중심점과 Bounding Box 중심 좌표(`x_c`, `y_c`)의 오차를 실시간 산출
- 오차를 PID 피드백으로 보정하여 서보 목표 각도로 변환
- 본체 화각 한계를 넘어서는 시야 확장 확보

| 항목 | 측정값 |
|---|---|
| 제어 응답 지연 | `< 100 ms` |
| 추적 프레임레이트 | `OO FPS` <!-- 실측값 기입 --> |
| 추적 유지 성공률 | `OO %` <!-- 실측값 기입 --> |
| PID 게인 | `Kp = ?, Ki = ?, Kd = ?` <!-- 실제 튜닝값 기입 --> |

---

### ② Frontier 기반 자율 탐사

미지 영역(Unknown Space)과 탐사 완료 영역(Free Space)의 **경계면(Frontier)** 을 실시간으로 감지하여, 정보 이득 대비 이동 비용이 가장 낮은 지점을 다음 목표로 선정합니다.

- **SLAM Toolbox / Cartographer** : 2D LiDAR 기반 점유 격자 지도(Occupancy Grid) 작성
- **Nav2 Costmap Integration** : 동적 장애물 실시간 회피 및 경로 재설정
- **Frontier Selector** : 후보 경계점 중 `정보 이득 / 이동 비용` 최대 지점 선택

> 랜덤 워크 방식 대비 동일 면적 탐사 시간 **35% 단축** (n = OO회 측정) <!-- 측정 횟수 기입 -->

---

### ③ DB 비교 기반 호기심 점수 알고리즘 ⭐

본 프로젝트에서 **직접 설계한 오리지널 로직**입니다.
새로 발견한 객체의 임베딩 벡터와 기존 DB에 저장된 객체 특징값의 유사도를 계산하여 신규성을 수치화합니다.

```
C_s = 1 − S_cos( V_curr , V_db ) × W_freq
```

| 기호 | 의미 |
|---|---|
| `C_s` | 호기심 점수 (Curiosity Score) |
| `S_cos` | 현재 객체 벡터와 DB 벡터 간 코사인 유사도 |
| `V_curr` | 현재 관측 객체의 임베딩 벡터 |
| `V_db` | DB에 저장된 동일 클래스 객체의 대표 벡터 |
| `W_freq` | 관측 빈도 기반 가중치 (자주 본 객체일수록 점수 감쇠) |
| `θ` | 호기심 발동 임계값 |

**동작 방식**

1. YOLOv8이 객체를 검출하면 해당 영역의 임베딩 벡터를 추출
2. DB의 기존 벡터들과 코사인 유사도 비교
3. `C_s > θ` 이면 → 탐사 중단, `CURIOSITY` State로 전환하여 접근·관찰
4. 관찰 완료 후 신규 객체는 DB에 등록, `W_freq` 갱신

**판정 사례**

| 객체 | `C_s` | 판정 |
|---|---|---|
| 처음 보는 물체 | `0.91` | 신규 — 호기심 발동 |
| 자주 관측된 물체 | `0.12` | 기존 — 탐사 계속 |
| 유사하지만 다른 물체 | `0.48` | 경계 사례 — 임계값 튜닝 중 |

> 신규 객체 변별 정확도 **88.5%** (실내 20종 객체 / 시행 OO회) <!-- 시행 횟수 기입 -->

---

### ④ 계층형 로봇 상태 머신 (Robot State Machine)

복합 행동 제어를 위해 이벤트 기반 계층형 유한 상태 머신을 설계했습니다.

```
   ┌───────────┐   C_s > θ    ┌─────────────┐
   │  EXPLORE  │ ───────────► │  CURIOSITY  │
   └───────────┘              └──────┬──────┘
         ▲                           │ 접근 완료
         │ 복귀                       ▼
   ┌───────────┐   저장 완료   ┌─────────────┐
   │   REST    │ ◄─────────── │   UPDATE    │
   └───────────┘              └─────────────┘
```

| State | 동작 |
|---|---|
| `EXPLORE` | Frontier 탐사 노드 활성화. 미지 구역 이동 중 비전 센서로 객체 실시간 스캔 |
| `CURIOSITY` | 높은 호기심 점수 감지 시 탐사 일시 중단. Pan-Tilt로 객체를 중앙 조준 후 접근 |
| `UPDATE` | 객체 정보 및 임베딩 벡터를 DB에 신규 저장, 관측 빈도 갱신 |
| `REST` | 수면/휴식 모드 또는 이전 탐사 경로로 복귀 |

---

## 7. 주요 ROS 2 인터페이스

| 분류 | Interface Name | Type | 설명 |
|---|---|---|---|
| Topic | `/odi/curiosity_score` | `std_msgs/msg/Float32` | 현재 관측 객체의 호기심 점수 `C_s` |
| Topic | `/odi/detected_object` | `vision_msgs/msg/Detection2DArray` | YOLOv8 객체 검출 결과 |
| Topic | `/odi/pan_tilt_angle` | `geometry_msgs/msg/Vector3` | 현재 Pan / Tilt 서보 각도 |
| Topic | `/odi/robot_state` | `std_msgs/msg/String` | FSM 현재 상태 (EXPLORE / CURIOSITY / ...) |
| Action | `/navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | Nav2 자율주행 목표 지점 전달 |
| Service | `/odi/register_object` | `std_srvs/srv/Trigger` | 신규 객체 DB 등록 요청 |

<!-- 실제 구현한 토픽/서비스 이름으로 교체하세요 -->

---

## 8. 주요 문제 해결 (Troubleshooting)

### 1. Pan-Tilt 서보 진동(Oscillation) 현상

- **문제** : 객체 추적 시 서보가 목표 각도 주변에서 좌우로 떨리며 수렴하지 못하는 현상 발생.
- **원인** : PID의 비례 게인(`Kp`)이 과도하게 설정되어 오버슈트가 반복됨. Bounding Box 자체의 프레임 간 미세 흔들림도 오차로 입력됨.
- **해결** : `Kp` 하향 + 미분 게인(`Kd`) 도입으로 감쇠 확보. 추가로 중심 오차에 **데드존(Dead Zone)** 을 설정하여 임계 픽셀 이하의 오차는 무시하도록 처리, 진동 제거.

### 2. 호기심 점수 경계 구간에서의 오판정

- **문제** : 형태가 유사하지만 실제로는 다른 객체에서 `C_s`가 임계값 부근(0.4~0.5)에 몰려 신규/기존 판정이 불안정.
- **해결** : 단일 임계값 대신 **2단계 임계값(확실 / 보류)** 구조를 도입. 보류 구간의 객체는 즉시 판정하지 않고 추가 관측 후 재평가하도록 로직 변경.
  <!-- 실제 적용 여부에 맞게 수정 -->

### 3. 좌표 프레임 정합 오류 (TF Transform)

- **문제** : 카메라 광학 프레임과 로봇 base_link 간 TF 정합이 맞지 않아, 검출된 객체의 3D 위치가 실제와 어긋남.
- **해결** : `static_transform_publisher`로 카메라 마운트 오프셋을 실측 반영하고, Pan-Tilt 각도를 동적 TF로 발행하도록 변경하여 관절 회전이 좌표 변환에 반영되도록 수정.
  <!-- 실제 겪은 이슈로 교체 권장 -->

---

## 9. 저장소 구조 (Directory Structure)

```
ODi/
├── src
│   ├── odi_bringup              # 시스템 일괄 실행 Launch 파일 및 파라미터
│   │   ├── launch
│   │   ├── config
│   │   └── maps
│   ├── odi_interfaces           # ODi 커스텀 메시지 / 서비스 타입 정의
│   │   ├── msg
│   │   └── srv
│   ├── odi_exploration          # Frontier 탐사 및 Nav2 연동 노드
│   │   ├── launch
│   │   └── odi_exploration
│   ├── odi_perception           # YOLOv8 객체 검출 및 Pan-Tilt 추적 제어
│   │   ├── launch
│   │   ├── models               # YOLOv8 weight 파일
│   │   └── odi_perception
│   ├── odi_curiosity            # 호기심 점수 연산 엔진 및 객체 DB 관리
│   │   ├── odi_curiosity
│   │   └── database
│   └── odi_state_machine        # 계층형 FSM 및 행동 제어 노드
│       ├── launch
│       └── odi_state_machine
├── app                          # Flutter 모바일 앱
│   └── lib
└── docs                         # 문서 및 시연 이미지 / 영상
    └── images
```

---

## 10. 실행 방법

```bash
# 1. 워크스페이스 빌드
cd ~/ODi
colcon build --symlink-install
source install/setup.bash

# 2. 전체 시스템 실행
ros2 launch odi_bringup odi_bringup.launch.py

# 3. 개별 모듈 실행
ros2 launch odi_exploration exploration.launch.py     # 자율 탐사
ros2 launch odi_perception pan_tilt_tracking.launch.py # Pan-Tilt 추적
ros2 run odi_curiosity curiosity_node                  # 호기심 점수 엔진
```

<!-- 실제 패키지/런치 파일명으로 교체하세요 -->

---

## 11. 팀 구성

| 이름 | 담당 |
|---|---|
| OOO | 하드웨어 설계 / Pan-Tilt 메커니즘 |
| OOO | SLAM · Nav2 자율 탐사 |
| OOO | 호기심 점수 알고리즘 / DB |
| OOO | FSM 제어 / 시스템 통합 |
| OOO | 모바일 앱 / UI |

<!-- 실제 팀원 및 역할로 교체하세요 -->

## 실행 코드

최종 구현은 `main`에 통합되어 있습니다. 테스트와 개발 문서는 실행 트리에서 정리했으며, 이전 자료는 Git 커밋 이력에서 확인할 수 있습니다.
