# 회전 반복 현상: RPP 시험 설정

## 두 번째 기록에서 확인한 것

약49초 기록 중 주행 명령 구간 약40초 동안 위치 변화는 작고 각속도 부호가 반복 반전했다. 약1초마다 경로가 갱신되며 25.63초/45.70초에 Failed to make progress가 발생했다. TF와 경로를 비교하면 경로 방향과 어긋난 상태에서도 반대 방향 회전이 나타난다. 대표 시점의 직접 장애물 셀은 로봇 중심에서 약0.4m였고, inflation 비용 영역이 주변에 존재했다. 비용지도99는 팽창된 위험 영역이며 직접 장애물100과 구분했다.

이 기록에는 컨트롤러 내부 critic 점수와 shim 전환 DEBUG 로그가 없으므로 정확한 전환 원인은 확정하지 않는다. 경로 재계산만 늦추거나 장애물 여유를 줄이지 않고, 회전과 주행을 하나의 알고리즘으로 처리하는 RPP를 시험한다.

## 변경

- FollowPath를 nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController로 교체.
- 방향차0.52rad 이상일 때 회전, 목표 회전속도0.6rad/s, 가속도1.5rad/s².
- 전진 기준0.15m/s, 경로 참조 거리0.35m. 곡률/장애물 비용/목표 접근에 따라 감속.
- 충돌 예측 검사 활성화, 기존 local/global costmap과 footprint/inflation 유지.
- 후진 주행은 비활성화. 기존 Nav2 복구 행동은 유지.
- 진행 판정20초/0.15m 유지. 불가능한 경로를 계속 강행하지 않는다.
- 설치된 Nav2 기본 설정에 병합하되 FollowPath 플러그인 교체 시 DWB 전용 매개변수는 제거한다.
- 탐험, 귀환, 일반모드가 공통으로 쓰는 Nav2에 적용된다.

## PC 적용

로봇을 정지하고 프로젝트/주행 launch를 정상 종료한 뒤:

```bash
sudo apt install ros-humble-nav2-regulated-pure-pursuit-controller
# 최신 코드를 받은 저장소의 Odi_ws에서
colcon build --symlink-install --packages-select odi_bringup
source install/setup.bash
```

odi_robot_start와 odi_project_start를 각각 한 번만 실행한다. Pi/Uno 변경 없음.

```bash
ros2 param get /controller_server FollowPath.plugin
```

기대값: nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController.

넓은 곳에서 후방 경로 정렬→전진을 확인하고 같은 벽 앞 귀환을 재현한다. 탐험·일반모드도 함께 확인한다. 실제 성공을 확인한 설정이 아니라 기록에 근거한 시험 수정이며, 오프라인에서는 설정 병합과 안전 설정 보존을 검증했다. 새 컨트롤러도 충돌을 예측하면 정지하므로 모든 정지를 없애는 수정이 아니다.

공식 Humble 소스: https://github.com/ros-navigation/navigation2/tree/humble/nav2_regulated_pure_pursuit_controller
