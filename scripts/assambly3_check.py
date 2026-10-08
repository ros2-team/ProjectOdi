"""Read-only checks. Never starts nodes, publishes commands or changes DB rows."""
import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web_ws'))
import config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', action='store_true', help='Check DB connection and web queries (read-only)')
    parser.add_argument('--live', action='store_true', help='Inspect running web state and ROS topics')
    args = parser.parse_args()
    failures = []

    def report(name, ok, detail=''):
        print(f'{"OK" if ok else "FAIL"} | {name}' + (f' | {detail}' if detail else ''))
        if not ok:
            failures.append(name)

    for name in ('flask', 'flask_sock', 'pymysql', 'PIL', 'numpy', 'rclpy', 'cv_bridge',
                 'openai', 'ultralytics', 'cv2'):
        try:
            ok = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            ok = False
        report('Python: ' + name, ok)
    report('실제 ROS 웹 모드', config.USE_FAKE is False)
    for name in ('ODI_DB_PASSWORD', 'OPENAI_API_KEY'):
        report(name + ' 설정', bool(os.getenv(name)))  # Never print credentials.
    report('현재 작업 폴더 빌드', (ROOT / 'Odi_ws/install/setup.bash').exists())
    for module, names in [('odi_interfaces.msg', ['MissionState', 'BehaviorState']),
                          ('odi_interfaces.srv', ['PrepareMapping', 'SetHomePose'])]:
        try:
            loaded = importlib.import_module(module)
            for name in names:
                obj = getattr(loaded, name)
                if name == 'BehaviorState':
                    assert hasattr(obj(), 'exploration_mode')
            report(module + ' 최신 인터페이스', True)
        except Exception as exc:
            report(module + ' 최신 인터페이스', False, type(exc).__name__)
    print('INFO | 일반 모드 머리 제어 | ' + ('자동 시작 설정됨' if os.getenv('ODI_HEAD_SETUP') else 'ODI_HEAD_SETUP 미설정: SBC에서 head_bridge를 별도 실행해야 함'))
    if args.db:
        try:
            from bridge import db
            rows = db.list_sessions()
            if rows:
                db.get_session(rows[0]['id'])
                db.get_observations(rows[0]['id'])
            report('DB 일기 조회', True, f'{len(rows)}개 (데이터 변경 없음)')
        except Exception as exc:
            report('DB 일기 조회', False, type(exc).__name__ + ' — 접속 설정과 스키마 확인')
    if args.live:
        try:
            # Use loopback even when the web is bound to 0.0.0.0.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f'http://127.0.0.1:{config.PORT}/state', timeout=5) as response:
                state = json.load(response)
            report('웹 상태 응답', True, str(state.get('mission')))
            report('카메라 프레임 수신', bool(state.get('camera')))
            print('INFO | 지도 | ' + ('수신됨' if state.get('map') else '아직 없음: 플랫폼/SLAM 로그 확인'))
            print('INFO | 배터리 | ' + str(state.get('battery')))
        except Exception as exc:
            report('웹 상태 응답', False, type(exc).__name__)
        try:
            result = subprocess.run(['ros2', 'topic', 'list'], capture_output=True, text=True, timeout=15)
            topics = set(result.stdout.splitlines())
            for topic in ('/mission/state', '/behavior/state', '/camera/image_raw/compressed', '/battery_state', '/scan'):
                report('ROS 토픽 ' + topic, result.returncode == 0 and topic in topics)
            print('INFO | 토픽 존재만 확인: 실제 메시지 수신 및 주기는 별도 확인 필요')
        except Exception as exc:
            report('ROS 토픽 조회', False, type(exc).__name__)
    print(f'결과: {len(failures)}개 항목 확인 필요')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
