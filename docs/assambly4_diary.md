# test/assambly4 — 생성 마무리와 탐험 지도 보관

## 동작

- 회고 때 관찰 기록을 근거로 본문과 1~2문장의 마무리 소감을 한 번 생성한다.
- 마무리는 기억에 남은 특징과 소감/다음 호기심으로 구성한다. 이동 시간, 날씨, 장소 등 제공되지 않은 사실은 추측하지 않도록 지시한다.
- 관찰이 없는 탐험도 빈 기록이라는 사실을 근거로 생성한다. 따라서 이 경우에도 OpenAI 연결이 필요하다.
- JSON 응답의 필수 문자열을 검사한 뒤 기존 diaries.diary_text TEXT 필드에 `odi.diary.v2` 형식으로 보관한다. DB 스키마와 ROS 인터페이스 변경은 없다.
- 기존 일반 텍스트 일기는 계속 읽을 수 있다. 생성 소감이 없는 이전 일기에는 고정 소감을 덧붙이지 않는다. 새 구조화 일기는 이 브랜치의 웹으로 조회한다.
- 지도를 약 2초 간격으로 경로와 함께 `ODI_DATASET_DIR/routes`에 저장한다. 기본 위치는 `~/ProjectOdi_data/routes`다.
- 귀환에서 회고로 바뀌기 전에 지도와 경로를 최종 저장한다. 확정한 일기는 다음 탐험에서 변경하지 않는다.
- 이미지, 크롭/좌표 정보, 경로, 시작/마지막 위치를 한 JSON 파일에 원자적으로 저장한다. 세션 ID는 해시 파일명으로 변환한다.
- 기존 지도·경로·시작/마지막 점을 Pillow로 합성해 탐험별 PNG 파일로 저장한다. 일기는 합성된 이미지 하나만 표시한다. 탐험 화면의 지도·경로 수집 방식은 바꾸지 않는다. 큰 좌표 점프와 지도 밖 구간은 이어 그리지 않는다.
- 미완료 기록은 저장된 구간임을 표시한다. 기록이 없는 과거 지도는 복원하거나 만들어내지 않는다.
- 웹을 종료하면 경로 수집도 멈춘다. 재시작 시 미완료 세션의 저장 경로를 복원하지만, 꺼져 있던 동안의 이동은 복원할 수 없다. SLAM 좌표 보정에 따른 오차는 실제 주행에서 확인해야 한다.

## 집에서 확인

기존 저장소 루트에서 최초 한 번:

```bash
git fetch origin
git worktree add ../ProjectOdi_assambly4 -b test/assambly4 origin/test/assambly4
cd ../ProjectOdi_assambly4
python3 -m pip install -r web_ws/requirements.txt
python3 web_ws/preview.py --port 8001
```

http://127.0.0.1:8001/diary/3 에서 예시 소감과 지도/경로를 확인한다.
프리뷰 데이터는 고정 예시이며 생성 호출이나 로봇 명령, 실제 기록 저장은 하지 않는다.

## 실습실 적용

새 폴더에 기존 환경 설정을 준비하고 ODI_DATASET_DIR을 기존 데이터 경로와 맞춘다.
기존 실행을 종료하고 ROS 환경에서:

```bash
source /opt/ros/humble/setup.bash
cd Odi_ws
colcon build --symlink-install
source install/setup.bash
cd ..
```

새 폴더를 ODI_PROJECT_ROOT로 설정하고 기존 방식으로 로봇과 앱을 실행한다.
새 탐험을 완료한 뒤 소감, 경로, 시작/마지막 위치를 확인한다.
다음 탐험과 웹 재시작 후에도 이전 일기가 같은 기록을 표시하는지 확인한다.

## 검증

```bash
python3 -m unittest discover -s tests -p 'test_diary_archive.py'
python3 -m unittest discover -s tests -p 'test_session_lifecycle.py'
python3 -m unittest discover -s web_ws/tests
node tests/test_diary_route_dom.js
```

총 Python 테스트 41개 통과. PNG 합성의 경로/표식 픽셀과 저장·조회 일치 여부, 이미지 표시 및 소감/이전 일기 fallback을 검증했다.
OpenAI는 대체 응답, DB는 대체 연결/SQLite로 검증했다. 실제 API, MySQL, 로봇 수집 및 브라우저 렌더링은 미검증이다.

PNG 파일은 routes 디렉터리의 세션 해시명.png로 저장한다. JSON에는 재시작 복원과 이미지/좌표의 일치 보장을 위한 동일 이미지와 메타데이터도 보관한다. 기존 v1 기록은 조회 시 PNG로 합성해 호환한다.
