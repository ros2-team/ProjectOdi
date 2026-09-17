# Camera stream: restored to 320x240

The 640x480 field trial showed intermittent lag. Restore the prior stream to compare responsiveness; this does not prove whether CPU load or transport caused the lag.

system_control.py requests YUYV 320x240. Normal-mode YAML and node defaults use 320x240. ObservationLocator restores fx=270.2 and cx=157.2. Compressed transport, YOLO filters and the current identity settings are unchanged: label_identity_enabled=true, recent_detection_guards_enabled=false.

Rebuild odi_bringup, odi_normal and odi_observation. Stop both old launch commands, then restart odi_robot_start and odi_project_start once each. Camera restart is required for launch dimensions to take effect. No Arduino upload is needed. Confirm /camera width=320 and height=240.

This restores the existing pixel-bearing assumptions, not a new calibration. The previously reported empty camera_info is not fixed by lowering resolution; YOLO's calibrated LiDAR projection still requires valid calibration.

Offline tests cover locator bearing, normal attention and head tracking. Verify camera latency and observation start on the robot.
