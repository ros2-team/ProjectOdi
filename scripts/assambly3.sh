#!/usr/bin/env bash
# Run with bash scripts/assambly3.sh <check|robot|app|preview|live>.
set -e
ODI_TEST_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ODI_TEST_ROOT/.env" ]]; then
  set -a
  source "$ODI_TEST_ROOT/.env"
  set +a
fi
# Always bind this launcher to its own checkout, even if .env has an old path.
export ODI_PROJECT_ROOT="$ODI_TEST_ROOT"
cd "$ODI_TEST_ROOT"
mode="${1:-check}"
if [[ $# -gt 0 ]]; then shift; fi
case "$mode" in
  preview) cd web_ws; exec python3 preview.py "$@" ;;
  check|robot|app|live) ;;
  *) echo 'Usage: bash scripts/assambly3.sh check|robot|app|preview|live'; exit 2 ;;
esac
if [[ ! -f /opt/ros/humble/setup.bash || ! -f Odi_ws/install/setup.bash ]]; then
  echo 'ROS Humble 또는 이 작업 폴더의 빌드 결과가 없습니다. docs/assambly3_testing.md를 확인하세요.' >&2
  exit 1
fi
source /opt/ros/humble/setup.bash
source Odi_ws/install/setup.bash
case "$mode" in
  check) exec python3 scripts/assambly3_check.py "$@" ;;
  live) exec python3 scripts/assambly3_check.py --live "$@" ;;
  robot) exec ros2 run odi_bringup odi_robot_start "$@" ;;
  app) exec ros2 run odi_bringup odi_project_start "$@" ;;
esac
