"""全局配置：路径、邮箱、行情阈值、持仓解析。"""
import os
from pathlib import Path

import settings_store
from dotenv import load_dotenv

BASE_DIR = Path(os.getenv("A_STOCK_BRIEFING_DIR") or Path(__file__).resolve().parent)
PROJECT_DIR = BASE_DIR.parent
LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR / ".env")

# 邮箱
SMTP_HOST = os.getenv("QQ_SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.getenv("QQ_SMTP_PORT", "465"))
SMTP_USER = os.getenv("QQ_SMTP_USER", "")
SMTP_AUTH_CODE = os.getenv("QQ_SMTP_AUTH_CODE", "")
SMTP_TO_ENV = os.getenv("QQ_SMTP_TO", "")

# DeepSeek
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# OpenAI-compatible LLM API. The UI stores these under llm_api; old DeepSeek
# env vars remain supported so existing setups keep working.
OPENAI_COMPATIBLE_API_KEY = os.getenv("OPENAI_COMPATIBLE_API_KEY", "")
OPENAI_COMPATIBLE_BASE_URL = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "")
OPENAI_COMPATIBLE_MODEL = os.getenv("OPENAI_COMPATIBLE_MODEL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "")

HOLDINGS_FILE = PROJECT_DIR / "持仓记录_2026-08-20.md"
USER_SETTINGS = settings_store.load_settings(env_recipients=SMTP_TO_ENV)
SMTP_SETTINGS = settings_store.settings_to_smtp_settings(
    USER_SETTINGS,
    env_host=SMTP_HOST,
    env_port=SMTP_PORT,
    env_user=SMTP_USER,
    env_auth_code=SMTP_AUTH_CODE,
)
SMTP_HOST = SMTP_SETTINGS["host"]
SMTP_PORT = SMTP_SETTINGS["port"]
SMTP_USER = SMTP_SETTINGS["user"]
SMTP_AUTH_CODE = SMTP_SETTINGS["auth_code"]
SMTP_TO = ", ".join(settings_store.settings_to_recipients(USER_SETTINGS, fallback=SMTP_TO_ENV))
LLM_API_SETTINGS = settings_store.settings_to_llm_api_settings(
    USER_SETTINGS,
    env_base_url=OPENAI_COMPATIBLE_BASE_URL or OPENAI_BASE_URL or DEEPSEEK_BASE_URL,
    env_api_key=OPENAI_COMPATIBLE_API_KEY or OPENAI_API_KEY or DEEPSEEK_API_KEY,
    env_model=OPENAI_COMPATIBLE_MODEL or OPENAI_MODEL or "deepseek-chat",
)
LLM_BASE_URL = LLM_API_SETTINGS["base_url"]
LLM_API_KEY = LLM_API_SETTINGS["api_key"]
LLM_MODEL = LLM_API_SETTINGS["model"]

# 盘中实时监控触发阈值
ALERT_THRESHOLDS = {
    "single_day_change_pct": 5.0,       # 单只持仓日内涨跌幅超过 ±5%
    "index_change_pct": 1.5,            # 上证/深证指数涨跌超过 ±1.5%
    "turnover_pct": 8.0,                # 持仓换手率超过 8%
    "from_high_drawdown_pct": 3.0,      # 距日内最高回撤超过 3%
}

# 盘中额外提醒邮件：避免太频繁
MONITOR_COOLDOWN_MINUTES = 60          # 两封提醒之间至少间隔 60 分钟
MONITOR_MAX_EMAILS_PER_DAY = 3         # 盘中额外提醒全天最多 3 封

# 各持仓风险线（来自操作计划，仅用于盘中提示，不自动交易）
POSITION_RISK_LINES = settings_store.settings_to_position_risk_lines(USER_SETTINGS)
WATCHLIST_STOCKS = settings_store.settings_to_stock_rows(USER_SETTINGS)
