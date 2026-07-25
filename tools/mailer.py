import os, smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formataddr
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
MANAGER_EMAIL = os.environ.get("AR_MANAGER_EMAIL", SMTP_USER)

MIME_MAP = {".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel", ".pdf": "application/pdf"}


def _send(to: str, subject: str, body: str, attachments: list = None):
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if attachments:
        for filepath in attachments:
            if not os.path.exists(filepath):
                continue
            ext = os.path.splitext(filepath)[1].lower()
            mime_type = MIME_MAP.get(ext, "application/octet-stream")
            main, sub = mime_type.split("/", 1)
            filename = os.path.basename(filepath)
            with open(filepath, "rb") as f:
                part = MIMEBase(main, sub)
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", "attachment",
                                filename=("utf-8", "", filename))
                msg.attach(part)

    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls(context=context)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to, msg.as_string())


def send_recon_result(excel_path: str, stats: dict, diff_details: list):
    subject = f"AR审核对账结果 - 匹配{stats['match']} 差额{stats['diff']}"
    body = f"""清远芊丽酒店 AR审核对账结果

========================
总记录数: {stats['total']}
完全匹配: {stats['match']}
有 差 额: {stats['diff']}
仅 OTA :  {stats['ota_only']}
仅 PMS :  {stats['pms_only']}
========================

"""
    if diff_details:
        body += "差额明细:\n"
        for d in diff_details:
            body += (f"  账号{d['账号']} 房号{d['房号']} {d['OTA姓名']}/{d['PMS姓名']} | "
                     f"{d['差异字段']} OTA={d['OTA值']} PMS={d['PMS值']} 差额={d['差额']}\n")
    else:
        body += "无差额，全部匹配。"

    body += "\n详见附件。"
    _send(MANAGER_EMAIL, subject, body, [excel_path])
    return f"已推送至 {MANAGER_EMAIL}"


def send_diff_alert(account, room, name_ota, name_pms, field, val_ota, val_pms, delta, guest_email=None):
    subject = f"[差额告警] 账号{account} {field} 不一致"
    body = (f"AR对账发现差额:\n"
            f"  账号: {account}\n  房号: {room}\n"
            f"  OTA姓名: {name_ota}  PMS姓名: {name_pms}\n"
            f"  差异字段: {field}\n"
            f"  OTA值: {val_ota}\n  PMS值: {val_pms}\n  差额: {delta}\n")
    _send(MANAGER_EMAIL, subject, body)
    if guest_email:
        _send(guest_email, subject, body)
    return f"差额告警已推送: 账号{account}"