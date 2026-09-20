"""PC test isolation only; production configuration and drivers are unchanged."""

import builtins
import copy
import importlib
import logging
import os
from pathlib import Path
import signal
import socket
from types import SimpleNamespace
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Config creates its singleton at import time. Do not read the user's file/.env
# during collection, or let environment overrides mutate DEFAULT_CONFIG.
_exists = Path.exists
with patch("dotenv.load_dotenv", return_value=False), patch.dict(os.environ):
    for key in ("ENABLE_MOCK", "ALIBABA_API_KEY", "AUDIO_INPUT_DEVICE_INDEX",
                "AUDIO_OUTPUT_DEVICE_INDEX", "LOG_LEVEL"):
        os.environ.pop(key, None)
    with patch.object(Path, "exists", lambda p: False if p == REPO_ROOT / "data/config.json" else _exists(p)):
        from src import config as config_module

TEST_DEFAULTS = copy.deepcopy(config_module.DEFAULT_CONFIG)


def pytest_addoption(parser):
    parser.addoption("--run-api", action="store_true", help="Enable cloud API tests (may incur charges)")
    parser.addoption("--run-hardware", action="store_true", help="Enable real microphone/device tests")


def pytest_configure(config):
    # Imported modules normally open repository log files during collection.
    # Let pytest capture standard logging instead, without opening user files.
    from src.utils import logger
    config._amiya_log_patch = patch.object(logger, "setup_logger", logging.getLogger)
    config._amiya_log_patch.start()


def pytest_unconfigure(config):
    if hasattr(config, "_amiya_log_patch"):
        config._amiya_log_patch.stop()


def pytest_collection_modifyitems(config, items):
    for item in items:
        for marker, option in (("api", "--run-api"), ("hardware", "--run-hardware")):
            if item.get_closest_marker(marker) and not config.getoption(option):
                item.add_marker(pytest.mark.skip(reason=f"requires explicit {option}"))


@pytest.fixture(autouse=True)
def isolated_runtime(request, monkeypatch, tmp_path):
    """Fresh config/data per test; block unrequested network/device access."""
    from src.config import config
    from src import memory_manager
    from src.headless_input import headless_input

    values = copy.deepcopy(TEST_DEFAULTS)
    values["mock"] = {key: True for key in values["mock"]}
    values["api_keys"] = {"alibaba": "offline-test-placeholder"}
    if request.node.get_closest_marker("api"):
        from dotenv import dotenv_values
        key = os.environ.get("ALIBABA_API_KEY") or dotenv_values(REPO_ROOT / ".env").get("ALIBABA_API_KEY")
        if not key or key == "sk-your-api-key-here":
            pytest.fail("--run-api requires ALIBABA_API_KEY in the environment or project .env")
        values["api_keys"]["alibaba"] = key
    else:
        def no_network(*args, **kwargs):
            pytest.fail("Network access is forbidden in a test without the api marker")
        monkeypatch.setattr(socket.socket, "connect", no_network)
        monkeypatch.setattr(socket.socket, "connect_ex", no_network)
        monkeypatch.setattr(socket, "create_connection", no_network)

    if request.node.get_closest_marker("hardware"):
        values["mock"]["enabled"] = False
    else:
        real_import = builtins.__import__
        real_import_module = importlib.import_module
        hardware_modules = {
            "pyaudio", "gpiozero", "lgpio", "pigpio", "RPi", "board", "busio",
            "smbus", "smbus2", "adafruit_servokit", "adafruit_vl53l0x", "picamera2",
        }

        def no_hardware(name, *args, **kwargs):
            if name.split(".", 1)[0] in hardware_modules:
                pytest.fail(f"Hardware import {name!r} is forbidden without the hardware marker")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", no_hardware)

        def no_hardware_module(name, package=None):
            if name.split(".", 1)[0] in hardware_modules:
                pytest.fail(f"Hardware import {name!r} is forbidden without the hardware marker")
            return real_import_module(name, package)
        monkeypatch.setattr(importlib, "import_module", no_hardware_module)

    monkeypatch.setattr(config_module, "DEFAULT_CONFIG", copy.deepcopy(TEST_DEFAULTS))
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_manager, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "_config", values)
    # New Config instances created inside a test must see test-only overrides too.
    monkeypatch.setenv("ENABLE_MOCK", str(values["mock"]["enabled"]).lower())
    monkeypatch.setenv("ALIBABA_API_KEY", values["api_keys"]["alibaba"])
    for key in ("AUDIO_INPUT_DEVICE_INDEX", "AUDIO_OUTPUT_DEVICE_INDEX", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    monkeypatch.setattr(headless_input, "_enabled", True)
    monkeypatch.setattr(headless_input, "_default_timeout", 0.1)
    headless_input.clear()

    # Remove only simulated servo delays, never real driver delays or clocks.
    from src.devices import servo_mock
    monkeypatch.setattr(servo_mock, "time", SimpleNamespace(sleep=lambda _: None))

    from src.devices.camera import CameraMock
    from src.state_controller import FocusTimer
    from src.tts_client import TTSClient
    from src.main import AmiyaSystem

    timers, cameras, speakers, apps = [], [], [], []
    for cls, instances in ((FocusTimer, timers), (CameraMock, cameras),
                           (TTSClient, speakers), (AmiyaSystem, apps)):
        original = cls.__init__

        def tracked_init(self, *args, _init=original, _instances=instances, **kwargs):
            _init(self, *args, **kwargs)
            _instances.append(self)
        monkeypatch.setattr(cls, "__init__", tracked_init)

    old_sigint = signal.getsignal(signal.SIGINT)
    try:
        yield tmp_path
    finally:
        threads = []
        for app in apps:
            app._running = False
            app.shutdown_event.set()
            threads.extend([app._sensor_thread, app._sensor_checker_thread])
        for timer in timers:
            timer.stop()
            threads.append(timer._thread)
        for camera in cameras:
            # Test teardown compensates for the known Mock stop/close omission;
            # tests of that omission still exercise the unchanged implementation.
            camera._running = False
            threads.append(camera._tracking_thread)
        for speaker in speakers:
            speaker.stop_playback()
            threads.append(speaker._worker_thread)
        for thread in threads:
            if thread is not None:
                thread.join(timeout=5)
        headless_input.clear()
        signal.signal(signal.SIGINT, old_sigint)
        alive = [t.name for t in threads if t is not None and t.is_alive()]
        assert not alive, f"Test left background threads running: {alive}"
