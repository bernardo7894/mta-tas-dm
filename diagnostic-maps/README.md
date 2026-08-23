# Infernus waterjump diagnostics

Controlled stock-collision reference courses for the standalone Infernus physics work.

## Preferred: `infernus-waterjump-diagnostic`

Self-contained MTA resource. It does not require the Race gamemode, so there is no Race player-wait phase or Race countdown. Stop `race`, start this resource, and it creates/warps an Infernus itself.

Five automatic stages are recorded:

1. flat baseline;
2. stock `waterjumpx2` (model 1655), short approach;
3. stock `waterjumpx2`, medium approach;
4. stock `waterjumpx2`, long approach;
5. long-approach repeat.

Every lane uses a continuous stock `vgncarshade1` (model 3458) deck from the stage start through and underneath the ramp to the finish. The ramp therefore does not bridge a missing floor section.

The resource resets position/orientation, linear and angular velocity, health and nitro state between stages. It temporarily disables TAS confirmation warnings, starts `/record`, gives a stationary pre-roll and 3-2-1-GO, stops at the finish marker, and calls `/saveboth` automatically. It restores TAS warnings when the course completes or the client resource stops.

Useful manual commands: `/diagstage 1-5`, `/diagretry`, `/diaginstructions`.

## Race-compatible: `race-diagnostic-infernus-blue-ramp-course`

Same geometry and stage workflow as a Race map. This version waits for Race to enter its `Running` state before arming the first diagnostic countdown, so the two countdowns no longer overlap. Prefer the standalone resource for repeated testing.

## Geometry

- Ramp: GTA:SA stock model 1655, `waterjumpx2`, COL2.
- Deck: GTA:SA stock model 3458, `vgncarshade1`, COL3.
- Vehicle: Infernus, model 411.

The `.map` geometry remains suitable for `gta-sa-asset-tools` collision-scene extraction and independent simulator comparisons.
