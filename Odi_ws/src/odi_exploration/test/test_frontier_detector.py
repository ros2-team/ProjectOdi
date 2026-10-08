"""Unit tests for frontier detection and candidate scoring."""

import math

import pytest
from geometry_msgs.msg import Pose
from nav_msgs.msg import MapMetaData, OccupancyGrid

from odi_exploration.frontier_detector import FrontierDetector


def create_test_map(
    width: int,
    height: int,
    resolution: float = 1.0,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> OccupancyGrid:
    """Create an OccupancyGrid initialized entirely as unknown space."""
    map_message = OccupancyGrid()
    map_message.header.frame_id = 'map'

    map_message.info = MapMetaData()
    map_message.info.width = width
    map_message.info.height = height
    map_message.info.resolution = resolution
    map_message.info.origin = Pose()
    map_message.info.origin.position.x = origin_x
    map_message.info.origin.position.y = origin_y
    map_message.info.origin.orientation.w = 1.0

    map_message.data = [-1] * (width * height)
    return map_message


def set_cell(
    map_message: OccupancyGrid,
    x: int,
    y: int,
    value: int,
) -> None:
    """Set one OccupancyGrid cell to the supplied occupancy value."""
    index = y * map_message.info.width + x
    data = list(map_message.data)
    data[index] = value
    map_message.data = data


def set_free_rectangle(
    map_message: OccupancyGrid,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
) -> None:
    """Mark an inclusive rectangular section of the test map as free."""
    for y in range(start_y, end_y + 1):
        for x in range(start_x, end_x + 1):
            set_cell(map_message, x, y, FrontierDetector.FREE)


def test_empty_map_returns_no_candidates():
    """An empty map must not produce a navigation candidate."""
    detector = FrontierDetector(minimum_frontier_size=1)
    map_message = create_test_map(width=0, height=0)

    candidates = detector.detect(
        map_message,
        robot_x=0.0,
        robot_y=0.0,
    )

    assert candidates == []


def test_invalid_map_data_size_raises_error():
    """A malformed OccupancyGrid must be rejected explicitly."""
    detector = FrontierDetector(minimum_frontier_size=1)
    map_message = create_test_map(width=5, height=5)
    map_message.data = [-1, -1]

    with pytest.raises(ValueError, match='data size does not match'):
        detector.detect(
            map_message,
            robot_x=0.0,
            robot_y=0.0,
        )


def test_detects_frontier_around_free_area():
    """The free-space boundary adjoining unknown space forms a frontier."""
    detector = FrontierDetector(minimum_frontier_size=5)
    map_message = create_test_map(width=10, height=10)
    set_free_rectangle(map_message, 2, 2, 7, 7)

    candidates = detector.detect(
        map_message,
        robot_x=4.5,
        robot_y=4.5,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.size == 20

    selected_index = (
        candidate.cell_y * map_message.info.width
        + candidate.cell_x
    )
    assert map_message.data[selected_index] == FrontierDetector.FREE

    frontier_cells = detector.find_frontier_cells(map_message)
    assert (candidate.cell_x, candidate.cell_y) in frontier_cells


def test_ignores_small_frontier_cluster():
    """A frontier smaller than the configured threshold is ignored."""
    detector = FrontierDetector(minimum_frontier_size=10)
    map_message = create_test_map(width=6, height=6)
    set_free_rectangle(map_message, 2, 2, 3, 3)

    candidates = detector.detect(
        map_message,
        robot_x=0.0,
        robot_y=0.0,
    )

    assert candidates == []


def test_converts_cell_to_world_coordinates():
    """A map cell center is converted using origin and resolution."""
    map_message = create_test_map(
        width=10,
        height=10,
        resolution=0.5,
        origin_x=-2.0,
        origin_y=-1.0,
    )

    world_x, world_y = FrontierDetector.cell_to_world(
        cell_x=4,
        cell_y=6,
        map_message=map_message,
    )

    assert math.isclose(world_x, 0.25)
    assert math.isclose(world_y, 2.25)


def test_candidates_are_sorted_by_score():
    """Multiple frontier candidates are returned in descending score order."""
    detector = FrontierDetector(minimum_frontier_size=1)
    map_message = create_test_map(width=15, height=10)
    set_free_rectangle(map_message, 1, 2, 3, 4)
    set_free_rectangle(map_message, 10, 2, 13, 6)

    candidates = detector.detect(
        map_message,
        robot_x=0.0,
        robot_y=3.0,
    )

    assert len(candidates) == 2
    assert candidates[0].score >= candidates[1].score


def test_score_balances_information_gain_and_distance():
    """Large frontiers may outrank nearer ones when gain is worthwhile."""
    detector = FrontierDetector(
        minimum_frontier_size=1,
        information_gain_weight=1.0,
        distance_weight=0.1,
    )
    map_message = create_test_map(width=20, height=12)
    set_free_rectangle(map_message, 1, 4, 2, 5)
    set_free_rectangle(map_message, 10, 2, 16, 8)

    candidates = detector.detect(
        map_message,
        robot_x=0.0,
        robot_y=5.0,
    )

    assert len(candidates) == 2
    assert candidates[0].size > candidates[1].size
    assert candidates[0].distance > candidates[1].distance
