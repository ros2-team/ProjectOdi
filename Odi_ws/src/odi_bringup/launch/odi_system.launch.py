"""Launch SLAM, Nav2, and all ODI application nodes on the main PC."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description() -> LaunchDescription:
    """Create the complete main-PC launch description."""
    bringup_share = get_package_share_directory('odi_bringup')
    cartographer_share = get_package_share_directory(
        'turtlebot3_cartographer'
    )
    nav2_share = get_package_share_directory('nav2_bringup')

    use_sim_time = LaunchConfiguration('use_sim_time')
    robot_model = LaunchConfiguration('robot_model')
    use_slam = LaunchConfiguration('use_slam')
    use_nav2 = LaunchConfiguration('use_nav2')
    use_application = LaunchConfiguration('use_application')
    use_detection = LaunchConfiguration('use_detection')
    use_world_memory = LaunchConfiguration('use_world_memory')

    slam_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                cartographer_share,
                'launch',
                'cartographer.launch.py',
            )
        ),
        launch_arguments={
            'use_sim_time': use_sim_time,
        }.items(),
        condition=IfCondition(use_slam),
    )

    navigation_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                nav2_share,
                'launch',
                'navigation_launch.py',
            )
        ),
        launch_arguments={
            'use_sim_time': use_sim_time,
            'autostart': 'true',
        }.items(),
        condition=IfCondition(use_nav2),
    )

    application_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                bringup_share,
                'launch',
                'odi_integration.launch.py',
            )
        ),
        launch_arguments={
            'use_detection': use_detection,
            'use_world_memory': use_world_memory,
        }.items(),
        condition=IfCondition(use_application),
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Use a simulation clock',
        ),
        DeclareLaunchArgument(
            'robot_model',
            default_value='waffle_pi',
            description='TurtleBot3 model',
        ),
        DeclareLaunchArgument(
            'use_slam',
            default_value='true',
            description='Run TurtleBot3 Cartographer',
        ),
        DeclareLaunchArgument(
            'use_nav2',
            default_value='true',
            description='Run the Nav2 navigation stack',
        ),
        DeclareLaunchArgument(
            'use_application',
            default_value='true',
            description='Run all ODI application nodes',
        ),
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
        SetEnvironmentVariable(
            name='TURTLEBOT3_MODEL',
            value=robot_model,
        ),
        slam_launch,
        TimerAction(
            period=3.0,
            actions=[navigation_launch],
        ),
        TimerAction(
            period=6.0,
            actions=[application_launch],
        ),
    ])
