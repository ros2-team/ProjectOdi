"""Hold new exploration observations during turns; preserve image/tracking output."""
import math


class TurnGate:
    def __init__(self, start=0.20, stop=0.10, settle=0.5, stale=1.0):
        if not (all(math.isfinite(v) for v in (start, stop, settle, stale))
                and 0 <= stop < start and settle >= 0 and stale > 0):
            raise ValueError('Invalid observation turn thresholds')
        self.start, self.stop, self.settle, self.stale = start, stop, settle, stale
        self.last_turn = None
        self.last = None
        self.turning = True
        self.stable_since = None

    def update(self, angular_speed, now):
        if self.last is None or now - self.last > self.stale or now < self.last:
            self.last_turn = None
            self.turning = True
            self.stable_since = None
        self.last = now
        if not math.isfinite(angular_speed):
            self.last_turn = None
            self.turning = True
            self.stable_since = None
            return
        speed = abs(angular_speed)
        if speed >= self.start or (self.turning and self.last_turn is not None
                                   and speed > self.stop):
            self.last_turn = now
        if speed >= self.start:
            self.turning = True
            self.stable_since = None
        elif speed <= self.stop:
            self.turning = False
            if self.stable_since is None:
                self.stable_since = now
        elif self.stable_since is not None and now - self.stable_since < self.settle:
            # Settling requires a continuous low-speed interval.
            self.stable_since = None

    def allowed(self, now):
        return (self.last is not None and 0 <= now - self.last <= self.stale
                and not self.turning and self.stable_since is not None
                and now - self.stable_since >= self.settle)

    def can_link(self, now):
        """Only a measured turn enables association, never missing odometry."""
        return (self.last is not None and 0 <= now-self.last <= self.stale
                and self.last_turn is not None and 0 <= now-self.last_turn <= 2.0)
