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
