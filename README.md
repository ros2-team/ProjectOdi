# Project ODI

탐험 일기 로봇 ODI 프로젝트입니다.

## Directory

- `Odi_ws/`: ROS2 로봇 워크스페이스
- `web_ws/`: 웹 서비스
- `db_ws/`: 데이터베이스 스키마 및 초기화 파일

## ROS2 Build

```bash
cd Odi_ws
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash
