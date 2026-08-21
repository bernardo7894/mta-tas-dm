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
