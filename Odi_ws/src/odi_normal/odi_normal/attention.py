"""Image-only attention admission; does not claim to identify trash or distance."""
import math

class Attention:
    def __init__(self, width=320, height=240, classes=('bottle', 'backpack', 'cup'),
                 confidence=0.6, minimum_area=0.02, cooldown=60.0):
        self.width, self.height = width, height
        self.classes = set(classes)
        self.confidence, self.minimum_area, self.cooldown = confidence, minimum_area, cooldown
        self.samples = {}
        self.handled = {}
        self.latest = None

    def observe(self, obj, now):
        if (obj.class_name not in self.classes or not math.isfinite(obj.confidence)
                or obj.confidence < self.confidence
                or obj.width <= 0 or obj.height <= 0
                or not 0 <= obj.center_x < self.width or not 0 <= obj.center_y < self.height
                or obj.width * obj.height / (self.width*self.height) < self.minimum_area
                or now - self.handled.get(obj.class_name, -math.inf) < self.cooldown):
            return False
        # Bound memory and require stable, distinct inference updates.
        self.samples = {k:v for k,v in self.samples.items() if now-v[0] < 1.0}
        previous = self.samples.get(obj.detection_id)
        count = 1
        if previous and 0.05 <= now-previous[0] <= 0.8:
            if math.hypot(obj.center_x-previous[2], obj.center_y-previous[3]) < self.width*.2:
                count = previous[1]+1
        self.samples[obj.detection_id] = (now, count, obj.center_x, obj.center_y)
        if count >= 3:
            self.latest = (now, obj)
            return True
        return False

    def candidate(self, now):
        if self.latest and now-self.latest[0] < 0.6:
            return self.latest[1]
        return None

    def handled_target(self, obj, now):
        self.handled[obj.class_name] = now
        self.latest = None
        self.samples.clear()

def tracking_angles(obj, width, height, pan, tilt, pan_sign, tilt_sign,
                    pan_limits, tilt_limits):
    # At most 3 degrees per acknowledged step, with a central dead band.
    def step(error):
        return 0.0 if abs(error) < 0.07 else max(-3.0, min(3.0, error*8.0))
    px = (obj.center_x-width/2)/(width/2)
    py = (obj.center_y-height/2)/(height/2)
    return (max(pan_limits[0], min(pan_limits[1], pan + pan_sign*step(px))),
            max(tilt_limits[0], min(tilt_limits[1], tilt + tilt_sign*step(py))),
            abs(px) < .1 and abs(py) < .1)

