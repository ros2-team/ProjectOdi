# Camera stream: 640x480

The remote camera launch in system_control.py now requests YUYV 640x480. The normal node YAML and standalone node defaults use 640x480. Detection boxes and crops continue using the actual incoming dimensions. Compressed transport is unchanged.

ObservationLocator fx/cx are doubled from 270.2/157.2 to 540.4/314.4. This preserves the existing bearing calculation for a 2x image at the same field of view; it is not a new calibration. A different sensor crop/field of view requires calibration.

Restart the camera through odi_robot_start after rebuilding odi_bringup; restarting only odi_project_start does not apply the camera launch change. Stop both old launches before restarting once each. No Uno firmware change is required.

Check /camera width and height are 640 and 480, and inspect /camera/camera_info. Its dimensions and intrinsics must describe the new image; the YOLO LiDAR filter skips projection if dimensions mismatch. Existing calibration files on the Pi are not modified by this change. Verify new camera_info if calibration is loaded via camera_info_url.

Offline validation: equivalent old/new pixel bearings, right-half normal detection admission, normalized head tracking, and existing normal/fresh-mapping/label-flicker tests. Live image rate, camera_info calibration and robot behavior require hardware verification.
