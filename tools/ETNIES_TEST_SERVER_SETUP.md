# Etnies local test-server setup

`tools/configure_etnies_test_servers.ps1` keeps the ordinary MTA 1.6 server and the local `mtasa-blue` Debug/native-capture server on the same Etnies cadence and deploys the same TAS resource to both.

From the repository root, run an elevated PowerShell when the ordinary MTA server lives under `Program Files`:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\configure_etnies_test_servers.ps1
```

Defaults:

- ordinary server: `C:\Program Files (x86)\MTA San Andreas 1.6\server`
- debug/native server: `D:\Users\Bernardo\Documents\mtasa-blue\Bin\server`
- server FPS limit: `100`
- Race map: `race-dm-Skynetv5-EtniesII(fix)`

The script:

1. makes a one-time `.pre-etnies-test.bak` backup of each `mtaserver.conf`;
2. sets `<fpslimit>` to `100` in both configurations;
3. mirrors `new/tas` into both servers, so the same playback code and source-frame HUD are used;
4. disables the ordinary `play` gamemode on the normal server;
5. starts `mapmanager`, `race`, `tas`, and a small `etnies-startup` helper on the normal server; and
6. has that helper ask `mapmanager` to launch Race with `race-dm-Skynetv5-EtniesII(fix)` when the server boots.

The source-frame HUD is enabled by default during TAS playback. It shows the source frame, total source frame count, and source timestamp. It can be disabled persistently with:

```text
/tascvar showPlaybackFrameHud false
```

The native-capture harness may re-prepare its TAS resource from this repository; that is expected and preserves the same HUD/code because the repository is the source for both environments.
