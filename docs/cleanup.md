# 실행 코드 정리 — cleanup/assambly4

기준: `test/assambly4`의 `537a3181b2c76fa55c0fa2c182f2dd75de9267b4`.
주행·탐험·일반모드·카메라·소리·일기 생성의 동작 설정은 유지했습니다.

## 제거한 항목

- Behavior Executor 초기 개발용 더미 노드 6개와 `behavior_test.launch.py`.
- 위 더미의 console_scripts 및 비어 있는 launch 설치 등록.
- 실제 `odi_detection`으로 대체된 First Encounter 패키지의 옛 YOLO 노드.
- 사용하지 않는 VLM 호환 파일 및 옛 YOLO/VLM 실행 별칭.
  실제 `first_encounter_node` 실행 항목은 유지했습니다.
- 항상 skip 처리된 초기 `test_copyright.py` 템플릿 8개와 해당 검사 의존성.
- 빈 디렉터리용 `.gitkeep` 2개.
- 교체 후 참조가 없는 `odi-companion.svg`, `illustrations/odi-home.webp`.
- 관찰 위치 계산기의 비활성 수동 bbox 테스트 타이머·상수·함수.
- 주석 처리된 예전 탐지 처리/좌표 계산 코드, 오래된 개발 단계 설명,
  웹 브리지의 미사용 QoS import.

총 21개 파일을 제거했습니다. 실제 관찰 위치 계산과 보정값은 동일합니다.

## 유지한 항목

- `__init__.py`, ROS resource 마커, package.xml, setup.cfg, launch/config:
  비어 있거나 직접 실행하지 않아도 패키지 검색·빌드에 필요합니다.
- `tests/`, 실제 lint/좌표/웹 테스트, firmware_stubs: 회귀 검증에 사용합니다.
- 웹 `preview.py`, fake/diary_fake/route_preview: 로봇 없는 디자인 프리뷰에서
  실제 사용하는 기능입니다. 기본 실물 실행은 `USE_FAKE=False`입니다.
- 설치·실행 문서, 라이선스, 설계 자료, 동작 이유와 안전 조건을 설명하는 주석.

## 검증

- Python 회귀 테스트 127개 + 웹 DB 조회 테스트 1개 통과.
- 일기 DOM 검사와 C++ 호스트 펌웨어 검사 통과.
- 모든 남은 ROS console_scripts의 모듈·main 함수와 패키징 resource 경로 확인.
- 주석/문서만 정리한 실행 파일 6개의 AST 동등성 확인(미사용 import 제외).
- Python 구문 및 JavaScript 구문 확인.

이 환경에는 ROS2 Humble/실제 로봇이 없으므로 colcon 및 실물 시연은 별도 확인이 필요합니다.

## 적용 시 주의

기존 install 폴더에는 삭제한 더미 실행 파일이 남을 수 있으므로 새 worktree에서
빌드하는 것을 권장합니다. 기존 촬영·시연 worktree와 데이터 폴더는 그대로 보존하세요.
새 worktree에서 ROS 환경 및 프로젝트 의존성을 준비하고 다음을 실행합니다.

```bash
cd Odi_ws
colcon build --symlink-install
source install/setup.bash
```

PC에서만 수정한 블랙보드 값이나 설정은 새 브랜치에 자동 복사되지 않습니다.
이 정리 기준의 원격 블랙보드 기본값과 reset 값은 의욕 10, 최소 관찰 1회,
최대 시간 300초입니다. 촬영용으로 바꾼 값이 있으면 기존 worktree와 비교해
기본값과 reset 양쪽을 함께 반영하세요.
