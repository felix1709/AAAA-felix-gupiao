from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import requests


def resolve_project_root_from_anchors(anchors: Iterable[Path]) -> Path | None:
    for anchor in anchors:
        anchor = Path(anchor).resolve()
        for candidate in (anchor, *anchor.parents):
            if (
                candidate.name.casefold() == "tradingagents"
                and (candidate / "tools").exists()
                and (candidate.parent / "daily_briefing").exists()
            ):
                return candidate
            if (candidate / "tools").exists() and (candidate / "daily_briefing").exists():
                return candidate
            project_dir = candidate / "TradingAgents"
            if project_dir.exists() and (candidate / "daily_briefing").exists():
                return project_dir
            if (candidate / "daily_briefing").exists():
                return candidate / "TradingAgents"
    return None


def resolve_project_root() -> Path:
    anchors = [Path.cwd()]
    if getattr(sys, "frozen", False):
        anchors.insert(0, Path(sys.executable).resolve().parent)
    else:
        anchors.insert(0, Path(__file__).resolve().parents[1])
    return resolve_project_root_from_anchors(anchors) or Path(__file__).resolve().parents[1]


def resolve_briefing_dir(project_root: Path) -> Path:
    configured = os.getenv("A_STOCK_BRIEFING_DIR")
    if configured:
        return Path(configured).resolve()

    sibling = project_root.parent / "daily_briefing"
    if sibling.exists():
        return sibling

    in_repo = project_root / "daily_briefing"
    if in_repo.exists():
        return in_repo

    return sibling


PROJECT_ROOT = resolve_project_root()
BRIEFING_DIR = resolve_briefing_dir(PROJECT_ROOT)
WORKSPACE_ROOT = BRIEFING_DIR.parent
BRIEFING_SCRIPT = BRIEFING_DIR / "run_briefing.py"
SETUP_TASKS_SCRIPT = BRIEFING_DIR / "setup_tasks.ps1"
MANAGER_SCRIPT_NAME = "tradingagents_service_manager.py"
LAUNCHER_SCRIPT_NAME = "start_service_manager.bat"
PACKAGED_EXE_NAME = "astockbriefingmanager.exe"
APP_TITLE = "A股每日简报服务管理器"
APP_RUNNING_TITLE = f"{APP_TITLE} - 后台运行中"
APP_VERSION = "0.2.4"
GITHUB_REPO_URL = "https://github.com/felix1709/AAAA-felix-gupiao"
GITHUB_LATEST_RELEASE_API = (
    "https://api.github.com/repos/felix1709/AAAA-felix-gupiao/releases/latest"
)
RELEASE_ASSET_NAME = "AStockBriefingManager-clean.zip"
BRIEFING_SCRIPT_NAME = "run_briefing.py"
SERVICE_PROCESS_NAMES = {
    "python.exe",
    "pythonw.exe",
    "uv.exe",
    "tradingagents.exe",
    PACKAGED_EXE_NAME,
}
MAINTENANCE_COMMAND_MARKERS = (
    " -m pytest",
    "\\pytest.exe",
    " ruff ",
    "\\ruff.exe",
    " py_compile",
    MANAGER_SCRIPT_NAME,
)
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
BANANA_DARK_THEME = {
    "window_bg": "#0f1117",
    "panel_bg": "#171a21",
    "card_bg": "#1f2430",
    "card_alt_bg": "#222837",
    "border": "#303746",
    "accent": "#ffd84d",
    "accent_active": "#ffe680",
    "accent_fg": "#15120a",
    "text": "#f5f7fb",
    "muted": "#98a2b3",
    "success": "#2ee59d",
    "warning": "#ffb020",
    "danger": "#ff5c5c",
    "info": "#4dd8ff",
    "input_bg": "#10141d",
}
os.environ.setdefault("A_STOCK_BRIEFING_DIR", str(BRIEFING_DIR))

if str(BRIEFING_DIR) not in sys.path:
    sys.path.insert(0, str(BRIEFING_DIR))

import config  # noqa: E402
import llm_api  # noqa: E402
import settings_store  # noqa: E402

BRIEFING_TASK_NAMES = [item["task_name"] for item in settings_store.DEFAULT_EMAIL_SCHEDULE]


@dataclass(frozen=True)
class ScheduledTaskRecord:
    name: str
    state: str
    next_run_time: str
    last_run_time: str
    last_result: str


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    parent_pid: int
    name: str
    executable_path: str
    command_line: str

    @classmethod
    def from_cim(cls, item: dict) -> ProcessRecord:
        return cls(
            pid=int(item.get("ProcessId") or 0),
            parent_pid=int(item.get("ParentProcessId") or 0),
            name=str(item.get("Name") or ""),
            executable_path=str(item.get("ExecutablePath") or ""),
            command_line=str(item.get("CommandLine") or ""),
        )


@dataclass(frozen=True)
class StopResult:
    stopped: list[int]
    failed: dict[int, str]


@dataclass(frozen=True)
class BriefingTaskAction:
    execute: str
    arguments: str
    working_directory: str


@dataclass(frozen=True)
class UpdateCheckResult:
    ok: bool
    has_update: bool
    latest_version: str
    message: str
    release_url: str = ""
    asset_name: str = ""
    asset_download_url: str = ""


@dataclass(frozen=True)
class UpdateInstallResult:
    ok: bool
    message: str
    script_path: str = ""
    package_root: str = ""


def _version_numbers(value: str) -> tuple[int, ...]:
    numbers = [int(part) for part in re.findall(r"\d+", value or "")]
    return tuple(numbers) or (0,)


def is_newer_version(current: str, latest: str) -> bool:
    current_parts = _version_numbers(current)
    latest_parts = _version_numbers(latest)
    length = max(len(current_parts), len(latest_parts))
    current_padded = current_parts + (0,) * (length - len(current_parts))
    latest_padded = latest_parts + (0,) * (length - len(latest_parts))
    return latest_padded > current_padded


def find_release_zip_asset(release_data: dict) -> tuple[str, str]:
    assets = release_data.get("assets")
    if not isinstance(assets, list):
        return "", ""

    normalized_name = RELEASE_ASSET_NAME.casefold()
    zip_assets: list[tuple[str, str]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        download_url = str(asset.get("browser_download_url") or "").strip()
        if not name or not download_url:
            continue
        if name.casefold() == normalized_name:
            return name, download_url
        if name.casefold().endswith(".zip"):
            zip_assets.append((name, download_url))

    return zip_assets[0] if zip_assets else ("", "")


def check_latest_release(
    *,
    current_version: str = APP_VERSION,
    request_get=requests.get,
    timeout: int = 10,
) -> UpdateCheckResult:
    try:
        response = request_get(
            GITHUB_LATEST_RELEASE_API,
            headers={"Accept": "application/vnd.github+json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return UpdateCheckResult(False, False, "", f"检测更新失败：{exc}")

    if getattr(response, "status_code", None) == 404:
        return UpdateCheckResult(
            True,
            False,
            current_version,
            "仓库暂未发布 Release，当前版本可继续使用。",
            GITHUB_REPO_URL,
        )

    try:
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return UpdateCheckResult(False, False, "", f"检测更新失败：{exc}")
    except ValueError:
        return UpdateCheckResult(False, False, "", "检测更新失败：GitHub 返回内容不是 JSON。")

    latest_version = str(data.get("tag_name") or data.get("name") or "").strip()
    release_url = str(data.get("html_url") or GITHUB_REPO_URL)
    if not latest_version:
        return UpdateCheckResult(False, False, "", "检测更新失败：没有读取到最新版本号。")

    asset_name, asset_download_url = find_release_zip_asset(data)
    has_update = is_newer_version(current_version, latest_version)
    if has_update:
        if asset_download_url:
            message = f"发现新版本 {latest_version}，可一键下载并安装。"
        else:
            message = f"发现新版本 {latest_version}，但未找到可自动安装的 zip 包。"
    else:
        message = f"当前已是最新版本（{current_version}）。"
    return UpdateCheckResult(
        True,
        has_update,
        latest_version,
        message,
        release_url,
        asset_name,
        asset_download_url,
    )


def _is_sensitive_update_path(relative_path: Path) -> bool:
    parts = tuple(part.casefold() for part in relative_path.parts)
    if relative_path.name.casefold() == ".env":
        return True
    return len(parts) >= 2 and parts[0] == "daily_briefing" and parts[1] in {"data", "logs"}


def build_update_file_manifest(package_root: Path) -> list[Path]:
    package_root = Path(package_root)
    files: list[Path] = []
    for item in package_root.rglob("*"):
        if not item.is_file():
            continue
        relative_path = item.relative_to(package_root)
        if _is_sensitive_update_path(relative_path):
            continue
        files.append(relative_path)
    return sorted(files, key=lambda path: tuple(part.casefold() for part in path.parts))


def find_update_package_root(extract_root: Path) -> Path:
    extract_root = Path(extract_root)
    for item in extract_root.iterdir():
        if item.is_file() and item.name.casefold() == PACKAGED_EXE_NAME:
            return extract_root

    candidates = [
        item.parent
        for item in extract_root.rglob("*")
        if item.is_file() and item.name.casefold() == PACKAGED_EXE_NAME
    ]
    if not candidates:
        raise ValueError("更新包中没有找到 AStockBriefingManager.exe。")
    return sorted(candidates, key=lambda path: (len(path.parts), str(path).casefold()))[0]


def _is_path_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def extract_update_archive(archive_path: Path, extract_root: Path) -> None:
    archive_path = Path(archive_path)
    extract_root = Path(extract_root).resolve()
    extract_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            member_name = member.filename.replace("\\", "/")
            target_path = (extract_root / member_name).resolve()
            if not _is_path_relative_to(target_path, extract_root):
                raise ValueError(f"更新包包含不安全路径：{member.filename}")
        archive.extractall(extract_root)


def _powershell_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def write_update_script(
    *,
    package_root: Path,
    install_root: Path,
    current_executable: Path,
    current_pid: int,
    manifest: list[Path] | None = None,
    script_path: Path | None = None,
    temp_root: Path | None = None,
) -> Path:
    package_root = Path(package_root).resolve()
    install_root = Path(install_root).resolve()
    current_executable = Path(current_executable).resolve()
    temp_root = Path(temp_root or package_root.parent).resolve()
    script_path = Path(script_path or temp_root / "install_update.ps1").resolve()
    manifest = manifest if manifest is not None else build_update_file_manifest(package_root)

    files = "\n".join(
        f"    {_powershell_literal(str(relative_path))}"
        for relative_path in manifest
        if not _is_sensitive_update_path(relative_path)
    )
    script = f"""$ErrorActionPreference = 'Stop'
$PidToWait = {int(current_pid)}
$SourceRoot = {_powershell_literal(package_root)}
$InstallRoot = {_powershell_literal(install_root)}
$ExePath = {_powershell_literal(current_executable)}

try {{
    Wait-Process -Id $PidToWait -Timeout 120 -ErrorAction SilentlyContinue
}} catch {{
}}
Start-Sleep -Milliseconds 800

$Files = @(
{files}
)

foreach ($Relative in $Files) {{
    $Source = Join-Path $SourceRoot $Relative
    $Destination = Join-Path $InstallRoot $Relative
    $DestinationDir = Split-Path -Parent $Destination
    if (!(Test-Path -LiteralPath $DestinationDir)) {{
        New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null
    }}
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}}

Start-Process -FilePath $ExePath -WorkingDirectory $InstallRoot
"""
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8")
    return script_path


def _download_file(
    url: str,
    destination: Path,
    *,
    request_get=requests.get,
    timeout: int = 60,
) -> None:
    response = request_get(url, stream=True, timeout=timeout)
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)
    if destination.stat().st_size == 0:
        raise ValueError("下载到的更新包为空。")


def start_update_installation(
    update: UpdateCheckResult,
    *,
    request_get=requests.get,
    popen=subprocess.Popen,
    current_executable: Path | None = None,
    current_pid: int | None = None,
    install_root: Path | None = None,
    temp_root_factory=tempfile.mkdtemp,
) -> UpdateInstallResult:
    if not update.has_update:
        return UpdateInstallResult(False, "当前已经是最新版本，无需安装更新。")
    if not update.asset_download_url:
        return UpdateInstallResult(False, "没有找到可自动安装的更新包，请到 GitHub Release 手动下载。")
    if os.name != "nt":
        return UpdateInstallResult(False, "自动安装更新目前仅支持 Windows 发布版。")

    current_executable = Path(current_executable or sys.executable).resolve()
    if current_executable.name.casefold() != PACKAGED_EXE_NAME:
        return UpdateInstallResult(False, "当前是源码调试模式，请使用发布版 EXE 执行一键更新。")

    install_root = Path(install_root or current_executable.parent).resolve()
    current_pid = int(current_pid or os.getpid())
    temp_root = Path(temp_root_factory(prefix="astock-update-")).resolve()
    archive_path = temp_root / (update.asset_name or RELEASE_ASSET_NAME)
    extract_root = temp_root / "extracted"

    _download_file(update.asset_download_url, archive_path, request_get=request_get)
    extract_root.mkdir(parents=True, exist_ok=True)
    extract_update_archive(archive_path, extract_root)

    package_root = find_update_package_root(extract_root)
    manifest = build_update_file_manifest(package_root)
    if not any(path.name.casefold() == PACKAGED_EXE_NAME for path in manifest):
        return UpdateInstallResult(False, "更新包中没有找到主程序，已取消安装。")

    script_path = write_update_script(
        package_root=package_root,
        install_root=install_root,
        current_executable=current_executable,
        current_pid=current_pid,
        manifest=manifest,
        temp_root=temp_root,
    )
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe") or "powershell.exe"
    popen(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        cwd=str(temp_root),
        creationflags=CREATE_NO_WINDOW,
    )
    return UpdateInstallResult(
        True,
        "更新程序已启动，当前窗口将关闭。安装完成后会自动重新打开新版。",
        str(script_path),
        str(package_root),
    )


def _normalized_text(value: object) -> str:
    return str(value or "").replace("/", "\\").casefold()


def tencent_quote_code_for_stock(value: str) -> str:
    stock = settings_store.normalize_stock({"code": value})
    prefix = {"SS": "sh", "SZ": "sz", "BJ": "bj"}[stock["suffix"]]
    return f"{prefix}{stock['code']}"


def lookup_stock_name(
    value: str,
    *,
    request_get=requests.get,
    timeout: int = 6,
) -> str:
    query_code = tencent_quote_code_for_stock(value)
    try:
        response = request_get(
            "https://qt.gtimg.cn/q=" + query_code,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException:
        return ""

    content = getattr(response, "content", b"")
    raw = content.decode("gbk", "ignore") if content else str(getattr(response, "text", ""))

    for line in raw.split(";"):
        if "=" not in line:
            continue
        _var, value_text = line.split("=", 1)
        fields = value_text.strip().strip('"').split("~")
        if len(fields) >= 3 and fields[1].strip():
            return fields[1].strip()
    return ""


def _process_haystack(process: ProcessRecord) -> str:
    return _normalized_text(f"{process.name} {process.executable_path} {process.command_line}")


def _is_manager_process(process: ProcessRecord) -> bool:
    text = _process_haystack(process)
    if process.name.casefold() == PACKAGED_EXE_NAME and "--run-briefing" not in text:
        return True
    return MANAGER_SCRIPT_NAME in text or LAUNCHER_SCRIPT_NAME in text


def _is_packaged_briefing_process(process: ProcessRecord) -> bool:
    text = _process_haystack(process)
    return process.name.casefold() == PACKAGED_EXE_NAME and "--run-briefing" in text


def _is_maintenance_process(process: ProcessRecord) -> bool:
    text = _process_haystack(process)
    return any(marker in text for marker in MAINTENANCE_COMMAND_MARKERS)


def _is_supported_runtime(process: ProcessRecord) -> bool:
    return process.name.casefold() in SERVICE_PROCESS_NAMES


def find_tradingagents_processes(
    processes: Iterable[ProcessRecord],
    *,
    project_root: str | Path = PROJECT_ROOT,
    briefing_dir: str | Path = BRIEFING_DIR,
    excluded_pids: set[int] | None = None,
) -> list[ProcessRecord]:
    """Return running processes that clearly belong to this TradingAgents checkout."""
    excluded_pids = excluded_pids or set()
    project_path = Path(project_root)
    project_marker = _normalized_text(project_path)
    briefing_marker = _normalized_text(Path(briefing_dir) / BRIEFING_SCRIPT_NAME)
    matches = []

    for process in processes:
        if process.pid in excluded_pids:
            continue
        if not _is_supported_runtime(process):
            continue
        if _is_manager_process(process) or _is_maintenance_process(process):
            continue

        text = _process_haystack(process)
        if _is_packaged_briefing_process(process):
            matches.append(process)
            continue
        is_project_process = project_marker in text
        is_briefing_process = briefing_marker in text
        if is_project_process or is_briefing_process:
            matches.append(process)

    return sorted(matches, key=lambda item: item.pid)


def collect_process_tree(
    root_pids: Iterable[int],
    processes: Iterable[ProcessRecord],
    *,
    excluded_pids: set[int] | None = None,
) -> list[int]:
    """Return descendants before parents so shutdown works from leaves upward."""
    excluded_pids = excluded_pids or set()
    children_by_parent: dict[int, list[int]] = {}
    known_pids = set()
    for process in processes:
        known_pids.add(process.pid)
        children_by_parent.setdefault(process.parent_pid, []).append(process.pid)

    ordered: list[int] = []
    seen: set[int] = set()

    def visit(pid: int) -> None:
        if pid in seen or pid in excluded_pids:
            return
        seen.add(pid)
        for child_pid in sorted(children_by_parent.get(pid, [])):
            visit(child_pid)
        if pid in known_pids:
            ordered.append(pid)

    for root_pid in root_pids:
        visit(int(root_pid))

    return ordered


def query_processes() -> list[ProcessRecord]:
    if os.name != "nt":
        raise RuntimeError("This manager is designed for Windows.")

    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "$OutputEncoding=[System.Text.Encoding]::UTF8; "
        "$items = @(Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine); "
        "$items | ConvertTo-Json -Depth 3"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Could not query Windows processes.")

    raw = result.stdout.strip().lstrip("\ufeff")
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    return [ProcessRecord.from_cim(item) for item in data if item]


def current_process_family(processes: Iterable[ProcessRecord]) -> set[int]:
    by_pid = {process.pid: process for process in processes}
    protected = {os.getpid()}
    current = by_pid.get(os.getpid())
    while current and current.parent_pid and current.parent_pid not in protected:
        protected.add(current.parent_pid)
        current = by_pid.get(current.parent_pid)
    return protected


def discover_services() -> tuple[list[ProcessRecord], list[ProcessRecord]]:
    processes = query_processes()
    protected = current_process_family(processes)
    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids=protected,
    )
    return matches, processes


def stop_process_tree(root_pids: Iterable[int]) -> StopResult:
    processes = query_processes()
    protected = current_process_family(processes)
    targets = collect_process_tree(root_pids, processes, excluded_pids=protected)
    stopped: list[int] = []
    failed: dict[int, str] = {}

    for pid in targets:
        result = subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        if result.returncode == 0:
            stopped.append(pid)
        else:
            failed[pid] = (result.stderr or result.stdout or "taskkill failed").strip()

    return StopResult(stopped=stopped, failed=failed)


def get_pythonw_path() -> str:
    current = Path(sys.executable)
    candidate = current.with_name("pythonw.exe")
    if candidate.exists():
        return str(candidate)
    found = shutil.which("pythonw.exe") or shutil.which("python.exe") or shutil.which("py.exe")
    return found or sys.executable


def build_briefing_task_action(mode: str) -> BriefingTaskAction:
    if mode not in {"premarket", "midday", "close", "monitor"}:
        raise ValueError(f"Unsupported briefing mode: {mode}")
    if getattr(sys, "frozen", False):
        return BriefingTaskAction(
            execute=sys.executable,
            arguments=f"--run-briefing --mode {mode}",
            working_directory=str(WORKSPACE_ROOT),
        )
    return BriefingTaskAction(
        execute=get_pythonw_path(),
        arguments=f'"{BRIEFING_SCRIPT}" --mode {mode}',
        working_directory=str(WORKSPACE_ROOT),
    )


def build_briefing_command(mode: str, *, send: bool) -> list[str]:
    if mode not in {"premarket", "midday", "close", "monitor"}:
        raise ValueError(f"Unsupported briefing mode: {mode}")
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--run-briefing", "--mode", mode]
    else:
        command = [get_pythonw_path(), str(BRIEFING_SCRIPT), "--mode", mode]
    if not send:
        command.append("--no-send")
    return command


def _run_powershell_json(script: str) -> object:
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "$OutputEncoding=[System.Text.Encoding]::UTF8; "
        + script
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "PowerShell command failed.")
    raw = result.stdout.strip().lstrip("\ufeff")
    if not raw:
        return []
    return json.loads(raw)


def query_briefing_tasks() -> list[ScheduledTaskRecord]:
    quoted_names = ",".join("'" + name.replace("'", "''") + "'" for name in BRIEFING_TASK_NAMES)
    script = f"""
$names = @({quoted_names})
$rows = foreach ($name in $names) {{
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if ($null -eq $task) {{
    [PSCustomObject]@{{Name=$name;State='NotFound';NextRunTime='';LastRunTime='';LastResult=''}}
  }} else {{
    $info = Get-ScheduledTaskInfo -TaskName $name
    [PSCustomObject]@{{Name=$name;State=[string]$task.State;NextRunTime=[string]$info.NextRunTime;LastRunTime=[string]$info.LastRunTime;LastResult=[string]$info.LastTaskResult}}
  }}
}}
$rows | ConvertTo-Json -Depth 3
"""
    data = _run_powershell_json(script)
    if isinstance(data, dict):
        data = [data]
    return [
        ScheduledTaskRecord(
            name=str(item.get("Name", "")),
            state=str(item.get("State", "")),
            next_run_time=str(item.get("NextRunTime", "")),
            last_run_time=str(item.get("LastRunTime", "")),
            last_result=str(item.get("LastResult", "")),
        )
        for item in data
    ]


def set_briefing_tasks_enabled(enabled: bool) -> None:
    command = "Enable-ScheduledTask" if enabled else "Disable-ScheduledTask"
    quoted_names = ",".join("'" + name.replace("'", "''") + "'" for name in BRIEFING_TASK_NAMES)
    script = f"""
$names = @({quoted_names})
foreach ($name in $names) {{
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if ($null -ne $task) {{ {command} -TaskName $name | Out-Null }}
}}
"""
    _run_powershell_json(script + "\n'[]' | ConvertFrom-Json | ConvertTo-Json")


def register_briefing_tasks() -> None:
    actions = {item["mode"]: build_briefing_task_action(item["mode"]) for item in settings_store.DEFAULT_EMAIL_SCHEDULE}
    schedule = {
        item["mode"]: {
            "task_name": item["task_name"],
            "description": item["content"],
            "action": actions[item["mode"]],
        }
        for item in settings_store.DEFAULT_EMAIL_SCHEDULE
    }
    ps_schedule = json.dumps(
        {
            mode: {
                "task_name": item["task_name"],
                "description": item["description"],
                "execute": item["action"].execute,
                "arguments": item["action"].arguments,
                "working_directory": item["action"].working_directory,
            }
            for mode, item in schedule.items()
        },
        ensure_ascii=False,
    )
    script = f"""
$items = ConvertFrom-Json @'
{ps_schedule}
'@
function New-BriefingTask {{
    param(
        [string]$Name,
        [string]$Mode,
        [object[]]$Triggers,
        [string]$Description
    )
    $item = $items.$Mode
    $Action = New-ScheduledTaskAction -Execute $item.execute -Argument $item.arguments -WorkingDirectory $item.working_directory
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Trigger $Triggers -Action $Action -Settings $Settings -Description $Description -Force | Out-Null
}}

$PremarketTrigger = New-ScheduledTaskTrigger -Daily -At 09:35
New-BriefingTask -Name $items.premarket.task_name -Mode "premarket" -Triggers @($PremarketTrigger) -Description $items.premarket.description

$MiddayTrigger = New-ScheduledTaskTrigger -Daily -At 11:45
New-BriefingTask -Name $items.midday.task_name -Mode "midday" -Triggers @($MiddayTrigger) -Description $items.midday.description

$CloseTrigger = New-ScheduledTaskTrigger -Daily -At 18:00
New-BriefingTask -Name $items.close.task_name -Mode "close" -Triggers @($CloseTrigger) -Description $items.close.description

$MorningRepetition = (New-ScheduledTaskTrigger -Once -At 09:35 -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Minutes 115)).Repetition
$MorningMonitor = New-ScheduledTaskTrigger -Daily -At 09:35
$MorningMonitor.Repetition = $MorningRepetition
$AfternoonRepetition = (New-ScheduledTaskTrigger -Once -At 13:05 -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Minutes 115)).Repetition
$AfternoonMonitor = New-ScheduledTaskTrigger -Daily -At 13:05
$AfternoonMonitor.Repetition = $AfternoonRepetition
New-BriefingTask -Name $items.monitor.task_name -Mode "monitor" -Triggers @($MorningMonitor, $AfternoonMonitor) -Description $items.monitor.description

@() | ConvertTo-Json
"""
    _run_powershell_json(script)


def launch_briefing_once(mode: str, *, send: bool) -> subprocess.Popen:
    return subprocess.Popen(
        build_briefing_command(mode, send=send),
        cwd=str(WORKSPACE_ROOT),
        creationflags=CREATE_NO_WINDOW,
    )


class CloseServiceDialog:
    def __init__(self, parent: tk.Tk, message: str) -> None:
        tokens = BANANA_DARK_THEME
        self.result = "cancel"
        self.window = tk.Toplevel(parent)
        self.window.title("后台服务仍在运行")
        self.window.configure(bg=tokens["panel_bg"])
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)

        body = tk.Frame(self.window, bg=tokens["panel_bg"], padx=22, pady=18)
        body.pack(fill="both", expand=True)
        tk.Label(
            body,
            text="后台服务仍在运行",
            bg=tokens["panel_bg"],
            fg=tokens["accent"],
            font=("Segoe UI", 14, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            body,
            text=message,
            bg=tokens["panel_bg"],
            fg=tokens["text"],
            font=("Segoe UI", 10),
            justify="left",
            wraplength=440,
        ).pack(fill="x", pady=(10, 18))

        buttons = tk.Frame(body, bg=tokens["panel_bg"])
        buttons.pack(fill="x")
        ttk.Button(buttons, text="取消", command=self._cancel).pack(side="right")
        ttk.Button(
            buttons,
            text="彻底退出服务",
            style="Danger.TButton",
            command=lambda: self._choose("shutdown"),
        ).pack(side="right", padx=(0, 8))
        ttk.Button(
            buttons,
            text="任务栏运行",
            style="Primary.TButton",
            command=lambda: self._choose("minimize"),
        ).pack(side="right", padx=(0, 8))

        self._center_over_parent(parent)
        self.window.wait_window()

    def _choose(self, result: str) -> None:
        self.result = result
        self.window.destroy()

    def _cancel(self) -> None:
        self._choose("cancel")

    def _center_over_parent(self, parent: tk.Tk) -> None:
        self.window.update_idletasks()
        try:
            parent_x = parent.winfo_rootx()
            parent_y = parent.winfo_rooty()
            parent_width = parent.winfo_width()
            parent_height = parent.winfo_height()
            width = self.window.winfo_width()
            height = self.window.winfo_height()
            x = parent_x + max((parent_width - width) // 2, 0)
            y = parent_y + max((parent_height - height) // 2, 0)
            self.window.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass


class ServiceManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("980x620")
        self.root.minsize(780, 520)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_request)

        self.processes: list[ProcessRecord] = []
        self.task_records: list[ScheduledTaskRecord] = []
        self.settings = settings_store.load_settings()
        self.auto_refresh = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar(value="检测中")
        self.status_color = tk.StringVar(value=BANANA_DARK_THEME["warning"])
        self.recipient_entry = tk.StringVar()
        self.smtp_vars: dict[str, tk.StringVar] = {
            "host": tk.StringVar(),
            "port": tk.StringVar(),
            "user": tk.StringVar(),
            "auth_code": tk.StringVar(),
        }
        self.smtp_key_hint = tk.StringVar(value="未填写授权码")
        self.api_vars: dict[str, tk.StringVar] = {
            "base_url": tk.StringVar(),
            "api_key": tk.StringVar(),
            "model": tk.StringVar(),
        }
        self.api_key_hint = tk.StringVar(value="未填写 API Key")
        self.api_test_status = tk.StringVar(value="未测试")
        self.update_check_status = tk.StringVar(value=f"当前版本 {APP_VERSION}")
        self.latest_update_result: UpdateCheckResult | None = None
        self.stock_vars: dict[str, tk.StringVar] = {
            "code": tk.StringVar(),
            "name": tk.StringVar(),
            "shares": tk.StringVar(),
            "cost": tk.StringVar(),
            "risk": tk.StringVar(),
            "risk2": tk.StringVar(),
            "clear": tk.StringVar(),
            "hard_stop": tk.StringVar(),
            "reduce_low": tk.StringVar(),
            "reduce_high": tk.StringVar(),
        }
        self.stock_enabled = tk.BooleanVar(value=True)
        self._refreshing = False
        self.pages: dict[str, ttk.Frame] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        self.overview_cards: dict[str, tuple[tk.Label, tk.Label]] = {}
        self.checklist_rows: dict[str, tuple[tk.Label, tk.Button]] = {}
        self.log_messages: list[str] = []
        self.recent_log_text = tk.StringVar(value="暂无日志")

        self._build_ui()
        self.refresh_async()
        self._schedule_refresh()

    def _taskbar_title_for_status(self, status_text: str) -> str:
        if status_text.startswith("运行中"):
            return APP_RUNNING_TITLE
        return APP_TITLE

    def _theme_tokens(self) -> dict[str, str]:
        return BANANA_DARK_THEME

    def _nav_items(self) -> tuple[tuple[str, str], ...]:
        return (
            ("overview", "总览"),
            ("service", "服务状态"),
            ("recipients", "添加收件人邮箱"),
            ("stocks", "股票"),
            ("schedule", "定时"),
            ("settings", "设置"),
            ("logs", "日志"),
        )

    def _checklist_config(self) -> tuple[tuple[str, str], ...]:
        return (
            ("API 已配置并测试通过", "settings"),
            ("发件邮箱已配置", "settings"),
            ("至少有一个收件人", "recipients"),
            ("至少有一只关注股票", "stocks"),
            ("定时服务已启用", "service"),
        )

    def _stock_form_fields(self) -> tuple[tuple[str, str], ...]:
        return (
            ("code", "代码"),
            ("shares", "股数"),
            ("cost", "成本"),
            ("risk", "风险线"),
            ("clear", "清仓线"),
            ("reduce_low", "减仓下限"),
            ("reduce_high", "减仓上限"),
            ("risk2", "第二风险线"),
            ("hard_stop", "硬止损"),
        )

    def _api_action_layout(self) -> dict[str, object]:
        return {
            "row": 0,
            "column": 2,
            "columnspan": 2,
            "sticky": "e",
            "pady": (0, 8),
        }

    def _overview_card_grid_position(self, index: int) -> tuple[int, int]:
        return index // 2, index % 2

    def _has_enabled_task(self) -> bool:
        return any(record.state.casefold() in {"ready", "running"} for record in self.task_records)

    def _has_background_activity(self) -> bool:
        return bool(self.processes) or self._has_enabled_task()

    def _close_choice_message(self) -> str:
        status_parts = []
        if self.processes:
            status_parts.append(f"检测到 {len(self.processes)} 个正在运行的分析进程")
        if self._has_enabled_task():
            status_parts.append("每日邮件定时服务处于启用状态")
        current_status = "；".join(status_parts) or "后台状态正在刷新"
        return (
            f"{current_status}。\n\n"
            "选择“任务栏运行”：窗口会最小化到任务栏，分析和定时邮件继续执行。\n"
            "选择“彻底退出服务”：会停用定时任务，并停止当前运行进程。"
        )

    def _ask_close_action(self) -> str:
        dialog = CloseServiceDialog(self.root, self._close_choice_message())
        return dialog.result

    def _minimize_to_taskbar(self) -> None:
        self.root.iconify()
        self._append_log("窗口已最小化到任务栏，后台服务继续运行。")

    def _shutdown_service_and_exit(self) -> None:
        errors = []
        if self._has_enabled_task():
            try:
                set_briefing_tasks_enabled(False)
            except Exception as exc:  # noqa: BLE001 - keep the window open and show the user
                errors.append(f"停用定时服务失败：{exc}")
            else:
                self._append_log("定时服务已停用")

        pids = [process.pid for process in self.processes]
        if pids:
            try:
                result = stop_process_tree(pids)
            except Exception as exc:  # noqa: BLE001 - keep the window open and show the user
                errors.append(f"停止运行进程失败：{exc}")
            else:
                if result.stopped:
                    self._append_log(f"已停止 PID: {', '.join(str(pid) for pid in result.stopped)}")
                for pid, error in result.failed.items():
                    errors.append(f"停止 PID {pid} 失败：{error}")

        if errors:
            message = "\n".join(errors)
            self._append_log(f"彻底退出服务失败：{message}")
            messagebox.showerror(
                "退出失败",
                f"以下操作没有完成：\n\n{message}\n\n窗口将保留，请检查后再试。",
            )
            self.refresh_async(silent=True)
            return

        self._append_log("服务已停止，正在退出管理器。")
        self.root.destroy()

    def on_close_request(self) -> None:
        if not self._has_background_activity():
            self.root.destroy()
            return

        action = self._ask_close_action()
        if action == "minimize":
            self._minimize_to_taskbar()
        elif action == "shutdown":
            self._shutdown_service_and_exit()
        else:
            self._append_log("已取消退出操作。")

    def _next_run_time(self) -> str:
        for record in self.task_records:
            if record.next_run_time:
                return record.next_run_time
        return "暂无"

    def _smtp_is_configured(self) -> bool:
        smtp = settings_store.settings_to_smtp_settings(
            self.settings,
            env_host=config.SMTP_HOST,
            env_port=config.SMTP_PORT,
            env_user=config.SMTP_USER,
            env_auth_code=config.SMTP_AUTH_CODE,
        )
        return bool(smtp.get("host") and smtp.get("user") and smtp.get("auth_code"))

    def _api_is_configured(self) -> bool:
        api_settings = settings_store.settings_to_llm_api_settings(
            self.settings,
            env_base_url=config.LLM_BASE_URL,
            env_api_key=config.LLM_API_KEY,
            env_model=config.LLM_MODEL,
        )
        return bool(api_settings.get("base_url") and api_settings.get("api_key"))

    def _overview_items(self) -> list[tuple[str, str, str]]:
        recipients = self.settings.get("recipients", [])
        stocks = self.settings.get("stocks", [])
        api_settings = settings_store.settings_to_llm_api_settings(
            self.settings,
            env_base_url=config.LLM_BASE_URL,
            env_api_key=config.LLM_API_KEY,
            env_model=config.LLM_MODEL,
        )
        api_status = self.api_test_status.get() if hasattr(self, "api_test_status") else "未测试"

        if self.processes:
            service_item = ("服务状态", "正常", f"后台运行中，{len(self.processes)} 个进程")
        elif self._has_enabled_task():
            service_item = ("服务状态", "正常", "定时服务已启用")
        elif self.task_records:
            service_item = ("服务状态", "待处理", "定时服务已停用")
        else:
            service_item = ("服务状态", "待处理", "定时任务未安装")

        email_state = "正常" if self._smtp_is_configured() and recipients else "待处理"
        email_detail = (
            f"发件邮箱已配置，收件人 {len(recipients)} 个"
            if self._smtp_is_configured()
            else f"发件邮箱待配置，收件人 {len(recipients)} 个"
        )

        api_state = "正常" if self._api_is_configured() and api_status == "连接正常" else "待处理"
        api_detail = api_settings.get("model") or api_settings.get("base_url") or "API 待配置"

        return [
            service_item,
            ("下次发送", "正常" if self._next_run_time() != "暂无" else "待处理", self._next_run_time()),
            ("邮箱配置", email_state, email_detail),
            ("API 配置", api_state, api_detail),
            ("关注股票", "正常" if stocks else "待处理", f"{len(stocks)} 只股票"),
        ]

    def _build_ui(self) -> None:
        tokens = self._theme_tokens()
        self.root.configure(bg=tokens["window_bg"])
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=tokens["window_bg"])
        style.configure("Content.TFrame", background=tokens["panel_bg"])
        style.configure("Panel.TFrame", background=tokens["panel_bg"])
        style.configure(
            "TLabel",
            background=tokens["panel_bg"],
            foreground=tokens["text"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Panel.TLabel",
            background=tokens["panel_bg"],
            foreground=tokens["text"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Title.TLabel",
            background=tokens["window_bg"],
            font=("Segoe UI", 18, "bold"),
            foreground=tokens["text"],
        )
        style.configure(
            "PageTitle.TLabel",
            background=tokens["panel_bg"],
            font=("Segoe UI", 15, "bold"),
            foreground=tokens["text"],
        )
        style.configure(
            "Section.TLabel",
            background=tokens["panel_bg"],
            font=("Segoe UI", 11, "bold"),
            foreground=tokens["accent"],
        )
        style.configure(
            "Muted.TLabel",
            background=tokens["window_bg"],
            foreground=tokens["muted"],
        )
        style.configure(
            "PanelMuted.TLabel",
            background=tokens["panel_bg"],
            foreground=tokens["muted"],
        )
        style.configure(
            "TButton",
            background=tokens["card_alt_bg"],
            foreground=tokens["text"],
            bordercolor=tokens["border"],
            focusthickness=2,
            focuscolor=tokens["accent"],
            font=("Segoe UI", 10),
            padding=(10, 6),
        )
        style.map(
            "TButton",
            background=[("active", tokens["border"]), ("disabled", tokens["panel_bg"])],
            foreground=[("disabled", tokens["muted"])],
        )
        style.configure(
            "Primary.TButton",
            background=tokens["accent"],
            foreground=tokens["accent_fg"],
            font=("Segoe UI", 10, "bold"),
            padding=(10, 6),
        )
        style.map("Primary.TButton", background=[("active", tokens["accent_active"])])
        style.configure(
            "Danger.TButton",
            background=tokens["card_alt_bg"],
            foreground=tokens["danger"],
            padding=(10, 6),
        )
        style.configure(
            "TCheckbutton",
            background=tokens["panel_bg"],
            foreground=tokens["text"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "TEntry",
            fieldbackground=tokens["input_bg"],
            foreground=tokens["text"],
            insertcolor=tokens["text"],
            bordercolor=tokens["border"],
        )
        style.configure(
            "TCombobox",
            fieldbackground=tokens["input_bg"],
            foreground=tokens["text"],
            bordercolor=tokens["border"],
            arrowcolor=tokens["accent"],
        )
        style.configure(
            "Treeview",
            rowheight=28,
            font=("Segoe UI", 9),
            background=tokens["input_bg"],
            fieldbackground=tokens["input_bg"],
            foreground=tokens["text"],
            bordercolor=tokens["border"],
        )
        style.configure(
            "Treeview.Heading",
            background=tokens["card_alt_bg"],
            foreground=tokens["accent"],
            font=("Segoe UI", 9, "bold"),
            padding=(6, 6),
        )
        style.map(
            "Treeview",
            background=[("selected", tokens["accent"])],
            foreground=[("selected", tokens["accent_fg"])],
        )

        self.root.geometry("1120x720")
        self.root.minsize(920, 620)

        shell = ttk.Frame(self.root, padding=14)
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell)
        header.pack(fill="x")

        title_block = ttk.Frame(header)
        title_block.pack(side="left", fill="x", expand=True)
        ttk.Label(title_block, text="A股每日简报服务管理器", style="Title.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            title_block,
            text=f"项目路径: {WORKSPACE_ROOT}",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        status_frame = ttk.Frame(header)
        status_frame.pack(side="right", anchor="ne")
        self.status_badge = tk.Label(
            status_frame,
            textvariable=self.status_text,
            bg=self.status_color.get(),
            fg=tokens["window_bg"],
            font=("Segoe UI", 10, "bold"),
            padx=14,
            pady=7,
        )
        self.status_badge.pack(anchor="e")

        main_area = ttk.Frame(shell)
        main_area.pack(fill="both", expand=True, pady=(18, 0))
        main_area.columnconfigure(1, weight=1)
        main_area.rowconfigure(0, weight=1)

        sidebar = tk.Frame(
            main_area,
            bg=tokens["panel_bg"],
            width=154,
            highlightbackground=tokens["border"],
            highlightthickness=1,
        )
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        sidebar.grid_propagate(False)
        tk.Label(
            sidebar,
            text="控制台",
            bg=tokens["panel_bg"],
            fg=tokens["muted"],
            font=("Segoe UI", 9, "bold"),
            padx=16,
            pady=14,
            anchor="w",
        ).pack(fill="x")

        self.content_host = ttk.Frame(main_area, style="Content.TFrame")
        self.content_host.grid(row=0, column=1, sticky="nsew")
        self.content_host.columnconfigure(0, weight=1)
        self.content_host.rowconfigure(0, weight=1)

        for key, label in self._nav_items():
            self._add_nav_button(sidebar, key, label)

        overview_page = self._create_page("overview", "总览", "快速确认每日盘点服务是否可以正常工作。")
        service_page = self._create_page("service", "服务状态", "查看后台进程和 Windows 定时任务。")
        recipients_page = self._create_page("recipients", "添加收件人邮箱", "维护每日简报发送到哪些邮箱。")
        stocks_page = self._create_page("stocks", "股票", "维护关注股票、持仓数量和风险线。")
        schedule_page = self._create_page("schedule", "定时", "查看发送时间，也可以手动生成或发送简报。")
        settings_page = self._create_page("settings", "设置", "配置接口、发件邮箱，并检查/安装新版本。")
        logs_page = self._create_page("logs", "日志", "查看本次窗口打开后的操作记录。")

        self._build_overview_tab(overview_page)
        self._build_service_tab(service_page)
        self._build_recipients_tab(recipients_page)
        self._build_stocks_tab(stocks_page)
        self._build_schedule_tab(schedule_page)
        self._build_api_tab(settings_page)
        self._build_logs_tab(logs_page)

        self._sync_settings_widgets()
        self._show_page("overview")

    def _add_nav_button(self, parent: tk.Frame, key: str, label: str) -> None:
        tokens = self._theme_tokens()
        button = tk.Button(
            parent,
            text=label,
            anchor="w",
            relief="flat",
            bd=0,
            bg=tokens["panel_bg"],
            fg=tokens["muted"],
            activebackground=tokens["card_alt_bg"],
            activeforeground=tokens["text"],
            font=("Segoe UI", 10),
            padx=16,
            pady=9,
            command=lambda page_key=key: self._show_page(page_key),
        )
        button.pack(fill="x", padx=8, pady=2)
        self.nav_buttons[key] = button

    def _create_page(self, key: str, title: str, subtitle: str) -> ttk.Frame:
        page = ttk.Frame(self.content_host, padding=18, style="Content.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.pages[key] = page

        header = ttk.Frame(page, style="Content.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        ttk.Label(header, text=title, style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(header, text=subtitle, style="PanelMuted.TLabel").pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(page, style="Content.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        return body

    def _show_page(self, page_key: str) -> None:
        tokens = self._theme_tokens()
        for key, page in self.pages.items():
            if key == page_key:
                page.tkraise()
            button = self.nav_buttons.get(key)
            if button is None:
                continue
            if key == page_key:
                button.configure(
                    bg=tokens["accent"],
                    fg=tokens["accent_fg"],
                    activebackground=tokens["accent_active"],
                    activeforeground=tokens["accent_fg"],
                    font=("Segoe UI", 10, "bold"),
                )
            else:
                button.configure(
                    bg=tokens["panel_bg"],
                    fg=tokens["muted"],
                    activebackground=tokens["card_alt_bg"],
                    activeforeground=tokens["text"],
                    font=("Segoe UI", 10),
                )

    def _status_color_for_state(self, state: str) -> str:
        tokens = self._theme_tokens()
        return {
            "正常": tokens["success"],
            "待处理": tokens["warning"],
            "失败": tokens["danger"],
        }.get(state, tokens["muted"])

    def _build_card(self, parent: ttk.Frame, row: int, column: int) -> tk.Frame:
        tokens = self._theme_tokens()
        card = tk.Frame(
            parent,
            bg=tokens["card_bg"],
            highlightbackground=tokens["border"],
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        return card

    def _build_overview_tab(self, parent: ttk.Frame) -> None:
        tokens = self._theme_tokens()
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        canvas = tk.Canvas(
            parent,
            bg=tokens["panel_bg"],
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_body = tk.Frame(canvas, bg=tokens["panel_bg"])
        scroll_window = canvas.create_window((0, 0), window=scroll_body, anchor="nw")

        def sync_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def sync_body_width(event) -> None:
            canvas.itemconfigure(scroll_window, width=event.width)

        scroll_body.bind("<Configure>", sync_scroll_region)
        canvas.bind("<Configure>", sync_body_width)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        cards = tk.Frame(scroll_body, bg=tokens["panel_bg"])
        cards.grid(row=0, column=0, sticky="ew")
        scroll_body.columnconfigure(0, weight=1)
        for column in range(2):
            cards.columnconfigure(column, weight=1)

        for index, name in enumerate(("服务状态", "下次发送", "邮箱配置", "API 配置", "关注股票")):
            row, column = self._overview_card_grid_position(index)
            card = self._build_card(cards, row, column)
            card_bg = card.cget("bg")
            tk.Label(
                card,
                text=name,
                bg=card_bg,
                fg=tokens["muted"],
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            ).pack(fill="x")
            state_label = tk.Label(
                card,
                text="检测中",
                bg=card_bg,
                fg=tokens["warning"],
                font=("Segoe UI", 14, "bold"),
                anchor="w",
            )
            state_label.pack(fill="x", pady=(6, 2))
            detail_label = tk.Label(
                card,
                text="-",
                bg=card_bg,
                fg=tokens["text"],
                font=("Segoe UI", 9),
                anchor="w",
                wraplength=360,
                justify="left",
            )
            detail_label.pack(fill="x")
            self.overview_cards[name] = (state_label, detail_label)

        checklist = self._build_card(scroll_body, 1, 0)
        checklist.grid_configure(pady=(10, 6), sticky="ew")
        checklist_bg = checklist.cget("bg")
        tk.Label(
            checklist,
            text="启动检查清单",
            bg=checklist_bg,
            fg=tokens["accent"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).pack(fill="x")
        for label, page_key in self._checklist_config():
            row = tk.Frame(checklist, bg=checklist_bg)
            row.pack(fill="x", pady=(8, 0))
            state = tk.Label(
                row,
                text="待处理",
                bg=checklist_bg,
                fg=tokens["warning"],
                font=("Segoe UI", 10, "bold"),
                width=8,
                anchor="w",
            )
            state.pack(side="left")
            tk.Label(row, text=label, bg=checklist_bg, fg=tokens["text"], font=("Segoe UI", 10)).pack(
                side="left", fill="x", expand=True
            )
            button = tk.Button(
                row,
                text="去设置",
                relief="flat",
                bg=tokens["card_alt_bg"],
                fg=tokens["accent"],
                activebackground=tokens["border"],
                activeforeground=tokens["accent_active"],
                font=("Segoe UI", 9),
                padx=10,
                pady=4,
                command=lambda target=page_key: self._show_page(target),
            )
            button.pack(side="right")
            self.checklist_rows[label] = (state, button)

        recent = self._build_card(scroll_body, 2, 0)
        recent.grid_configure(sticky="ew", pady=(10, 0))
        recent_bg = recent.cget("bg")
        tk.Label(
            recent,
            text="最近日志",
            bg=recent_bg,
            fg=tokens["accent"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            recent,
            textvariable=self.recent_log_text,
            bg=recent_bg,
            fg=tokens["text"],
            font=("Consolas", 9),
            anchor="nw",
            justify="left",
        ).pack(fill="both", expand=True, pady=(8, 0))

    def _build_service_tab(self, parent: ttk.Frame) -> None:
        controls = ttk.Frame(parent, style="Content.TFrame")
        controls.pack(fill="x", pady=(0, 10))
        ttk.Button(controls, text="刷新状态", command=self.refresh_async).pack(side="left")
        ttk.Button(controls, text="安装/修复定时任务", command=self.register_tasks).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(controls, text="启用定时服务", command=self.enable_tasks).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(controls, text="停用定时服务", command=self.disable_tasks).pack(
            side="left", padx=(8, 0)
        )
        self.stop_selected_button = ttk.Button(
            controls,
            text="停止选中",
            command=self.stop_selected,
            state="disabled",
        )
        self.stop_selected_button.pack(side="left", padx=(8, 0))
        self.stop_all_button = ttk.Button(
            controls,
            text="停止全部运行进程",
            command=self.stop_all,
            state="disabled",
        )
        self.stop_all_button.pack(side="left", padx=(8, 0))
        ttk.Checkbutton(
            controls,
            text="自动刷新",
            variable=self.auto_refresh,
        ).pack(side="right")

        ttk.Label(parent, text="每日简报定时任务", style="Section.TLabel").pack(anchor="w")
        task_frame = ttk.Frame(parent, style="Content.TFrame")
        task_frame.pack(fill="x", pady=(6, 14))
        self.task_tree = ttk.Treeview(
            task_frame,
            columns=("name", "state", "next", "last", "result"),
            show="headings",
            height=5,
        )
        for key, label, width in (
            ("name", "任务", 160),
            ("state", "状态", 90),
            ("next", "下次运行", 190),
            ("last", "上次运行", 190),
            ("result", "结果", 80),
        ):
            self.task_tree.heading(key, text=label)
            self.task_tree.column(key, width=width, stretch=key in {"next", "last"})
        self.task_tree.grid(row=0, column=0, sticky="ew")
        task_frame.columnconfigure(0, weight=1)

        ttk.Label(parent, text="当前运行进程", style="Section.TLabel").pack(anchor="w")
        table_frame = ttk.Frame(parent, style="Content.TFrame")
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            table_frame,
            columns=("pid", "name", "command"),
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("pid", text="PID")
        self.tree.heading("name", text="进程")
        self.tree.heading("command", text="启动命令")
        self.tree.column("pid", width=90, minwidth=70, stretch=False, anchor="center")
        self.tree.column("name", width=140, minwidth=110, stretch=False)
        self.tree.column("command", width=680, minwidth=360, stretch=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._sync_buttons())

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

    def _build_recipients_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        top = ttk.Frame(parent, style="Content.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="收件人邮箱", style="Section.TLabel").pack(anchor="w")
        ttk.Label(top, text="可添加多个收件人，发送时会发给这里列出的邮箱。", style="Muted.TLabel").pack(
            anchor="w",
            pady=(4, 10),
        )
        self.recipient_count_text = tk.StringVar(value="当前 0 个收件人")
        ttk.Label(top, textvariable=self.recipient_count_text, style="Muted.TLabel").pack(
            anchor="w",
            pady=(0, 8),
        )

        input_row = ttk.Frame(parent, style="Content.TFrame")
        input_row.pack(fill="x")
        ttk.Entry(input_row, textvariable=self.recipient_entry).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(input_row, text="添加收件人邮箱", command=self.add_recipient).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(input_row, text="删除选中", command=self.remove_selected_recipients).pack(
            side="left", padx=(8, 0)
        )

        list_frame = ttk.Frame(parent, style="Content.TFrame")
        list_frame.pack(fill="both", expand=True, pady=(12, 0))
        self.recipient_list = tk.Listbox(
            list_frame,
            height=12,
            bg=self._theme_tokens()["input_bg"],
            fg=self._theme_tokens()["text"],
            selectbackground=self._theme_tokens()["accent"],
            selectforeground=self._theme_tokens()["accent_fg"],
            selectmode="extended",
            relief="solid",
            borderwidth=1,
            highlightbackground=self._theme_tokens()["border"],
            font=("Segoe UI", 10),
        )
        recipient_scroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.recipient_list.yview
        )
        self.recipient_list.configure(yscrollcommand=recipient_scroll.set)
        self.recipient_list.grid(row=0, column=0, sticky="nsew")
        recipient_scroll.grid(row=0, column=1, sticky="ns")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

    def _build_stocks_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        ttk.Label(parent, text="关注股票 / 持仓", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        tree_frame = ttk.Frame(parent, style="Content.TFrame")
        tree_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 12))
        self.stock_tree = ttk.Treeview(
            tree_frame,
            columns=(
                "enabled",
                "code",
                "name",
                "shares",
                "cost",
                "risk",
                "risk2",
                "clear",
                "hard_stop",
                "reduce",
            ),
            show="headings",
            selectmode="browse",
            height=8,
        )
        for key, label, width in (
            ("enabled", "启用", 60),
            ("code", "代码", 110),
            ("name", "名称", 120),
            ("shares", "股数", 80),
            ("cost", "成本", 80),
            ("risk", "风险线", 80),
            ("risk2", "第二风险线", 90),
            ("clear", "清仓线", 80),
            ("hard_stop", "硬止损", 80),
            ("reduce", "减仓区", 120),
        ):
            self.stock_tree.heading(key, text=label)
            self.stock_tree.column(
                key,
                width=width,
                stretch=key == "name",
                anchor="center" if key != "name" else "w",
            )
        self.stock_tree.bind("<Double-1>", self.edit_selected_stock)
        stock_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.stock_tree.yview)
        self.stock_tree.configure(yscrollcommand=stock_scroll.set)
        self.stock_tree.grid(row=0, column=0, sticky="nsew")
        stock_scroll.grid(row=0, column=1, sticky="ns")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.stock_empty_text = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.stock_empty_text, style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 8)
        )

        form = ttk.Frame(parent, style="Content.TFrame")
        form.grid(row=3, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        fields = self._stock_form_fields()
        for index, (key, label) in enumerate(fields):
            row = index // 2
            column = (index % 2) * 2
            ttk.Label(form, text=label).grid(row=row, column=column, sticky="w", padx=(0, 6), pady=4)
            ttk.Entry(form, textvariable=self.stock_vars[key]).grid(
                row=row, column=column + 1, sticky="ew", padx=(0, 16), pady=4
            )
        ttk.Label(
            form,
            text="输入股票代码后保存，名称会自动检索；双击上方股票可载入持仓修改。",
            style="Muted.TLabel",
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Checkbutton(form, text="启用监控", variable=self.stock_enabled).grid(
            row=6, column=0, sticky="w", pady=(6, 0)
        )

        actions = ttk.Frame(parent, style="Content.TFrame")
        actions.grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Button(actions, text="保存股票", style="Primary.TButton", command=self.add_or_update_stock).pack(
            side="left"
        )
        ttk.Button(actions, text="清空输入", command=self.clear_stock_form).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(actions, text="删除选中股票", style="Danger.TButton", command=self.remove_selected_stock).pack(
            side="left", padx=(8, 0)
        )

    def _build_schedule_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        ttk.Label(parent, text="几点发，发什么", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.schedule_tree = ttk.Treeview(
            parent,
            columns=("time", "title", "content"),
            show="headings",
            height=5,
        )
        self.schedule_tree.heading("time", text="时间")
        self.schedule_tree.heading("title", text="邮件")
        self.schedule_tree.heading("content", text="内容")
        self.schedule_tree.column("time", width=190, stretch=False)
        self.schedule_tree.column("title", width=120, stretch=False)
        self.schedule_tree.column("content", width=760, stretch=True)
        self.schedule_tree.grid(row=1, column=0, sticky="ew", pady=(8, 16))

        ttk.Label(parent, text="手动运行", style="Section.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        preview = ttk.Frame(parent, style="Content.TFrame")
        preview.grid(row=3, column=0, sticky="w", pady=(8, 8))
        for mode, label in (
            ("premarket", "生成盘前预览"),
            ("midday", "生成午间预览"),
            ("close", "生成收盘预览"),
            ("monitor", "运行监控预览"),
        ):
            ttk.Button(
                preview,
                text=label,
                command=lambda selected_mode=mode: self.run_briefing_now(selected_mode, send=False),
            ).pack(side="left", padx=(0, 8))

        send_row = ttk.Frame(parent, style="Content.TFrame")
        send_row.grid(row=4, column=0, sticky="w")
        for mode, label in (
            ("premarket", "发送盘前"),
            ("midday", "发送午间"),
            ("close", "发送收盘"),
        ):
            ttk.Button(
                send_row,
                text=label,
                command=lambda selected_mode=mode: self.run_briefing_now(selected_mode, send=True),
            ).pack(side="left", padx=(0, 8))
        ttk.Button(send_row, text="打开报告文件夹", command=self.open_report_dir).pack(
            side="left", padx=(8, 0)
        )

    def _build_api_tab(self, parent: ttk.Frame) -> None:
        tokens = self._theme_tokens()
        parent.columnconfigure(0, weight=1)

        api_panel = tk.Frame(
            parent,
            bg=tokens["card_bg"],
            highlightbackground=tokens["border"],
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        api_panel.grid(row=0, column=0, sticky="ew")
        api_panel.columnconfigure(1, weight=1)
        api_panel.columnconfigure(3, weight=1)

        header_info = tk.Frame(api_panel, bg=tokens["card_bg"])
        header_info.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        tk.Label(
            header_info,
            text="OpenAI 兼容 API",
            bg=tokens["card_bg"],
            fg=tokens["accent"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            header_info,
            textvariable=self.api_key_hint,
            bg=tokens["card_bg"],
            fg=tokens["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(api_panel, bg=tokens["card_bg"])
        actions.grid(**self._api_action_layout())
        ttk.Button(
            actions,
            text="保存 API 设置",
            style="Primary.TButton",
            command=self.save_api_settings,
        ).pack(side="left")
        self.api_test_button = ttk.Button(actions, text="测试连接", command=self.test_api_connection)
        self.api_test_button.pack(side="left", padx=(8, 0))
        tk.Label(
            actions,
            textvariable=self.api_test_status,
            bg=tokens["card_bg"],
            fg=tokens["info"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(side="left", padx=(10, 0))

        for row, key, label, show in (
            (1, "base_url", "Base URL", ""),
            (2, "api_key", "API Key", "*"),
            (3, "model", "Model", ""),
        ):
            tk.Label(
                api_panel,
                text=label,
                bg=tokens["card_bg"],
                fg=tokens["muted"],
                font=("Segoe UI", 10),
                width=10,
                anchor="w",
            ).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            if key == "model":
                self.model_combo = ttk.Combobox(
                    api_panel,
                    textvariable=self.api_vars["model"],
                    values=(),
                    state="normal",
                )
                self.model_combo.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
            else:
                ttk.Entry(api_panel, textvariable=self.api_vars[key], show=show).grid(
                    row=row,
                    column=1,
                    columnspan=3,
                    sticky="ew",
                    pady=4,
                )

        self._build_smtp_settings_panel(parent, 1)

        update_panel = tk.Frame(
            parent,
            bg=tokens["card_bg"],
            highlightbackground=tokens["border"],
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        update_panel.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        update_panel.columnconfigure(0, weight=1)

        tk.Label(
            update_panel,
            text="软件更新",
            bg=tokens["card_bg"],
            fg=tokens["accent"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            update_panel,
            text=f"当前版本 {APP_VERSION} · {GITHUB_REPO_URL}",
            bg=tokens["card_bg"],
            fg=tokens["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        update_actions = tk.Frame(update_panel, bg=tokens["card_bg"])
        update_actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.update_check_button = ttk.Button(
            update_actions,
            text="检测更新",
            command=self.check_for_updates,
        )
        self.update_check_button.pack(side="left")
        self.install_update_button = ttk.Button(
            update_actions,
            text="下载并安装",
            style="Primary.TButton",
            command=self.install_update,
        )
        self.install_update_button.pack(side="left", padx=(8, 0))
        self.install_update_button.configure(state="disabled")
        tk.Label(
            update_actions,
            textvariable=self.update_check_status,
            bg=tokens["card_bg"],
            fg=tokens["text"],
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(side="left", padx=(10, 0), fill="x", expand=True)

    def _build_smtp_settings_panel(self, parent: ttk.Frame, row: int) -> None:
        tokens = self._theme_tokens()
        smtp_panel = tk.Frame(
            parent,
            bg=tokens["card_bg"],
            highlightbackground=tokens["border"],
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        smtp_panel.grid(row=row, column=0, sticky="ew", pady=(12, 0))
        smtp_panel.columnconfigure(1, weight=1)
        smtp_panel.columnconfigure(3, weight=1)

        tk.Label(
            smtp_panel,
            text="发件邮箱 SMTP",
            bg=tokens["card_bg"],
            fg=tokens["accent"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=4, sticky="ew")
        tk.Label(
            smtp_panel,
            text="用于每日盘点邮件的发件账号；收件人请到“添加收件人邮箱”。",
            bg=tokens["card_bg"],
            fg=tokens["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 8))

        for index, (key, label) in enumerate(
            (
                ("host", "SMTP 服务器"),
                ("port", "端口"),
                ("user", "发件邮箱"),
                ("auth_code", "授权码"),
            )
        ):
            field_row = 2 + index // 2
            column = (index % 2) * 2
            tk.Label(
                smtp_panel,
                text=label,
                bg=tokens["card_bg"],
                fg=tokens["muted"],
                font=("Segoe UI", 10),
                width=12,
                anchor="w",
            ).grid(row=field_row, column=column, sticky="w", padx=(0, 8), pady=4)
            show = "*" if key == "auth_code" else ""
            ttk.Entry(smtp_panel, textvariable=self.smtp_vars[key], show=show).grid(
                row=field_row,
                column=column + 1,
                sticky="ew",
                padx=(0, 16),
                pady=4,
            )

        tk.Label(
            smtp_panel,
            textvariable=self.smtp_key_hint,
            bg=tokens["card_bg"],
            fg=tokens["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=4, column=1, sticky="w", pady=(8, 0))
        ttk.Button(
            smtp_panel,
            text="保存发件邮箱设置",
            style="Primary.TButton",
            command=self.save_smtp_settings,
        ).grid(row=4, column=3, sticky="w", pady=(8, 0))

    def _build_logs_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        actions = ttk.Frame(parent, style="Content.TFrame")
        actions.grid(row=0, column=0, sticky="w", pady=(0, 10))
        ttk.Button(actions, text="复制日志", command=self.copy_logs).pack(side="left")
        ttk.Button(actions, text="清空显示", command=self.clear_logs).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="打开报告文件夹", command=self.open_report_dir).pack(
            side="left", padx=(8, 0)
        )
        self.log = tk.Text(
            parent,
            height=18,
            wrap="word",
            bg=self._theme_tokens()["input_bg"],
            fg=self._theme_tokens()["text"],
            insertbackground=self._theme_tokens()["text"],
            selectbackground=self._theme_tokens()["accent"],
            selectforeground=self._theme_tokens()["accent_fg"],
            relief="solid",
            borderwidth=1,
            highlightbackground=self._theme_tokens()["border"],
            font=("Consolas", 9),
        )
        self.log.grid(row=1, column=0, sticky="nsew")
        self.log.configure(state="disabled")

    def _sync_settings_widgets(self) -> None:
        self._sync_recipient_list()
        self._sync_stock_tree()
        self._sync_schedule_table()
        self._sync_api_widgets()
        self._sync_smtp_widgets()
        self._sync_overview()

    def _sync_recipient_list(self) -> None:
        self.recipient_list.delete(0, "end")
        for email in self.settings.get("recipients", []):
            self.recipient_list.insert("end", email)
        if hasattr(self, "recipient_count_text"):
            count = self.recipient_list.size()
            self.recipient_count_text.set(f"当前 {count} 个收件人")

    def _sync_stock_tree(self) -> None:
        for item in self.stock_tree.get_children():
            self.stock_tree.delete(item)
        stocks = self.settings.get("stocks", [])
        for stock in stocks:
            reduce_zone = ""
            if stock.get("reduce_low") is not None and stock.get("reduce_high") is not None:
                reduce_zone = f"{stock['reduce_low']} - {stock['reduce_high']}"
            self.stock_tree.insert(
                "",
                "end",
                iid=stock["full_code"],
                values=(
                    "是" if stock.get("enabled", True) else "否",
                    stock["full_code"],
                    stock.get("name", ""),
                    stock.get("shares", ""),
                    stock.get("cost", ""),
                    stock.get("risk") or "",
                    stock.get("risk2") or "",
                    stock.get("clear") or "",
                    stock.get("hard_stop") or "",
                    reduce_zone,
                ),
            )
        if hasattr(self, "stock_empty_text"):
            self.stock_empty_text.set(
                "" if stocks else "还没有关注股票，先添加一只股票用于每日盘点。"
            )

    def _sync_schedule_table(self) -> None:
        for item in self.schedule_tree.get_children():
            self.schedule_tree.delete(item)
        for item in self.settings.get("schedule", settings_store.DEFAULT_EMAIL_SCHEDULE):
            self.schedule_tree.insert(
                "",
                "end",
                values=(item.get("time", ""), item.get("title", ""), item.get("content", "")),
            )

    def _checklist_items(self) -> list[tuple[str, str]]:
        recipients = self.settings.get("recipients", [])
        stocks = self.settings.get("stocks", [])
        return [
            (
                "API 已配置并测试通过",
                "已完成"
                if self._api_is_configured() and self.api_test_status.get() == "连接正常"
                else "待处理",
            ),
            ("发件邮箱已配置", "已完成" if self._smtp_is_configured() else "待处理"),
            ("至少有一个收件人", "已完成" if recipients else "待处理"),
            ("至少有一只关注股票", "已完成" if stocks else "待处理"),
            ("定时服务已启用", "已完成" if self._has_enabled_task() else "待处理"),
        ]

    def _sync_overview(self) -> None:
        if not hasattr(self, "overview_cards"):
            return
        tokens = self._theme_tokens()
        for name, state, detail in self._overview_items():
            labels = self.overview_cards.get(name)
            if labels is None:
                continue
            state_label, detail_label = labels
            state_label.configure(text=state, fg=self._status_color_for_state(state))
            detail_label.configure(text=detail)

        for label, state in self._checklist_items():
            row = self.checklist_rows.get(label)
            if row is None:
                continue
            state_label, button = row
            color = tokens["success"] if state == "已完成" else tokens["warning"]
            state_label.configure(text=state, fg=color)
            button.configure(state="disabled" if state == "已完成" else "normal")

    def _sync_api_widgets(self) -> None:
        api_settings = settings_store.settings_to_llm_api_settings(
            self.settings,
            env_base_url=config.LLM_BASE_URL,
            env_api_key=config.LLM_API_KEY,
            env_model=config.LLM_MODEL,
        )
        for key, var in self.api_vars.items():
            var.set(api_settings.get(key, ""))
        redacted = settings_store.redact_secret(api_settings.get("api_key", ""))
        self.api_key_hint.set(f"当前 Key：{redacted}" if redacted else "未填写 API Key")
        self.api_test_status.set("未测试")

    def _sync_smtp_widgets(self) -> None:
        smtp_settings = settings_store.settings_to_smtp_settings(
            self.settings,
            env_host=config.SMTP_HOST,
            env_port=config.SMTP_PORT,
            env_user=config.SMTP_USER,
            env_auth_code=config.SMTP_AUTH_CODE,
        )
        for key, var in self.smtp_vars.items():
            var.set(str(smtp_settings.get(key, "")))
        redacted = settings_store.redact_secret(smtp_settings.get("auth_code", ""))
        self.smtp_key_hint.set(f"当前授权码：{redacted}" if redacted else "未填写授权码")

    def _settings_from_recipient_list(self) -> dict:
        self.settings["recipients"] = [
            self.recipient_list.get(index) for index in range(self.recipient_list.size())
        ]
        return self.settings

    def _smtp_settings_from_form(self) -> dict[str, str | int]:
        return settings_store.normalize_smtp_settings(
            {key: var.get() for key, var in self.smtp_vars.items()}
        )

    def _api_settings_from_form(self) -> dict[str, str]:
        return settings_store.normalize_llm_api_settings(
            {key: var.get() for key, var in self.api_vars.items()}
        )

    def save_current_settings(self, *, silent: bool = False) -> None:
        self.settings = settings_store.save_settings(self.settings)
        self._sync_settings_widgets()
        if not silent:
            self._append_log(f"设置已保存：{settings_store.SETTINGS_FILE}")

    def save_api_settings(self) -> None:
        api_settings = self._api_settings_from_form()
        previous_api_settings = settings_store.settings_to_llm_api_settings(
            self.settings,
            env_base_url=config.LLM_BASE_URL,
            env_api_key=config.LLM_API_KEY,
            env_model=config.LLM_MODEL,
        )
        keep_success_status = (
            self.api_test_status.get() == "连接正常"
            and api_settings == previous_api_settings
        )
        self.settings["llm_api"] = api_settings
        self.save_current_settings(silent=True)
        if keep_success_status:
            self.api_test_status.set("连接正常")
        redacted = settings_store.redact_secret(api_settings.get("api_key", ""))
        self.api_key_hint.set(f"当前 Key：{redacted}" if redacted else "未填写 API Key")
        self._sync_overview()
        self._append_log(
            f"API 设置已保存：Base URL={api_settings.get('base_url') or '-'}，"
            f"Model={api_settings.get('model') or '-'}。"
        )

    def save_smtp_settings(self) -> None:
        smtp_settings = self._smtp_settings_from_form()
        self.settings["smtp"] = smtp_settings
        self.save_current_settings(silent=True)
        redacted = settings_store.redact_secret(smtp_settings.get("auth_code", ""))
        self.smtp_key_hint.set(f"当前授权码：{redacted}" if redacted else "未填写授权码")
        self._sync_overview()
        self._append_log(
            f"发件邮箱设置已保存：Host={smtp_settings.get('host') or '-'}，"
            f"User={smtp_settings.get('user') or '-'}。"
        )

    def add_recipient(self) -> None:
        new_recipients = settings_store.parse_recipients(self.recipient_entry.get())
        if not new_recipients:
            messagebox.showwarning("邮箱格式不正确", "请输入类似 name@qq.com 的邮箱地址。")
            return
        existing = {
            self.recipient_list.get(index).casefold()
            for index in range(self.recipient_list.size())
        }
        for email in new_recipients:
            if email.casefold() not in existing:
                self.recipient_list.insert("end", email)
                existing.add(email.casefold())
        self.recipient_entry.set("")
        self._settings_from_recipient_list()
        self.save_current_settings()

    def remove_selected_recipients(self) -> None:
        selected = list(self.recipient_list.curselection())
        if not selected:
            return
        if len(selected) > 1 and not messagebox.askyesno(
            "确认删除",
            f"将删除 {len(selected)} 个收件邮箱，确定继续吗？",
        ):
            return
        for index in reversed(selected):
            self.recipient_list.delete(index)
        self._settings_from_recipient_list()
        self.save_current_settings()

    def _stock_from_form(self) -> dict:
        raw = {key: var.get().strip() for key, var in self.stock_vars.items()}
        raw["enabled"] = self.stock_enabled.get()
        raw["name"] = ""
        stock = settings_store.normalize_stock(raw)
        resolved_name = lookup_stock_name(stock["full_code"])
        if not resolved_name:
            for existing in self.settings.get("stocks", []):
                if existing.get("full_code") == stock["full_code"]:
                    resolved_name = str(existing.get("name") or "").strip()
                    break
        if resolved_name:
            stock["name"] = resolved_name
        return stock

    def clear_stock_form(self) -> None:
        for var in self.stock_vars.values():
            var.set("")
        self.stock_enabled.set(True)
        for item in self.stock_tree.selection():
            self.stock_tree.selection_remove(item)

    def edit_selected_stock(self, _event=None) -> None:
        selected = self.stock_tree.selection()
        if not selected:
            return
        full_code = selected[0]
        for stock in self.settings.get("stocks", []):
            if stock.get("full_code") != full_code:
                continue
            for key, var in self.stock_vars.items():
                value = stock.get(key)
                var.set("" if value is None else str(value))
            self.stock_vars["code"].set(stock.get("full_code", stock.get("code", "")))
            self.stock_enabled.set(bool(stock.get("enabled", True)))
            break

    def on_stock_selected(self, _event=None) -> None:
        self.edit_selected_stock(_event)

    def add_or_update_stock(self) -> None:
        try:
            stock = self._stock_from_form()
        except ValueError as exc:
            messagebox.showwarning("股票代码不正确", str(exc))
            return

        stocks = [
            item
            for item in self.settings.get("stocks", [])
            if item.get("full_code") != stock["full_code"]
        ]
        stocks.append(stock)
        self.settings["stocks"] = stocks
        self.save_current_settings()
        self.stock_tree.selection_set(stock["full_code"])
        self._append_log(f"已更新关注股票：{stock['full_code']} {stock.get('name', '')}")

    def remove_selected_stock(self) -> None:
        selected = self.stock_tree.selection()
        if not selected:
            return
        full_code = selected[0]
        if not messagebox.askyesno("确认删除", f"从关注列表删除 {full_code}？"):
            return
        self.settings["stocks"] = [
            item for item in self.settings.get("stocks", []) if item.get("full_code") != full_code
        ]
        self.save_current_settings()
        self.clear_stock_form()

    def _run_background(self, label: str, func, success_message, *, refresh_after: bool = True) -> None:
        self._append_log(f"开始：{label}")

        def worker() -> None:
            try:
                result = func()
            except Exception as exc:  # noqa: BLE001 - surface OS failures in the GUI
                error_message = str(exc)
                self.root.after(0, lambda: self._after_background_error(label, error_message))
                return
            self.root.after(
                0,
                lambda: self._after_background_success(
                    label,
                    result,
                    success_message,
                    refresh_after=refresh_after,
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _after_background_success(
        self,
        label: str,
        result,
        success_message,
        *,
        refresh_after: bool = True,
    ) -> None:
        message = success_message(result) if callable(success_message) else str(success_message)
        self._append_log(message or f"{label} 完成。")
        if refresh_after:
            self.refresh_async(silent=True)

    def _after_background_error(self, label: str, error_message: str) -> None:
        if label == "测试 API 连接":
            self.api_test_status.set("连接失败")
            if hasattr(self, "api_test_button"):
                self.api_test_button.configure(state="normal")
            self._sync_overview()
        if label == "检测更新":
            self.update_check_status.set("检测更新失败")
            if hasattr(self, "update_check_button"):
                self.update_check_button.configure(state="normal")
            if hasattr(self, "install_update_button"):
                self.install_update_button.configure(state="disabled")
        if label == "安装更新":
            self.update_check_status.set("安装更新失败")
            if hasattr(self, "update_check_button"):
                self.update_check_button.configure(state="normal")
            if hasattr(self, "install_update_button"):
                self.install_update_button.configure(state="normal")
        self._append_log(f"{label} 失败：{error_message}")

    def test_api_connection(self) -> None:
        api_settings = self._api_settings_from_form()
        self.api_test_status.set("测试中...")
        if hasattr(self, "api_test_button"):
            self.api_test_button.configure(state="disabled")
        self._sync_overview()
        self._run_background(
            "测试 API 连接",
            lambda: llm_api.test_openai_compatible_connection(api_settings),
            self._format_api_test_result,
            refresh_after=False,
        )

    def _format_api_test_result(self, result: llm_api.ConnectionTestResult) -> str:
        self.api_test_status.set("连接正常" if result.ok else "连接失败")
        if result.ok and result.models:
            self.model_combo["values"] = result.models
        if hasattr(self, "api_test_button"):
            self.api_test_button.configure(state="normal")
        self._sync_overview()
        return result.message

    def check_for_updates(self) -> None:
        self.update_check_status.set("检测中...")
        if hasattr(self, "update_check_button"):
            self.update_check_button.configure(state="disabled")
        self._run_background(
            "检测更新",
            check_latest_release,
            self._format_update_check_result,
            refresh_after=False,
        )

    def _format_update_check_result(self, result: UpdateCheckResult) -> str:
        self.latest_update_result = result
        self.update_check_status.set(result.message)
        if hasattr(self, "update_check_button"):
            self.update_check_button.configure(state="normal")
        install_state = "normal" if result.ok and result.has_update and result.asset_download_url else "disabled"
        if hasattr(self, "install_update_button"):
            self.install_update_button.configure(state=install_state)
        return result.message

    def install_update(self) -> None:
        update = getattr(self, "latest_update_result", None)
        if update is None:
            messagebox.showinfo("请先检测更新", "请先点击“检测更新”，确认有新版本后再安装。")
            return
        if not update.has_update:
            messagebox.showinfo("无需更新", "当前已经是最新版本。")
            return
        if not update.asset_download_url:
            messagebox.showwarning("无法自动安装", "最新版本没有可自动安装的 zip 包，请到 GitHub Release 手动下载。")
            return
        if os.name != "nt" or Path(sys.executable).name.casefold() != PACKAGED_EXE_NAME:
            messagebox.showwarning("当前不能自动安装", "一键自动安装只支持从发布版 EXE 中运行。")
            return
        if not messagebox.askyesno(
            "安装更新",
            f"将下载并安装 {update.latest_version}。\n\n"
            "程序会自动关闭，安装完成后重新打开；你的邮箱、API Key、股票和持仓设置会保留。",
        ):
            return

        self.update_check_status.set(f"正在下载 {update.latest_version}...")
        if hasattr(self, "update_check_button"):
            self.update_check_button.configure(state="disabled")
        if hasattr(self, "install_update_button"):
            self.install_update_button.configure(state="disabled")
        self._run_background(
            "安装更新",
            lambda: start_update_installation(update),
            self._format_update_install_result,
            refresh_after=False,
        )

    def _format_update_install_result(self, result: UpdateInstallResult) -> str:
        self.update_check_status.set(result.message)
        if hasattr(self, "update_check_button"):
            self.update_check_button.configure(state="normal")
        if hasattr(self, "install_update_button"):
            self.install_update_button.configure(state="disabled" if result.ok else "normal")
        if result.ok:
            self.root.after(800, self.root.destroy)
        else:
            messagebox.showwarning("安装更新", result.message)
        return result.message

    def register_tasks(self) -> None:
        self._run_background(
            "安装/修复定时任务",
            register_briefing_tasks,
            "定时任务已安装/修复。",
        )

    def enable_tasks(self) -> None:
        self._run_background(
            "启用定时服务",
            lambda: set_briefing_tasks_enabled(True),
            "定时服务已启用。",
        )

    def disable_tasks(self) -> None:
        if not messagebox.askyesno("确认停用", "停用后不会自动发送每日简报，确定继续吗？"):
            return
        self._run_background(
            "停用定时服务",
            lambda: set_briefing_tasks_enabled(False),
            "定时服务已停用。",
        )

    def run_briefing_now(self, mode: str, *, send: bool) -> None:
        labels = {
            "premarket": "盘前简报",
            "midday": "午间简报",
            "close": "收盘总结",
            "monitor": "盘中监控",
        }
        label = labels.get(mode, mode)
        if send and not messagebox.askyesno("确认发送", f"现在生成并发送一次{label}？"):
            return
        action = f"{label}{'发送' if send else '预览'}"
        self._run_background(
            action,
            lambda: launch_briefing_once(mode, send=send),
            lambda process: f"已启动{action}，PID {process.pid}。",
        )

    def open_report_dir(self) -> None:
        report_dir = BRIEFING_DIR / "data" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(report_dir)  # noqa: S606 - user-triggered Explorer action
        else:
            self._append_log(f"报告文件夹：{report_dir}")

    def _schedule_refresh(self) -> None:
        self.root.after(5000, self._auto_refresh_tick)

    def _auto_refresh_tick(self) -> None:
        if self.auto_refresh.get():
            self.refresh_async(silent=True)
        self._schedule_refresh()

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        if not hasattr(self, "log_messages"):
            self.log_messages = []
        self.log_messages.append(line)
        if len(self.log_messages) > 300:
            self.log_messages = self.log_messages[-300:]
        if hasattr(self, "log"):
            self.log.configure(state="normal")
            self.log.insert("end", f"{line}\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        if hasattr(self, "recent_log_text"):
            recent = "\n".join(self.log_messages[-5:]) or "暂无日志"
            self.recent_log_text.set(recent)

    def _set_status(self, text: str, color: str) -> None:
        self.status_text.set(text)
        self.status_color.set(color)
        if hasattr(self, "status_badge"):
            self.status_badge.configure(bg=color)
        if hasattr(self.root, "title"):
            self.root.title(self._taskbar_title_for_status(text))
        self._sync_overview()

    def copy_logs(self) -> None:
        content = "\n".join(getattr(self, "log_messages", []))
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self._append_log("日志已复制到剪贴板。")

    def clear_logs(self) -> None:
        self.log_messages = []
        if hasattr(self, "log"):
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            self.log.configure(state="disabled")
        if hasattr(self, "recent_log_text"):
            self.recent_log_text.set("暂无日志")

    def _sync_buttons(self) -> None:
        has_processes = bool(self.processes)
        has_selection = bool(self.tree.selection())
        self.stop_selected_button.configure(state="normal" if has_selection else "disabled")
        self.stop_all_button.configure(state="normal" if has_processes else "disabled")

    def refresh_async(self, silent: bool = False) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        if not silent:
            self._set_status("检测中", self._theme_tokens()["warning"])
            self._append_log("正在后台刷新状态。")

        def worker() -> None:
            processes: list[ProcessRecord] = []
            task_records: list[ScheduledTaskRecord] = []
            process_error = ""
            task_error = ""
            try:
                processes, _all_processes = discover_services()
            except Exception as exc:  # noqa: BLE001 - show OS-level failure in the GUI
                process_error = str(exc)
            try:
                task_records = query_briefing_tasks()
            except Exception as exc:  # noqa: BLE001 - show OS-level failure in the GUI
                task_error = str(exc)

            self.root.after(
                0,
                lambda: self._apply_refresh_result(
                    processes,
                    task_records,
                    process_error=process_error,
                    task_error=task_error,
                    silent=silent,
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _apply_refresh_result(
        self,
        processes: list[ProcessRecord],
        task_records: list[ScheduledTaskRecord],
        *,
        process_error: str,
        task_error: str,
        silent: bool,
    ) -> None:
        self._refreshing = False
        if process_error:
            self.processes = []
            self._set_status("检测失败", self._theme_tokens()["danger"])
            if not silent:
                self._append_log(f"检测失败: {process_error}")
            self._sync_table()
            return

        self.processes = processes
        self.task_records = task_records
        self._sync_table()
        self._sync_task_table()
        self._sync_status_label(task_error=task_error, silent=silent)

    def _sync_status_label(self, *, task_error: str = "", silent: bool = False) -> None:
        tokens = self._theme_tokens()
        if self.processes:
            self._set_status(f"运行中: {len(self.processes)}", tokens["success"])
            if not silent:
                self._append_log(f"发现 {len(self.processes)} 个 TradingAgents 相关进程。")
        elif task_error:
            self._set_status("任务检测失败", tokens["danger"])
            if not silent:
                self._append_log(f"定时任务检测失败: {task_error}")
        elif any(record.state.casefold() in {"ready", "running"} for record in self.task_records):
            self._set_status("定时已启用", tokens["info"])
            if not silent:
                self._append_log("未发现运行进程；每日简报定时任务已启用。")
        elif self.task_records:
            self._set_status("定时已停用", tokens["muted"])
            if not silent:
                self._append_log("未发现运行进程；每日简报定时任务已停用。")
        else:
            self._set_status("未安装", tokens["muted"])
            if not silent:
                self._append_log("没有发现运行进程，也没有发现每日简报定时任务。")

    def refresh(self, silent: bool = False) -> None:
        task_error = ""
        try:
            self.processes, _all_processes = discover_services()
        except Exception as exc:  # noqa: BLE001 - show the user the OS-level failure
            self.processes = []
            self._set_status("检测失败", self._theme_tokens()["danger"])
            if not silent:
                self._append_log(f"检测失败: {exc}")
            self._sync_table()
            return

        try:
            self.task_records = query_briefing_tasks()
        except Exception as exc:  # noqa: BLE001 - show the user the OS-level failure
            self.task_records = []
            task_error = str(exc)

        self._sync_table()
        self._sync_task_table()
        self._sync_status_label(task_error=task_error, silent=silent)

    def _sync_task_table(self) -> None:
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        for task in self.task_records:
            self.task_tree.insert(
                "",
                "end",
                values=(
                    task.name,
                    task.state,
                    task.next_run_time,
                    task.last_run_time,
                    task.last_result,
                ),
            )

    def _sync_table(self) -> None:
        selected_pids = {
            int(self.tree.set(item, "pid"))
            for item in self.tree.selection()
            if self.tree.set(item, "pid").isdigit()
        }
        for item in self.tree.get_children():
            self.tree.delete(item)
        for process in self.processes:
            item_id = str(process.pid)
            self.tree.insert(
                "",
                "end",
                iid=item_id,
                values=(process.pid, process.name, process.command_line or process.executable_path),
            )
            if process.pid in selected_pids:
                self.tree.selection_add(item_id)
        self._sync_buttons()

    def _stop_pids(self, pids: list[int]) -> None:
        if not pids:
            messagebox.showinfo("没有可停止的进程", "当前没有选中的 TradingAgents 进程。")
            return

        if not messagebox.askyesno(
            "确认停止",
            f"将停止 {len(pids)} 个 TradingAgents 进程及其子进程。\n\n确定继续吗？",
        ):
            self._append_log("已取消停止操作。")
            return

        result = stop_process_tree(pids)
        if result.stopped:
            self._append_log(f"已停止 PID: {', '.join(str(pid) for pid in result.stopped)}")
        for pid, error in result.failed.items():
            self._append_log(f"停止 PID {pid} 失败: {error}")
        self.refresh(silent=True)

    def stop_selected(self) -> None:
        pids = [
            int(self.tree.set(item, "pid"))
            for item in self.tree.selection()
            if self.tree.set(item, "pid").isdigit()
        ]
        self._stop_pids(pids)

    def stop_all(self) -> None:
        self._stop_pids([process.pid for process in self.processes])


def print_status_once() -> int:
    matches, _all_processes = discover_services()
    if not matches:
        print("TradingAgents status: not running")
        return 0

    print(f"TradingAgents status: running ({len(matches)} process(es))")
    for process in matches:
        command = process.command_line or process.executable_path
        print(f"- PID {process.pid} | {process.name} | {command}")
    return 0


def run_embedded_briefing(args: argparse.Namespace) -> int:
    if str(BRIEFING_DIR) not in sys.path:
        sys.path.insert(0, str(BRIEFING_DIR))
    import run_briefing  # noqa: PLC0415

    briefing_args = ["--mode", args.mode]
    if args.date:
        briefing_args.extend(["--date", args.date])
    if args.no_send:
        briefing_args.append("--no-send")
    if args.force:
        briefing_args.append("--force")
    return run_briefing.main(briefing_args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TradingAgents Windows service manager")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print service status once instead of opening the GUI.",
    )
    parser.add_argument(
        "--run-briefing",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--install-tasks",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--mode", choices=["premarket", "midday", "close", "monitor"])
    parser.add_argument("--date", default="")
    parser.add_argument("--no-send", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if args.run_briefing:
        if not args.mode:
            parser.error("--run-briefing requires --mode")
        return run_embedded_briefing(args)

    if args.install_tasks:
        register_briefing_tasks()
        return 0

    if args.once:
        return print_status_once()

    root = tk.Tk()
    ServiceManagerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
