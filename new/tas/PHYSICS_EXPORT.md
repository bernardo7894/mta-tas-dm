# Physics analysis export

This extends the `new/tas` version of **mta-tas-dm** without changing its
existing `.tas` save/load format or normal playback behavior.

## Captured per frame

Format-v3 keeps all format-v2 fields and adds an optional `vehicleTelemetry`
object. Format-v2 recordings remain valid and old consumers can ignore the new
fields.

- actual capture-frame delta time (`dt`, milliseconds) and derived FPS; recording uses the `onClientPreRender` delta, while `/recordplayback` uses that delta when playback is on pre-render and elapsed `getTickCount()` time between callbacks otherwise
- current game speed
- full 4x4 vehicle transform matrix (`getElementMatrix(vehicle, false)`)
- position, Euler rotation, linear velocity and angular velocity
- individual wheel contact states in MTA order: front-left, rear-left, front-right, rear-right
- per-wheel ground probes with hit position, normal, hit element type/model and world model ID
- effective GTA control states and raw analog values
- nitro state
- collision events: impulse magnitude, body part, point, surface normal, other-vehicle force and world model ID
- `vehicleTelemetry.currentGear`, measured from `getVehicleCurrentGear`
- `vehicleTelemetry.wheelOrder`: explicit stable order `front_left`, `rear_left`, `front_right`, `rear_right`
- `vehicleTelemetry.wheels.<identity>.index` and component name
- measured `onGround` from `isVehicleWheelOnGround`
- measured `frictionState` from `getVehicleWheelFrictionState` (`0` normal, `1` acceleration slip, `2` slip without acceleration, `3` locked)
- measured structural `wheelState` from `getVehicleWheelStates` when available (`0` inflated, `1` flat, `2` fallen off, `3` collisionless)
- measured component position and rotation in `parent`, `root`, and `world` bases from the component APIs when available
- a `steering` object containing measured sampled controls and a separately
  labeled derived control-based estimate; private GTA steering members are not
  exposed by the Lua API
- a separately labeled `derived` object per wheel containing the selected
  contact point, `v_point = v_linear + omega × r` in raw and world-per-second
  units, and projections onto the vehicle basis. These values are derived, not
  private GTA `contactSpeeds[]`.

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
Playback captures copy the measured `dt`, `fps`, and `vehicleTelemetry` into each refreshed frame's extended analysis state, so those fields are preserved in the exported format-v3 JSONL.

- vehicle model
- FPS limit
- initial game speed
- dimension and interior
- complete `getVehicleHandling(vehicle)` table

## API verification

The local installation is MTA San Andreas `1.6.0.24139`. The installed
`mods/deathmatch/client.dll` contains all of these bindings, and the current
MTA Wiki documents the following signatures:

- `getVehicleWheelFrictionState(vehicle, wheel)` — client-side; wheel indices
  0/1/2/3 are front-left/rear-left/front-right/rear-right; documented values
  are 0 normal, 1 acceleration slip, 2 slip without acceleration, 3 locked.
- `isVehicleWheelOnGround(vehicle, wheel)` — client-side; accepts the same
  numeric indices (and documented string identities).
- `getVehicleCurrentGear(vehicle)` — client-side integer gear.
- `getVehicleComponentPosition(vehicle, component, base)` — client-side;
  `parent`, `root`, and `world` bases are documented.
- `getVehicleComponentRotation(vehicle, component, base)` — client-side;
  `parent`, `root`, and `world` bases are documented.
- `getVehicleWheelStates(vehicle)` — shared API; returns structural wheel
  states in front-left/rear-left/front-right/rear-right order.

The exporter records all component Euler axes and all three documented bases;
it does not assume which Euler axis means steering, suspension, or spin. The
standalone diagnostic report may show a clearly labeled front-minus-rear
`componentRotation.root` Euler-Z candidate, but it is not treated as measured
private GTA steering state until the traces establish that interpretation.

## Direct native ProcessWheel instrumentation

Lua cannot expose the transient `contactSpeeds[4]` array or the continuous
private wheel state used by `CVehicle::ProcessWheel`. The workspace now includes
`tools/native_processwheel_capture.py` for the intentionally permissive local
`mtasa-blue` debug client. It installs a reversible Frida `Interceptor` before a
Frida-spawned US 1.0 `gta_sa.exe` resumes; it does not replace the wheel
function or modify its arguments.

The hook target is `gta_sa.exe` VA `0x6D6C00` (`RVA 0x2D6C00` from image base
`0x400000`), `CVehicle::ProcessWheel`. At entry it records, when the object
model is 411:

- the four `CVector&` arguments (`wheelFwd`, `wheelRight`, `wheelContactSpeed`,
  and `wheelContactPoint`);
- `wheelsOnGround`, thrust, brake, adhesion, wheel ID, wheel speed pointer,
  wheel state pointer, and wheel status;
- private suspension compression arrays at `CAutomobile` offsets `0x7D4`,
  `0x7E4`, and `0x7F4` (`current`, `previous`, and `m_WheelCounts`);
- actual `m_fSteerAngle` at `0x494`, raw steering at `0x58C`, contact counts,
  mass/turn-mass/centre-of-mass, model-origin position/matrix, and
  before/after velocity deltas.

The native JSONL rows are explicitly marked `gta-native-pre-ProcessWheel` and
must not be presented as Lua-derived telemetry. The corresponding alignment
helper is owned by `infernus-physics`:

```powershell
python tools/native_processwheel_capture.py `
  --gta-exe "D:\\Users\\Bernardo\\Documents\\mtasa-blue\\Bin\\gta_sa.exe" `
  --mta-bin "D:\\Users\\Bernardo\\Documents\\mtasa-blue\\Bin" `
  --server-exe "D:\\Users\\Bernardo\\Documents\\mtasa-blue\\Bin\\server\\MTA Server_d.exe" `
  --start-resource tas --start-resource native_capture `
  --orchestrator "C:\\Users\\berna\\mtasa_deobfuscation\\mta_bytecode_orchestrator.py" `
  --prepare-registry --use-real-vorbis `
  --output "..\\infernus-physics\\generated\\native-processwheel.jsonl"

python ..\\infernus-physics\\tools\\align_native_processwheel.py `
  "C:\\path\\to\\etnies-ii-wheel-telemetry-v3.physics.jsonl" `
  "..\\infernus-physics\\generated\\native-processwheel.jsonl" `
  --causal "..\\infernus-physics\\generated\\etnies-ii-wheel-telemetry-v3.causal-instrumented-final-275-350.json" `
  --output "..\\infernus-physics\\generated\\native-causal-aligned.json"
```

The debug server must disable only the anti-cheats that reject the local
instrumented client (the current local harness uses AC `4,56`), and the debug
client must use the matching local server/resource setup. The local
`mtasa-blue` Debug build also requests the private connection from
`CCore::DoPostFramePulse` after the GUI/network stack is ready; this is a
harness-only launch change, not ordinary TAS behavior. These are local harness
settings, not changes to ordinary recordings or production servers.

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

## Automated reference playback

The repetitive map/load/playback sequence can be driven without using the MTA
GUI. The patched `tas` server script exports an authenticated HTTP API that:

1. changes the `race` gamemode to the requested map;
2. waits for the target player's race vehicle;
3. tells the TAS client to load its local `.tas` file; and
4. starts `/recordplayback`, which saves fresh telemetry as `.physics.jsonl`.

The small client for that API is `tools/mta_reference_capture.py`. An “MTA
HTTP account” is not a separate service account: it is an ordinary MTA server
account that is allowed to use the HTTP interface. Set
`MTA_HTTP_USER` and `MTA_HTTP_PASSWORD` to that account's normal MTA login
credentials, then run from the repository root:

```powershell
$env:MTA_HTTP_USER = "your-mta-account"
$env:MTA_HTTP_PASSWORD = "your-mta-password"
python mta-tas-dm/tools/mta_reference_capture.py run `
  "DM Skynet v5 Etnies II" previous_record new_telemetry
```

The account's ACL group needs both `general.http` and `resource.tas`; the
latter is required because the two TAS automation exports are marked
`protected="true"`. Grant `resource.tas` only to the account/group that should
control captures. The local test server uses its existing Admin account and
has this right persisted in its `acl.xml`; other installations must grant the
same right in their own ACL.

Use `start` instead of `run` to return immediately, or `status` to query the
current request. The MTA server and client must already be running and
connected. This control path uses authenticated HTTP and normal MTA
server-to-client events; it does not use Windows focus, keyboard input, or the
server-console window. With a single connected player the target is inferred.
On a multi-player server pass `--target-player "name"`. The saved output is
`<name>.physics.jsonl` in the client's normal TAS private save area.

## Wheel diagnostic comparison

The standalone parser accepts the optional telemetry as
`Frame.vehicle_telemetry`. To join it with an existing simulation JSON around
the ramp window, run from `infernus-physics`:

```powershell
python -m infernus_physics wheel-diagnostics `
  "C:\path\to\recording.physics.jsonl" `
  --simulation generated\benchmark-iteration-full-control-order.json `
  --start-frame 275 --end-frame 350
```

The generated report keeps measured MTA gear/contact/friction/component values
separate from simulator gear, logical/raw contact, steering, compression,
contact-speed, and ProcessWheel correction fields.
