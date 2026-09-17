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

    def __init__(self, min_area=0.025, min_hits=2, cooldown=90.0,
                 excluded=('tv', 'laptop', 'person', 'chair', 'refrigerator', 'bed'), ignored_top_ratio=0.0):
        self.min_area = min_area
        self.min_hits = min_hits
        self.cooldown = cooldown
        self.excluded = set(excluded)
        self.ignored_top_ratio = max(0.0, min(1.0, float(ignored_top_ratio)))
        self.reset('')

    def in_observation_view(self, box, name, height):
        """Keep full-image coordinates; reject boxes centered in the top band."""
        return (name not in self.excluded
                and (box[1] + box[3]) / 2 >= height * self.ignored_top_ratio)

    def reset(self, session):
        self.session = session
        self.counter = 0
        self.tracks = {}
        self.history = {}
        self.recent = []
        self.completion_guards = []
        self.completed_ids = set()

    def update(self, items, width, height, now, pose=None, *, turn_link=False, label_link=True):
        self.tracks = {k: v for k, v in self.tracks.items() if now-v['seen'] <= 3.0}
        self.recent = [r for r in self.recent if now-r['time'] < self.cooldown]
        self.history = {k: v for k, v in self.history.items() if now-v['seen'] < 120.0}
        self.completion_guards = [g for g in self.completion_guards
                                  if now < g['until']]
        items = list(items)
        previous_tracks = {k: dict(v) for k, v in self.tracks.items()}
        available = set(self.tracks)
        output = []
        # Largest boxes first makes association independent of YOLO box order.
        for box, name in sorted(items, key=lambda item: -(item[0][2]-item[0][0])*(item[0][3]-item[0][1])):
            # Class names may flicker after observation. Require reciprocal
            # geometric uniqueness before transferring an identity across labels.
            matches = []
            cross_label = []
            for k in available:
                previous = previous_tracks[k]
                overlap = iou(box, previous['box'])
                if previous['name'] == name:
                    matches.append((overlap, k))
                elif (label_link and overlap >= 0.3 and 0 <= now - previous['seen'] <= 3.0
                      and name not in self.excluded
                      and previous['name'] not in self.excluded):
                    competing_boxes = sum(
                        iou(other_box, previous['box']) >= 0.3
                        for other_box, _ in items)
                    competing_tracks = sum(
                        iou(box, old['box']) >= 0.3
                        for old in previous_tracks.values())
                    if competing_boxes == 1 and competing_tracks == 1:
                        cross_label.append((overlap, k))
            if len(cross_label) == 1:
                matches.extend(cross_label)
            score, key = max(matches, default=(0, ''))
            if score < 0.3 and turn_link:
                # Use only a unique same-class pair, never steal an overlap match.
                same_class = [k for k, old in previous_tracks.items()
                              if old['name'] == name]
                if (len(same_class) == 1
                        and sum(n == name for _, n in items) == 1):
                    candidate = same_class[0]
                    old = previous_tracks[candidate]
                    competing_overlap = any(
                        other_box != box and iou(other_box, old['box']) >= 0.3
                        for other_box, _ in items)
                    if (candidate in available and 0 <= now-old['seen'] <= 2.0
                            and not competing_overlap):
                        key, score = candidate, 0.3
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
            blocked = blocked or any(iou(g['box'], box) >= 0.3
                                     for g in self.completion_guards)
            eligible = (self.in_observation_view(box, name, height) and area >= self.min_area
                        and track['hits'] >= self.min_hits and not blocked)
            output.append((box, name, key, eligible))
        return output

    def observation_completed(self, key, now):
        """Freeze a fresh final box for three seconds, without extending ID cooldowns."""
        if key in self.completed_ids:
            return False
        self.completed_ids.add(key)
        track = self.history.get(key)
        # Never reuse the first-encounter box after a long observation or target loss.
        if track is None or not 0 <= now-track['seen'] <= 1.0:
            return False
        self.completion_guards.append(dict(box=tuple(track['box']), until=now+3.0))
        return True

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
