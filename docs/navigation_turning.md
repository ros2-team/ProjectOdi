# 벽 앞 경로 방향 전환

Humble DWB에 RotationShimController를 추가한다. 새 경로 방향이 0.52rad(약30도) 이상 어긋나면 충돌 검사 후 제자리 회전을 시도하고 DWB에 넘긴다. 회전 목표 속도는 0.6rad/s, 가속도는 1.5rad/s², 경로 샘플 거리는 0.35m다. Humble의 공통 지원 파라미터만 사용한다. 회전이 불가능할 때 플러그인은 DWB로 넘길 수 있으며, 반드시 유턴 성공을 보장하지 않는다.

SimpleProgressChecker는 회전을 진행으로 계산하지 않는다. 제한은 10초/0.5m에서 20초/0.15m로 변경해 유턴과 저속 이동 여유를 확보하되 영구 정체는 실패로 처리한다. trans_stopped_velocity는 0.25에서 0.03m/s로 내려 주행 속도를 정지로 판정하는 범위를 줄인다. 이는 주로 목표점 회전 판정과 관련된다.

설치된 nav2_bringup/params/nav2_params.yaml에 navigation_overrides.yaml만 합친다. local/global costmap, 로봇 크기, inflation, planner, recovery, velocity smoother는 원래 설정을 유지한다. 적용 경로는 mapping_supervisor(탐험마다 재시작 포함)와 SLAM 없는 odi_system 실행 모두 odi_navigation.launch.py로 통일한다. 임시 설정은 launch 종료 시 제거된다.

## 적용 (PC)

로봇이 정지한 뒤 프로젝트와 주행 launch를 정상 종료한다. 변경 전까지의 실험 데이터/설정은 보관한다.

```bash
sudo apt install ros-humble-nav2-rotation-shim-controller
# 저장소 최신화 후 Odi_ws에서
colcon build --symlink-install --packages-select odi_bringup odi_normal
source install/setup.bash
```

기존 방식대로 odi_robot_start와 odi_project_start를 각각 한 번만 실행한다. 기존 Nav2를 남긴 채 새 launch를 추가하면 안 된다. Pi/Uno 수정은 이번 주행 변경에 필요 없다. 사용자가 올린 카메라84/75는 유지하며 normal_node 기본값도75로 맞춘다.

```bash
ros2 param get /controller_server FollowPath.plugin
ros2 param get /controller_server FollowPath.primary_controller
ros2 param get /controller_server progress_checker.movement_time_allowance
```

기대값: nav2_rotation_shim_controller::RotationShimController, dwb_core::DWBLocalPlanner, 20.0.

## 실물 확인

넓은 공간에서 뒤쪽 목표로 회전 후 출발하는지 먼저 확인하고, 벽 앞에서 같은 귀환 상황을 재현한다. 탐험과 일반모드도 동일 컨트롤러를 쓰므로 함께 확인한다. 충돌 판정 때문에 회전이 안 되면 로봇 외형/footprint 및 local costmap을 점검해야 하며, inflation을 임의로 줄여 통과시키지 않는다. 반복 실패 시 controller_server의 오류와 /plan, /local_costmap/costmap, /odom, /cmd_vel, /tf를 함께 기록한다.

오프라인 검증은 설정 병합/보존과 실행 연결을 확인한다. ROS2 플러그인 로딩과 실제 유턴 성공은 실물에서 검증해야 한다.

공식 소스: https://github.com/ros-navigation/navigation2/tree/humble/nav2_rotation_shim_controller
