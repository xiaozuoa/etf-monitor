# ETF Monitor: Email Format Redesign + Bug Fixes

## Email Format

结构化布局，去掉全角分隔线 `━`（兼容性），去掉风险提示块，用 ASCII `═`。

```
══════════════════════════════════
  ETF信号提醒  06月01日 19:00
══════════════════════════════════

市场: 上升趋势  信号强度: 中 ⭐⭐
总仓位: 75% (每只15%)

【买入清单 — 明天06月02日开盘买入】
  1. 510300 沪深300ETF      4.123元  CP:82  止损:3.996
  2. 510050 上证50ETF       3.456元  CP:75  止损:3.352

【卖出规则】
  持有到期: 06月10日
  止盈: 任一涨超5% → 卖它
  止损: 任一跌超3% → 卖它

下次检查: 明天盘后 ｜ 自动发送
```

Changes from old format:
- Remove `━` fullwidth separators → ASCII `═`
- Remove risk warning block
- Remove "为什么发这封邮件" block
- Remove "一句话" block, merge into header
- Flatten layout: 3 sections (buy list, sell rules, footer)
- Subject: use `email.header.Header` for RFC 2047 encoding
- Delete dead `buy_etf_names` variable

## Bug Fixes

### P0: Weight display (BUG #1)
- `etf_signals.py`: fix comment 50/20/30 → 45/35/20
- `etf_engine.py` `get_optimal_weights()`: 50/20/30 → 45/35/20
- `etf_alert.py` print: align with actual values
- Down-market comment fix: "方向翻倍→量能升" → correct description

### P0: fetch() error handling (BUG #3)
- Wrap `etf_signals.py` `fetch()` urlopen in try/except, return [] on failure

### P1: Email subject encoding (BUG #10)
- Use `email.header.Header` for subject with UTF-8

### P1: calc_dynamic_exit uses current price (BUG #13)
- Change `profit_pct` from highest-based to current-price-based

### P1: Down-market tag logic (BUG #15)
- `counter_n >= 2 and t == "down"` → "建议关注"

### P2: Bare except → except Exception (BUG #9)
- All bare `except:` and `except: pass` → `except Exception`

### P2: Position pyramiding bug (BUG #12)
- Only auto-close previous position when `allow_pyramiding` is False

### P2: buy_etf_names dead code (BUG #4)
- Delete line 84
