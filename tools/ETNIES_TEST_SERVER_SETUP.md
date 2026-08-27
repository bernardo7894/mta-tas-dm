# Etnies local test-server setup

`tools/configure_etnies_test_servers.ps1` standardizes the ordinary MTA 1.6 server and the local `mtasa-blue` Debug/native-capture server for Etnies playback comparisons without replacing either server's existing TAS client variant.

Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\configure_etnies_test_servers.ps1
```

Verified local defaults:

- ordinary server: `C:\Program Files (x86)\MTA San Andreas 1.6\server`
- debug/native server: `D:\Users\Bernardo\Documents\mtasa-blue\Bin\server`
- server FPS limit: `100`
- Race map resource name: `race-dm-Skynetv5-EtniesII(fix)`
- the map is actually grouped under `mods\deathmatch\resources\[gamemodes]\[race]\[maps]\...` in both installations; the script searches by resource directory name rather than assuming it is directly below `resources`.

The script:

1. verifies the exact Etnies resource exists in both server trees;
2. sets both server `fpslimit` values to `100`;
3. leaves the Debug/native server's other startup settings alone (including its capture-oriented `play` setup);
4. adds only the HUD `meta.xml` entry and `frame_hud.lua` to each existing TAS resource instead of using `robocopy /MIR` or rewriting `client.lua`;
5. configures the normal server to start `mapmanager`, `tas`, and `etnies-startup`, while leaving bare `race`/`play` startup disabled when those entries exist; and
6. has `etnies-startup` call `mapmanager:changeGamemodeByName` so Race starts atomically with `race-dm-Skynetv5-EtniesII(fix)`.

This selective deployment matters because the Debug TAS copy can contain native-capture-specific local settings and code. Replacing the entire folder can destroy or temporarily undo active capture work.

## Source-frame HUD

During playback the top-center overlay shows:

```text
TAS SOURCE  <frame> / <total>   |   <source timestamp>
```

`frame_hud.lua` registers `showPlaybackFrameHud` after `client.lua` initializes. Because the main config loader has already run by then, the HUD reads that one persisted key from `@config.json` itself, using the same `enableUserConfig == true` condition. This keeps `/tascvar showPlaybackFrameHud false` persistent without modifying either TAS `client.lua` variant. The default is `true`.

The Etnies reference file currently used locally reports `17781` frames and carries its original source tick on each frame, so the overlay is intended for source-frame comparison rather than video-time alignment.
