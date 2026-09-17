# Diagnostic bypass

recent_detection_guards_enabled defaults to false in yolo_node and odi.yaml. It bypasses turn/settling observation holds, cross-label identity association and turn-based same-label fallback association. It does not bypass base motion safety controls.

Existing same-class IoU tracking, handled records, 90-second recent-encounter policy, 3-hit stability, ROI, class exclusions, confidence and box-size filters remain active. Camera stays 640x480. Repeated observations after label changes may recur during this comparison test.

Offline callback test confirms candidates publish without odometry while bypassed, changed labels get new IDs, and handled same-ID objects remain suppressed. This does not establish the cause of the field failure. Compare a fresh exploration mission before further tuning.

Re-enable only by setting recent_detection_guards_enabled: true in odi.yaml and restarting the project (no live parameter callback).
