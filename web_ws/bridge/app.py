"""
Flask 라우트 + WebSocket + MJPEG 스트림.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
이 모듈이 지키는 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

state 와 frames 를 '읽기만' 한다.
ros_link / db / fake 를 import 하지 않는다.

그래서 ROS 가 없어도, DB 가 없어도 이 모듈은 그대로 돌아간다.
1 단계에서 로봇 없이 화면을 전부 완성할 수 있었던 이유다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
브라우저와 통신하는 세 가지 길
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  (1) 정적 파일   GET /  /css/*  /js/*     — 한 번 받고 끝
  (2) 상태        WS  /ws                  — 1 초마다 JSON 푸시
  (3) 영상        GET /camera/stream       — 연결 하나로 계속 밀어넣기

세 개가 서로 독립적이다. 하나가 느려도 나머지에 영향이 없다.
"""

# ┌─ 연결 지도 ────────────────────────────────────────────────
# │ import 하는 것 :
# │     config                        설정값
# │     bridge.state                  로봇 상태 (읽기만)
# │     bridge.frames                 카메라 사진 (읽기만)
# │     bridge.commands               로봇에게 보낼 명령 (쓰기만)
# │     bridge.diary_fake             일기 데이터
# │                                   ↑ DB 생기면 bridge.db 로 교체
# │
# │ ★ ros_link / fake 를 import 하지 않는다.
# │   그래서 ROS 가 없어도 이 파일은 그대로 돌아간다.
# │   로봇에게 말을 걸어야 할 때도 commands 큐에 넣기만 한다 —
# │   그게 토픽이 되는지 아무것도 안 되는지 이 파일은 모른다.
# │
# │ 브라우저에게 넘겨주는 파일 :
# │     GET /               → static/index.html
# │     GET /diary, /diary/3 → static/diary.html
# │     GET /css/*, /js/*    → static/css, static/js
# │     GET /media/*         → static/media
# └────────────────────────────────────────────────────────────

import json
import time

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_sock import Sock
from werkzeug.exceptions import NotFound

import config
from bridge import commands, frames, state

if config.USE_FAKE:
    from bridge import diary_fake as diary_source
else:
    from bridge import db as diary_source


def create_app():
    """Flask 앱을 만들어 돌려준다.

    ★ 왜 모듈 최상단에 app = Flask(...) 라고 안 쓰고 함수로 감쌌는가
      import 하는 것만으로 앱이 만들어지면 테스트할 때 곤란하다.
      함수로 두면 필요할 때 원하는 설정으로 여러 번 만들 수 있다.
      (application factory 패턴이라고 부른다)

    static_folder=None 인 이유 :
      Flask 가 알아서 /static/ 경로를 만드는 걸 끄고,
      우리가 직접 라우트를 정의하기 위해서다.
    """
    app = Flask(__name__, static_folder=None)
    sock = Sock(app)   # flask-sock 이 WebSocket 기능을 얹어준다

    # ════════════════════════════════════════════════════════
    # (1) 정적 파일
    #
    # 경로를 명시적으로 나눈다.
    # '/<path:filename>' 같은 포괄 규칙 하나로 처리하면
    # /ws 나 /sessions 같은 다른 경로와 겹칠 수 있다.
    # ════════════════════════════════════════════════════════

    @app.get("/")
    def index():
        """브라우저가 localhost:8000 을 열면 이게 응답한다."""
        return send_from_directory(config.STATIC_DIR, "index.html")

    @app.get("/css/<path:filename>")
    def css(filename):
        # index.html 안의 <link href="/css/odi.css"> 가 여기로 온다
        return send_from_directory(config.STATIC_DIR / "css", filename)

    @app.get("/js/<path:filename>")
    def js(filename):
        # <script src="/js/schema.js"> 가 여기로 온다
        return send_from_directory(config.STATIC_DIR / "js", filename)

    @app.get("/media/<path:filename>")
    def media(filename):
        """관찰 사진.

        로봇 쪽(인지/미션 노드)이 이 폴더에 저장하고,
        DB 의 photo_path 가 여기를 가리킨다.
        브리지는 사진을 만들지 않고 서빙만 한다.
        """
        return send_from_directory(config.STATIC_DIR / "media", filename)

    @app.get("/media/obs/<path:filename>")
    def observation_media(filename):
        """Serve images written during encounter or close observation."""
        for photo_dir in config.PHOTO_DIRS:
            try:
                return send_from_directory(photo_dir, filename)
            except NotFound:
                continue
        raise NotFound()

    # ════════════════════════════════════════════════════════
    # 일기
    #
    # 지금은 diary_fake 가 목 데이터를 준다.
    # DB 테이블이 생기면 bridge/db.py 로 바꿔 끼우기만 하면 된다.
    # 함수 이름을 같게 맞춰뒀으므로 import 한 줄만 바꾸면 끝난다.
    # ════════════════════════════════════════════════════════

    @app.get("/diary")
    @app.get("/diary/<session_id>")
    def diary_page(session_id=None):
        """일기 화면. session_id 는 자바스크립트가 주소에서 직접 읽는다."""
        return send_from_directory(config.STATIC_DIR, "diary.html")

    @app.get("/api/sessions")
    def api_sessions():
        """지난 일기 목록."""
        return jsonify(diary_source.list_sessions())

    @app.get("/api/sessions/<session_id>")
    def api_session(session_id):
        """일기 한 편 + 그날의 관찰 기록.

        두 개를 한 번에 주는 이유 :
          화면을 그리려면 둘 다 필요한데, 따로 요청하면
          한쪽만 도착한 상태에서 화면이 반쯤 그려진다.
          어차피 같이 쓸 데이터라 한 번에 보낸다.
        """
        s = diary_source.get_session(session_id)
        if s is None:
            return jsonify(error="not found"), 404

        return jsonify({
            "session": s,
            "observations": diary_source.get_observations(session_id),
        })


    # ════════════════════════════════════════════════════════
    # (3) 카메라 MJPEG 스트림
    #
    # multipart/x-mixed-replace 는 아주 오래된 HTTP 기법이다.
    # 하나의 응답 안에 이미지를 계속 이어붙여 보내면,
    # 브라우저가 새 이미지가 올 때마다 앞의 것을 '교체'해서 그린다.
    #
    # 그래서 <img src="/camera/stream"> 하나만 걸어두면
    # 자바스크립트를 한 줄도 안 쓰고 영상이 재생된다.
    #
    # ★ 왜 이 방식인가
    #   전에는 1 초마다 latest.jpg 를 새로 받게 했는데 뚝뚝 끊겼다.
    #     - WebSocket 이 1Hz 라 영상도 1 초에 한 장
    #     - 매번 32KB 재다운로드
    #     - <img> 엘리먼트가 매번 새로 생성돼 로딩 중 빈 화면 → 깜빡임
    #   MJPEG 은 연결을 유지한 채로 밀어넣으므로 이 셋이 전부 사라진다.
    # ════════════════════════════════════════════════════════

    @app.get("/camera/stream")
    def camera_stream():
        def generate():
            """제너레이터(generator).

            return 이 아니라 yield 를 쓰면 함수가 '조금씩 값을 내놓는'
            객체가 된다. Flask 는 이걸 받아서, yield 할 때마다
            그 바이트를 브라우저로 흘려보낸다. 함수는 끝나지 않는다.

            브라우저가 탭을 닫으면 이 제너레이터에 GeneratorExit 이
            발생하면서 자연스럽게 종료된다.
            """
            last_seq = 0
            min_gap = 1.0 / config.STREAM_FPS   # 프레임 사이 최소 간격(초)
            next_at = 0.0                        # 다음에 보내도 되는 시각

            while True:
                # 새 프레임이 올 때까지 잠든다 (폴링 안 함)
                last_seq, jpeg = frames.wait_for(last_seq)

                if jpeg is None:
                    continue   # 타임아웃. 카메라가 아직 없다. 계속 기다린다

                # ★ FPS 상한
                #   카메라는 16fps 인데 그대로 다 보내면
                #   클라이언트당 초당 0.5MB 다. 여러 명이 붙으면 와이파이가 버겁다.
                #   config.STREAM_FPS 를 넘는 프레임은 그냥 버린다.
                now = time.time()
                if now < next_at:
                    continue
                next_at = now + min_gap

                # multipart 형식 :
                #   --boundary
                #   Content-Type: image/jpeg
                #   Content-Length: 32703
                #   (빈 줄)
                #   <JPEG 바이트>
                #
                # \r\n 인 이유는 HTTP 규격이 줄바꿈을 CRLF 로 정해서다.
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                       + jpeg + b"\r\n")

        # boundary=frame 은 위에서 쓴 "--frame" 구분자와 짝이 맞아야 한다
        return Response(generate(),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

    # ════════════════════════════════════════════════════════
    # 진단용
    #
    # 화면이 안 뜰 때 여기부터 열어본다.
    # 응답이 오면 → 서버는 살아있고 문제는 WebSocket 이나 프론트
    # 응답이 없으면 → 서버 자체 문제
    # ════════════════════════════════════════════════════════

    @app.get("/health")
    def health():
        s = state.snapshot()
        return jsonify(ok=True, mission=s["mission"], elapsed=s["elapsed_sec"])

    @app.get("/state")
    def full_state():
        """WebSocket 으로 나가는 것과 똑같은 내용을 한 번만 준다.
        발견 목록이 실제로 쌓이는지 눈으로 확인할 때 쓴다."""
        return jsonify(state.snapshot())

    # ════════════════════════════════════════════════════════
    # 화면 흐름을 여는 두 개의 문
    #
    #   POST /sessions        관제 → 탐험    (START 명령을 로봇에게)
    #   POST /sessions/home   일기 → 관제    (완료 보고를 확인 처리)
    #
    # 브라우저가 상태를 직접 바꾸는 유일한 자리다.
    # 나머지는 전부 로봇이 보고한 것을 그대로 흘려보낸다.
    # ════════════════════════════════════════════════════════

    @app.post("/sessions")
    def start_session():
        """탐험 시작 요청. 대기 화면의 [탐험 보내기] 가 부른다.

        ★ 상태의 주인은 여전히 로봇이다.
          여기서 mission 을 EXPLORING 으로 바꾸지 않는다.
          로봇이 실제로 못 뜨면 화면만 거짓말하게 된다.
          PREPARING 까지만 바꾸고, EXPLORING 은 로봇이 보고할 때 바뀐다.

        ★ 명령은 큐에 넣기만 한다.
          여기서 ROS 퍼블리셔를 만들면 app.py 가 rclpy 를 import 하게 되고,
          ROS 없는 컴퓨터에서 웹 서버가 아예 안 뜬다.
          bridge/commands.py 에 넣어두면 ros_link 가 꺼내서 발행한다.
        """
        if not config.USE_FAKE:
            status, error = state.queue_mission_command(
                'START', commands.send, allowed_states={'IDLE'},
            )
            if error:
                return jsonify(error=error), status
            return jsonify(command='START', accepted=True), status

        s = state.snapshot()
        if s["mission"] != "IDLE":
            # 이미 탐험 중이면 거절한다.
            # 이게 없으면 데모 때 버튼이 두 번 눌려서 세션이 꼬인다.
            # 409 Conflict = "지금 상태에서는 그 요청을 처리할 수 없다"
            return jsonify(error="already exploring"), 409

        state.reset()
        state.patch(mission="PREPARING")

        # 로봇에게 출발하라고 알린다.
        # 로봇이 안 떠 있으면 아무도 안 꺼내가고, 화면은 PREPARING 에 머문다.
        # (프론트가 12 초 뒤 "로봇이 아직 응답하지 않아요" 를 띄운다)
        if not commands.send("START"):
            state.patch(mission="IDLE")
            return jsonify(error="command queue is full"), 503

        # 가짜 모드에서는 시나리오를 처음부터 다시 돌린다.
        if config.USE_FAKE:
            from bridge import fake
            fake.restart()

        return jsonify(command="START", accepted=True), 202

    @app.post('/normal/start')
    def start_normal():
        if config.USE_FAKE:
            return jsonify(error='Normal mode requires the real ROS connection'), 503
        status, error = state.queue_mission_command('NORMAL', commands.send, allowed_states={'IDLE'})
        if error:
            return jsonify(error=error), status
        return jsonify(accepted=True), status

    @app.post('/normal/stop')
    def stop_normal():
        if config.USE_FAKE:
            return jsonify(error='Normal mode requires the real ROS connection'), 503
        status, error = state.queue_mission_command('NORMAL_STOP', commands.send,
            allowed_states={'NORMAL', 'NORMAL_STOPPING'})
        if error:
            return jsonify(error=error), status
        return jsonify(accepted=True), status

    @app.post("/sessions/stop")
    def stop_session():
        """Request an orderly stop, return home, and reflection."""
        if not config.USE_FAKE:
            status, error = state.queue_mission_command(
                'STOP', commands.send, allowed_states={'PREPARING', 'EXPLORING'},
            )
            if error:
                return jsonify(error=error), status
            return jsonify(command='STOP', accepted=True), status
        if state.snapshot()["mission"] not in ("PREPARING", "EXPLORING"):
            return jsonify(error="mission is not exploring"), 409
        if not commands.send("STOP"):
            return jsonify(error="command queue is full"), 503
        return jsonify(command="STOP", accepted=True), 202

    @app.post("/sessions/reset")
    def reset_session():
        """Reset the Mission Manager and Behavior Executor."""
        if config.USE_FAKE:
            state.reset()
            return jsonify(command='RESET', accepted=True), 202
        status, error = state.queue_mission_command('RESET', commands.send)
        if error:
            return jsonify(error=error), status
        return jsonify(command='RESET', accepted=True), status

    @app.post("/sessions/home")
    def go_home():
        """Return to the dashboard, resetting only a finished mission.

        Browsing an older diary must not cancel a currently running mission.
        PREPARING cancellation uses the explicit /sessions/reset route.
        """
        if config.USE_FAKE:
            state.go_idle()
            return jsonify(accepted=True), 202
        if state.snapshot()['mission'] not in ('COMPLETED', 'ERROR'):
            return jsonify(accepted=True, command=None), 200
        status, error = state.queue_mission_command(
            'RESET', commands.send, allowed_states={'COMPLETED', 'ERROR'},
        )
        if error:
            return jsonify(error=error), status
        return jsonify(command='RESET', accepted=True), status

    # ════════════════════════════════════════════════════════
    # (2) WebSocket — 상태 푸시
    #
    # 전체 상태를 통째로 보낸다. 바뀐 부분만 골라 보내는(델타)
    # 방식도 있지만, 프론트가 Object.assign 으로 병합하기 때문에
    # 전체를 보내는 쪽이 훨씬 단순하고 버그가 없다.
    # 페이로드가 2KB 남짓이라 1Hz 면 부담도 없다.
    # ════════════════════════════════════════════════════════

    @sock.route("/ws")
    def ws(conn):
        """브라우저 하나가 접속할 때마다 이 함수가 새 스레드에서 실행된다.

        conn 은 그 브라우저와의 연결이다.
        함수가 끝나면 연결이 닫히므로, while True 로 붙잡고 있어야 한다.
        """
        peer = request.remote_addr
        print(f"[ws] connected  {peer}")
        try:
            while True:
                # snapshot() 은 락 안에서 복사만 하고 바로 놓는다.
                # 직렬화는 락 밖에서 — ROS 콜백을 막지 않기 위해서.
                payload = json.dumps(state.snapshot(), ensure_ascii=False)
                conn.send(payload)
                time.sleep(1.0 / config.PUSH_HZ)
        except Exception:
            # 브라우저가 탭을 닫으면 send() 가 예외를 던진다. 정상 종료다.
            pass
        finally:
            print(f"[ws] closed     {peer}")

    return app
