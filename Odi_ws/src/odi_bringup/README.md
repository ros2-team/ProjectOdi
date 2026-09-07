# ODI Bringup

This package starts the complete ODI robot system.

## Process layout

- Raspberry Pi: TurtleBot3 bringup and camera
- Main PC: Cartographer SLAM, Nav2, and all ODI application nodes

The Raspberry Pi processes run in a tmux session named `odi_robot`.
Stopping `odi_start` with `Ctrl+C` also stops that remote session.

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

## Start everything

Load the project environment variables first when OpenAI or database settings
are stored in an env file.

```bash
cd ~/ProjectOdi_assembly
source .env
source Odi_ws/install/setup.bash

ros2 run odi_bringup odi_start
```

Extra ROS launch arguments may be appended:

```bash
ros2 run odi_bringup odi_start use_detection:=false
```

To leave the Raspberry Pi bringup and camera running after the local launch
exits:

```bash
ros2 run odi_bringup odi_start --keep-robot-running
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

## Main PC only

For diagnostics, run SLAM, Nav2, and ODI without starting Raspberry Pi
processes:

```bash
ros2 launch odi_bringup odi_system.launch.py
```

Individual parts can be disabled:

```bash
ros2 launch odi_bringup odi_system.launch.py \
  use_slam:=true \
  use_nav2:=true \
  use_application:=false
```
