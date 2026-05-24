#!/usr/bin/env python3
"""ETF国家队共振监控 v5 — 4项改进 + 仓位建议邮件"""

import os, sys, io, smtplib, json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from etf_engine import (full_analysis, get_optimal_weights, save_signal_history,
                         ETFS, WORKSPACE, detect_market_trend, get_dynamic_params,
                         get_min_position, check_consecutive_days, calc_atr,
                         fetch_realtime, fetch_shares_confirmation)

CONFIG_FILE = os.path.join(WORKSPACE, "alert_config.json")
os.makedirs(WORKSPACE, exist_ok=True)


def load_config():
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: cfg = json.load(f)
        except: pass
    return {
        "email_from": os.environ.get("ETF_EMAIL_FROM") or cfg.get("email_from", ""),
        "email_to":   os.environ.get("ETF_EMAIL_TO")   or cfg.get("email_to", ""),
        "smtp_pass":  os.environ.get("SMTP_PASS") or os.environ.get("QQMAIL_AUTH_CODE") or cfg.get("smtp_pass", ""),
        "smtp_host":  os.environ.get("ETF_SMTP_HOST")  or cfg.get("smtp_host", "smtp.qq.com"),
        "smtp_port":  int(os.environ.get("ETF_SMTP_PORT") or cfg.get("smtp_port", "465")),
    }

CFG = load_config()


def send_email(analysis, is_post_market, trend, params, min_pct, consec_info):
    if not CFG["smtp_pass"]:
        print("  未配置SMTP"); return False

    res = analysis["resonance"]
    macro = analysis["macro"]
    atrs = analysis["atr_stops"]
    alerts = res["etfs"]
    now = datetime.now()

    # 标题
    high_n = sum(1 for a in alerts if a["composite_prob"] >= 60)
    counter_n = sum(1 for a in alerts if a.get("is_counter_market"))
    t = trend["trend"]
    t_label = {"up": "🟢","down": "🔴"}.get(t, "🟡")

    if counter_n >= 3 and t == "down":
        tag = "国家队托底"
    elif high_n >= 2:
        tag = f"{high_n}只高确信"
    elif len(alerts) >= 3:
        tag = f"{len(alerts)}只共振"
    else:
        tag = f"{params['label']}"

    subject = f"{t_label} {tag} — {now.strftime('%m-%d %H:%M')}"

    # 正文
    lines = [f"{now.strftime('%Y-%m-%d %H:%M')}  |  v5趋势自适应"]

    # ---- 1. 原因 ----
    lines.append("")
    lines.append("【触发原因】")
    for a in sorted(alerts, key=lambda x: x["composite_prob"], reverse=True):
        counter = " ⚡逆市抗跌" if a.get("is_counter_market") else ""
        lines.append(f"  {a['code']} {a['name']} 概率{a['composite_prob']:.0f}%"
                     f" 量比{a.get('vol_ratio',0):.1f}x{counter}")

    # ---- 2. 趋势 ----
    lines.append("")
    lines.append("【当前趋势】")
    lines.append(f"  方向: {params['label']} (MA斜率{trend['slope']:+.1f}%, 强度{trend['strength']:.0f})")
    lines.append(f"  参数: ≥{params['resonance_min']}只≥{params['cp_threshold']}%触达, 持{params['hold_days']}天"
                 f"{', 可加仓' if params.get('allow_pyramiding') else ''}")

    if macro["decline_days"] >= 3:
        lines.append(f"  背景: 沪深300连跌{macro['decline_days']}日, 恐惧度={macro['fear_level']}")
    else:
        lines.append(f"  背景: 市场情绪正常")
    if macro["north_flow"]:
        nf = macro["north_flow"]
        lines.append(f"  北向: {nf['net_flow_yi']:+.0f}亿 ({nf['signal']})")

    # ---- 3. 走向 ----
    lines.append("")
    lines.append("【近期走向】")
    counter_n = sum(1 for a in alerts if a.get("is_counter_market"))
    if trend["trend"] == "down" and counter_n >= 2:
        lines.append("  国家队托底迹象 → 短期企稳概率高, 1-2日内或有反弹")
    elif trend["trend"] == "up" and high_n >= 2:
        lines.append("  趋势向上+多信号共振 → 继续看涨, 持股待涨")
    elif counter_n >= 3:
        lines.append("  多ETF逆市抗跌 → 国家队明确进场, 底部信号较强")
    elif trend["trend"] == "up":
        lines.append("  上升趋势中 → 顺势而为, 回调加仓")
    elif trend["strength"] < 30:
        lines.append("  趋势极弱 → 多看少动, 等待明确信号")
    else:
        lines.append("  震荡格局 → 精选个股, 控制仓位")

    # 连日趋
    if consec_info["consecutive"] >= 2:
        lines.append(f"  ⚡已连续{consec_info['consecutive']}日共振 → 战役级信号!")

    # ---- 4. 仓位建议 ----
    lines.append("")
    lines.append("【仓位建议】")
    base_pct = int(min_pct * 100)
    if base_pct > 0:
        lines.append(f"  底仓: {base_pct}% (趋势{trend['trend']} 强度{trend['strength']:.0f})")

    sig_pct = 40 if high_n >= 2 else 30
    if params.get("allow_pyramiding"):
        sig_pct = 60
    if consec_info["consecutive"] >= 2:
        sig_pct = min(80, sig_pct + 20)

    lines.append(f"  信号仓: {sig_pct}% (触发{res['mid_count']}只, 高确信{high_n}只)")

    total = min(100, base_pct + sig_pct)
    lines.append(f"  ─────────────────")
    lines.append(f"  建议总仓位: {total}%")

    # ---- 5. 买什么 ----
    lines.append("")
    lines.append("【买入标的】")
    buy_list = sorted(alerts, key=lambda x: x["composite_prob"], reverse=True)[:5]
    for a in buy_list:
        atr = atrs.get(a['code'], {})
        sl_pct = atr.get("stop_loss_pct", 3)
        t1_pct = atr.get("target_1_pct", 5)
        lines.append(f"  {a['code']} {a['name']} 现{a['close']:.3f} "
                     f"概率{a['composite_prob']:.0f}% SL-{sl_pct}% TP+{t1_pct}%")

    # ---- 6. 操作 ----
    lines.append("")
    lines.append("【操作】")
    if is_post_market:
        if base_pct > 0:
            lines.append(f"  ① 明日开盘: 先建{base_pct}%底仓(510300)")
            lines.append(f"  ② 信号买入: 再加{sig_pct}%仓位上表标的, 等权分配")
        else:
            lines.append(f"  明日开盘: {total}%仓位等权买入上表标的")

        if params.get("allow_pyramiding"):
            lines.append(f"  持有: ~{params['hold_days']}天, 期间可追加信号仓位")
        else:
            lines.append(f"  持有: ~{params['hold_days']}天, 止损按上表")

        if consec_info["consecutive"] >= 2:
            lines.append(f"  ⚡连日趋: 仓位×{1.0+min(0.5,(consec_info['consecutive']-1)*0.25):.1f}倍")
    else:
        lines.append("  盘中初筛, 等盘后19:00确认再操作")

    lines.append("")
    lines.append(f"--- v5趋势自适应 | {params['label']} | 下检:{'盘后19:00' if not is_post_market else '明盘'}")

    body = "\n".join(lines)

    try:
        msg = MIMEMultipart()
        msg["From"] = CFG["email_from"]; msg["To"] = CFG["email_to"]
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        import smtplib as _smtplib
        server = _smtplib.SMTP_SSL(CFG["smtp_host"], CFG["smtp_port"], timeout=30)
        server.login(CFG["email_from"], CFG["smtp_pass"])
        server.sendmail(CFG["email_from"], CFG["email_to"], msg.as_string())
        server.quit()
        print(f"  ✅ 已发送 → {CFG['email_to']}")
        return True
    except Exception as e:
        print(f"  ❌ 发送失败: {e}")
        return False


def run(is_post_market=None):
    if is_post_market is None:
        now = datetime.now(); is_post_market = now.hour >= 19

    use_shares = is_post_market
    use_realtime = not is_post_market

    print("=" * 60)
    print(f"🔍 ETF v5趋势自适应  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 趋势+参数+底仓
    trend = detect_market_trend()
    params = get_dynamic_params(trend)
    min_pct, min_reason = get_min_position(trend)

    print(f"  趋势: {trend['trend']} (斜率{trend['slope']}%) → {params['label']}")
    print(f"  参数: ≥{params['resonance_min']}只≥{params['cp_threshold']}%, 持{params['hold_days']}天")
    print(f"  底仓: {min_pct*100:.0f}% ({min_reason})")

    weights = get_optimal_weights()
    print(f"  权重: 量{weights['vol']*100:.0f}% 向{weights['dir']*100:.0f}% 份{weights['share']*100:.0f}%")

    # 分析
    analysis = full_analysis(use_realtime=use_realtime, use_shares=use_shares, weights=weights)
    analysis["trend"] = trend
    analysis["dynamic_params"] = params

    results = analysis["results"]
    resonance = analysis["resonance"]

    # v5动态阈值
    dynamic_mid = [r for r in results if r["composite_prob"] >= params["cp_threshold"]]
    dynamic_trig = len(dynamic_mid) >= params["resonance_min"]
    resonance["triggered"] = dynamic_trig
    resonance["mid_count"] = len(dynamic_mid)
    resonance["etfs"] = dynamic_mid
    resonance["high_count"] = sum(1 for r in dynamic_mid if r["composite_prob"] >= 60)

    # 连日趋
    consec_info = check_consecutive_days(resonance["mid_count"], resonance["high_count"])
    cons_days, is_campaign, boost = consec_info
    consec_info = {"consecutive": cons_days, "campaign": is_campaign, "boost": boost}

    # 打印
    print(f"  信号: 高{resonance['high_count']} 中{resonance['mid_count']} 触达:{'✅' if dynamic_trig else '❌'}")
    for r in sorted(results, key=lambda x: x["composite_prob"], reverse=True):
        icon = "🔴" if r["composite_prob"] >= 60 else ("🟡" if r["composite_prob"] >= params["cp_threshold"] else "⚪")
        counter = " ⚡抗跌" if r.get("is_counter_market") else ""
        print(f"  {icon} {r['code']} {r['name']:<14} CP={r['composite_prob']}%"
              f" (V{r['vol_prob']:.0f} D{r['dir_prob']:.0f}){counter}")

    if analysis["macro"]["decline_days"] >= 3:
        print(f"  ⚠️ 连跌{analysis['macro']['decline_days']}日")

    # 决策
    if not dynamic_trig:
        print(f"\n  未触达 (需≥{params['resonance_min']}只≥{params['cp_threshold']}%)")
        save_signal_history(resonance)
        return

    if not is_post_market:
        print(f"\n  📡 盘中初筛 → 等盘后确认")
        save_signal_history(resonance)
        return

    print(f"\n  ✅ 盘后确认")
    save_signal_history(resonance)

    # 去重
    log_path = os.path.join(WORKSPACE, "alert_sent_v5.json")
    log = {}
    if os.path.exists(log_path):
        try:
            with open(log_path) as f: log = json.load(f)
        except: pass
    last = log.get("last_sent", "")
    if last:
        parts = last.split("_")
        if len(parts) >= 2:
            try:
                if (datetime.now() - datetime.fromisoformat(parts[1])).total_seconds() < 7200:
                    print(f"  2h内已发送")
                    return
            except: pass

    print(f"  🚨 发送...")
    send_email(analysis, is_post_market=True, trend=trend, params=params,
               min_pct=min_pct, consec_info=consec_info)
    log["last_sent"] = f"{datetime.now().strftime('%Y%m%d')}_{datetime.now().isoformat()}"
    with open(log_path, 'w') as f: json.dump(log, f)


if __name__ == "__main__":
    run()
