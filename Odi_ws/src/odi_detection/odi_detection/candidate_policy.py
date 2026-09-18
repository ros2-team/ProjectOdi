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
                 excluded=('tv', 'laptop', 'person', 'chair', 'refrigerator', 'bed'),
                 ignored_top_ratio=0.0, observation_zone_radius=0.5,
                 observation_zone_sec=45.0):
        self.min_area = min_area
        self.min_hits = min_hits
        self.cooldown = cooldown
        self.excluded = set(excluded)
        self.ignored_top_ratio = max(0.0, min(1.0, float(ignored_top_ratio)))
        self.observation_zone_radius = max(0.0, float(observation_zone_radius))
        self.observation_zone_sec = max(0.0, float(observation_zone_sec))
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
        self.observation_zones = []
        self.completed_ids = set()

    def update(self, items, width, height, now, pose=None, *, turn_link=False, label_link=True):
        self.tracks = {k: v for k, v in self.tracks.items() if now-v['seen'] <= 3.0}
        self.recent = [r for r in self.recent if now-r['time'] < self.cooldown]
        self.observation_zones = [
            zone for zone in self.observation_zones if now < zone['until']
        ]
        self.history = {k: v for k, v in self.history.items() if now-v['seen'] < 120.0}
        items = list(items)
        guarded_items = self._follow_completion_guards(items, now)
        previous_tracks = {k: dict(v) for k, v in self.tracks.items()}
        available = set(self.tracks)
        output = []
        # Largest boxes first makes association independent of YOLO box order.
        for item_index, (box, name) in sorted(enumerate(items), key=lambda item: -(item[1][0][2]-item[1][0][0])*(item[1][0][3]-item[1][0][1])):
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
            location_blocked = (
                pose is not None
                and any(
                    math.hypot(
                        pose[0] - zone['pose'][0],
                        pose[1] - zone['pose'][1],
                    ) <= self.observation_zone_radius
                    for zone in self.observation_zones
                )
            )
            blocked = blocked or item_index in guarded_items or location_blocked
            eligible = (self.in_observation_view(box, name, height) and area >= self.min_area
                        and track['hits'] >= self.min_hits and not blocked)
            output.append((box, name, key, eligible))
        return output

    def observation_completed(self, key, now, pose=None):
        """Suppress the observation-finish area regardless of YOLO class changes."""
        if key in self.completed_ids:
            return False
        self.completed_ids.add(key)

        zone_added = False
        if (pose is not None
                and self.observation_zone_radius > 0
                and self.observation_zone_sec > 0):
            self.observation_zones.append(dict(
                pose=tuple(pose),
                until=now + self.observation_zone_sec,
            ))
            zone_added = True

        # Keep the short image-space guard as an additional fallback when the
        # final detection is still fresh.
        guard_added = False
        track = self.history.get(key)
        if track is not None and 0 <= now-track['seen'] <= 1.0:
            self.completion_guards.append(dict(
                box=tuple(track['box']),
                seen=track['seen'],
                until=now + 10.0,
            ))
            guard_added = True

        return zone_added or guard_added

    @staticmethod
    def _nearby_box(previous, current):
        """Bound center drift and size change relative to the previous box."""
        pw, ph = previous[2]-previous[0], previous[3]-previous[1]
        cw, ch = current[2]-current[0], current[3]-current[1]
        if min(pw, ph, cw, ch) <= 0:
            return False
        dx = ((current[0]+current[2])-(previous[0]+previous[2])) / (2*pw)
        dy = ((current[1]+current[3])-(previous[1]+previous[3])) / (2*ph)
        return (.5 <= cw/pw <= 2.0 and .5 <= ch/ph <= 2.0
                and math.hypot(dx, dy) <= .5)

    def _follow_completion_guards(self, items, now):
        guards = [g for g in self.completion_guards
                  if now < g['until'] and 0 <= now-g['seen'] < 2.0]
        proposals = []
        for g in guards:
            strong = [i for i, (box, _) in enumerate(items)
                      if iou(g['box'], box) >= .3]
            # Prefer overlap; use bounded geometry only when overlap fails.
            proposals.append(strong or [i for i, (box, _) in enumerate(items)
                                        if self._nearby_box(g['box'], box)])
        retained, blocked = [], set()
        for g, candidates in zip(guards, proposals):
            if not candidates:
                retained.append(g)  # Brief absence; never block an old region.
                continue
            if len(candidates) != 1:
                continue  # Ambiguity ends this temporary association.
            index = candidates[0]
            if sum(index in other for other in proposals) != 1:
                continue
            g.update(box=tuple(items[index][0]), seen=now)
            retained.append(g)
            blocked.add(index)
        self.completion_guards = retained
        return blocked

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
