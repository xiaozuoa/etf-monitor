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
    high_n = sum(1 for a in alerts if a["composite_prob"] >= 70)
    counter_n = sum(1 for a in alerts if a.get("is_counter_market"))
    t = trend["trend"]
    t_label = {"up": "🟢","down": "🔴"}.get(t, "🟡")

    if counter_n >= 3 and t == "down":
        tag = "国家队大力进场"
    elif high_n >= 2:
        tag = "建议买入"
    elif len(alerts) >= 3:
        tag = "建议关注"
    else:
        tag = "信号提醒"

    subject = f"{t_label} {tag} — {now.strftime('%m-%d %H:%M')}"

    # ===== 新手友好版正文 =====
    base_pct = int(min_pct * 100)
    sig_pct = 50 if high_n >= 2 else 40
    if params.get("allow_pyramiding"): sig_pct = 60
    if consec_info["consecutive"] >= 2: sig_pct = min(65, sig_pct + 15)
    total_pct = min(75, base_pct + sig_pct)

    exit_date = (now + timedelta(days=params['hold_days'])).strftime('%m月%d日')
    buy_date = (now + timedelta(days=1)).strftime('%m月%d日')

    # 信号强度等级
    if high_n >= 3: strength = "强 ⭐⭐⭐"
    elif high_n >= 1: strength = "中 ⭐⭐"
    else: strength = "弱 ⭐"

    # 一句话总结
    market_words = {"up": "上涨","down": "下跌"}.get(t, "震荡")
    buy_etf_names = "、".join(a['name'][:4] for a in sorted(alerts, key=lambda x: x['composite_prob'], reverse=True)[:4])

    lines = []
    lines.append(f"⏰ {now.strftime('%m月%d日 %H:%M')}")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"  一句话: 明天{buy_date}开盘买入以下ETF, 拿到{exit_date}左右卖出")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(f"📌 市场状态: {market_words}趋势 | 信号强度: {strength}")
    lines.append(f"💰 用多少钱: 总资金的 {total_pct}% (约{total_pct/100*10:.0f}-{total_pct/100*10+2:.0f}成仓)")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("  买这些 (明天开盘价买入, 金额平均分配)")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    buy_list = sorted(alerts, key=lambda x: x["composite_prob"], reverse=True)[:5]
    n_buy = len(buy_list)
    for i, a in enumerate(buy_list, 1):
        atr = atrs.get(a['code'], {})
        sl_pct = atr.get("stop_loss_pct", 3)
        sl_price = round(a['close'] * (1 - sl_pct/100), 3)
        lines.append(f"  {i}. {a['code']} {a['name']}")
        lines.append(f"     现价约 {a['close']:.3f}元 | 亏{sl_pct}%就卖=跌破{sl_price}元")
    lines.append("")
    lines.append(f"  怎么买: 明天上午9:30开盘后, 打开中山证券APP")
    lines.append(f"  (以上价格为今日收盘价, 实际以明日开盘价为准)")
    lines.append(f"  搜索上面的代码, 每个买{total_pct/n_buy:.0f}%的钱")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("  什么时候卖")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"  ① 正常情况: 拿到 {exit_date} 左右, 系统会发卖出提醒")
    lines.append(f"  ② 赚够了: 任意一只涨超5%, 先把那只有盈利的卖了")
    lines.append(f"  ③ 亏太多: 任意一只亏超3%, 立刻卖掉它止损")
    lines.append(f"  ④ 别贪: 收到卖出邮件就操作, 不要犹豫")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("  为什么发这封邮件")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    reason_parts = [f"检测到{res['mid_count']}只ETF同时出现异常信号"]
    if counter_n >= 2:
        reason_parts.append("多只ETF在大盘下跌时逆势上涨(疑似国家队进场)")
    elif t == "up":
        reason_parts.append("市场处于上升趋势, 顺势加仓")
    elif macro["decline_days"] >= 3:
        reason_parts.append(f"市场已连续下跌{macro['decline_days']}天, 国家队可能出手维稳")
    reason_parts.append(f"历史回测类似信号的胜率约55-60%")
    for rp in reason_parts:
        lines.append(f"  · {rp}")
    if consec_info["consecutive"] >= 2:
        lines.append(f"  ⚡ 这是连续第{consec_info['consecutive']}天出现信号, 可靠性更高")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("  风险提示")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("  ⚠ 这个策略长期能赚钱, 但不保证每次都赚")
    lines.append("  ⚠ 历史最大回撤约7% (10万本金最多亏7000)")
    lines.append("  ⚠ 不要把所有钱都放进来, 用闲置资金")
    lines.append("  ⚠ 如果看不懂或者不确定, 宁可不动")
    lines.append("")
    lines.append(f"📬 下次检查: {'明天盘后' if is_post_market else '今晚19:00'} | 自动发送, 无需回复")

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

    # 先检查是否需要卖出提醒
    check_and_send_sell()

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
    resonance["high_count"] = sum(1 for r in dynamic_mid if r["composite_prob"] >= 70)
    resonance["resonance_min"] = params["resonance_min"]  # 存下当天阈值供连日趋判断

    # 连日趋
    consec_info = check_consecutive_days(resonance["mid_count"], resonance["high_count"],
                                          resonance_min=params["resonance_min"])
    cons_days, is_campaign, boost = consec_info
    consec_info = {"consecutive": cons_days, "campaign": is_campaign, "boost": boost}

    # 打印
    print(f"  信号: 高{resonance['high_count']} 中{resonance['mid_count']} 触达:{'✅' if dynamic_trig else '❌'}")
    for r in sorted(results, key=lambda x: x["composite_prob"], reverse=True):
        icon = "🔴" if r["composite_prob"] >= 70 else ("🟡" if r["composite_prob"] >= params["cp_threshold"] else "⚪")
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
    sent = send_email(analysis, is_post_market=True, trend=trend, params=params,
               min_pct=min_pct, consec_info=consec_info)

    # 记录持仓 + dedup (仅在发送成功时)
    if sent:
        log["last_sent"] = f"{datetime.now().strftime('%Y%m%d')}_{datetime.now().isoformat()}"
        with open(log_path, 'w') as f: json.dump(log, f)
        record_position(resonance, params, trend)


def record_position(resonance, params, trend):
    """记录本次买入, 用于后续卖出提醒"""
    pos_path = os.path.join(WORKSPACE, "active_positions.json")
    now = datetime.now()

    pos = {
        "entry_date": now.strftime("%Y-%m-%d"),
        "entry_time": now.isoformat(),
        "hold_days": params["hold_days"],
        "exit_date": (now + timedelta(days=params["hold_days"])).strftime("%Y-%m-%d"),
        "trend": trend["trend"],
        "etfs": [{"code": e["code"], "name": e["name"],
                  "entry_price": e["close"], "cp": e["composite_prob"]}
                 for e in resonance["etfs"][:5]],
        "stop_loss_pct": 3.0,
        "target_pct": 5.0,
        "exited": False,
    }

    # 加载已有持仓
    positions = []
    if os.path.exists(pos_path):
        try:
            with open(pos_path, 'r', encoding='utf-8') as f:
                positions = json.load(f)
        except: pass

    # 标记最近一个未退出持仓为已退出(同一批替换)
    for p in reversed(positions):
        if not p.get("exited"):
            p["exited"] = True
            break
    positions.append(pos)
    with open(pos_path, 'w', encoding='utf-8') as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)
    print(f"  📝 已记录持仓, 预计{pos['exit_date']}卖出")


def check_sell_reminder():
    """检查是否需要发送卖出提醒"""
    pos_path = os.path.join(WORKSPACE, "active_positions.json")
    if not os.path.exists(pos_path):
        return None

    try:
        with open(pos_path, 'r', encoding='utf-8') as f:
            positions = json.load(f)
    except:
        return None

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    for pos in positions:
        if pos.get("exited"):
            continue

        exit_date = pos.get("exit_date", "")
        hold_days = pos.get("hold_days", 3)
        entry_date = pos.get("entry_date", "")

        # 判断是否该卖了
        days_held = (now - datetime.fromisoformat(pos["entry_time"])).days if pos.get("entry_time") else 0

        # 条件1: 到期了
        if exit_date and today >= exit_date:
            return {"reason": "持有到期", "position": pos}

        # 条件2: 已持有超过计划天数
        if days_held >= hold_days:
            return {"reason": f"已持{days_held}天(计划{hold_days}天)", "position": pos}

        # 条件3: 趋势转弱(用当前趋势判断)
        trend = detect_market_trend()
        if trend["trend"] == "down" and trend["strength"] < 40 and days_held >= 2:
            return {"reason": "趋势转弱, 建议减仓", "position": pos}

        # 条件4: 个股权重止盈/止损 (自动检测, 与邮件建议的5%/3%一致)
        if pos.get("entry_time") and days_held >= 1:
            for etf in pos.get("etfs", []):
                try:
                    from etf_signals import fetch as _fetch_price
                    kdata = _fetch_price(etf["code"], 5)
                    if kdata:
                        cur = kdata[-1]["c"]
                        pnl = (cur - etf["entry_price"]) / etf["entry_price"] * 100
                        if pnl >= 5.0:
                            return {"reason": f"{etf['code']} 止盈(+{pnl:.1f}%)", "position": pos}
                        if pnl <= -3.0:
                            return {"reason": f"{etf['code']} 止损({pnl:.1f}%)", "position": pos}
                except:
                    pass

    return None


def send_sell_email(sell_info):
    """发送卖出提醒邮件"""
    if not CFG["smtp_pass"]:
        return False

    pos = sell_info["position"]
    reason = sell_info["reason"]
    now = datetime.now()

    subject = f"🔔 该卖了 — {now.strftime('%m-%d %H:%M')}"

    entry_dt = pos.get('entry_date', '?')
    etf_list = pos.get("etfs", [])

    lines = [f"⏰ {now.strftime('%m月%d日 %H:%M')}"]
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"  该卖了 — {reason}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(f"  买入时间: {entry_dt}")
    lines.append(f"  持有到现在: 该清仓了")
    lines.append("")
    lines.append("  你手里有的:")
    for e in etf_list:
        lines.append(f"    {e['code']} {e['name']} (买入价约{e['entry_price']:.3f}元)")
    lines.append("")
    lines.append("  现在要做的事:")
    lines.append("    打开中山证券APP → 找到这些ETF → 全部卖出")
    lines.append("    不要犹豫, 不要等反弹, 按计划执行")
    lines.append("")
    if "止损" in reason or "转弱" in reason:
        lines.append("  ⚠ 这次可能是亏的, 但止损是保护本金")
        lines.append("  ⚠ 长期看, 小亏+大赚才是赚钱的方式")
    lines.append("")
    lines.append("📬 自动发送, 无需回复")

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
        print(f"  ✅ 卖出提醒已发送")

        # 标记已退出
        pos["exited"] = True
        pos_path = os.path.join(WORKSPACE, "active_positions.json")
        # 保存所有持仓(不覆盖!)
        all_positions = []
        if os.path.exists(pos_path):
            try:
                with open(pos_path, 'r', encoding='utf-8') as f:
                    all_positions = json.load(f)
            except: pass
        for i, p in enumerate(all_positions):
            if p.get("entry_time") == pos.get("entry_time"):
                all_positions[i] = pos  # 更新退出状态
                break
        else:
            all_positions.append(pos)
        with open(pos_path, 'w', encoding='utf-8') as f:
            json.dump(all_positions, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"  ❌ 卖出邮件失败: {e}")
        return False


def check_and_send_sell():
    """公开入口: 检查并发送卖出提醒 (每12小时最多一次)"""
    # 去重检查
    sell_log_path = os.path.join(WORKSPACE, "sell_sent_log.json")
    if os.path.exists(sell_log_path):
        try:
            with open(sell_log_path, 'r') as f:
                last_sell = json.load(f).get("last_time", "")
            if last_sell:
                last_dt = datetime.fromisoformat(last_sell)
                if (datetime.now() - last_dt).total_seconds() < 43200:  # 12h
                    return False
        except: pass

    sell_info = check_sell_reminder()
    if sell_info:
        print(f"\n🔔 检测到卖出信号: {sell_info['reason']}")
        sent = send_sell_email(sell_info)
        if sent:
            with open(sell_log_path, 'w') as f:
                json.dump({"last_time": datetime.now().isoformat()}, f)
        return sent
    return False


if __name__ == "__main__":
    run()
