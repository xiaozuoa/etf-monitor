# Email Format Redesign + Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign email to clean 3-section layout, fix weight display lies (50/20/30→45/35/20), add fetch() error handling, fix 6 other bugs from audit.

**Architecture:** etf_alert.py is the email layer (format/send), etf_signals.py is core CP computation (weights/fetch), etf_engine.py is the analysis engine (weights display/exit calc). Tests go in test_etf_fixes.py.

**Tech Stack:** Python 3.6+, MIMEText/multipart for email, urllib for data fetch

---

### Task 1: Fix weight display — etf_signals.py comments

**Files:**
- Modify: `scripts/etf_signals.py:14-17`

- [ ] **Step 1: Fix comments to match actual weight values**

```python
# Line 14: change comment from 50/20/30 to 45/35/20
# CP权重 — P0统一版 (45/35/20)
W_VOL = 0.45
W_DIR = 0.35
W_SHARE = 0.20
```

- [ ] **Step 2: Fix down-market weight comment (line 106)**

```python
# 动态权重: 跌市中量能升权(放量抛售需更大确认), 方向降权(逆势信号更珍贵)
if idx_chg < 0:
    w_vol, w_dir = 0.60, 0.20
```

- [ ] **Step 3: Run existing tests, verify pass**

Run: `cd scripts && python test_etf_fixes.py`
Expected: 16/16 pass

- [ ] **Step 4: Commit**

```bash
git add scripts/etf_signals.py
git commit -m "fix: weight comments — 50/20/30→45/35/20, fix down-market description"
```

---

### Task 2: Fix weight display — etf_engine.py get_optimal_weights()

**Files:**
- Modify: `scripts/etf_engine.py:643`

- [ ] **Step 1: Fix get_optimal_weights() return values**

```python
def get_optimal_weights():
    """返回最优权重(涨市/跌市动态由compute_cp内部处理)"""
    return {"vol": 0.45, "dir": 0.35, "share": 0.20}
```

- [ ] **Step 2: Run tests**

Run: `cd scripts && python test_etf_fixes.py`
Expected: 16/16 pass

- [ ] **Step 3: Commit**

```bash
git add scripts/etf_engine.py
git commit -m "fix: get_optimal_weights() 50/20/30→45/35/20"
```

---

### Task 3: Add fetch() error handling in etf_signals.py

**Files:**
- Modify: `scripts/etf_signals.py:21-36`
- Test: `scripts/test_etf_fixes.py`

- [ ] **Step 1: Write failing test**

```python
def test_fetch_handles_network_error():
    """BUG: fetch() in etf_signals.py has no try/except, crashes on network failure."""
    import etf_signals
    # Temporarily patch urlopen to raise
    import urllib.request
    original_urlopen = urllib.request.urlopen
    def raise_timeout(*args, **kwargs):
        raise OSError("simulated network failure")
    urllib.request.urlopen = raise_timeout
    try:
        result = etf_signals.fetch("510300", 60)
        assert result == [], f"should return empty list on error, got {len(result)} items"
        print("  PASS: fetch() returns [] on network error")
    finally:
        urllib.request.urlopen = original_urlopen
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python -c "from test_etf_fixes import test_fetch_handles_network_error; test_fetch_handles_network_error()"`
Expected: CRASH with OSError (no try/except)

- [ ] **Step 3: Add try/except to fetch()**

```python
def fetch(code, limit=800):
    """获取K线数据"""
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={code},day,,,{limit},qfq"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as r:
            raw = r.read().decode("utf-8")
        # ... rest of parsing ...
    except Exception as e:
        print(f"  fetch({code}) error: {e}")
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python -c "from test_etf_fixes import test_fetch_handles_network_error; test_fetch_handles_network_error()"`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `cd scripts && python test_etf_fixes.py`
Expected: 17/17 pass

- [ ] **Step 6: Commit**

```bash
git add scripts/etf_signals.py scripts/test_etf_fixes.py
git commit -m "fix: add try/except to fetch(), return [] on network error"
```

---

### Task 4: Fix email subject RFC 2047 encoding (BUG #10)

**Files:**
- Modify: `scripts/etf_alert.py:65,149-152`

- [ ] **Step 1: Add import and encode subject**

```python
from email.header import Header

# Line 65: encode subject
subject_raw = f"{t_label} {tag} — {now.strftime('%m-%d %H:%M')}"
subject = Header(subject_raw, "utf-8").encode()
```

- [ ] **Step 2: Verify email module import works**

Run: `python -c "from email.header import Header; print(Header('test', 'utf-8').encode())"`
Expected: `=?utf-8?b?dGVzdA==?=`

- [ ] **Step 3: Commit**

```bash
git add scripts/etf_alert.py
git commit -m "fix: email subject RFC 2047 encoding for non-ASCII chars"
```

---

### Task 5: Delete dead buy_etf_names variable (BUG #4)

**Files:**
- Modify: `scripts/etf_alert.py:84`

- [ ] **Step 1: Remove line 84**

Delete:
```python
buy_etf_names = "、".join(a['name'][:4] for a in sorted(alerts, key=lambda x: x['composite_prob'], reverse=True)[:4])
```

- [ ] **Step 2: Commit**

```bash
git add scripts/etf_alert.py
git commit -m "fix: remove dead buy_etf_names variable"
```

---

### Task 6: Fix down-market tag logic (BUG #15)

**Files:**
- Modify: `scripts/etf_alert.py:56-63`

- [ ] **Step 1: Add counter_n==2 + down market case**

```python
if counter_n >= 3 and t == "down":
    tag = "国家队大力进场"
elif counter_n >= 2 and t == "down":
    tag = "建议关注"  # <-- new condition
elif high_n >= 2:
    tag = "建议买入"
elif len(alerts) >= 3:
    tag = "建议关注"
else:
    tag = "信号提醒"
```

- [ ] **Step 2: Commit**

```bash
git add scripts/etf_alert.py
git commit -m "fix: counter_n>=2 + down market → 建议关注 (was 信号提醒)"
```

---

### Task 7: Fix calc_dynamic_exit uses current price (BUG #13)

**Files:**
- Modify: `scripts/etf_engine.py:695-720`

- [ ] **Step 1: Change profit calculation from highest-based to current-price-based**

```python
def calc_dynamic_exit(entry_price, highest_since_entry, atr, days_held,
                       current_price=None, time_stop=8, target_pct=5.0, trail_mult=1.5):
    # ...
    # Target take-profit: based on current price
    cur = current_price if current_price is not None else entry_price
    if cur >= entry_price * (1 + target_pct / 100):
        profit_pct = (cur - entry_price) / entry_price * 100
        return True, f"止盈 +{profit_pct:.1f}%"
```

- [ ] **Step 2: Commit**

```bash
git add scripts/etf_engine.py
git commit -m "fix: calc_dynamic_exit uses current price for take-profit (not highest)"
```

---

### Task 8: Fix bare except → except Exception (BUG #9)

**Files:**
- Modify: `scripts/etf_alert.py:28,168,269,316,339,447,474`
- Modify: `scripts/etf_engine.py:152-153,172-173,210-211,233-234,271-272`

- [ ] **Step 1: Replace all bare `except:` and `except: pass` with `except Exception`**

```python
# etf_alert.py examples:
except Exception:  # was: except:
    pass

# etf_engine.py examples:
except Exception as e:  # was: except:
    print(f"  error: {e}")
```

- [ ] **Step 2: Run tests**

Run: `cd scripts && python test_etf_fixes.py`
Expected: 17/17 pass

- [ ] **Step 3: Commit**

```bash
git add scripts/etf_alert.py scripts/etf_engine.py
git commit -m "fix: bare except → except Exception in all files"
```

---

### Task 9: Fix position pyramiding (BUG #12)

**Files:**
- Modify: `scripts/etf_alert.py:318-322`

- [ ] **Step 1: Only close previous position when pyramiding is NOT allowed**

```python
# Only auto-close previous position when NOT in pyramiding mode
if not params.get("allow_pyramiding"):
    for p in reversed(positions):
        if not p.get("exited"):
            p["exited"] = True
            break
```

- [ ] **Step 2: Pass params to record_position**

```python
# In send_email(), line 288:
record_position(resonance, params, trend)
```

- [ ] **Step 3: Update record_position signature**

```python
def record_position(resonance, params, trend):
    # ... now has access to params["allow_pyramiding"]
```

- [ ] **Step 4: Commit**

```bash
git add scripts/etf_alert.py
git commit -m "fix: only auto-close position when allow_pyramiding=False"
```

---

### Task 10: Redesign email body to new 3-section format

**Files:**
- Modify: `scripts/etf_alert.py:86-146` (send_email body generation)

- [ ] **Step 1: Replace entire email body with new format**

```python
    lines = []
    lines.append(f"⏰ {now.strftime('%m月%d日 %H:%M')}")
    lines.append("")
    lines.append("══════════════════════════════════")
    lines.append(f"  ETF信号提醒  {now.strftime('%m月%d日 %H:%M')}")
    lines.append("══════════════════════════════════")
    lines.append("")
    lines.append(f"市场: {market_words}趋势  信号强度: {strength}")
    lines.append(f"总仓位: {total_pct}% (每只{total_pct/n_buy:.0f}%)")
    lines.append("")
    lines.append(f"【买入清单 — 明天{buy_date}开盘买入】")
    lines.append("")
    buy_list = sorted(alerts, key=lambda x: x["composite_prob"], reverse=True)[:5]
    n_buy = len(buy_list)
    for i, a in enumerate(buy_list, 1):
        atr = atrs.get(a['code'], {})
        sl_pct = atr.get("stop_loss_pct", 3)
        sl_price = round(a['close'] * (1 - sl_pct/100), 3)
        name_short = a['name'][:12] if len(a['name']) > 12 else a['name']
        lines.append(f"  {i}. {a['code']} {name_short:<14} {a['close']:.3f}元  CP:{a['composite_prob']}  止损:{sl_price}")
    lines.append("")
    lines.append("【卖出规则】")
    lines.append(f"  持有到期: {exit_date}")
    lines.append(f"  止盈: 任一涨超5% → 卖它")
    lines.append(f"  止损: 任一跌超3% → 卖它")
    lines.append("")
    lines.append(f"下次检查: {'明天盘后' if is_post_market else '今晚19:00'} ｜ 自动发送")
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "compile(open('scripts/etf_alert.py').read(), 'etf_alert.py', 'exec')"`
Expected: no output (syntax OK)

- [ ] **Step 3: Commit**

```bash
git add scripts/etf_alert.py
git commit -m "feat: redesign email layout — 3-section clean format"
```

---

### Task 11: Final test run + push

**Files:**
- All modified files

- [ ] **Step 1: Run all tests**

Run: `cd scripts && python test_etf_fixes.py`
Expected: 17/17 pass

- [ ] **Step 2: Push to GitHub**

```bash
git push origin main
```

- [ ] **Step 3: Trigger a test email**

Add comment to workflow, push, or use workflow_dispatch to trigger postmarket run.
