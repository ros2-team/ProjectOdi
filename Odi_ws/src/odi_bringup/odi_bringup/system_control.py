"""One-command launcher for the ODI robot, application, and web dashboard."""

import argparse
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys


DEFAULT_ROBOT_HOST = 'team4@team4.local'
REMOTE_SESSION = 'odi_robot'


def _robot_host() -> str:
    return os.environ.get('ODI_ROBOT_HOST', DEFAULT_ROBOT_HOST)


def _remote_script(action: str) -> str:
    ros_domain_id = shlex.quote(os.environ.get('ROS_DOMAIN_ID', '0'))
    ros_localhost_only = shlex.quote(
        os.environ.get('ROS_LOCALHOST_ONLY', '0')
    )
    setup_commands = (
        'source /opt/ros/humble/setup.bash; '
        'if [ -f "$HOME/turtlebot3_ws/install/setup.bash" ]; '
        'then source "$HOME/turtlebot3_ws/install/setup.bash"; fi; '
        'export TURTLEBOT3_MODEL=waffle_pi; '
        f'export ROS_DOMAIN_ID={ros_domain_id}; '
        f'export ROS_LOCALHOST_ONLY={ros_localhost_only}'
    )

    if action == 'start':
        bringup_command = (
            setup_commands
            + '; exec ros2 launch turtlebot3_bringup robot.launch.py '
            + 'usb_port:=/dev/odi_opencr'
        ).replace('\n', '; ')
        camera_command = (
            setup_commands
            + '; exec ros2 launch turtlebot3_bringup camera.launch.py '
            + 'format:=YUYV width:=320 height:=240'
        ).replace('\n', '; ')

        return f'''set -eu
if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is not installed on the robot" >&2
    exit 2
fi
if tmux has-session -t {REMOTE_SESSION} 2>/dev/null; then
    echo "ODI robot session is already running"
    exit 0
fi
tmux new-session -d -s {REMOTE_SESSION} -n bringup
tmux send-keys -t {REMOTE_SESSION}:bringup {bringup_command!r} C-m
tmux new-window -t {REMOTE_SESSION} -n camera
tmux send-keys -t {REMOTE_SESSION}:camera {camera_command!r} C-m
echo "ODI robot bringup and camera started"
'''

    if action == 'stop':
        return f'''set -eu
if tmux has-session -t {REMOTE_SESSION} 2>/dev/null; then
    tmux send-keys -t {REMOTE_SESSION}:bringup C-c
    tmux send-keys -t {REMOTE_SESSION}:camera C-c
    sleep 1
    tmux kill-session -t {REMOTE_SESSION}
    echo "ODI robot session stopped"
else
    echo "ODI robot session is not running"
fi
'''

    return f'''set -eu
if tmux has-session -t {REMOTE_SESSION} 2>/dev/null; then
    echo "ODI robot session is running"
    tmux list-windows -t {REMOTE_SESSION}
else
    echo "ODI robot session is not running"
    exit 1
fi
'''


def _run_remote(action: str) -> int:
    completed = subprocess.run(
        ['ssh', _robot_host(), 'bash', '-s'],
        input=_remote_script(action),
        text=True,
        check=False,
    )
    return completed.returncode


def _web_run_path() -> Path:
    configured_root = os.environ.get('ODI_PROJECT_ROOT')
    candidates = []
    if configured_root:
        candidates.append(Path(configured_root).expanduser() / 'web_ws' / 'run.py')
    candidates.extend([
        Path.cwd() / 'web_ws' / 'run.py',
        Path.home() / 'ProjectOdi_assembly' / 'web_ws' / 'run.py',
    ])

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    checked = ', '.join(str(path) for path in candidates)
    raise FileNotFoundError(
        'web_ws/run.py was not found. Set ODI_PROJECT_ROOT. '
        f'Checked: {checked}'
    )


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)


def _run_local_stack(
    command: list[str],
    start_web: bool = True,
) -> int:
    web_path = _web_run_path() if start_web else None
    launch_process = None
    web_process = None

    try:
        if web_path is not None:
            web_process = subprocess.Popen(
                [sys.executable, str(web_path)],
                cwd=web_path.parent,
                start_new_session=True,
            )
        launch_process = subprocess.Popen(
            command,
            start_new_session=True,
        )
        return launch_process.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        _stop_process(launch_process)
        _stop_process(web_process)


def _start_system(
    default_launch_arguments: list[str] | None = None,
    start_web: bool = True,
) -> None:
    parser = argparse.ArgumentParser(
        description='Start the complete ODI robot system.'
    )
    parser.add_argument(
        '--keep-robot-running',
        action='store_true',
        help='Do not stop Raspberry Pi nodes when local launch exits.',
    )
    args, launch_arguments = parser.parse_known_args()

    if default_launch_arguments:
        launch_arguments = [*default_launch_arguments, *launch_arguments]

    if _run_remote('start') != 0:
        raise SystemExit('Failed to start Raspberry Pi nodes')

    command = [
        'ros2', 'launch', 'odi_bringup', 'odi_system.launch.py',
        *launch_arguments,
    ]
    try:
        return_code = _run_local_stack(
            command,
            start_web=start_web,
        )
    finally:
        if not args.keep_robot_running:
            _run_remote('stop')

    raise SystemExit(return_code)


def main_start() -> None:
    _start_system()


def main_robot_start() -> None:
    _start_system(
        ['use_application:=false'],
        start_web=False,
    )


def main_project_start() -> None:
    command = [
        'ros2', 'launch', 'odi_bringup', 'odi_integration.launch.py',
        *sys.argv[1:],
    ]
    raise SystemExit(_run_local_stack(command))


def main_stop() -> None:
    raise SystemExit(_run_remote('stop'))


def main_status() -> None:
    raise SystemExit(_run_remote('status'))


def main_logs() -> None:
    command = [
        'ssh', '-t', _robot_host(),
        f'tmux attach-session -t {REMOTE_SESSION}',
    ]
    raise SystemExit(subprocess.call(command))


if __name__ == '__main__':
    sys.exit(main_start())
