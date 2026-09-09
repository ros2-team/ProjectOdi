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

## Field tuning: mode display, observation candidates and return home

`BehaviorState.exploration_mode` carries `FRONTIER`/`ROAM` to the web bridge.
This changes the ROS message interface: stop the application and rebuild the
whole workspace (`colcon build --symlink-install`), source the new installation,
and restart all ODI application nodes together. Refresh the web page.

Candidate parameters in `config/odi.yaml`:

| Parameter | Initial value | Meaning |
| --- | --- | --- |
| `minimum_box_area_ratio` | `0.025` | Candidate box must occupy at least 2.5% of the image. This is not a metric distance. |
| `minimum_detection_frames` | `3` | Require repeated matched detections before sending a candidate. |
| `excluded_classes` | `['tv', 'laptop']` | Excluded from observation candidates; still visible in the YOLO preview. |
| `reobserve_cooldown_sec` | `60.0` | After an encounter attempt, suppress the same class within 0.5m of the recent robot position. This also suppresses a second same-class object at that position temporarily. |
| `maximum_observation_distance` | `2.0` | Reject farther candidates when calibrated scan projection provides an estimate; `0.0` disables this check. |
| `camera_info_topic` | `/camera/camera_info` | Must match the image camera's calibrated CameraInfo publisher. |

Short-term box overlap matching retains IDs when YOLO changes box order.
It is not persistent identity tracking: a long occlusion or a large viewpoint
change can create a new ID. The encounter cooldown is reset for each mission.

Distance checks need CameraInfo matching the image dimensions with zero distortion,
scan-to-camera TF, and image/scan timestamps within 0.25 seconds. Points are projected
inside the central half of the box; at least three consistent returns are required.
Without this association the metric distance check is skipped; visual filters remain
active. A periodic warning identifies missing projection data. A 2D laser can still
see a background surface rather than a raised object, so verify this association on
the robot before relying on distance filtering. Objects beyond the room are not
guaranteed to be excluded solely by this heuristic.

Return Home uses `home_arrival_radius: 0.3` and `home_arrival_hold_sec: 0.8`.
With fresh map TF inside that radius for the hold duration, it cancels the Nav2
goal to avoid continued final-heading correction. Completion requires the terminal
Nav2 result, fresh odometry indicating low linear/angular velocity for 0.4 seconds,
and a final position still inside the radius. Missing/stale TF or odometry never
counts as arrival. `home_arrival_radius: 0.0` disables the proximity shortcut.
Other Nav2 goals and their tolerances are unchanged.

Robot checks: confirm the web changes to ROAM, place a near bag and distant TV in
view, and check both filtering and repeated-view behavior. During return, confirm
that arrival is reported after stopping; if it fails, capture the Return Home
distance/recovery log and any TF/odometry error. The defaults are initial tuning
values and require validation in the actual room.
