# Vision Relative Localization Design

**Intent:** Preserve useful localization from a model-vision navigation answer even when the game log emits no world coordinate.

**Design:** A vision answer may append `relative=<N|NE|E|SE|S|SW|W|NW>` and `distance=<inside|near|far>`. The direction describes Tara's position relative to the named region. The graph persists one `Tara -> region` `relative_to` edge with direction, qualitative distance, source, and game time. Direction-to-target is derived as the inverse of this observation; no exact world coordinate is invented.

**Compatibility:** Existing `inside`, `walk <cell>`, and `target <cell>` answers remain valid. Exact event/save coordinates continue to outrank relative vision evidence.

**Rejected:** Converting a screen observation into fabricated world coordinates; replacing the graph with a garden-specific state machine; storing only a transient result field.
