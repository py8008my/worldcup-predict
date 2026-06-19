#!/usr/bin/env python3
"""通过163邮箱SMTP发送邮件"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys, json

SMTP_CONFIG = {
    "host": "smtp.163.com",
    "port": 465,
    "user": "py8008my@163.com",
    "password": "JQQW4LYJ5r2kswci",
    "to": "py8008my@163.com"
}

def send_email(subject, body):
    msg = MIMEMultipart("alternative")
    msg["From"] = f"世界杯冷门预测 <{SMTP_CONFIG['user']}>"
    msg["To"] = SMTP_CONFIG["to"]
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html", "utf-8"))
    
    with smtplib.SMTP_SSL(SMTP_CONFIG["host"], SMTP_CONFIG["port"], timeout=15) as s:
        s.login(SMTP_CONFIG["user"], SMTP_CONFIG["password"])
        s.sendmail(SMTP_CONFIG["user"], SMTP_CONFIG["to"], msg.as_string())
    return True

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: mail_sender.py <主题> <正文>")
        sys.exit(1)
    send_email(sys.argv[1], sys.argv[2])
    print("✅ 邮件发送成功")
