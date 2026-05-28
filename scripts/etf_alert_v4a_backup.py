#!/usr/bin/env python3
"""ETF国家队共振监控 v4a — 趋势自适应 + 简洁邮件"""

import os, sys, io, smtplib, json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
# 注意: 此备份原配7-ETF引擎(etf_engine_v4a_backup), 现导入etf_engine(15-ETF池).
# 如需恢复原始7-ETF行为, 改为 from etf_engine_v4a_backup import ...
from etf_engine import (full_analysis, get_optimal_weights, save_signal_history,
                         ETFS, WORKSPACE, detect_market_trend, get_dynamic_params,
                         calc_atr, fetch_realtime, fetch_shares_confirmation)

CONFIG_FILE = os.path.join(WORKSPACE, "alert_config.json")
SENT_LOG    = os.path.join(WORKSPACE, "alert_sent_v4.json")
os.makedirs(WORKSPACE, exist_ok=True)


def load_config():
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except: pass
    return {
        "email_from": os.environ.get("ETF_EMAIL_FROM") or cfg.get("email_from", ""),
        "email_to":   os.environ.get("ETF_EMAIL_TO")   or cfg.get("email_to", ""),
        "smtp_pass":  os.environ.get("SMTP_PASS") or os.environ.get("QQMAIL_AUTH_CODE") or cfg.get("smtp_pass", ""),
        "smtp_host":  os.environ.get("ETF_SMTP_HOST")  or cfg.get("smtp_host", "smtp.qq.com"),
        "smtp_port":  int(os.environ.get("ETF_SMTP_PORT") or cfg.get("smtp_port", "465")),
    }

CFG = load_config()


def trend_analysis(trend_info, results, macro, atrs):
    """生成趋势分析文字"""
    t = trend_info["trend"]
    lines = []

    if t == "up":
        lines.append(f"趋势: 上升 (MA斜率+{trend_info['slope']}%, 强度{trend_info['strength']:.0f})")
        lines.append(f"策略: 宽松模式 — ≥2只≥45%即进场, 持有约6天, 可加仓")
    elif t == "down":
        lines.append(f"趋势: 下降 (MA斜率{trend_info['slope']}%, 强度{trend_info['strength']:.0f})")
        lines.append(f"策略: 防御模式 — ≥3只≥50%才进场, 持有约3天, 不追")
    else:
        lines.append(f"趋势: 震荡 (MA斜率{trend_info['slope']:.2f}%)")
        lines.append(f"策略: 默认模式")

    # 宏观
    if macro["decline_days"] >= 3:
        lines.append(f"背景: 沪深300连跌{macro['decline_days']}日, 恐惧度={macro['fear_level']}")
        if macro["decline_days"] >= 5:
            lines.append("      → 极度恐惧, 国家队维稳概率很高")
    else:
        lines.append(f"背景: 市场情绪正常")
    if macro["north_flow"]:
        nf = macro["north_flow"]
        lines.append(f"北向: {nf['net_flow_yi']:+.0f}亿 ({nf['signal']})")

    return "\n".join(lines)


def likely_direction(etf_list, trend_info):
    """根据当前信号和趋势, 判断近期走向"""
    if not etf_list:
        return "无显著信号, 维持观望"

    high_n = sum(1 for e in etf_list if e.get("composite_prob", 0) >= 60)
    counter_n = sum(1 for e in etf_list if e.get("is_counter_market"))

    if trend_info["trend"] == "down" and counter_n >= 2:
        return "国家队托底迹象 → 短期企稳概率高, 1-2日内可能有反弹"
    elif trend_info["trend"] == "up" and high_n >= 2:
        return "趋势向上+国家队加码 → 短期继续看涨, 持有5-7天"
    elif counter_n >= 3:
        return "多只ETF逆市抗跌 → 国家队明确进场, 底部信号较强"
    elif trend_info["trend"] == "up":
        return "上升趋势中的正常信号 → 顺势持有, 不宜追高"
    else:
        return "信号力度一般 → 少量参与, 设好止损"


def send_email(analysis, is_post_market):
    """发送简洁的买入建议邮件"""
    if not CFG["smtp_pass"]:
        print("  未配置SMTP, 跳过")
        return False

    res    = analysis["resonance"]
    macro  = analysis["macro"]
    atrs   = analysis["atr_stops"]
    alerts = res["etfs"]
    trend  = analysis.get("trend", {"trend": "neutral", "slope": 0, "strength": 50})
    params = analysis.get("dynamic_params", {"cp_threshold": 50, "resonance_min": 3, "hold_days": 3})

    now = datetime.now()

    # 标题
    high_n = sum(1 for a in alerts if a["composite_prob"] >= 60)
    counter_n = sum(1 for a in alerts if a.get("is_counter_market"))
    t = trend["trend"]

    emoji = "🟢" if t == "up" else ("🔴" if t == "down" else "🟡")
    if counter_n >= 3 and t == "down":
        tag = "国家队托底"
    elif high_n >= 2:
        tag = f"{high_n}只高确信"
    else:
        tag = f"{len(alerts)}只共振"

    subject = f"{emoji} {tag} — {now.strftime('%m-%d %H:%M')}"

    # 正文
    lines = []
    lines.append(f"{now.strftime('%Y-%m-%d %H:%M')}")

    # 1. 原因
    lines.append("")
    lines.append("【触发原因】")
    for a in sorted(alerts, key=lambda x: x["composite_prob"], reverse=True):
        counter = " [逆市抗跌]" if a.get("is_counter_market") else ""
        lines.append(f"  · {a['code']} {a['name']} 概率{a['composite_prob']:.0f}%"
                     f" 量比{a.get('vol_ratio',0):.1f}x{counter}")

    # 2. 趋势
    lines.append("")
    lines.append("【当前趋势】")
    lines.append(trend_analysis(trend, analysis["results"], macro, atrs))

    # 3. 走向分析
    lines.append("")
    lines.append("【走向判断】")
    lines.append(f"  {likely_direction(alerts, trend)}")

    # 4. 买什么
    lines.append("")
    lines.append("【建议买入】")
    buy_list = sorted(alerts, key=lambda x: x["composite_prob"], reverse=True)[:3]
    for a in buy_list:
        atr = atrs.get(a['code'], {})
        sl_pct = atr.get("stop_loss_pct", 3)
        t1_pct = atr.get("target_1_pct", 5)
        lines.append(f"  {a['code']} {a['name']} 现价{a['close']:.3f}")
        lines.append(f"    概率{a['composite_prob']:.0f}% | 止损-{sl_pct}% | 目标+{t1_pct}%")

    # 5. 什么时候买
    lines.append("")
    lines.append("【操作】")

    if is_post_market:
        if t == "up":
            lines.append(f"  明天开盘买50%仓位, 等回调0.5-1%加仓50%")
            lines.append(f"  持有约{params.get('hold_days',6)}天, 止损按上表")
        elif t == "down" and counter_n >= 2:
            lines.append(f"  明天开盘买30%仓位试探")
            lines.append(f"  若2天内继续出现信号 → 加仓到50%")
            lines.append(f"  持有约{params.get('hold_days',3)}天")
        else:
            lines.append(f"  明天开盘买30%仓位")
            lines.append(f"  持有约{params.get('hold_days',3)}天, 设好止损")
    else:
        lines.append("  盘中初筛信号, 等待盘后19:00确认后再决定")
        if counter_n >= 2:
            lines.append("  (多个逆市信号, 建议关注尾盘是否有国家队大单)")

    lines.append("")
    lines.append("---")
    lines.append(f"v4a趋势自适应 | 下次更新: {'盘后19:00' if not is_post_market else '下一个交易日'}")

    body = "\n".join(lines)

    try:
        msg = MIMEMultipart()
        msg["From"] = CFG["email_from"]
        msg["To"] = CFG["email_to"]
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
        now = datetime.now()
        is_post_market = now.hour >= 19

    use_shares = is_post_market
    use_realtime = not is_post_market

    print("=" * 60)
    print(f"🔍 ETF国家队 v4a趋势自适应  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 趋势检测
    trend = detect_market_trend()
    params = get_dynamic_params(trend)
    print(f"  趋势: {trend['trend']} (斜率{trend['slope']}%) → {params['label']}")
    print(f"  参数: ≥{params['resonance_min']}只≥{params['cp_threshold']}%, "
          f"持{params['hold_days']}天, 叠仓={'是' if params.get('allow_pyramiding') else '否'}")

    # 权重
    weights = get_optimal_weights()
    print(f"  权重: 量{weights['vol']*100:.0f}% 向{weights['dir']*100:.0f}% 份{weights['share']*100:.0f}%")

    # 分析
    analysis = full_analysis(use_realtime=use_realtime, use_shares=use_shares, weights=weights)
    analysis["trend"] = trend
    analysis["dynamic_params"] = params

    results   = analysis["results"]
    resonance = analysis["resonance"]

    # v4a: 用动态阈值覆盖共振检测
    dynamic_mid = [r for r in results if r["composite_prob"] >= params["cp_threshold"]]
    dynamic_triggered = len(dynamic_mid) >= params["resonance_min"]
    resonance["triggered"] = dynamic_triggered
    resonance["mid_count"] = len(dynamic_mid)
    resonance["etfs"] = dynamic_mid
    resonance["high_count"] = sum(1 for r in dynamic_mid if r["composite_prob"] >= 60)

    # 打印
    high_n = resonance["high_count"]
    mid_n  = resonance["mid_count"]
    print(f"  信号: 高{high_n}只 中{mid_n}只 共振: {'✅' if dynamic_triggered else '❌'}")
    for r in sorted(results, key=lambda x: x["composite_prob"], reverse=True):
        icon = "🔴" if r["composite_prob"] >= 60 else ("🟡" if r["composite_prob"] >= params["cp_threshold"] else "⚪")
        counter = " ⚡抗跌" if r.get("is_counter_market") else ""
        print(f"  {icon} {r['code']} {r['name']}: CP={r['composite_prob']}%"
              f" (V{r['vol_prob']:.0f} D{r['dir_prob']:.0f}){counter}")

    # 宏观
    macro = analysis["macro"]
    if macro["decline_days"] >= 3:
        print(f"  ⚠️ 连跌{macro['decline_days']}日 | 恐惧:{macro['fear_level']}")

    # 决策
    if not dynamic_triggered:
        print(f"\n  未触发 (需≥{params['resonance_min']}只≥{params['cp_threshold']}%)")
        save_signal_history(resonance)
        return

    if not is_post_market:
        print(f"\n  📡 盘中初筛 ({resonance['mid_count']}只) → 等盘后19:00确认")
        save_signal_history(resonance)
        return

    print(f"\n  ✅ 盘后确认")
    save_signal_history(resonance)

    # 发送
    import time as _time
    log = {}
    log_path = os.path.join(WORKSPACE, "alert_sent_v4.json")
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r') as f:
                log = json.load(f)
        except: pass

    last = log.get("last_sent", "")
    if last:
        parts = last.split("_")
        if len(parts) >= 2:
            try:
                lt = datetime.fromisoformat(parts[1])
                if (datetime.now() - lt).total_seconds() < 7200:
                    print(f"  2h内已发送, 跳过")
                    return
            except: pass

    print(f"  🚨 发送邮件...")
    send_email(analysis, is_post_market=True)

    log["last_sent"] = f"{datetime.now().strftime('%Y%m%d')}_{datetime.now().isoformat()}"
    with open(log_path, 'w') as f:
        json.dump(log, f)


if __name__ == "__main__":
    run()
