# Short-term identity across base turns

The detector keeps its existing class/IoU association and strong-overlap label
flicker handling. Only when these fail, a recently measured base turn can enable
a same-class association across a large image displacement.

Both the current frame and retained previous tracks must contain exactly one
object of that class. The previous track must be available, last seen at most
2 seconds ago, and not overlap another current box at IoU >= 0.3. Its ID and
handled flag are retained. Ambiguous cases receive a new ID normally.

Turn eligibility requires fresh odometry (within 1 second) and a measured turn
within 2 seconds. Startup, invalid odometry and odometry gaps do not enable it.
Existing turn thresholds (0.20/0.10 rad/s) and observation settling (0.5 seconds)
are unchanged. Tracking continues while new observations are paused.
The 90-second recent-encounter policy, ROI and exclusions are unchanged.

This is a heuristic, not appearance recognition: a different same-class object
entering alone within the short window can still inherit the old ID. A
non-overlapping class change cannot be linked by this fallback. No spatial
exclusion radius was added.

Offline tests cover handled-state retention, disappearance, ambiguity, overlap
priority, stale odometry, expiry, and actual detector callbacks across a turn
and a new mission. ROS timing and physical robot performance need field testing.

Field check: observe an object, turn until it crosses the image, then settle.
Check that no second observation starts. Then approach a different object and
verify normal observation. Also check two same-class objects and a disappearance
longer than 2 seconds; neither should force a fallback association.
