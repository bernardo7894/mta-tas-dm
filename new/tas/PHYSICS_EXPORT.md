# Physics analysis export

This extends the `new/tas` version of **mta-tas-dm** without changing its
existing `.tas` save/load format or normal playback behavior.

## Captured per frame

- actual capture-frame delta time (`dt`, milliseconds) and derived FPS; recording uses the `onClientPreRender` delta, while `/recordplayback` uses that delta when playback is on pre-render and elapsed `getTickCount()` time between callbacks otherwise
- current game speed
- full 4x4 vehicle transform matrix (`getElementMatrix(vehicle, false)`)
- position, Euler rotation, linear velocity and angular velocity
- individual wheel contact states in MTA order: front-left, rear-left, front-right, rear-right
- per-wheel ground probes with hit position, normal, hit element type/model and world model ID
- effective GTA control states and raw analog values
- nitro state
- collision events: impulse magnitude, body part, point, surface normal, other-vehicle force and world model ID

Collision events are discrete `onClientVehicleCollision` callbacks, not a complete
per-frame contact list. A vehicle already resting on a map object can have
`wheelOnGround` set while producing no collision event or world model ID. The
new `groundContacts` field uses a downward `processLineOfSight` probe per wheel
and is intended to identify those supporting surfaces.

Use `/recordplayback <output-name>` after loading a `.tas` to play it back while
capturing fresh ground-contact probes. For a fresh playback capture, TAS
temporarily disables playback interpolation and visits every source `.tas`
frame, so render-loop frame skips do not leave source frames without telemetry.
The user's interpolation setting is restored when capture finishes. It writes
`<output-name>.physics.jsonl`; the source `.tas` playback data is not modified
on disk.
Playback captures copy the measured `dt` and `fps` into each refreshed frame's extended analysis state, so those fields are preserved in the exported format-v2 JSONL.

- vehicle model
- FPS limit
- initial game speed
- dimension and interior
- complete `getVehicleHandling(vehicle)` table

## Workflow

1. Start the patched `tas` resource.
2. Use an Infernus.
3. Run `/record`.
4. Drive the test or DM sequence.
5. Run `/record` again to stop.
6. Run `/saveboth <name>` to save both the original TAS recording and the physics export.

You can also save them separately with `/saver <name>` and `/savephysics <name>`.

The analysis file is `saves/<name>.physics.jsonl`. With the upstream default
`usePrivateFolder=true`, it is written in the resource's private MTA data area.
The first JSONL line is recording metadata; subsequent lines are frames.

For replica testing, initialize the new engine from the first frame and replay
only the recorded controls. Position, orientation and velocity are ground-truth
comparison targets and should not be forced onto the replica after initialization.
