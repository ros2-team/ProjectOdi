# ODI Bringup

This package starts the ODI robot platform and application layers.

## Recommended two-terminal layout

### Terminal 1: robot platform

This command starts TurtleBot3 bringup and camera on the Raspberry Pi, then
Cartographer and Nav2 on the main PC.

```bash
ros2 run odi_bringup odi_robot_start
```

### Terminal 2: ODI application

This command starts mission management, behavior, detection, exploration,
first encounter, observation, return home, reflection, and world memory.

```bash
ros2 run odi_bringup odi_project_start
```

Stop each layer with `Ctrl+C`. Stopping Terminal 1 also stops the Raspberry
Pi tmux session.

## One-time setup

Install tmux on the Raspberry Pi:

```bash
ssh team4@team4.local
sudo apt update
sudo apt install -y tmux
```

Configure SSH key authentication on the main PC to avoid entering a password:

```bash
ssh-keygen -t ed25519
ssh-copy-id team4@team4.local
```

Verify the required main-PC packages:

```bash
ros2 pkg prefix turtlebot3_cartographer
ros2 pkg prefix nav2_bringup
```

## Build

```bash
cd ~/ProjectOdi_assembly/Odi_ws
source /opt/ros/humble/setup.bash

colcon build --symlink-install --packages-select odi_bringup
source install/setup.bash
```

Load the project environment before starting the application layer:

```bash
cd ~/ProjectOdi_assembly
source .env
source Odi_ws/install/setup.bash
```

## Full single-terminal mode

The original all-in-one command remains available:

```bash
ros2 run odi_bringup odi_start
```

Extra ROS launch arguments may be appended:

```bash
ros2 run odi_bringup odi_project_start use_detection:=false
```

## Robot process control

```bash
ros2 run odi_bringup odi_status
ros2 run odi_bringup odi_logs
ros2 run odi_bringup odi_stop
```

When attached to remote tmux logs, press `Ctrl+B`, then `D` to detach
without stopping the robot processes.

The default host is `team4@team4.local`. Override it when needed:

```bash
export ODI_ROBOT_HOST=team4@192.168.0.20
```

## Diagnostic launch

Run only SLAM and Nav2 without Raspberry Pi process control:

```bash
ros2 launch odi_bringup odi_system.launch.py use_application:=false
```

## Repeating missions from the web

- After a completed or failed mission, the diary/dashboard **대기 화면으로**
  button requests `RESET`. The dashboard stays in `RESETTING` until ROS reports
  `RESETTING` followed by `IDLE` with an empty session ID. `START` is blocked
  during this interval; repeated clicks do not enqueue duplicate commands.
- Canceling the preparation screen also requests `RESET`. Returning from an old
  diary while a mission is active only opens the dashboard; it does not cancel
  the active mission.
- A new mission clears detection episodes, discovery records, route history and
  object markers for the live view. Previously saved diaries remain in MySQL.
  The running SLAM map is retained. Starting in an already mapped space may
  therefore switch to `ROAM`; object detection is active in both exploration modes.
- YOLO keeps publishing the camera preview while idle, but only sends mission
  detection batches during `EXPLORING`. It retries every
  `batch_publish_interval_sec` (default `1.0`), and Behavior ignores handled IDs.
  IDs include the session so delayed previous-mission detections are discarded.
- Returning with zero observations saves a short diary stating that no object
  observations were recorded. It skips model generation and completes normally
  only if the diary save succeeds.

After updating, rebuild `odi_behavior_executor`, `odi_detection`,
`odi_reflection` and `odi_bringup`, then restart the application terminal
(`odi_project_start`). Refresh the browser to load the updated JavaScript.

Offline regressions, run from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

These tests use the production callbacks with fake ROS/model/service dependencies.
The HTTP route tests additionally need Flask, flask-sock and PyMySQL from
`web_ws/requirements.txt`; they are explicitly skipped if those packages are absent.
They do not replace hardware testing of navigation, cancellation or camera quality.

For the robot check, repeat **start → return home → diary → dashboard → start**
three times, including one mission with no observations. Verify that the dashboard
waits for reset completion, old markers disappear, and a visible bag can be detected
in the next mission. Also cancel once during preparation and wait for `IDLE` before
starting again.
