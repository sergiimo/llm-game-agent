# Tracker-only Tara navigation design

**Intent:** Remove redundant Tara appearance-vector guesses from navigation so they cannot reject visibly safe
waypoints or inflate every gameplay observation.

**Goal:** Region vector scopes contain only world objects. Tara's centre-seeded feet tracker is the sole screen-space
Tara anchor used by waypoint clearance.

**Non-goals:** Do not change target-object vectors, the tracker algorithm, the 240 px tracker clearance, movement
verification, modal safety, or save lineage checks.

**Approaches considered:** Keeping Tara vectors but ignoring them in the guard preserves unnecessary scan and receipt
cost. Removing all Tara localization loses the reliable safety anchor. The selected approach removes Tara from vector
scope and makes the guard consider only the confirmed tracker candidate.

**Unknown screens:** A Tara vector no longer upgrades an OCR-uncertain frame to gameplay. Existing HUD, affordance,
textless-frame, or model-vision evidence must establish gameplay instead; uncertainty remains safe.

**Acceptance:** A learned region scope omits Tara; false Tara vector candidates do not veto a safe waypoint; the
tracker candidate still vetoes a waypoint within 240 px; focused and broader gameplay tests pass. Live gameplay is a
separate verification step after this isolated code change.
