"""邮件发送：使用 QQ 邮箱 SMTP SSL，发送 HTML 简报。"""
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import config
import settings_store


def send_html(subject: str, html: str, to: str = None) -> bool:
    """发送一封 HTML 邮件。返回是否成功。"""
    recipients = settings_store.parse_recipients(to or config.SMTP_TO)
    if not recipients:
        raise RuntimeError("缺少收件邮箱，请在小工具中添加收件人或检查 QQ_SMTP_TO")
    if not config.SMTP_AUTH_CODE:
        raise RuntimeError("缺少 QQ_SMTP_AUTH_CODE，请检查 daily_briefing/.env")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("A股每日简报", "utf-8")), config.SMTP_USER))
    msg["To"] = ", ".join(recipients)

    part_html = MIMEText(html, "html", "utf-8")
    part_text = MIMEText(html_to_text(html), "plain", "utf-8")
    msg.attach(part_text)
    msg.attach(part_html)

    with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
        server.login(config.SMTP_USER, config.SMTP_AUTH_CODE)
        server.sendmail(config.SMTP_USER, recipients, msg.as_string())
    return True


def html_to_text(html: str) -> str:
    """极简 HTML 转纯文本，便于邮件客户端无 HTML 时降级。"""
    import re
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</(p|div|tr|h[1-6]|li)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    import html as html_lib
    return html_lib.unescape(text)
