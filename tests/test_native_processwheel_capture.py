from __future__ import annotations

import importlib.util
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "native_processwheel_capture.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("native_processwheel_capture", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_one_tick_resource_prep_handles_crlf_and_delay(tmp_path):
    tool = _load_tool()
    resource = (
        tmp_path / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    )
    resource.mkdir(parents=True)
    server = (
        'local vehicle = nil\r\n'
        'local function startPlayer(player)\r\n'
        '    triggerClientEvent(player, "nativeCapture:start", resourceRoot, "etnies-native", "native-etnies")\r\n'
        'end\r\n'
    )
    client = 'addEvent("nativeCapture:start", true)\r\n'
    (resource / "server.lua").write_bytes(server.encode())
    (resource / "client.lua").write_bytes(client.encode())

    restore = tool._prepare_one_tick_resource(
        tmp_path,
        {"position": [1, 2, 3], "nativeInternal": {}, "oneTickDelayMs": 30000},
    )
    prepared = (resource / "server.lua").read_bytes().decode()
    assert 'nativeCapture:oneTick' in prepared
    assert "end, 30000, 1)" in prepared
    assert "\r\n" in prepared

    restore()
    assert (resource / "server.lua").read_bytes().decode() == server
    assert (resource / "client.lua").read_bytes().decode() == client


def test_one_tick_resource_prep_accepts_current_source_tag_trigger(tmp_path):
    tool = _load_tool()
    resource = tmp_path / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    resource.mkdir(parents=True)
    server = (
        'local function startPlayer(player)\n'
        '    triggerClientEvent(player, "nativeCapture:start", resourceRoot, "etnies-native", "source-tag-smoke")\n'
        'end\n'
    )
    client = "addEvent(\"nativeCapture:oneTick\", true)\n"
    (resource / "server.lua").write_text(server, encoding="utf-8")
    (resource / "client.lua").write_text(client, encoding="utf-8")
    restore = tool._prepare_one_tick_resource(
        tmp_path, {"position": [1, 2, 3], "nativeInternal": {}, "oneTickDelayMs": 30000}
    )
    prepared = (resource / "server.lua").read_text(encoding="utf-8")
    assert "nativeCapture:oneTick" in prepared
    assert "end, 30000, 1)" in prepared
    restore()
    assert (resource / "server.lua").read_text(encoding="utf-8") == server


def test_actual_race_duration_guard_preserves_full_playback():
    source = TOOL.read_text(encoding="utf-8")
    assert "17781.0 / 99.0" in source
    assert "requires --duration" in source


def test_actual_race_map_start_waits_for_client_join():
    source = TOOL.read_text(encoding="utf-8")
    assert "server_joined.wait(0.25)" in source
    assert "start_reference_race_after_join" in source
    assert "after_server_join_start_race_then_map" in source
    assert '(25.0, "start race")' not in source


def test_loader_mode_disables_mixed_frida_bootstrap():
    tool = _load_tool()
    script = tool._native_script(Path("C:/mta"), "loader", skip_frida_bootstrap=True)
    assert "if (!true)" in script
    assert "if (!skip_frida_bootstrap)" not in script


def test_one_tick_wheel_state_offset_is_after_gas_audio_field():
    source = TOOL.read_text(encoding="utf-8")
    assert "writeU32Array(0x968, internal.wheelStates)" in source
    assert "u32Array4(vehicle.add(0x968))" in source


def test_collision_diagnostics_capture_fresh_automobile_col_points():
    source = TOOL.read_text(encoding="utf-8")
    assert "main.base.add(0x81BFF8)" in source
    assert "automobileCollisionPoints:colPointArray(automobileCollisionPoints, 12)" in source
    assert "outputCollisionPoints:colPointArray(this.nativeEntityCollisionOutput, 32)" in source
    assert "automobileCollisionPointsAfter:colPointArray(automobileCollisionPoints, 12)" in source
    assert "CAPTURE_FROM_FIRST_GAS" in source
    assert "SUSPENSION_STAGE_ONLY" in source
    assert "if (!SUSPENSION_STAGE_ONLY)" in source
    assert "captureActive = true" in source
    assert "maxPreCaptureRecords = 512" in source


def test_timing_probe_captures_native_timer_fields():
    source = TOOL.read_text(encoding="utf-8")
    assert "timerOldStep:timerOldStep.readFloat()" in source
    assert "timerStepNonClipped:timerStepNonClipped.readFloat()" in source
    assert "timerStep:timerStep.readFloat()" in source


def test_cpp_collision_stream_flushes_partial_batches():
    source = TOOL.read_text(encoding="utf-8")
    assert 'MTA_NATIVE_COLLISION_ALT_CPP_FLUSH_EVERY' in source
    assert 'os.environ["MTA_NATIVE_COLLISION_ALT_CPP_FLUSH_EVERY"] = "1"' in source
    assert '"cpp_collision_flush_every"' in source


def test_actual_race_capture_removes_synthetic_map_and_polls_race_vehicle(tmp_path):
    tool = _load_tool()
    resource = (
        tmp_path / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    )
    resource.mkdir(parents=True)
    original_meta = (
        '<meta>\r\n'
        '  <map src="Etnies.map" dimension="0" />\r\n'
        '  <script src="server.lua" type="server" />\r\n'
        '  <script src="client.lua" type="client" />\r\n'
        '</meta>\r\n'
    ).encode()
    original_server = b'local original = true\r\n'
    (resource / "meta.xml").write_bytes(original_meta)
    (resource / "server.lua").write_bytes(original_server)

    restore = tool._prepare_actual_race_capture(
        tmp_path, "etnies-native", "race-tags", delay_ms=30000
    )
    meta = (resource / "meta.xml").read_bytes().decode()
    server = (resource / "server.lua").read_bytes().decode()
    assert "Etnies.map" not in meta
    assert 'src="client.lua"' not in meta
    assert 'getPedOccupiedVehicle(player)' in server
    assert 'getElementModel(vehicle) ~= 411' in server
    assert '"race-tags"' in server
    assert "end, 30000, 1)" in server
    assert '"tas:automationStart"' in server
    assert "\r\n" in server

    restore()
    assert (resource / "meta.xml").read_bytes() == original_meta
    assert (resource / "server.lua").read_bytes() == original_server


def test_tas_automation_playback_replaces_native_event_and_restores(tmp_path):
    tool = _load_tool()
    resource = (
        tmp_path / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    )
    resource.mkdir(parents=True)
    original = (
        'local vehicle = nil\r\n'
        '    triggerClientEvent(player, "nativeCapture:start", resourceRoot, "etnies-native", "native-etnies")\r\n'
    ).encode()
    path = resource / "server.lua"
    path.write_bytes(original)

    restore = tool._prepare_tas_automation_playback(tmp_path, "tagged-run")
    prepared = path.read_bytes().decode()
    assert '"tas:automationStart"' in prepared
    assert 'getResourceRootElement(tasResource)' in prepared
    assert '"tagged-run"' in prepared
    assert "\r\n" in prepared
    restore()
    assert path.read_bytes() == original


def test_gta_import_redirects_and_restores(tmp_path):
    tool = _load_tool()
    path = tmp_path / "gta_sa.exe"
    original = b"prefixWINMM.dllsuffix"
    path.write_bytes(original)

    restore = tool._prepare_gta_import(path)

    assert path.read_bytes() == b"prefixmtasa.dllsuffix"
    assert (tmp_path / "gta_sa.exe.native-capture-original").read_bytes() == original
    restore()
    assert path.read_bytes() == original

    path.write_bytes(b"prefixWINMM.dllmiddleWINMM.dllsuffix")
    restore = tool._prepare_gta_import(path)
    assert path.read_bytes() == b"prefixmtasa.dllmiddleWINMM.dllsuffix"
    restore()
    assert path.read_bytes() == b"prefixWINMM.dllmiddleWINMM.dllsuffix"


def test_real_vorbis_recovers_stale_real_dll_from_backup(tmp_path):
    tool = _load_tool()
    (tmp_path / "vorbisfile.dll").write_bytes(b"real")
    (tmp_path / "vorbisfile_real.dll").write_bytes(b"real")
    (tmp_path / "vorbisfile.native-capture-original.dll").write_bytes(b"proxy")

    restore = tool._prepare_real_vorbis(tmp_path)

    assert (tmp_path / "vorbisfile.dll").read_bytes() == b"proxy"
    restore()
    assert (tmp_path / "vorbisfile.dll").read_bytes() == b"proxy"


def test_native_capture_start_delay_handles_crlf_and_restores(tmp_path):
    tool = _load_tool()
    resource = (
        tmp_path / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    )
    resource.mkdir(parents=True)
    original = (
        'addEvent("nativeCapture:start", true)\r\n'
        'addEventHandler("nativeCapture:start", resourceRoot, function(recordName, outputName)\r\n'
        '    setTimer(function()\r\n'
        '        executeCommandHandler("loadr", recordName)\r\n'
        '        setTimer(function()\r\n'
        '            executeCommandHandler("recordplayback", outputName)\r\n'
        '        end, 1000, 1)\r\n'
        '    end, 1000, 1)\r\n'
        'end)\r\n'
    ).encode()
    path = resource / "client.lua"
    path.write_bytes(original)

    restore = tool._prepare_native_capture_start_delay(tmp_path, 30000)
    prepared = path.read_bytes().decode()
    assert "end, 30000, 1)" in prepared
    assert "\r\n" in prepared
    restore()
    assert path.read_bytes() == original
