# Temporary post-observation tracking

After a successful observation in the current session, retain the target's
latest box only if it was seen within the last second. Follow its geometry
without requiring the YOLO class or track ID to stay the same.

- Hard expiry: 10 seconds from completion; repeated results do not extend it.
- Loss timeout: 2 seconds since the last matched detection.
- Prefer IoU >= 0.3. Otherwise require width and height ratios between 0.5 and
  2.0 and center displacement <= 0.5 in previous-box-normalized coordinates.
- Update the remembered box after each unique match. Only that detection is
  suppressed; preview and unrelated candidates continue normally.
- Multiple matching boxes, or competing completion guards, end the association.
- Reset with the mission. Existing handled-ID and same-class cooldown policies
  remain independent and may continue suppressing their own matches.

This is geometric tracking, not appearance recognition. A different object
replacing the observed object at a similar position may be suppressed briefly.
A stale/lost completion target cannot seed the guard. Large abrupt displacement
combined with a class change may still break association.

Field check: observe a bottle, let the classifier change its label while the
box shifts/resizes, and check that observation is not immediately repeated.
Then show an unrelated object elsewhere and check that it remains observable.
No camera resolution, motion parameters, or global observation gate were changed.
