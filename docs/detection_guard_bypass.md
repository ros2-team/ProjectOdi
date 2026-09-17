# Observation guard comparison

Current defaults:
- label_identity_enabled: true — retain ID/handled state across unambiguous overlapping label changes (IoU >= 0.3, last seen within 3 seconds).
- recent_detection_guards_enabled: false — do not hold observations during turns/settling and do not connect non-overlapping boxes across turns.

These are independent startup parameters. Restart the project after changing odi.yaml; there is no live parameter callback. Setting label_identity_enabled to false restores the previous full diagnostic bypass of recent additions.

Existing same-class IoU tracking, handled records, 90-second recent-encounter policy, 3-hit stability, ROI, exclusions, confidence, size filters and 640x480 camera configuration remain unchanged. Base movement safety is unchanged.

Offline callbacks verify label-only mode suppresses a handled overlapping object after relabeling, still emits a distinct object with no fresh odometry or while turning, and keeps turn fallback disabled. Existing turn and lifecycle tests also pass. Actual field behavior still requires testing. Geometric association can confuse objects replacing one another at the same image location; this is not appearance recognition.
