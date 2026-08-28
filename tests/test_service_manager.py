from pathlib import Path

import tools.tradingagents_service_manager as manager
from tools.tradingagents_service_manager import (
    ProcessRecord,
    ScheduledTaskRecord,
    ServiceManagerApp,
    build_briefing_command,
    build_briefing_task_action,
    collect_process_tree,
    find_tradingagents_processes,
    resolve_briefing_dir,
    resolve_project_root_from_anchors,
)

PROJECT_ROOT = str(manager.PROJECT_ROOT)
WORKSPACE_ROOT = str(manager.WORKSPACE_ROOT)
BRIEFING_DIR = str(manager.BRIEFING_DIR)


def test_finds_python_process_started_from_project_path():
    processes = [
        ProcessRecord(
            pid=100,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{PROJECT_ROOT}\main.py"',
        ),
        ProcessRecord(
            pid=101,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=r'python "E:\other\server.py"',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids=set(),
    )

    assert [process.pid for process in matches] == [100]


def test_ignores_the_service_manager_itself():
    processes = [
        ProcessRecord(
            pid=200,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{PROJECT_ROOT}\tools\tradingagents_service_manager.py"',
        ),
        ProcessRecord(
            pid=201,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{PROJECT_ROOT}\main.py"',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids={200},
    )

    assert [process.pid for process in matches] == [201]


def test_ignores_test_runner_processes_inside_project_path():
    processes = [
        ProcessRecord(
            pid=300,
            parent_pid=1,
            name="python.exe",
            executable_path=rf"{PROJECT_ROOT}\.venv\Scripts\python.exe",
            command_line=rf'python -m pytest "{PROJECT_ROOT}\tests\test_service_manager.py"',
        ),
        ProcessRecord(
            pid=301,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{PROJECT_ROOT}\main.py"',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids=set(),
    )

    assert [process.pid for process in matches] == [301]


def test_ignores_processes_from_other_tradingagents_checkouts():
    other_project = r"D:\other-work\TradingAgents"
    processes = [
        ProcessRecord(
            pid=350,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{other_project}\main.py"',
        ),
        ProcessRecord(
            pid=351,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{PROJECT_ROOT}\main.py"',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids=set(),
    )

    assert [process.pid for process in matches] == [351]


def test_finds_daily_briefing_process_started_from_workspace_path():
    processes = [
        ProcessRecord(
            pid=400,
            parent_pid=1,
            name="pythonw.exe",
            executable_path=r"C:\Python310\pythonw.exe",
            command_line=rf'pythonw "{BRIEFING_DIR}\run_briefing.py" --mode monitor',
        ),
        ProcessRecord(
            pid=401,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=r'python "E:\other\daily_briefing\run_briefing.py" --mode monitor',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids=set(),
    )

    assert [process.pid for process in matches] == [400]


def test_finds_packaged_briefing_process_started_from_clean_folder():
    processes = [
        ProcessRecord(
            pid=410,
            parent_pid=1,
            name="AStockBriefingManager.exe",
            executable_path=rf"{WORKSPACE_ROOT}\AStockBriefingManager.exe",
            command_line=rf'"{WORKSPACE_ROOT}\AStockBriefingManager.exe" --run-briefing --mode monitor',
        ),
        ProcessRecord(
            pid=411,
            parent_pid=1,
            name="AStockBriefingManager.exe",
            executable_path=rf"{WORKSPACE_ROOT}\AStockBriefingManager.exe",
            command_line=rf'"{WORKSPACE_ROOT}\AStockBriefingManager.exe"',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids=set(),
    )

    assert [process.pid for process in matches] == [410]


def test_collect_process_tree_returns_descendants_before_parent():
    processes = [
        ProcessRecord(10, 1, "uv.exe", "", "uv run python main.py"),
        ProcessRecord(11, 10, "python.exe", "", "python main.py"),
        ProcessRecord(12, 11, "python.exe", "", "worker"),
        ProcessRecord(20, 1, "python.exe", "", "other"),
    ]

    assert collect_process_tree([10], processes, excluded_pids=set()) == [12, 11, 10]


def test_build_briefing_command_can_generate_preview_without_sending():
    command = build_briefing_command("premarket", send=False)

    assert command[0].endswith(("pythonw.exe", "python.exe", "py.exe"))
    assert command[-4:] == [
        str(Path(BRIEFING_DIR) / "run_briefing.py"),
        "--mode",
        "premarket",
        "--no-send",
    ]


def test_build_briefing_command_can_generate_and_send():
    command = build_briefing_command("close", send=True)

    assert command[-3:] == [
        str(Path(BRIEFING_DIR) / "run_briefing.py"),
        "--mode",
        "close",
    ]


def test_build_briefing_command_uses_packaged_exe_when_frozen(monkeypatch):
    monkeypatch.setattr(manager.sys, "frozen", True, raising=False)
    monkeypatch.setattr(manager.sys, "executable", rf"{WORKSPACE_ROOT}\AStockBriefingManager.exe")

    command = build_briefing_command("midday", send=False)

    assert command == [
        rf"{WORKSPACE_ROOT}\AStockBriefingManager.exe",
        "--run-briefing",
        "--mode",
        "midday",
        "--no-send",
    ]


def test_scheduled_task_action_uses_packaged_exe_when_frozen(monkeypatch):
    monkeypatch.setattr(manager.sys, "frozen", True, raising=False)
    monkeypatch.setattr(manager.sys, "executable", rf"{WORKSPACE_ROOT}\AStockBriefingManager.exe")

    action = build_briefing_task_action("close")

    assert action.execute == rf"{WORKSPACE_ROOT}\AStockBriefingManager.exe"
    assert action.arguments == "--run-briefing --mode close"
    assert action.working_directory == WORKSPACE_ROOT


def test_scheduled_refresh_waits_before_polling_again():
    calls = []

    class FakeRoot:
        def after(self, delay_ms, callback):
            calls.append((delay_ms, callback))

    class Enabled:
        def get(self):
            return True

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.root = FakeRoot()
    app.auto_refresh = Enabled()
    app.refresh = lambda silent=False: calls.append(("refresh", silent))

    app._schedule_refresh()

    assert len(calls) == 1
    assert calls[0][0] == 5000
    assert callable(calls[0][1])


def test_resolve_project_root_when_exe_is_in_workspace_root(tmp_path):
    workspace = tmp_path / "A沪深"
    project = workspace / "TradingAgents"
    (project / "tools").mkdir(parents=True)
    (workspace / "daily_briefing").mkdir()

    assert resolve_project_root_from_anchors([workspace]) == project


def test_resolve_project_root_when_exe_is_in_dist_folder(tmp_path):
    workspace = tmp_path / "A沪深"
    project = workspace / "TradingAgents"
    dist = project / "dist"
    (project / "tools").mkdir(parents=True)
    (workspace / "daily_briefing").mkdir()
    dist.mkdir()

    assert resolve_project_root_from_anchors([dist]) == project


def test_resolve_project_root_when_repo_contains_briefing_dir(tmp_path):
    project = tmp_path / "AAAA-felix-gupiao"
    (project / "tools").mkdir(parents=True)
    (project / "daily_briefing").mkdir()

    assert resolve_project_root_from_anchors([project]) == project


def test_resolve_project_root_from_clean_portable_folder(tmp_path):
    workspace = tmp_path / "AStockBriefingManager"
    (workspace / "daily_briefing").mkdir(parents=True)

    assert resolve_project_root_from_anchors([workspace]) == workspace / "TradingAgents"


def test_resolve_briefing_dir_prefers_sibling_layout(tmp_path, monkeypatch):
    monkeypatch.delenv("A_STOCK_BRIEFING_DIR", raising=False)
    workspace = tmp_path / "AStock"
    project = workspace / "TradingAgents"
    briefing = workspace / "daily_briefing"
    project.mkdir(parents=True)
    briefing.mkdir()

    assert resolve_briefing_dir(project) == briefing


def test_resolve_briefing_dir_supports_repo_local_layout(tmp_path, monkeypatch):
    monkeypatch.delenv("A_STOCK_BRIEFING_DIR", raising=False)
    project = tmp_path / "AAAA-felix-gupiao"
    briefing = project / "daily_briefing"
    briefing.mkdir(parents=True)

    assert resolve_briefing_dir(project) == briefing


def test_api_settings_form_values_are_normalized():
    class FakeVar:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.api_vars = {
        "base_url": FakeVar(" https://api.example.com/v1/ "),
        "api_key": FakeVar(" sk-test-key "),
        "model": FakeVar(" gpt-test "),
    }

    assert app._api_settings_from_form() == {
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-key",
        "model": "gpt-test",
    }


def test_smtp_settings_form_values_are_normalized():
    class FakeVar:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.smtp_vars = {
        "host": FakeVar(" smtp.example.com "),
        "port": FakeVar(" 465 "),
        "user": FakeVar(" sender@example.com "),
        "auth_code": FakeVar(" auth-code "),
    }

    assert app._smtp_settings_from_form() == {
        "host": "smtp.example.com",
        "port": 465,
        "user": "sender@example.com",
        "auth_code": "auth-code",
    }


def test_api_connection_success_updates_model_options():
    class FakeVar:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    class FakeCombo:
        def __init__(self):
            self.values = ()

        def __setitem__(self, key, value):
            if key == "values":
                self.values = value

    result = type(
        "Result",
        (),
        {
            "ok": True,
            "message": "连接成功。",
            "models": ("model-a", "model-b"),
        },
    )()
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.api_test_status = FakeVar()
    app.model_combo = FakeCombo()

    message = app._format_api_test_result(result)

    assert message == "连接成功。"
    assert app.api_test_status.value == "连接正常"
    assert app.model_combo.values == ("model-a", "model-b")


def test_taskbar_title_shows_background_running_state():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    assert app._taskbar_title_for_status("运行中: 2") == "A股每日简报服务管理器 - 后台运行中"
    assert app._taskbar_title_for_status("定时已启用") == "A股每日简报服务管理器"


def test_theme_tokens_use_banana_dark_console_palette():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    tokens = app._theme_tokens()

    assert tokens["window_bg"] == "#0f1117"
    assert tokens["panel_bg"] == "#171a21"
    assert tokens["accent"] == "#ffd84d"
    assert tokens["success"] == "#2ee59d"


def test_navigation_renames_api_to_settings():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    nav_items = app._nav_items()

    assert ("settings", "设置") in nav_items
    assert all(label != "API" for _key, label in nav_items)


def test_overview_card_grid_uses_two_columns_to_avoid_overlap():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    assert app._overview_card_grid_position(0) == (0, 0)
    assert app._overview_card_grid_position(1) == (0, 1)
    assert app._overview_card_grid_position(2) == (1, 0)
    assert app._overview_card_grid_position(4) == (2, 0)


def test_is_newer_version_compares_release_tags():
    assert manager.is_newer_version("0.2.0", "v0.2.1") is True
    assert manager.is_newer_version("0.2.1", "v0.2.1") is False
    assert manager.is_newer_version("0.2.1", "v0.2.0") is False


def test_check_latest_release_detects_newer_release():
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "tag_name": "v0.2.1",
                "html_url": "https://github.com/felix1709/AAAA-felix-gupiao/releases/tag/v0.2.1",
            }

    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    result = manager.check_latest_release(current_version="0.2.0", request_get=fake_get)

    assert result.ok is True
    assert result.has_update is True
    assert result.latest_version == "v0.2.1"
    assert "发现新版本" in result.message
    assert calls[0][0].endswith("/releases/latest")


def test_update_check_result_restores_button_state():
    class FakeVar:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    class FakeButton:
        def __init__(self):
            self.state = "disabled"

        def configure(self, **kwargs):
            self.state = kwargs["state"]

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.update_check_status = FakeVar()
    app.update_check_button = FakeButton()

    message = app._format_update_check_result(
        manager.UpdateCheckResult(
            ok=True,
            has_update=False,
            latest_version="v0.2.0",
            message="当前已是最新版本。",
        )
    )

    assert message == "当前已是最新版本。"
    assert app.update_check_status.value == "当前已是最新版本。"
    assert app.update_check_button.state == "normal"


def test_window_close_handler_is_registered(monkeypatch):
    class FakeVar:
        def __init__(self, value=None):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    class FakeRoot:
        def __init__(self):
            self.protocol_calls = []

        def title(self, _value):
            pass

        def geometry(self, _value):
            pass

        def minsize(self, _width, _height):
            pass

        def protocol(self, name, callback):
            self.protocol_calls.append((name, callback))

    root = FakeRoot()
    monkeypatch.setattr(manager.settings_store, "load_settings", lambda: {})
    monkeypatch.setattr(manager.tk, "BooleanVar", lambda value=False: FakeVar(value))
    monkeypatch.setattr(manager.tk, "StringVar", lambda value="": FakeVar(value))
    monkeypatch.setattr(ServiceManagerApp, "_build_ui", lambda self: None)
    monkeypatch.setattr(ServiceManagerApp, "refresh_async", lambda self: None)
    monkeypatch.setattr(ServiceManagerApp, "_schedule_refresh", lambda self: None)

    app = ServiceManagerApp(root)

    assert root.protocol_calls == [("WM_DELETE_WINDOW", app.on_close_request)]


def test_has_background_activity_when_processes_or_tasks_enabled():
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.processes = []
    app.task_records = []

    assert app._has_background_activity() is False

    app.task_records = [ScheduledTaskRecord("daily", "Ready", "", "", "")]
    assert app._has_background_activity() is True

    app.task_records = [ScheduledTaskRecord("daily", "Disabled", "", "", "")]
    app.processes = [ProcessRecord(10, 1, "python.exe", "", "python run_briefing.py")]
    assert app._has_background_activity() is True


def test_close_request_without_background_exits_immediately():
    class FakeRoot:
        def __init__(self):
            self.destroyed = False
            self.iconified = False

        def destroy(self):
            self.destroyed = True

        def iconify(self):
            self.iconified = True

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.root = FakeRoot()
    app.processes = []
    app.task_records = [ScheduledTaskRecord("daily", "Disabled", "", "", "")]
    app._ask_close_action = lambda: "shutdown"

    app.on_close_request()

    assert app.root.destroyed is True
    assert app.root.iconified is False


def test_close_request_can_minimize_to_taskbar():
    class FakeRoot:
        def __init__(self):
            self.destroyed = False
            self.iconified = False

        def destroy(self):
            self.destroyed = True

        def iconify(self):
            self.iconified = True

    logs = []
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.root = FakeRoot()
    app.processes = [ProcessRecord(10, 1, "python.exe", "", "python run_briefing.py")]
    app.task_records = []
    app._ask_close_action = lambda: "minimize"
    app._append_log = logs.append

    app.on_close_request()

    assert app.root.iconified is True
    assert app.root.destroyed is False
    assert logs == ["窗口已最小化到任务栏，后台服务继续运行。"]


def test_close_request_can_shutdown_service_and_exit(monkeypatch):
    class FakeRoot:
        def __init__(self):
            self.destroyed = False
            self.iconified = False

        def destroy(self):
            self.destroyed = True

        def iconify(self):
            self.iconified = True

    disabled_values = []
    stopped_pids = []
    logs = []

    def fake_stop_process_tree(pids):
        stopped_pids.extend(pids)
        return manager.StopResult(stopped=list(pids), failed={})

    monkeypatch.setattr(manager, "set_briefing_tasks_enabled", disabled_values.append)
    monkeypatch.setattr(manager, "stop_process_tree", fake_stop_process_tree)

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.root = FakeRoot()
    app.processes = [ProcessRecord(10, 1, "python.exe", "", "python run_briefing.py")]
    app.task_records = [ScheduledTaskRecord("daily", "Ready", "", "", "")]
    app._ask_close_action = lambda: "shutdown"
    app._append_log = logs.append

    app.on_close_request()

    assert disabled_values == [False]
    assert stopped_pids == [10]
    assert app.root.destroyed is True
    assert app.root.iconified is False
    assert "定时服务已停用" in logs
    assert "已停止 PID: 10" in logs


def test_next_run_time_picks_first_available_task_time():
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.task_records = [
        ScheduledTaskRecord("a", "Disabled", "", "", ""),
        ScheduledTaskRecord("b", "Ready", "2026/08/28 15:00:00", "", ""),
    ]

    assert app._next_run_time() == "2026/08/28 15:00:00"


def test_overview_items_report_configuration_state():
    class FakeVar:
        def get(self):
            return "连接正常"

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.processes = []
    app.task_records = [ScheduledTaskRecord("daily", "Ready", "2026/08/28 09:00:00", "", "0")]
    app.settings = {
        "recipients": ["desk@example.com"],
        "stocks": [{"full_code": "600000.SS", "enabled": True}],
        "smtp": {
            "host": "smtp.example.com",
            "user": "desk@example.com",
            "auth_code": "secret",
        },
        "llm_api": {
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-key",
            "model": "gpt-test",
        },
    }
    app.api_test_status = FakeVar()

    items = app._overview_items()

    assert ("邮箱配置", "正常", "发件邮箱已配置，收件人 1 个") in items
    assert ("API 配置", "正常", "gpt-test") in items


def test_api_background_error_restores_test_button():
    class FakeVar:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    class FakeButton:
        def __init__(self):
            self.state = "disabled"

        def configure(self, **kwargs):
            self.state = kwargs["state"]

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.api_test_status = FakeVar()
    app.api_test_button = FakeButton()
    app._append_log = lambda message: None
    app._sync_overview = lambda: None

    app._after_background_error("测试 API 连接", "boom")

    assert app.api_test_status.value == "连接失败"
    assert app.api_test_button.state == "normal"


def test_saving_unchanged_api_settings_keeps_successful_test_status(monkeypatch):
    class FakeVar:
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.settings = {
        "llm_api": {
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-key",
            "model": "gpt-test",
        }
    }
    app.api_vars = {
        "base_url": FakeVar("https://api.example.com/v1"),
        "api_key": FakeVar("sk-test-key"),
        "model": FakeVar("gpt-test"),
    }
    app.api_key_hint = FakeVar()
    app.api_test_status = FakeVar("连接正常")
    app._sync_recipient_list = lambda: None
    app._sync_stock_tree = lambda: None
    app._sync_schedule_table = lambda: None
    app._sync_smtp_widgets = lambda: None
    app._sync_overview = lambda: None
    app._append_log = lambda _message: None
    monkeypatch.setattr(manager.settings_store, "save_settings", lambda settings: settings)

    app.save_api_settings()

    assert app.api_test_status.value == "连接正常"


def test_saving_changed_api_settings_requires_retest(monkeypatch):
    class FakeVar:
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.settings = {
        "llm_api": {
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-key",
            "model": "gpt-old",
        }
    }
    app.api_vars = {
        "base_url": FakeVar("https://api.example.com/v1"),
        "api_key": FakeVar("sk-test-key"),
        "model": FakeVar("gpt-new"),
    }
    app.api_key_hint = FakeVar()
    app.api_test_status = FakeVar("连接正常")
    app._sync_recipient_list = lambda: None
    app._sync_stock_tree = lambda: None
    app._sync_schedule_table = lambda: None
    app._sync_smtp_widgets = lambda: None
    app._sync_overview = lambda: None
    app._append_log = lambda _message: None
    monkeypatch.setattr(manager.settings_store, "save_settings", lambda settings: settings)

    app.save_api_settings()

    assert app.api_test_status.value == "未测试"
