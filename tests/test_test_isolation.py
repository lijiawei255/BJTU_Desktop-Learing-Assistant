"""Verify the PC test boundary and keep known Mock cleanup gaps visible."""

import importlib
import json
import socket

import pytest

from src.config import config
from src.memory_manager import MemoryManager


@pytest.mark.parametrize("nickname", ["first-test", "second-test"])
def test_config_and_memory_are_fresh_and_persist_only_in_sandbox(isolated_runtime, nickname):
    assert config.get("system.nickname") == "博士"
    assert config.get("mock.headless") is True
    assert all(config.mock_devices.values())
    memory = MemoryManager()
    assert memory.data_dir == isolated_runtime / "data"
    assert memory.longterm["user_profile"] == {}
    config.set("system.nickname", nickname)
    memory.set_nickname(nickname)
    saved = json.loads((isolated_runtime / "data/config.json").read_text(encoding="utf-8"))
    assert saved["system"]["nickname"] == nickname
    assert "api_keys" not in saved
    persisted = json.loads((isolated_runtime / "data/longterm_memory.json").read_text(encoding="utf-8"))
    assert persisted["user_profile"]["nickname"] == nickname


def test_unmarked_network_access_is_rejected():
    with pytest.raises(pytest.fail.Exception, match="Network access is forbidden"):
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)


def test_unmarked_device_import_is_rejected():
    with pytest.raises(pytest.fail.Exception, match="Hardware import"):
        __import__("pyaudio")
    with pytest.raises(pytest.fail.Exception, match="Hardware import"):
        importlib.import_module("picamera2")


@pytest.mark.parametrize("stop_method", ["stop_tracking", "close"])
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="MOCK-CAMERA: stop/close do not halt worker; src is intentionally unchanged")
def test_mock_camera_stop_halts_worker(stop_method):
    from src.devices.camera import CameraMock
    camera = CameraMock()
    camera.start_tracking()
    getattr(camera, stop_method)()
    camera._tracking_thread.join(timeout=0.2)
    assert not camera._tracking_thread.is_alive()
