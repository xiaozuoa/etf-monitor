#!/usr/bin/env python3
"""检查实盘信号的实际盈亏，与回测对比"""
import json, os, sys
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from etf_signals import fetch

WORKSPACE = os.path.expanduser(os.environ.get("ETF_WORKSPACE", "~/.etf-skill/workspace"))
TRACKER = os.path.join(WORKSPACE, "signal_tracker.json")

if not os.path.exists(TRACKER):
    print("无追踪记录")
    sys.exit(0)

with open(TRACKER, 'r', encoding='utf-8') as f:
    tracker = json.load(f)

print(f"{'日期':<12} {'趋势':<6} {'持有天':<8} {'ETF数':<6} {'盈亏':>8}")
print("-" * 48)

for sig in tracker:
    pnl = sig.get("actual_pnl")
    total = 0
    count = 0
    for e in sig.get("etfs", []):
        data = fetch(e["code"], 30)
        if data:
            exit_p = None
            exit_date = sig.get("exit_date", "")
            for d in data:
                if d["date"] >= exit_date:
                    exit_p = d["c"]
                    break
            if exit_p is None and data:
                exit_p = data[-1]["c"]
            if exit_p and e.get("entry_price"):
                p = (exit_p - e["entry_price"]) / e["entry_price"] * 100
                total += p
                count += 1
    if count > 0:
        avg_pnl = total / count
        pnl_str = f"{avg_pnl:+.2f}%"
    else:
        pnl_str = "N/A"
    print(f"{sig['date']:<12} {sig.get('trend','?'):<6} {sig.get('hold_days','?'):<8} {count:<6} {pnl_str:>8}")
