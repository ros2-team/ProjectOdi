#!/usr/bin/env python3
"""
Odi 웹 브리지 진입점.

    source ~/ProjectOdi_assembly/Odi_ws/install/setup.bash
    cd ~/ProjectOdi_assembly/web_ws
    python3 run.py

브라우저에서 http://127.0.0.1:8000
"""

import threading

import config
from bridge.app import create_app


def start_producers():
    """Start ROS input, or the explicitly enabled preview producer."""
    if config.USE_FAKE:
        from bridge import fake
        threading.Thread(target=fake.loop, daemon=True).start()
        print("[bridge] 가짜 시나리오 실행 중 (config.USE_FAKE = True)")
    else:
        from bridge import ros_link
        ros_link.spin_in_thread()


def main():
    start_producers()
    app = create_app()

    print(f"[bridge] http://{config.HOST}:{config.PORT}   (Ctrl+C 로 종료)")

    # use_reloader=False 가 핵심.
    # 리로더는 프로세스를 두 번 띄운다. 그러면 ROS 노드가 두 개 떠서
    # 같은 토픽을 중복 구독하고, 발견 이벤트가 두 번씩 들어온다.
    app.run(
        host=config.HOST,
        port=config.PORT,
        threaded=True,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
