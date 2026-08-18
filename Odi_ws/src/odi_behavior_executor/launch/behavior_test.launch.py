from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package = "odi_mission_manager",
            executable = "mission_manager",
            output = "screen",
        ),
        Node(
            package = "odi_behavior_executor",
            executable = "behavior_executor",
            output = "screen",
        ),
        Node(
            package = "odi_behavior_executor",
            executable = "dummy_perception",
            output = "screen",
        ),
        Node(
            package = "odi_behavior_executor",
            executable = "dummy_curiosity",
            output = "screen",
        ),
        Node(
            package = "odi_behavior_executor",
            executable = "dummy_observation",
            output = "screen",
        ),
        Node(
            package = "odi_behavior_executor",
            executable = "dummy_exploration",
            output = "screen",
        ),
        Node(
            package = "odi_behavior_executor",
            executable = "dummy_returnhome",
            output = "screen",
        ),
    ])
