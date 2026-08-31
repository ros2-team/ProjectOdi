import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')

    cartographer = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('turtlebot3_cartographer'),
            'launch', 'cartographer.launch.py')),
        launch_arguments={'use_sim_time': use_sim_time}.items()
    )

    map_trinary = Node(
        package='perception',
        executable='map_trinary_node',
        parameters=[{'use_sim_time': use_sim_time}],
        output='screen',
    )

    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('nav2_bringup'),
            'launch', 'navigation_launch.py')),
        launch_arguments={'use_sim_time': use_sim_time}.items()
    )

    # explore = IncludeLaunchDescription(
    #     PythonLaunchDescriptionSource(os.path.join(
    #         get_package_share_directory('explore_lite'),
    #         'launch', 'explore.launch.py')),
    #     launch_arguments={'use_sim_time': use_sim_time}.items()
    # )

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        cartographer,
        map_trinary,
        TimerAction(period=5.0, actions=[nav2]),
        # TimerAction(period=10.0, actions=[explore]),
    ])