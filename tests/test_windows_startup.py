import os

import tools.tradingagents_service_manager as manager
import tools.windows_startup as windows_startup
from tools.tradingagents_service_manager import ServiceManagerApp


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = object()
    REG_SZ = 1
    KEY_READ = 2
    KEY_SET_VALUE = 3

    def __init__(self):
        self.values = {}
        self.calls = []

    def OpenKey(self, root, path, reserved, access):
        self.calls.append(("OpenKey", path, access))
        return FakeKey()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def CreateKey(self, root, path):
        self.calls.append(("CreateKey", path))
        return FakeKey()

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value
        self.calls.append(("SetValueEx", name, value))

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]
        self.calls.append(("DeleteValue", name))


def test_is_windows_matches_os_name():
    assert windows_startup.is_windows() is (os.name == "nt")


def test_startup_command_uses_frozen_executable(monkeypatch):
    monkeypatch.setattr(windows_startup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows_startup.sys, "executable", r"C:\Program Files\AAA\AAA.exe")

    command = windows_startup.startup_command()

    assert command == r'"C:\Program Files\AAA\AAA.exe" --autostart'


def test_startup_command_includes_manager_script_for_source_runs(monkeypatch):
    monkeypatch.setattr(windows_startup.sys, "frozen", False, raising=False)
    monkeypatch.setattr(windows_startup.sys, "executable", r"C:\Python\python.exe")

    command = windows_startup.startup_command()

    assert "--autostart" in command
    assert "tradingagents_service_manager.py" in command


def test_set_enabled_true_writes_current_user_run_value(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setattr(windows_startup, "is_windows", lambda: True)
    monkeypatch.setattr(windows_startup, "winreg", fake)
    monkeypatch.setattr(
        windows_startup,
        "startup_command",
        lambda: r'"C:\Program Files\AAA\AAA.exe" --autostart',
    )

    windows_startup.set_enabled(True)

    assert fake.values[windows_startup.STARTUP_VALUE_NAME] == (
        r'"C:\Program Files\AAA\AAA.exe" --autostart'
    )
    assert ("CreateKey", windows_startup.RUN_KEY_PATH) in fake.calls


def test_set_enabled_false_removes_existing_value(monkeypatch):
    fake = FakeWinreg()
    fake.values[windows_startup.STARTUP_VALUE_NAME] = "old command"
    monkeypatch.setattr(windows_startup, "is_windows", lambda: True)
    monkeypatch.setattr(windows_startup, "winreg", fake)

    windows_startup.set_enabled(False)

    assert windows_startup.STARTUP_VALUE_NAME not in fake.values
    assert ("DeleteValue", windows_startup.STARTUP_VALUE_NAME) in fake.calls


def test_set_enabled_false_is_safe_when_value_is_missing(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setattr(windows_startup, "is_windows", lambda: True)
    monkeypatch.setattr(windows_startup, "winreg", fake)

    windows_startup.set_enabled(False)

    assert windows_startup.STARTUP_VALUE_NAME not in fake.values


def test_is_enabled_reads_run_value_presence(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setattr(windows_startup, "is_windows", lambda: True)
    monkeypatch.setattr(windows_startup, "winreg", fake)

    assert windows_startup.is_enabled_for_current_user() is False

    fake.values[windows_startup.STARTUP_VALUE_NAME] = "enabled command"

    assert windows_startup.is_enabled_for_current_user() is True


def test_non_windows_skips_registry_operations(monkeypatch):
    monkeypatch.setattr(windows_startup, "is_windows", lambda: False)
    monkeypatch.setattr(windows_startup, "winreg", None)

    assert windows_startup.is_enabled_for_current_user() is False
    windows_startup.set_enabled(True)
    windows_startup.set_enabled(False)


class FakeVar:
    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeStringVar(FakeVar):
    pass


class FakeRoot:
    def __init__(self):
        self.after_calls = []

    def title(self, _value):
        pass

    def geometry(self, _value):
        pass

    def minsize(self, _width, _height):
        pass

    def bind(self, _sequence, _callback):
        pass

    def protocol(self, _name, _callback):
        pass

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))


def _patch_app_construction(monkeypatch):
    monkeypatch.setattr(manager.settings_store, "load_settings", lambda: {})
    monkeypatch.setattr(manager.tk, "BooleanVar", lambda value=False: FakeVar(value))
    monkeypatch.setattr(manager.tk, "StringVar", lambda value="": FakeStringVar(value))
    monkeypatch.setattr(ServiceManagerApp, "_build_ui", lambda self: None)
    monkeypatch.setattr(ServiceManagerApp, "_apply_window_icon", lambda self: None)
    monkeypatch.setattr(ServiceManagerApp, "_sync_tray_mode", lambda self: None)
    monkeypatch.setattr(ServiceManagerApp, "refresh_async", lambda self: None)
    monkeypatch.setattr(ServiceManagerApp, "_schedule_refresh", lambda self: None)


def test_autostart_true_schedules_startup_tasks(monkeypatch):
    _patch_app_construction(monkeypatch)
    root = FakeRoot()

    app = ServiceManagerApp(root, autostart=True)

    assert any(callback == app._run_startup_tasks for _delay, callback in root.after_calls)


def test_manual_start_does_not_schedule_startup_tasks(monkeypatch):
    _patch_app_construction(monkeypatch)
    root = FakeRoot()

    ServiceManagerApp(root, autostart=False)

    assert root.after_calls == []


def test_run_startup_tasks_starts_api_and_scheduled_task_workers(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target, daemon=False):
            self.target = target
            self.daemon = daemon

        def start(self):
            started.append(self.target)

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app._safe_log = lambda message: None
    monkeypatch.setattr(manager.windows_startup, "is_windows", lambda: True)
    monkeypatch.setattr(manager.threading, "Thread", FakeThread)

    app._run_startup_tasks()

    assert app._enable_tasks_for_autostart in started
    assert app._check_api_for_autostart in started


def test_enable_tasks_for_autostart_records_success(monkeypatch):
    enabled_values = []
    log_messages = []
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app._write_startup_log = log_messages.append
    app._safe_log = log_messages.append
    monkeypatch.setattr(manager, "set_briefing_tasks_enabled", enabled_values.append)

    app._enable_tasks_for_autostart()

    assert enabled_values == [True]
    assert any("自动启用定时服务" in message for message in log_messages)


def test_enable_tasks_for_autostart_swallows_failure(monkeypatch):
    log_messages = []
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app._write_startup_log = log_messages.append
    app._safe_log = log_messages.append

    def fail(_enabled):
        raise OSError("scheduled task error")

    monkeypatch.setattr(manager, "set_briefing_tasks_enabled", fail)

    app._enable_tasks_for_autostart()

    assert any("失败" in message for message in log_messages)


def test_check_api_for_autostart_writes_success_message(monkeypatch):
    log_messages = []
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.settings = {}
    app._write_startup_log = log_messages.append
    app._safe_log = log_messages.append
    monkeypatch.setattr(
        manager.settings_store,
        "settings_to_llm_api_settings",
        lambda settings, **kwargs: {"base_url": "https://api.example.com/v1", "api_key": "k", "model": "m"},
    )

    class Result:
        message = "连接成功"

    monkeypatch.setattr(
        manager.llm_api,
        "test_openai_compatible_connection",
        lambda api_settings, timeout=15: Result(),
    )

    app._check_api_for_autostart()

    assert any("连接成功" in message for message in log_messages)


def test_check_api_for_autostart_swallows_network_errors(monkeypatch):
    log_messages = []
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.settings = {}
    app._write_startup_log = log_messages.append
    app._safe_log = log_messages.append
    monkeypatch.setattr(
        manager.settings_store,
        "settings_to_llm_api_settings",
        lambda settings, **kwargs: {"base_url": "", "api_key": "", "model": ""},
    )

    def fail(_api_settings, timeout=15):
        raise TimeoutError("network not ready")

    monkeypatch.setattr(manager.llm_api, "test_openai_compatible_connection", fail)

    app._check_api_for_autostart()

    assert any("异常" in message for message in log_messages)


def test_save_startup_preference_enabled_persists_and_writes_registry(monkeypatch):
    set_calls = []
    saved = []
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.start_with_windows = FakeVar(True)
    app.settings = {}
    app.startup_status_text = FakeStringVar("")
    app.save_current_settings = lambda silent=False: saved.append(
        dict(app.settings, start_with_windows=app.start_with_windows.get())
    )
    app._sync_startup_widgets = lambda: None
    app._append_log = lambda message: None
    monkeypatch.setattr(manager.windows_startup, "is_windows", lambda: True)
    monkeypatch.setattr(manager.windows_startup, "set_enabled", set_calls.append)
    monkeypatch.setattr(manager.windows_startup, "is_enabled_for_current_user", lambda: True)

    app._save_startup_preference()

    assert set_calls == [True]
    assert app.settings["start_with_windows"] is True
    assert saved[0]["start_with_windows"] is True


def test_save_startup_preference_failure_reverts_checkbox(monkeypatch):
    shown_errors = []
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.start_with_windows = FakeVar(True)
    app.settings = {}
    app.startup_status_text = FakeStringVar("")
    app.save_current_settings = lambda silent=False: None
    app._sync_startup_widgets = lambda: None
    app._append_log = lambda message: None
    monkeypatch.setattr(manager.windows_startup, "is_windows", lambda: True)
    monkeypatch.setattr(manager.windows_startup, "is_enabled_for_current_user", lambda: False)
    monkeypatch.setattr(
        manager.windows_startup,
        "set_enabled",
        lambda enabled: (_ for _ in ()).throw(OSError("registry denied")),
    )
    monkeypatch.setattr(
        manager.messagebox,
        "showerror",
        lambda title, message: shown_errors.append((title, message)),
    )

    app._save_startup_preference()

    assert app.start_with_windows.get() is False
    assert app.settings["start_with_windows"] is False
    assert shown_errors


def test_sync_startup_widgets_reports_actual_registry_state(monkeypatch):
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.startup_status_text = FakeStringVar("")
    monkeypatch.setattr(manager.windows_startup, "is_windows", lambda: True)
    monkeypatch.setattr(manager.windows_startup, "is_enabled_for_current_user", lambda: True)

    app._sync_startup_widgets()

    assert "已开启" in app.startup_status_text.get()

    monkeypatch.setattr(manager.windows_startup, "is_enabled_for_current_user", lambda: False)
    app._sync_startup_widgets()

    assert "已关闭" in app.startup_status_text.get()


def test_sync_startup_widgets_reports_non_windows(monkeypatch):
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.startup_status_text = FakeStringVar("")
    monkeypatch.setattr(manager.windows_startup, "is_windows", lambda: False)

    app._sync_startup_widgets()

    assert "不支持" in app.startup_status_text.get()
