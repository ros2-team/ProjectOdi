"""Launch all ODI application nodes for integrated robot testing."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Create the ODI application launch description."""
    bringup_share = get_package_share_directory('odi_bringup')
    parameters_file = os.path.join(
        bringup_share,
        'config',
        'odi.yaml',
    )

    use_detection = LaunchConfiguration('use_detection')
    use_world_memory = LaunchConfiguration('use_world_memory')

    return LaunchDescription([
        Node(package='odi_normal', executable='normal_node', name='normal_node',
             output='screen', parameters=[parameters_file]),
        DeclareLaunchArgument(
            'use_detection',
            default_value='true',
            description='Run the YOLO detector',
        ),
        DeclareLaunchArgument(
            'use_world_memory',
            default_value='true',
            description='Run database-backed world memory',
        ),
        Node(
            package='odi_mission_manager',
            executable='mission_manager',
            name='mission_manager_node',
            output='screen',
        ),
        Node(
            package='odi_behavior_executor',
            executable='behavior_executor',
            name='behavior_executor_node',
            output='screen',
        ),
        Node(
            package='odi_detection',
            executable='yolo_node',
            name='yolo_node',
            output='screen',
            parameters=[parameters_file],
            condition=IfCondition(use_detection),
        ),
        Node(
            package='odi_exploration',
            executable='exploration_node',
            name='exploration_node',
            output='screen',
            parameters=[parameters_file],
        ),
        Node(
            package='odi_first_encounter',
            executable='first_encounter_node',
            name='first_encounter_node',
            output='screen',
        ),
        Node(
            package='odi_curiosity_engine',
            executable='curiosity_engine_node',
            name='curiosity_engine_node',
            output='screen',
        ),
        Node(
            package='odi_observation',
            executable='observation_locator',
            name='observation_locator',
            output='screen',
        ),
        Node(
            package='odi_observation',
            executable='observation_node',
            name='observation_node',
            output='screen',
        ),
        Node(
            package='odi_return_home',
            executable='return_home_node',
            name='return_home_node',
            output='screen',
            parameters=[parameters_file],
        ),
        Node(
            package='odi_reflection',
            executable='reflection_node',
            name='reflection_node',
            output='screen',
        ),
        Node(
            package='odi_world_memory',
            executable='world_memory_node',
            name='world_memory_node',
            output='screen',
            condition=IfCondition(use_world_memory),
        ),
    ])
