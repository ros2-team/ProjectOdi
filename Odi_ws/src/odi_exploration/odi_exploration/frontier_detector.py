import math

from collections import deque
from dataclasses import dataclass

from nav_msgs.msg import OccupancyGrid


class _FreeCellRange:
    """Compatibility sentinel that treats low occupancy probabilities as free.

    ExplorationNode historically compares map values directly with
    ``FrontierDetector.FREE``.  Cartographer can publish known free cells with
    occupancy probabilities other than exactly zero, so keep those callers
    working while applying the same 0..49 free-space rule everywhere.
    """

    def __eq__(self, value) -> bool:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return False
        return 0 <= numeric < 50

    def __ne__(self, value) -> bool:
        return not self.__eq__(value)

    def __repr__(self) -> str:
        return 'free[0..49]'


@dataclass(frozen=True)
class FrontierCandidate:
    cell_x: int
    cell_y: int

    world_x: float
    world_y: float

    size: int
    distance: float
    score: float


class FrontierDetector:

    # Cartographer OccupancyGrid values are probabilities.  A known cell below
    # the occupied threshold is traversable; requiring exactly 0 makes a fresh
    # map appear to have no frontier even though free space already exists.
    FREE = _FreeCellRange()

    UNKNOWN = -1

    def __init__(
            self,
            minimum_frontier_size: int = 5,
            information_gain_weight: float = 1.0,
            distance_weight: float = 0.35,
    ) -> None:

        if minimum_frontier_size < 1:
            raise ValueError(
                'minimum_frontier_size must be at least 1'
            )
        self.minimum_frontier_size = (
            minimum_frontier_size
        )
        self.information_gain_weight = information_gain_weight
        self.distance_weight = distance_weight

    @staticmethod
    def is_free_value(value: int) -> bool:
        """Return True for known traversable occupancy values."""
        return value != FrontierDetector.UNKNOWN and 0 <= value < 50

    def is_frontier_cell(
            self,
            x: int,
            y: int,
            data: list[int],
            width: int,
            height: int,
    ) -> bool:

        index = self.get_index(
            x,
            y,
            width,
        )

        if not self.is_free_value(data[index]):
            return False

        for neighbor_x, neighbor_y in (
            self.get_neighbors(
                x,
                y,
                width,
                height,
            )
        ):
            neighbor_index = self.get_index(
                neighbor_x,
                neighbor_y,
                width,
            )
            if data[neighbor_index] == self.UNKNOWN:
                return True

        return False

    def find_frontier_cells(
            self,
            map_message: OccupancyGrid,
    ) -> set[tuple[int, int]]:

        width = map_message.info.width
        height = map_message.info.height
        data = list(map_message.data)

        frontier_cells = set()

        for y in range(height):
            for x in range(width):
                if self.is_frontier_cell(
                    x,
                    y,
                    data,
                    width,
                    height,
                ):
                    frontier_cells.add((x, y))

        return frontier_cells

    def cluster_frontier_cells(
        self,
        frontier_cells: set[tuple[int, int]],
        width: int,
        height: int,
    ) -> list[list[tuple[int, int]]]:

        remaining_cells = set(frontier_cells)
        clusters = []

        while remaining_cells:

            start_cell = remaining_cells.pop()

            queue = deque([start_cell])
            cluster = [start_cell]

            while queue:

                current_x, current_y = (
                    queue.popleft()
                )

                for neighbor in self.get_neighbors(
                    current_x,
                    current_y,
                    width,
                    height,
                ):
                    if neighbor not in remaining_cells:
                        continue

                    remaining_cells.remove(neighbor)
                    queue.append(neighbor)
                    cluster.append(neighbor)

            if (
                len(cluster)
                >= self.minimum_frontier_size
            ):
                clusters.append(cluster)

        return clusters

    def detect(
            self,
            map_message: OccupancyGrid,
            robot_x: float,
            robot_y: float,
    ) -> list[FrontierCandidate]:

        width = map_message.info.width
        height = map_message.info.height

        if width <= 0 or height <= 0:
            return []

        expected_cell_count = width * height

        if (
            len(map_message.data)
            != expected_cell_count
        ):
            raise ValueError(
                'OccupancyGrid data size does not match width and height'
            )

        frontier_cells = self.find_frontier_cells(map_message)
        clusters = (
            self.cluster_frontier_cells(
                frontier_cells,
                width,
                height,
            )
        )
        candidates = []

        for cluster in clusters:
            cell_x, cell_y = (
                self.select_cluster_center(
                    cluster
                )
            )
            world_x, world_y = (
                self.cell_to_world(
                    cell_x,
                    cell_y,
                    map_message,
                )
            )
            distance = math.hypot(
                world_x - robot_x,
                world_y - robot_y,
            )
            information_gain = (
                len(cluster)
                * map_message.info.resolution
            )
            score = (
                self.information_gain_weight
                * information_gain
                - self.distance_weight
                * distance
            )
            candidates.append(
                FrontierCandidate(
                    cell_x=cell_x,
                    cell_y=cell_y,
                    world_x=world_x,
                    world_y=world_y,
                    size=len(cluster),
                    distance=distance,
                    score=score,
                )
            )

        candidates.sort(
            key=lambda candidate: candidate.score,
            reverse=True,

        )
        return candidates

    @staticmethod
    def select_cluster_center(
        cluster: list[tuple[int, int]],
    ) -> tuple[int, int]:

        average_x = sum(
            cell_x
            for cell_x, _ in cluster
        ) / len(cluster)

        average_y = sum(
            cell_y
            for _, cell_y in cluster
        ) / len(cluster)

        return min(
            cluster,
            key=lambda cell: (
                (cell[0] - average_x) ** 2
                + (cell[1] - average_y) ** 2
            ),
        )

    @staticmethod
    def cell_to_world(
        cell_x: int,
        cell_y: int,
        map_message: OccupancyGrid,
    ) -> tuple[float, float]:
        """Convert a grid cell center to map-frame coordinates.

        OccupancyGrid origin is a full pose, not only a translation.  Applying
        its yaw keeps goals correct even when a newly-created map is rotated
        relative to the previous odom frame.
        """
        resolution = map_message.info.resolution
        origin = map_message.info.origin

        local_x = (cell_x + 0.5) * resolution
        local_y = (cell_y + 0.5) * resolution

        q = origin.orientation
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)

        world_x = origin.position.x + cos_yaw * local_x - sin_yaw * local_y
        world_y = origin.position.y + sin_yaw * local_x + cos_yaw * local_y
        return world_x, world_y

    @staticmethod
    def is_inside_map(
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> bool:

        return (
            0 <= x < width
            and 0 <= y < height
        )

    @staticmethod
    def get_index(
        x: int,
        y: int,
        width: int,
    ) -> int:

        return y * width + x

    @staticmethod
    def get_neighbors(
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> list[tuple[int, int]]:

        neighbors = []

        for offset_y in (-1, 0, 1):
            for offset_x in (-1, 0, 1):
                if offset_x == 0 and offset_y == 0:
                    continue
                neighbor_x = x + offset_x
                neighbor_y = y + offset_y

                if FrontierDetector.is_inside_map(
                    neighbor_x,
                    neighbor_y,
                    width,
                    height,
                ):
                    neighbors.append(
                        (
                            neighbor_x,
                            neighbor_y,
                        )
                    )

        return neighbors
