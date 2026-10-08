# test/assambly3 통합 테스트

## 기준과 확인 결과

기준은 `feature/web_design`의 `0ab26cb8453e48bf21fd2f7f3ecc0fd980cb8b3a`입니다.
`test/assambly2`의 `16ae8ae`를 모두 포함하고 46개 커밋이 추가된 상태로,
별도의 충돌 병합 없이 최신 웹·일반모드·기존 탐험 기능을 함께 테스트합니다.
웹 디자인 브랜치와 기존 통합 브랜치는 변경하지 않습니다.

오프라인 회귀 테스트 63개와 일기 목록 SQL 테스트 1개가 전부 통과했습니다.
이 검증은 실제 콜백과 HTTP 코드를 사용하되 ROS 전송·모델·DB 의존성을 대체합니다.
실제 DDS 연결, MySQL 읽기/쓰기, OpenAI 호출, 주행·복귀·팬틸트는 실물 검증 전입니다.
브라우저 렌더링 검증도 이 환경에서는 수행하지 못했습니다.

| 기능 | 코드 연결 | 실물 확인 |
| --- | --- | --- |
| 탐험 시작/종료/초기화 | HTTP → 명령 큐 → `/mission/command` → Mission Manager | 준비→탐험→복귀→회고→완료, 중간 취소 |
| 일반모드 시작/종료 | `/normal/start`, `/normal/stop` → NORMAL/NORMAL_STOP | Uno 준비·대기·이동·추종·끄덕임·종료 |
| 실시간 상태 | ROS 콜백 → 상태 저장 → `/ws` → 화면 갱신 | 상태·배터리·의욕 표시 |
| 카메라 | 압축 이미지 구독 → `/camera/stream` | 실제 프레임 수신과 영상 지속 |
| 지도 | OccupancyGrid → PNG·좌표 오버레이 | 지도·현재 위치·경로 일치 |
| 발견 기록 | 첫조우·호기심·관찰 결과 토픽 구독 | 물체별 상태 변화 |
| 일기 목록/상세/사진 | MySQL 조회 → `/api/sessions`, `/media/obs/*` | DB 스키마·사진 저장 경로 일치 |

일반모드는 일기나 DB 미션을 만들지 않는 구현입니다. LCD·부저는 웹 기능이 아니라
Uno 펌웨어와 SBC head_bridge가 수행하며, 실제 연결·펌웨어 업로드가 필요합니다.
`preview.py`는 예시 화면 전용으로 쓰기 요청이 차단됩니다. 실물 테스트는 `run.py`를
자동 실행하는 `odi_project_start`로 해야 합니다.

## 새 작업 폴더와 빌드

다음은 기존 저장소 루트에서 새 로컬 브랜치와 폴더를 처음 만드는 경우입니다.
이미 해당 worktree가 있으면 그 폴더에서 업데이트하고 중복 생성하지 않습니다.

```bash
git fetch origin
git worktree add ../ProjectOdi_assambly3 -b test/assambly3 origin/test/assambly3
```

기존 `.env`의 DB·OpenAI·ROS 설정을 새 폴더의 `.env`에도 준비합니다.
비밀값은 Git에 올리지 않습니다. 기존 Python 환경에 프로젝트 의존성이 설치돼 있다면
그 환경을 사용합니다. ROS Humble은 시스템 Python 3.10과 호환되는 환경을 사용합니다.

```bash
cd ../ProjectOdi_assambly3
source /opt/ros/humble/setup.bash
python3 -m pip install -r web_ws/requirements.txt
cd Odi_ws
colcon build --symlink-install
cd ..
bash scripts/assambly3.sh check --db
```

인터페이스 변경이 포함되어 전체 빌드가 필요합니다. 예전 작업 폴더의 overlay가
자동 source되는 터미널이면 새 터미널에서 해당 자동 설정을 확인하고 새 설치를 사용합니다.
`assambly3.sh`는 `.env`를 export하여 읽고 `ODI_PROJECT_ROOT`를 자신의 폴더로 고정합니다.

필요한 설정:

- `ODI_DB_HOST`, `ODI_DB_PORT`, `ODI_DB_NAME`, `ODI_DB_USER`, `ODI_DB_PASSWORD`: 기존 DB 설정.
- `OPENAI_API_KEY`: 실제 첫조우·회고에 사용. 모델명은 기존 검증한 환경 설정을 유지.
- `ROS_DOMAIN_ID`: PC/SBC 동일, `ROS_LOCALHOST_ONLY=0`.
- `ODI_DATASET_DIR`: 기본 `~/ProjectOdi_data`. 관찰/첫조우 노드와 웹이 동일 경로 사용.
- `ODI_ROBOT_HOST`: 기본 `team4@team4.local`.
- `ODI_HEAD_SETUP`: SBC에 빌드된 odi_normal의 `install/setup.bash` 절대 경로.
- `ODI_HEAD_PORT`: SBC Uno의 실제 `/dev/serial/by-id/...` 경로.
- `ODI_WEB_HOST`: 기본 `127.0.0.1`, 다른 장치에서 접속할 때만 `0.0.0.0`.

일반모드를 사용하려면 SBC에서도 최신 `odi_normal`을 빌드하고 기존 보정값을 확인합니다.
자동 head_bridge는 `ODI_HEAD_SETUP`이 있어야 시작됩니다. 기존 `odi_robot` tmux 세션이
살아 있으면 시작 명령이 세션을 재사용하므로 기존 스택을 정상 종료 후 실행하세요.
자세한 배선·SBC 빌드는 `docs/normal_mode.md`, LCD는 `docs/head_lcd.md` 참고.

## 실물 테스트 실행

기존 테스트 스택을 정상 종료한 뒤 새 폴더에서 터미널을 두 개 엽니다.

터미널 1 — SBC 브링업·카메라·선택적 head_bridge + PC 지도/Nav2 관리:

```bash
bash scripts/assambly3.sh robot
```

터미널 2 — ODI 노드 + 실제 웹:

```bash
bash scripts/assambly3.sh app
```

웹은 `http://127.0.0.1:8000/`입니다. 8001은 프리뷰입니다.
`app` 명령이 웹도 띄우므로 별도로 `python3 web_ws/run.py`를 중복 실행하지 않습니다.

터미널 3 — 읽기 전용 연결 확인:

```bash
bash scripts/assambly3.sh live --db
```

먼저 IDLE 상태·배터리·카메라를 확인합니다. 토픽 목록에 있다는 것만으로 정상 수신이
입증되지는 않습니다. 필요한 경우 다음 메시지를 각각 확인합니다.

```bash
ros2 topic echo /mission/state --once
ros2 topic echo /battery_state --once
ros2 topic hz /camera/image_raw/compressed
```

`hz`는 Ctrl+C로 끝냅니다. 출력에 비밀번호/API 키를 포함하지 마세요.

## 순서대로 확인

1. **연결**: IDLE, 배터리, 카메라. 시작 버튼이 잠기면 `/state`와 애플리케이션 로그 확인.
2. **탐험 1회**: 시작 → 새 지도 준비 → 탐험 → 물체 발견/관찰 → 탐험 종료 → 실제 정지·복귀 → 회고 → 일기 상세.
3. **일기**: 제목·본문·대표 사진·관찰 사진, 목록에 같은 세션 표시 확인. 사진이 없으면 DATASET_DIR와 실제 파일 경로 확인.
4. **반복**: 대기 화면으로 돌아가 IDLE 확인 후 두 번 더 반복. 이전 발견·경로가 새 세션에 섞이지 않는지 확인.
5. **일반모드**: 종료된 탐험의 IDLE에서 시작. 머리 정면 복귀 → 대기 → 이동 → cup/bottle/backpack 반응 → 종료. `/normal/status`와 웹 문구 비교.
6. **예외**: 준비 중 취소, 통신 끊김, 관찰 없는 탐험. 멈춤·오류·복구 화면과 로그를 함께 확인.

체크 스크립트는 노드를 시작하거나 이동 명령을 발행하지 않고 DB 내용을 변경하지 않습니다.
`robot`, `app`은 요청한 실제 실행 명령이며 웹 버튼부터 실제 미션 제어가 시작됩니다.
