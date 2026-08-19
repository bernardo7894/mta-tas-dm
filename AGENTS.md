# AGENTS.md — mta-tas-dm

## Repository Role

This repository provides the MTA:SA-side reference recorder for the larger `mta-sa-dm-standalone` project.

It is used to record real GTA:SA / MTA:SA vehicle behavior so that a future standalone physics implementation can be measured against it.

Read the parent workspace `AGENTS.md` for the overall project objective and methodology.

## Upstream

This repository is a fork of:

https://github.com/chris1384/mta-tas-dm

Original project: TAS / recording tooling for MTA:SA [DM].

Preserve the upstream project history and MIT license.

Do not unnecessarily rewrite or restructure upstream code. This fork should remain recognizable as an extension of `mta-tas-dm`.

## Physics-Analysis Branch

The standalone-project changes were initially developed on:

`physics-analysis-export`

The main implementation commit was created on top of upstream commit:

`db16023f3ade3f1e81eca37cff66d708d4f66754`

The purpose of these changes is to augment the existing TAS recorder with physics telemetry while preserving the ordinary `.tas` format and existing TAS behavior.

## Added Physics Telemetry

The fork adds a separate physics-analysis export.

Command:

`/savephysics <name>`

Example:

`/savephysics first_dm_run`

Output:

`saves/<name>.physics.jsonl`

The normal TAS recording can still be saved independently with:

`/saver <name>`

The fork also provides `/saveboth <name>` to save both files in one command.

## Physics JSONL Contents

The extended export records information useful for reproducing Infernus dynamics.

Recording-level metadata includes information such as:

- format/version information;
- vehicle model;
- FPS limit;
- initial game speed;
- dimension;
- interior;
- `getVehicleHandling(vehicle)` output.

Per-frame information includes:

- recording tick/time;
- actual `onClientPreRender` delta time;
- derived FPS;
- game speed;
- position;
- Euler rotation;
- full element transform matrix;
- linear velocity;
- angular velocity;
- vehicle health;
- vehicle model;
- nitro state;
- original TAS key information;
- effective GTA control states;
- analog control values;
- all four wheel-on-ground states;
- collision events associated with the frame.

Collision telemetry includes useful values exposed by MTA such as:

- collision impulse magnitude;
- body part;
- collision position;
- collision normal;
- hit-element force;
- world model ID / hit-element information.

This information is especially important for later wallride and landing analysis.

`onClientVehicleCollision` is an event stream, not a complete contact-manifold
stream. It can omit continuous suspension/ground contact, especially when the
vehicle is already resting on an object when recording begins. The per-frame
`wheelOnGround` values indicate contact but do not identify the world model.
Therefore `worldModel` IDs must not be treated as an exhaustive list of every
track surface used by a run.

## Compatibility Rule

Do not break the original `.tas` save/load format merely to add standalone-project telemetry.

Physics-analysis data should remain a separate export unless there is a strong reason to change this architecture.

Normal TAS usage should continue working.

## Recording Workflow

Typical experiment:

1. Start the MTA server.
2. Start the `tas` resource.
3. Enter an Infernus.
4. Run:

   `/record`

5. Drive the experiment or DM sequence.
6. Run `/record` again to stop.
7. Save both outputs:

   `/saveboth <name>`

   The traditional recording and physics telemetry can also be saved
   independently with `/saver <name>` and `/savephysics <name>`.

The `.tas` recording is useful for MTA playback/debugging. To replay a loaded
`.tas` while capturing fresh per-wheel ground probes, use
`/recordplayback <output-name>`; this writes a new `.physics.jsonl` without
changing the source `.tas` on disk.

The `.physics.jsonl` recording is the primary input for standalone physics analysis.

## Benchmark Philosophy

Recorded state must not later be used to force a standalone vehicle along the same trajectory.

The intended standalone test is:

- initialize from the first recorded state;
- apply recorded controls;
- run independent physics;
- compare resulting state against recorded MTA state.

Position, rotation, velocity, and angular velocity are comparison targets.

## Current Development Focus

The first vehicle of interest is the Infernus.

Do not add complexity for general vehicle compatibility unless it directly helps the current experiments.

Useful initial data includes:

- air control;
- acceleration;
- steering;
- braking;
- wheel contacts;
- collisions;
- wallrides;
- nitro;
- landings.

## Local MTA Resource Deployment

`install-to-mta-server.bat` mirrors the modified `new\tas` resource into the local MTA server so repeated TAS development iterations are quick. It deliberately limits deployment to the server's `resources\tas` directory.

## Testing Changes

At minimum, ensure edited Lua remains syntactically valid.

For `client.lua`, a `luac -p` syntax check is useful where a compatible Lua compiler is available.

Also inspect the actual Git diff before committing. This upstream file historically uses CRLF line endings; avoid creating enormous diffs consisting only of line-ending normalization.

## Proprietary Assets

This repository does not need and should not contain Rockstar game assets.

Do not commit DFF, TXD, COL, or other extracted GTA:SA data here.

This repository's responsibility is MTA telemetry capture.

Map/GTA asset import belongs elsewhere in the workspace.

## Repository-Specific Persistent Notes

If a coding agent establishes a durable fact specific to this repository, it may update this `AGENTS.md`.

Examples:

- a new telemetry field;
- an export-format version change;
- an MTA API quirk important to recordings;
- a changed deployment workflow.

Project-wide architectural notes belong in the parent workspace `AGENTS.md`, not here.

Do not record transient debugging history in this file.
