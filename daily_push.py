#!/usr/bin/env python3
"""每日世界杯方案生成 + 邮件推送 v7.4
高性价比实战比分模型，每日推送
v7.4: 全量赛果同步 + 开放型比赛强制入选
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
]

def run_model(script):
    os.chdir("/workspace")
    env = dict(os.environ)
    env.pop('WC_AUTO_SCHEDULE', None)
    result = subprocess.run(
        ["python3.11", script],
        capture_output=True, text=True, timeout=60, env=env
    )
    return result.stdout, result.stderr


def build_email(all_outputs):
    """合并模型输出为HTML邮件，含赛况汇总+方案"""
    def esc(s):
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    html = []
    html.append('<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;font-size:14px;color:#333;max-width:640px;margin:0 auto;">')
    
    today = datetime.now().strftime("%m月%d日")
    html.append(f'<div style="background:linear-gradient(135deg,#c0392b,#e74c3c);color:#fff;text-align:center;padding:16px;border-radius:8px 8px 0 0;font-size:20px;font-weight:bold;">')
    html.append(f'⚽ 世界杯竞彩方案 · {today}')
    html.append(f'<div style="font-size:12px;font-weight:normal;opacity:0.85;margin-top:4px;">v7.4 实战比分 · 分类驱动 · 总进球复式</div>')
    html.append('</div>')
    
    html.append('<div style="background:#fafafa;padding:12px 16px;border:1px solid #e0e0e0;border-top:none;">')

    for label, output in all_outputs:
        lines = output.strip().split('\n')
        
        # 提取赛况汇总
        summary_lines = []
        plan_lines = []
        in_summary = False
        in_plan = False
        for line in lines:
            if '世界杯全量赛果' in line or '世界杯赛况汇总' in line:
                in_summary = True
                summary_lines.append(line)
                continue
            if in_summary:
                if '今日实战方案' in line:
                    in_summary = False
                    in_plan = True
                    plan_lines.append(line)
                    continue
                if line.strip().startswith('===') and len(summary_lines) > 1:
                    in_summary = False
                    continue
                summary_lines.append(line)
                continue
            if '今日实战方案' in line:
                in_plan = True
            if in_plan:
                plan_lines.append(line)
                if '理性投注' in line:
                    break

        # 渲染赛况汇总卡片
        if summary_lines:
            html.append('<div style="background:#fff;border:1px solid #e8e8e8;border-radius:6px;padding:10px 14px;margin:6px 0;">')
            html.append('<div style="font-weight:bold;color:#c0392b;font-size:14px;margin-bottom:6px;">🌍 世界杯全量赛果</div>')
            for s_line in summary_lines:
                s = s_line.strip()
                if not s or s.startswith('==='): continue
                esc_s = esc(s)
                if '进球分布' in s or '胜平负分布' in s or '全部赛果' in s:
                    html.append(f'<div style="font-weight:bold;color:#555;font-size:12px;margin-top:6px;">{esc_s}</div>')
                elif any(s.startswith(f'{g}球') for g in range(9)):
                    html.append(f'<div style="color:#888;font-size:11px;padding-left:8px;font-family:monospace;">{esc_s}</div>')
                elif any(s.startswith(r) for r in ['主胜', '平', '客胜']):
                    html.append(f'<div style="color:#888;font-size:11px;padding-left:8px;font-family:monospace;">{esc_s}</div>')
                elif '2026-' in s:
                    html.append(f'<div style="color:#999;font-size:10px;padding-left:8px;">{esc_s}</div>')
            html.append('</div>')

        if not plan_lines:
            continue

        color_map = {'🔥 高性价比': '#c0392b', '💎 必胜': '#8e44ad'}
        bg_map = {'🔥 高性价比': '#fef5f5', '💎 必胜': '#faf5fc'}
        border_map = {'🔥 高性价比': '#e74c3c', '💎 必胜': '#9b59b6'}
        
        clr = color_map.get(label, '#333')
        bg = bg_map.get(label, '#fafafa')
        border = border_map.get(label, '#999')

        html.append(f'<div style="background:{bg};border-left:3px solid {border};padding:10px 14px;margin:8px 0;border-radius:4px;">')
        html.append(f'<div style="color:{clr};font-weight:bold;font-size:16px;margin-bottom:4px;">{label} · 今日方案</div>')

        in_detail = False
        for line in plan_lines:
            s = line.strip()
            if not s: continue
            esc_s = esc(s)

            if '今日实战方案' in s: continue
            if s.startswith('═══') or s.startswith('────'): continue

            if s.startswith('▶'):
                html.append(f'<div style="font-weight:bold;color:{clr};margin:6px 0 2px;">{esc_s}</div>')
                continue

            if s.startswith('📝'):
                html.append(f'<div style="color:#999;font-size:11px;padding-left:4px;">{esc_s}</div>')
                continue

            if s.startswith('┌'):
                in_detail = True
                html.append(f'<div style="background:#fff;border:1px solid #eee;border-radius:4px;padding:8px 10px;margin:6px 0;">')
                title = esc_s.replace('┌ 📌 ', '')
                html.append(f'<div style="font-size:12px;color:{clr};font-weight:bold;margin-bottom:4px;">{title}</div>')
                continue

            if s.startswith('│') and in_detail:
                if '进球区间' in s or '选项:' in s:
                    html.append(f'<div style="color:{clr};font-size:12px;font-weight:bold;padding:2px 0 2px 8px;">{esc_s}</div>')
                elif '@' in s:
                    html.append(f'<div style="color:#555;font-size:11px;padding:1px 0 1px 16px;">{esc_s}</div>')
                elif '💰' in s or '回报' in s:
                    html.append(f'<div style="color:#27ae60;font-size:11px;font-weight:bold;padding:3px 0 1px 4px;border-top:1px dashed #eee;margin-top:2px;">{esc_s}</div>')
                else:
                    html.append(f'<div style="color:#777;font-size:11px;padding-left:8px;">{esc_s}</div>')
                continue

            if in_detail and not s.startswith('│'):
                html.append('</div>')
                in_detail = False

            if '合计' in s:
                html.append(f'<div style="font-weight:bold;color:{clr};margin-top:4px;padding:4px 8px;font-size:13px;">{esc_s}</div>')
                continue

            if s.startswith('═══ 规则合规') or s.startswith('📏') or s.startswith('🔢') or s.startswith('⚠️'):
                html.append(f'<div style="color:#aaa;font-size:10px;padding:1px 0 1px 8px;">{esc_s}</div>')
                continue

            if '总投入' in s:
                html.append(f'<div style="background:#fff;border:2px solid {border};border-radius:4px;padding:6px 10px;margin:6px 0;font-weight:bold;color:{clr};font-size:13px;text-align:center;">{esc_s}</div>')
                continue

        if in_detail:
            html.append('</div>')
        html.append('</div>')

    html.append('</div>')

    html.append(f'<div style="text-align:center;color:#bbb;font-size:11px;padding:10px 0;border-top:1px solid #eee;margin-top:8px;">')
    html.append(f'生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}<br>')
    html.append('模型 v7.4 · 比赛分类驱动 · 总进球复式2串1 · 理性投注 仅供娱乐')
    html.append('</div>')
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
    subject = f"⚽ 世界杯竞彩方案 {today} | v7.4"

    send_email(subject, html_body)
    print(f"✅ 已发送到 {SMTP_CONFIG['to']}")
    print(f"📧 主题: {subject}")


if __name__ == "__main__":
    main()
