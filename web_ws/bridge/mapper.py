"""
지도 변환 — OccupancyGrid 를 브라우저가 볼 수 있는 PNG 로.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
왜 변환이 필요한가
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SLAM 이 내보내는 /map 은 숫자 배열이다.

     -1  아직 안 가본 곳
      0  빈 공간
    100  벽 / 장애물

브라우저는 이걸 못 읽는다. 이미지로 바꿔야 한다.
RViz 가 하는 일을 우리가 대신 하는 것이다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
꼭 알아야 할 함정 두 개
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

① y 축이 뒤집혀 있다
   ROS 는 y 가 위로 증가하고, 이미지는 y 가 아래로 증가한다.
   flipud 를 빼먹으면 지도는 그럴듯한데 마커 위치만 이상해진다.
   원인을 찾기가 매우 어려운 종류의 버그다.

② 대부분이 빈 공간이다
   slam_toolbox 는 그리드를 크게 잡는다.
   실제 방이 10m×10m 인데 그리드는 2000×2000 이고 99% 가 -1 이다.
   그대로 PNG 로 만들면 회색 바다 한가운데 방이 점처럼 찍힌다.
   가본 곳만 잘라내야(crop) 한다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
좌표 변환은 여기서 한다
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

프론트에 origin/resolution 을 내려주고 계산시키지 않는다.
crop 범위가 탐험이 진행되며 계속 바뀌는데 프론트는 그걸 알 도리가 없다.
브리지가 픽셀 좌표까지 계산해서 주면 프론트는 점만 찍으면 된다.
"""

# ┌─ 연결 지도 ────────────────────────────────────────────────
# │ import 하는 것 : config (여백 크기), numpy, Pillow
# │ ★ state 도 app 도 import 하지 않는다. 순수 변환 함수 모음이다.
# │
# │ 부르는 파일 : bridge/ros_link.py 의 on_map()
# │ 결과가 가는 곳 : static/media/map.png  +  state.map
# └────────────────────────────────────────────────────────────

import numpy as np
from PIL import Image

import config

# 화면에 쓸 색 (회색조)
COLOR_UNKNOWN = 205     # 아직 안 가본 곳
COLOR_FREE = 255        # 빈 공간
COLOR_WALL = 0          # 벽

OCCUPIED_THRESHOLD = 50     # 이 값보다 크면 벽으로 본다


class MapView:
    """한 번 변환한 지도의 결과.

    PNG 파일과, 세상 좌표(미터)를 그 PNG 안의 픽셀로 바꾸는 정보를 함께 들고 있다.
    """

    def __init__(self, info, crop_x0, crop_y0, width, height):
        self.res = info.resolution                  # 셀 하나가 몇 미터인가
        self.origin_x = info.origin.position.x      # 그리드 왼쪽아래의 세상 좌표
        self.origin_y = info.origin.position.y
        self.grid_h = info.height                   # 자르기 전 세로 셀 수
        self.crop_x0 = int(crop_x0)                 # 잘라낸 만큼의 offset
        self.crop_y0 = int(crop_y0)
        self.width = int(width)                     # PNG 크기
        self.height = int(height)

    def to_px(self, x, y):
        """세상 좌표(미터) → PNG 안의 픽셀 좌표.

        1) 원점을 빼고 해상도로 나눠 셀 번호를 구한다
        2) y 를 뒤집는다 (ROS 는 위로, 이미지는 아래로 증가)
        3) 잘라낸 만큼 빼준다
        """
        col = (x - self.origin_x) / self.res
        row = self.grid_h - (y - self.origin_y) / self.res      # ← flipud 대응

        # ★ float() 로 감싸는 이유
        #   numpy 값이 섞여 들어오면 np.float64 가 되는데,
        #   json.dumps() 가 그걸 직렬화하지 못해 WebSocket 전송이 통째로 터진다.
        #   화면이 갑자기 멈추는데 원인을 찾기 어려운 종류의 버그다.
        return [float(round(col - self.crop_x0, 1)),
                float(round(row - self.crop_y0, 1))]

    def inside(self, px):
        """PNG 밖으로 벗어난 좌표인지. 벗어난 마커는 그리지 않는다."""
        return 0 <= px[0] <= self.width and 0 <= px[1] <= self.height


def render(msg, out_path):
    """OccupancyGrid → PNG 파일. 성공하면 MapView 를 돌려준다.

    아직 아무 데도 안 가봐서 전부 -1 이면 None 을 준다.
    (그러면 화면에 "지도를 그리는 중" 이 계속 뜬다)
    """
    info = msg.info
    if info.width == 0 or info.height == 0:
        return None

    # ── 1) 숫자 배열로 ─────────────────────────────────────
    # msg.data 는 1차원이다. (height, width) 로 접는다.
    grid = np.asarray(msg.data, dtype=np.int8).reshape(info.height, info.width)

    # ── 2) 회색조 이미지로 ─────────────────────────────────
    img = np.full(grid.shape, COLOR_UNKNOWN, dtype=np.uint8)
    img[grid == 0] = COLOR_FREE
    img[grid > OCCUPIED_THRESHOLD] = COLOR_WALL

    # ── 3) y 뒤집기 ★ 이 줄을 빼먹으면 마커가 엉뚱한 곳에 찍힌다 ──
    img = np.flipud(img)
    known = np.flipud(grid) != -1       # 마스크도 같이 뒤집어야 짝이 맞는다

    # ── 4) 가본 곳만 잘라내기 ──────────────────────────────
    if not known.any():
        return None                     # 아직 아무 데도 안 가봤다

    rows, cols = np.where(known)
    m = config.MAP_CROP_MARGIN
    y0 = max(0, rows.min() - m)
    y1 = min(img.shape[0], rows.max() + m + 1)
    x0 = max(0, cols.min() - m)
    x1 = min(img.shape[1], cols.max() + m + 1)

    cropped = img[y0:y1, x0:x1]

    # ── 5) 저장 ────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(cropped, mode="L").save(out_path)

    return MapView(info, x0, y0, cropped.shape[1], cropped.shape[0])


def build_state(view, seq, path_world, pose_world, markers_world):
    """프론트가 그대로 쓸 수 있는 딕셔너리로 만든다.

    static/js/exploring.js 의 paintMap() 이 기대하는 모양이다.
    키 이름을 바꾸면 지도가 조용히 안 나온다.

    path_world    : [(x, y), …]                  지나온 길
    pose_world    : (x, y) 또는 None              지금 위치
    markers_world : [(x, y, "OBSERVE"|"IGNORE")]  발견 위치
    """
    path = [view.to_px(x, y) for x, y in path_world]
    path = [p for p in path if view.inside(p)]

    markers = []
    for x, y, action in markers_world:
        px = view.to_px(x, y)
        if view.inside(px):
            markers.append({"x": px[0], "y": px[1], "action": action})

    pose = view.to_px(*pose_world) if pose_world else None
    if pose and not view.inside(pose):
        pose = None

    return {
        # seq 가 올라갈 때만 프론트가 PNG 를 다시 받는다.
        # 같은 seq 면 경로선과 현재 위치만 갱신한다.
        "seq": int(seq),
        "url": f"/media/map.png?v={seq}",
        "width": int(view.width),       # numpy 정수가 섞이면 JSON 이 터진다
        "height": int(view.height),
        "path": path,
        "pose": pose,
        "markers": markers,
    }