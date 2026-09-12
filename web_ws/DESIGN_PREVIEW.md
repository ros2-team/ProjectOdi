# ODI 웹 디자인 미리보기

발표 시안의 연노랑 `#FFE08A`, 크림 `#FFF7D6`, 차콜 `#2E2E2E`, 하늘색 `#6ED9FF`를 적용한 웹 테마입니다.
홈의 모드 선택, 탐험 중 카메라·지도·발견 기록, 일반모드 상태, 탐험 일기를 같은 분위기로 구성했습니다.
`static/media/odi-companion.svg`는 발표 시안을 참고해 새로 그린 웹용 일러스트입니다.

## 로봇 없이 보기

```bash
cd web_ws
python3 -m venv .venv-preview
source .venv-preview/bin/activate
python -m pip install 'flask>=3.0' 'flask-sock>=0.7' pillow numpy
python preview.py
```

브라우저에서 **http://127.0.0.1:8001** 을 엽니다. HTTPS 주소가 아닙니다.

- 홈: http://127.0.0.1:8001/
- 탐험: http://127.0.0.1:8001/?screen=EXPLORING
- 일반모드: http://127.0.0.1:8001/?screen=NORMAL
- 일기 목록: http://127.0.0.1:8001/diary
- 준비 중: http://127.0.0.1:8001/?screen=PREPARING
- 오류 안내: http://127.0.0.1:8001/?screen=ERROR

미리보기는 예시 상태와 기존 샘플 일기를 사용합니다. 화면 상단에 미리보기 표시가 나오며, 시작·종료 등 쓰기 요청은 차단합니다. ROS 노드를 실행하거나 실제 DB를 읽지 않습니다. 카메라와 지도는 연결 대기 상태로 보입니다. 샘플 사진 파일이 없는 경우에는 사진이 표시되지 않습니다.

실제 로봇을 사용할 때는 기존 실행 명령을 그대로 사용합니다. `run.py`, ROS 제어, API 경로, 미션 상태 전환 로직은 변경하지 않았습니다.

## 디자인 수정 위치

- `static/css/companion.css`: 공통 색상, 반응형 배치, 버튼·카드·일기 스타일
- `static/index.html`, `static/diary.html`: 공통 로고와 내비게이션
- `static/js/exploring.js`의 `renderIdle()`: 홈 화면 구조
- `static/media/odi-companion.svg`: 오디 일러스트

카메라 DOM의 지속 연결과 지도 오버레이 좌표 처리는 유지합니다. 사진은 잘리지 않도록 원본 비율로 표시합니다.

## 홈 화면 예시

![로봇 없는 디자인 미리보기](design/home-preview.jpg)

데스크톱 1440px와 모바일 390px에서 배치, 상태 화면 전환, 일기 목록·상세 표시 및 미리보기 명령 차단을 확인했습니다. 실제 로봇 연결 테스트는 별도로 진행해야 합니다.
