# 일기 요약과 실제 의욕 게이지

관찰 모델의 diary_summary는 보이는 특징 1~2개와 오디의 호기심을 담은 짧은 한국어 일기 말투로 생성한다. 구조화된 속성은 기존 영어 스키마를 유지한다. 생성 누락 시 fallback도 영어 속성 나열 대신 짧은 일기 문장으로 쓴다. 기존 DB 기록은 변경하지 않으며 새 관찰에 적용된다. 모델 생성 말투는 실제 새 관찰 결과에서 확인한다.

BehaviorExecutor는 /exploration/motivation (std_msgs/String)으로 session_id/current/initial JSON을 1초마다 발행한다. initial은 세션 전환 시 실제 블랙보드 값에서 캡처한다. 웹은 현재 세션과 일치하는 유효한 수치만 받아 current/initial을 0~1로 제한하여 기존 게이지에 연결한다. 시작값0은0%로 표시한다. 늦은 이전 세션 메시지/NaN/잘못된 수치는 무시한다. 경과시간에 따른 가짜 감소는 추가하지 않는다. 의욕이 소모되는 행동에서만 값이 내려가며 탐험 종료 조건과 소모량은 변경하지 않는다.

PC에서 odi_behavior_executor와 odi_observation을 빌드하고 프로젝트 및 웹 프로세스를 재시작한다. 인터페이스 변경이나 Uno/Pi 재업로드는 필요 없다. 진단: ros2 topic echo /exploration/motivation --once.

오프라인: 발행 JSON→웹75%/0%, 이전 세션과 비정상 값 무시, 새 미션 초기화, 한국어 fallback 테스트 통과. 기존 세션 회귀19개 통과(선택 웹 의존성 테스트3개 생략). 실제 ROS 전달과 모델 생성은 로봇에서 확인해야 한다.
