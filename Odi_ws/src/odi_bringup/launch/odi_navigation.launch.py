"""Run the installed Nav2 stack with ODI's collision-checked initial rotation."""
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription,
                            OpaqueFunction, RegisterEventHandler)
from launch.event_handlers import OnShutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from odi_bringup.navigation_config import merge_navigation_config


def generate_launch_description():
    # Fail clearly before launching any navigation nodes if the plugin is absent.
    get_package_share_directory('nav2_rotation_shim_controller')
    nav = Path(get_package_share_directory('nav2_bringup'))
    odi = Path(get_package_share_directory('odi_bringup'))
    base = yaml.safe_load((nav / 'params/nav2_params.yaml').read_text())
    overrides = yaml.safe_load((odi / 'config/navigation_overrides.yaml').read_text())
    merged = merge_navigation_config(base, overrides)
    temporary = TemporaryDirectory(prefix='odi-nav2-')
    params = Path(temporary.name) / 'nav2.yaml'
    params.write_text(yaml.safe_dump(merged, sort_keys=False))

    def cleanup(context):
        temporary.cleanup()
        return []

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('autostart', default_value='true'),
        RegisterEventHandler(OnShutdown(on_shutdown=[OpaqueFunction(function=cleanup)])),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(nav / 'launch/navigation_launch.py')),
            launch_arguments={
                'use_sim_time': LaunchConfiguration('use_sim_time'),
                'autostart': LaunchConfiguration('autostart'),
                'params_file': str(params),
            }.items()),
    ])
