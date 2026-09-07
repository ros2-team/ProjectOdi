"""
카메라 프레임 버퍼.

state.py 와 같은 자리에 있다 — 아무것도 import 하지 않고,
쓰는 쪽(ros_link)과 읽는 쪽(app)이 여기서만 만난다.

JPEG 바이트는 STATE 에 넣지 않는다. STATE 는 통째로 JSON 직렬화돼서
웹소켓에 실리기 때문에, 바이너리가 들어가면 터진다.
"""

import threading

_cond = threading.Condition()
_frame = None      # 최신 JPEG 바이트
_seq = 0           # 프레임 번호


def publish(jpeg_bytes):
    """ros_link 의 카메라 콜백이 매 프레임 호출한다."""
    global _frame, _seq
    with _cond:
        _frame = jpeg_bytes
        _seq += 1
        _cond.notify_all()


def wait_for(last_seq, timeout=4.0):
    """새 프레임이 올 때까지 블록한다.

    폴링하지 않고 기다리는 게 중요하다. 폴링하면 클라이언트 수만큼
    CPU 를 갉아먹는다.

    반환: (seq, jpeg) — 타임아웃이면 (last_seq, None)
    """
    with _cond:
        if _seq == last_seq:
            _cond.wait(timeout)
        if _seq == last_seq:
            return last_seq, None
        return _seq, _frame


def latest():
    with _cond:
        return _seq, _frame