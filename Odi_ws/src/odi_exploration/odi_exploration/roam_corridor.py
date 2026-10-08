"""Map-only corridor scoring for local roaming; Nav2 still owns collision checks.

Prefer visible, open destinations instead of requesting detours behind walls.
This is not a replacement for the live Nav2 costmaps or a motion controller.
"""
import math


class RoamCorridor:
    def __init__(self, grid, clearance):
        self.grid = grid
        self.resolution = grid.info.resolution
        self.required = max(0.0, clearance)
        self.preferred = self.required + 0.15
        self.cache = {}
        q = grid.info.origin.orientation
        self.yaw = math.atan2(2 * (q.w*q.z + q.x*q.y),
                              1 - 2 * (q.y*q.y + q.z*q.z))

    def cell(self, x, y):
        origin = self.grid.info.origin.position
        dx, dy = x-origin.x, y-origin.y
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return (math.floor((c*dx+s*dy)/self.resolution),
                math.floor((-s*dx+c*dy)/self.resolution))

    def margin(self, cell):
        """Conservative square clearance, matching exploration's existing check."""
        if cell in self.cache:
            return self.cache[cell]
        x, y = cell
        width, height = self.grid.info.width, self.grid.info.height
        limit = math.ceil(self.preferred/self.resolution)
        value = self.preferred
        for radius in range(limit+1):
            blocked = False
            for dy in range(-radius, radius+1):
                for dx in range(-radius, radius+1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    cx, cy = x+dx, y+dy
                    if not (0 <= cx < width and 0 <= cy < height):
                        blocked = True
                        break
                    occupancy = self.grid.data[cy*width+cx]
                    if occupancy < 0 or occupancy >= 50:
                        blocked = True
                        break
                if blocked:
                    break
            if blocked:
                value = -1.0 if radius == 0 else (radius-1)*self.resolution
                break
        self.cache[cell] = value
        return value

    def score(self, start_x, start_y, goal_x, goal_y):
        """Return openness in [0, 1], or None for an unsuitable corridor.

        If already inside the preferred safety margin, allow only a corridor
        whose clearance never decreases until it reaches the required margin.
        It must leave this initial zone within 0.5 m. Never exempt occupied or
        unknown cells, and never command a direct escape velocity.
        """
        distance = math.hypot(goal_x-start_x, goal_y-start_y)
        count = max(1, math.ceil(distance/(self.resolution*0.5)))
        previous = self.margin(self.cell(start_x, start_y))
        if previous < 0:
            return None
        escaped = previous + 1e-9 >= self.required
        margins = []
        last_cell = None
        for i in range(count+1):
            fraction = i/count
            cell = self.cell(start_x+(goal_x-start_x)*fraction,
                             start_y+(goal_y-start_y)*fraction)
            margin = self.margin(cell)
            if margin < 0:
                return None
            if not escaped:
                if margin + 1e-9 < previous:
                    return None
                escaped = margin + 1e-9 >= self.required
                if not escaped and distance*fraction >= 0.5:
                    return None
            elif margin + 1e-9 < self.required:
                return None
            # Guard diagonal corner crossings as well as sampled center cells.
            if last_cell is not None and cell[0] != last_cell[0] and cell[1] != last_cell[1]:
                threshold = min(previous, self.required)
                if any(self.margin(side)+1e-9 < threshold or self.margin(side) < 0
                       for side in ((cell[0], last_cell[1]), (last_cell[0], cell[1]))):
                    return None
            margins.append(min(1.0, margin/self.preferred))
            previous, last_cell = margin, cell
        if not escaped:
            return None
        return sum(margins)/len(margins)
