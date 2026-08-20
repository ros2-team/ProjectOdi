"""
Flask 라우트 + 웹소켓.

state 를 읽기만 한다. ros_link / db / fake 를 import 하지 않는다.
그래서 ROS가 없어도, DB가 없어도 이 모듈은 그대로 돌아간다.
"""

import json
import time

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_sock import Sock

import config
from bridge import frames, state


def create_app():
    app = Flask(__name__, static_folder=None)
    sock = Sock(app)

    # ── 정적 파일 ────────────────────────────────────────
    # 경로를 명시적으로 나눈다. '/<path:filename>' 같은 포괄 규칙을 쓰면
    # /ws 나 /sessions 와 겹칠 수 있다.

    @app.get("/")
    def index():
        return send_from_directory(config.STATIC_DIR, "index.html")

    @app.get("/css/<path:filename>")
    def css(filename):
        return send_from_directory(config.STATIC_DIR / "css", filename)

    @app.get("/js/<path:filename>")
    def js(filename):
        return send_from_directory(config.STATIC_DIR / "js", filename)

    @app.get("/media/<path:filename>")
    def media(filename):
        """관찰 사진. ros_link 가 여기에 파일을 떨어뜨린다."""
        return send_from_directory(config.STATIC_DIR / "media", filename)

    # ── 카메라 MJPEG 스트림 ───────────────────────────────
    # <img src="/camera/stream"> 하나 걸어두면 브라우저가 연속 재생한다.
    # 웹소켓과 완전히 분리돼서 상태 갱신 주기와 무관하게 부드럽다.

    @app.get("/camera/stream")
    def camera_stream():
        def generate():
            last_seq = 0
            min_gap = 1.0 / config.STREAM_FPS
            next_at = 0.0
            while True:
                last_seq, jpeg = frames.wait_for(last_seq)
                if jpeg is None:
                    continue                    # 카메라가 아직 안 옴. 계속 기다린다
                now = time.time()
                if now < next_at:
                    continue                    # 상한 초과분은 버린다
                next_at = now + min_gap
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                       + jpeg + b"\r\n")

        return Response(generate(),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

    # ── 진단 ─────────────────────────────────────────────
    # 화면이 안 뜰 때 여기부터 열어본다.
    # 응답이 오면 서버는 살아있고 문제는 웹소켓이다.

    @app.get("/health")
    def health():
        s = state.snapshot()
        return jsonify(ok=True, mission=s["mission"], elapsed=s["elapsed_sec"])

    @app.get("/state")
    def full_state():
        return jsonify(state.snapshot())

    # ── 4단계에서 채울 자리 ───────────────────────────────

    @app.post("/sessions")
    def start_session():
        s = state.snapshot()
        if s["mission"] not in ("IDLE", "COMPLETED"):
            # 중복 시작 차단. 이거 없으면 데모 때 버튼 두 번 눌려서 꼬인다.
            return jsonify(error="already exploring"), 409
        state.reset()
        return jsonify(session_id=1), 201

    # ── 웹소켓 ───────────────────────────────────────────
    # 전체 상태를 주기적으로 밀어준다. 프론트가 Object.assign 으로 병합하므로
    # 델타를 계산할 필요가 없다. 지도 PNG는 여기 태우지 않는다 —
    # map.seq 만 보내고 프론트가 <img> 로 따로 받아간다.

    @sock.route("/ws")
    def ws(conn):
        peer = request.remote_addr
        print(f"[ws] connected  {peer}")
        try:
            while True:
                payload = json.dumps(state.snapshot(), ensure_ascii=False)
                conn.send(payload)
                time.sleep(1.0 / config.PUSH_HZ)
        except Exception:
            pass    # 클라이언트가 닫으면 send 가 던진다. 정상 종료.
        finally:
            print(f"[ws] closed     {peer}")

    return app