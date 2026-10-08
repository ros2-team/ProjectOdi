# Immediate repeat suppression

minimum_detection_frames is now 2 in node defaults, policy defaults and odi.yaml. Minimum area remains 1%, distance remains 2.0m, camera remains 320x240. Label identity remains enabled; turn hold and turn fallback remain disabled.

On a successful /observation/result belonging to the current session, freeze the target's most recent tracked box, only if seen within one second of result receipt. Suppress observation eligibility of any box with IoU >= 0.3 for three seconds, regardless of class or ID. Keep detection and preview publishing. The timer uses monotonic result receipt time. Repeated results do not extend it; a new session clears it. No global pause or larger robot-position exclusion radius is added.

The guard does not mark newly overlapping IDs permanently handled and does not reset the original 90-second encounter cooldown. It expires independently. If the target ID was lost, or its last box is stale, skip instead of using an old first-encounter location. A different object replacing the target at the same image position can be blocked briefly; large viewpoint changes cannot be matched by this guard.

Offline tests verify two-hit admission, latest rather than first box, changed-ID/name suppression, fixed expiry, stale/missing target, small overlaps, session reset and actual result/image callbacks. Hardware confirmation remains necessary.
