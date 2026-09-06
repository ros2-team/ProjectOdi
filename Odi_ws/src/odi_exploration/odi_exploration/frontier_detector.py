import math

from collections import deque
from dataclasses import dataclass

from nav_msgs.msg import OccupancyGrid


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

    FREE = 0

    UNKNOWN = -1

    def __init__(
            self,
            minimum_frontier_size: int = 5,
    ) -> None:

        if minimum_frontier_size < 1:
            raise ValueError(
                'minimum_frontier_size must be at least 1'
            )
        self.minimum_frontier_size = (
            minimum_frontier_size
        )

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

        if data[index] != self.FREE:
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
            score = (
                len(cluster) / max(distance, 0.1)
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
            for cell_y, _ in cluster
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

        resolution = map_message.info.resolution
        origin = map_message.info.origin.position

        world_x = (
            origin.x + (cell_x + 0.5) * resolution
        )

        world_y = (
            origin.y + (cell_y + 0.5) * resolution
        )
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
