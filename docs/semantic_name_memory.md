# Semantic names in memory lookup

World Memory now retrieves an explicit doll-family alias group, including
`doll`, `plush doll`, `stuffed doll`, `plush toy`, `stuffed toy`, `stuffed animal`,
`plush animal`, `soft toy`, and the Korean names listed in `object_names.py`.
Case, outer whitespace, hyphens and underscores are normalized for lookup.
Unlisted names still use an exact normalized comparison; no substring matching.

Existing database names and displayed diary names are preserved. No migration
or data deletion is needed. Name aliases only broaden retrieval: Curiosity's
existing feature similarity threshold and scoring still decide familiarity and
whether to observe. Different dolls can remain new objects.

The change-comparison baseline is the latest returned record that actually
passes the identity similarity threshold, not an unrelated newest doll. Visit
count uses only these matching records; compared count includes all candidates.

Limits: generated color/material/shape descriptions can still vary enough to
fail similarity; the unchanged result limit can omit older records. This is not
visual identity recognition and does not guarantee every repeat is suppressed.
First-encounter photography still runs before semantic memory lookup.

Offline test: `python -m unittest discover -s tests -p test_semantic_name_memory.py -v`
SQL filtering is exercised with SQLite-compatible functions and adapted
placeholders; live MySQL/ROS integration and physical robot tests remain needed.

Field check: keep an old `doll` observation, encounter it as `plush doll`, and
check the World Memory result count and Curiosity similarity/action. Compare a
different doll as well to verify it is not ignored solely because of its name.
