from __future__ import annotations

from pathlib import Path
import subprocess

import pytest


REPO = Path(__file__).resolve().parents[1]
CLIENT = REPO / "new" / "tas" / "client.lua"
HARNESS = Path(__file__).with_name("client_telemetry_harness.lua")
LUA = Path(r"C:\Program Files (x86)\Lua\5.1\lua.exe")
LUAC = Path(r"C:\Program Files (x86)\Lua\5.1\luac.exe")


@pytest.mark.skipif(not LUA.is_file(), reason="Lua 5.1 is not installed")
def test_client_telemetry_lua_harness():
    result = subprocess.run(
        [str(LUA), str(HARNESS), str(CLIENT)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "client telemetry harness: ok" in result.stdout


@pytest.mark.skipif(not LUAC.is_file(), reason="Lua 5.1 is not installed")
def test_client_lua_syntax():
    result = subprocess.run(
        [str(LUAC), "-p", str(CLIENT)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
