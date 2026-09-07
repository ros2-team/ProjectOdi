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
