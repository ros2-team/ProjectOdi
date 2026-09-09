"""Image-space association and observation eligibility, independent of ROS."""

import math


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union > 0 else 0.0


class CandidatePolicy:
    """Associate one-to-one by class/overlap; suppress recent local encounters.

    This is short-term image tracking, not persistent object identity.
    """

    def __init__(self, min_area=0.025, min_hits=3, cooldown=60.0,
                 excluded=('tv', 'laptop')):
        self.min_area = min_area
        self.min_hits = min_hits
        self.cooldown = cooldown
        self.excluded = set(excluded)
        self.reset('')

    def reset(self, session):
        self.session = session
        self.counter = 0
        self.tracks = {}
        self.history = {}
        self.recent = []

    def update(self, items, width, height, now, pose=None):
        self.tracks = {k: v for k, v in self.tracks.items() if now-v['seen'] <= 3.0}
        self.recent = [r for r in self.recent if now-r['time'] < self.cooldown]
        self.history = {k: v for k, v in self.history.items() if now-v['seen'] < 120.0}
        available = set(self.tracks)
        output = []
        # Largest boxes first makes association independent of YOLO box order.
        for box, name in sorted(items, key=lambda item: -(item[0][2]-item[0][0])*(item[0][3]-item[0][1])):
            matches = [(iou(box, self.tracks[k]['box']), k) for k in available
                       if self.tracks[k]['name'] == name]
            score, key = max(matches, default=(0, ''))
            if score < 0.3:
                key = f'{self.session}:track_{self.counter}'
                self.counter += 1
                track = dict(hits=0, handled=False)
            else:
                available.remove(key)
                track = self.tracks[key]
                if now-track['seen'] > 1.0:
                    track['hits'] = 0
            track.update(box=box, name=name, seen=now, pose=pose, hits=track['hits']+1)
            self.tracks[key] = track
            self.history[key] = track
            area = max(0, box[2]-box[0])*max(0, box[3]-box[1]) / max(1, width*height)
            blocked = track['handled'] or any(
                r['name'] == name and self._same_view(r, box, pose)
                for r in self.recent)
            eligible = (name not in self.excluded and area >= self.min_area
                        and track['hits'] >= self.min_hits and not blocked)
            output.append((box, name, key, eligible))
        return output

    @staticmethod
    def _same_view(record, box, pose):
        previous = record['pose']
        if previous is not None and pose is not None:
            return math.hypot(pose[0]-previous[0], pose[1]-previous[1]) < 0.5
        return iou(record['box'], box) >= 0.3

    def handled(self, key, now):
        track = self.history.get(key)
        if track is not None:
            track['handled'] = True
            self.recent.append(dict(track, time=now))


def projected_range(points, box, camera_matrix):
    """Estimate range only from several camera-frame scan points inside a box.

    Association is a 2D LiDAR heuristic: it cannot prove that a return belongs
    to the visual object, especially for objects above the scan plane.
    """
    fx, _, cx, _, fy, cy, *_ = camera_matrix
    if fx <= 0 or fy <= 0:
        return None
    x1, y1, x2, y2 = box
    margin = (x2-x1)*0.25
    distances = []
    for x, y, z, distance in points:
        if z <= 0:
            continue
        u, v = fx*x/z+cx, fy*y/z+cy
        if x1+margin <= u <= x2-margin and y1 <= v <= y2:
            distances.append(distance)
    if len(distances) < 3:
        return None
    distances.sort()
    median = distances[len(distances)//2]
    if distances[-1]-distances[0] > max(0.25, median*0.2):
        return None
    return median
