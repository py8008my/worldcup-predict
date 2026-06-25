#!/usr/bin/env python3
"""每日世界杯方案生成 + 邮件推送 v7.0
高性价比模型 + 必胜模型，合并推送
"""
import sys, os, subprocess, smtplib
from datetime import datetime
from email.mime.text import MIMEText

# ── 配置 ──
SMTP_CONFIG = {
    "host": "smtp.163.com",
    "port": 465,
    "user": "py8008my@163.com",
    "password": "JQQW4LYJ5r2kswci",
    "to": "py8008my@163.com"
}

MODELS = [
    ("worldcup_model.py", "🔥 高性价比"),
    ("worldcup_model_win.py", "💎 必胜"),
]

def run_model(script):
    """运行预测模型，捕获输出"""
    os.chdir("/workspace")
    env = dict(os.environ)
    env.pop('WC_AUTO_SCHEDULE', None)
    result = subprocess.run(
        ["python3.11", script],
        capture_output=True, text=True, timeout=60, env=env
    )
    return result.stdout, result.stderr


def build_email(all_outputs):
    """合并两个模型的方案输出为HTML"""
    def esc(s):
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    html = []
    html.append('<div style="font-family:monospace;font-size:14px;line-height:1.8;color:#333;max-width:600px;">')
    html.append(f'<div style="text-align:center;font-size:18px;font-weight:bold;color:#c0392b;padding:12px;">⚽ 世界杯方案 v7.0</div>')

    for label, output in all_outputs:
        lines = output.strip().split('\n')
        
        # 找方案起始
        plan_lines = []
        in_plan = False
        for line in lines:
            if '今日高性价比方案' in line or '今日稳健方案' in line or '今日必胜方案' in line:
                in_plan = True
            if in_plan:
                plan_lines.append(line)
                if '理性投注' in line:
                    break

        if not plan_lines:
            # 找无数据提示
            skip_msg = None
            for line in lines:
                if '无在售' in line or '无世界杯' in line:
                    skip_msg = line.strip()
            if skip_msg:
                html.append(f'<div style="color:#999;padding:8px;">{label}: {esc(skip_msg)}</div>')
            continue

        # 解析方案
        color_map = {'🔥 高性价比': '#c0392b', '🛡️ 稳健': '#2980b9', '💎 必胜': '#8e44ad'}
        bg_map = {'🔥 高性价比': '#fdf2f2', '🛡️ 稳健': '#f0f4fa', '💎 必胜': '#f9f0fc'}
        border_map = {'🔥 高性价比': '#c0392b', '🛡️ 稳健': '#2980b9', '💎 必胜': '#8e44ad'}
        
        clr = color_map.get(label, '#333')
        bg = bg_map.get(label, '#f8f9fa')
        border = border_map.get(label, '#999')

        html.append(f'<div style="background:{bg};border-left:4px solid {border};padding:10px 14px;margin:10px 0;border-radius:4px;">')
        html.append(f'<div style="color:{clr};font-weight:bold;font-size:16px;margin-bottom:6px;">{label}方案</div>')

        in_detail = False
        for line in plan_lines:
            s = line.strip()
            if not s:
                continue
            esc_s = esc(s)

            if '今日高性价比方案' in s or '今日稳健方案' in s or '今日必胜方案' in s:
                continue
            if s.startswith('═══') or s.startswith('────'):
                continue

            if s.startswith('▶'):
                html.append(f'<div style="font-weight:bold;color:{clr};margin-top:6px;">{esc_s}</div>')
                continue

            if s.startswith('📝') or s.startswith('💰 投入'):
                html.append(f'<div style="color:#888;font-size:11px;padding-left:8px;">{esc_s}</div>')
                continue

            if s.startswith('┌'):
                in_detail = True
                html.append(f'<div style="background:#fff;border:1px solid #e0e0e0;border-radius:3px;padding:6px 10px;margin:4px 0;">')
                html.append(f'<div style="font-size:11px;color:#e67e22;font-weight:bold;">{esc_s}</div>')
                continue

            if s.startswith('│') and in_detail:
                if '@' in s:
                    html.append(f'<div style="color:#555;font-size:11px;padding-left:6px;border-left:2px solid #ddd;margin:1px 0 1px 6px;">{esc_s}</div>')
                elif '→' in s:
                    html.append(f'<div style="color:#27ae60;font-size:11px;padding-left:6px;">{esc_s}</div>')
                else:
                    html.append(f'<div style="color:#777;font-size:11px;padding-left:6px;">{esc_s}</div>')
                continue

            if in_detail and not s.startswith('│'):
                html.append('</div>')
                in_detail = False

            if '合计' in s:
                html.append(f'<div style="font-weight:bold;color:{clr};margin-top:2px;padding:4px 8px;">{esc_s}</div>')
                continue

            if s.startswith('═══ 规则合规') or s.startswith('📏') or s.startswith('🔢') or s.startswith('⚠️'):
                html.append(f'<div style="color:#666;font-size:10px;padding-left:8px;">{esc_s}</div>')
                continue

            if '总投入' in s:
                html.append(f'<div style="background:#fff;border:1px solid {border};border-radius:3px;padding:4px 8px;margin:4px 0;font-weight:bold;color:{clr};font-size:12px;">{esc_s}</div>')
                continue

        if in_detail:
            html.append('</div>')
        html.append('</div>')  # 关闭模型块

    # 底部
    html.append('<div style="margin-top:16px;padding-top:10px;border-top:1px solid #eee;color:#999;font-size:11px;">')
    html.append(f'生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")} | 模型 v7.0 高性价比+必胜 | 理性投注 仅供娱乐')
    html.append('</div>')

    return '\n'.join(html), False


def send_email(subject, html_body):
    msg = MIMEText(html_body, "html", "utf-8")
    msg["From"] = f"世界杯方案 <{SMTP_CONFIG['user']}>"
    msg["To"] = SMTP_CONFIG["to"]
    msg["Subject"] = subject

    with smtplib.SMTP_SSL(SMTP_CONFIG["host"], SMTP_CONFIG["port"], timeout=15) as s:
        s.login(SMTP_CONFIG["user"], SMTP_CONFIG["password"])
        s.sendmail(SMTP_CONFIG["user"], SMTP_CONFIG["to"], msg.as_string())
    return True


def main():
    all_outputs = []
    for script, label in MODELS:
        print(f"🔄 运行{label}模型 ({script})...")
        stdout, stderr = run_model(script)
        if stderr and 'Error' in stderr:
            print(f"  ⚠️ {label}运行异常: {stderr[:100]}")
        if stdout.strip():
            all_outputs.append((label, stdout))
        else:
            all_outputs.append((label, ""))
    
    if not any(out for _, out in all_outputs):
        subject = "⚠️ 世界杯预测 - 今日无数据"
        body = "<p>体彩API未返回在售比赛数据。</p>"
        send_email(subject, body)
        print(f"✅ 无数据邮件已发送")
        return

    html_body, is_skip = build_email(all_outputs)

    today = datetime.now().strftime("%m-%d")
    subject = f"⚽ 世界杯方案 {today} | v7.0 高性价比+必胜"

    send_email(subject, html_body)
    print(f"✅ 已发送到 {SMTP_CONFIG['to']}")
    print(f"📧 主题: {subject}")


if __name__ == "__main__":
    main()
