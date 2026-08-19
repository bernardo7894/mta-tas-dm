# Physics analysis export

This extends the `new/tas` version of **mta-tas-dm** without changing its
existing `.tas` save/load format or normal playback behavior.

## Captured per frame

- actual `onClientPreRender` delta time (`dt`, milliseconds) and derived FPS
- current game speed
- full 4x4 vehicle transform matrix (`getElementMatrix(vehicle, false)`)
- position, Euler rotation, linear velocity and angular velocity
- individual wheel contact states in MTA order: front-left, rear-left, front-right, rear-right
- effective GTA control states and raw analog values
- nitro state
- collision events: impulse magnitude, body part, point, surface normal, other-vehicle force and world model ID

## Captured once per recording

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
6. Optionally use `/saver <name>` for the original TAS recording.
7. Run `/savephysics <name>`.

The analysis file is `saves/<name>.physics.jsonl`. With the upstream default
`usePrivateFolder=true`, it is written in the resource's private MTA data area.
The first JSONL line is recording metadata; subsequent lines are frames.

For replica testing, initialize the new engine from the first frame and replay
only the recorded controls. Position, orientation and velocity are ground-truth
comparison targets and should not be forced onto the replica after initialization.
