import json
from collections import Counter
from datetime import datetime

file_path = "replay/data/mode1_decisions.jsonl"
lines = [json.loads(l) for l in open(file_path).readlines() if l.strip()]

initial_capital = 10000.0
equity = initial_capital
trades = []
fee_rate = 0.0004  # 0.04% maker/taker avg fee per side (0.08% roundtrip)

for i in range(len(lines) - 4):
    d = lines[i]["decision"]
    if d == "HOLD":
        continue

    t_in = datetime.fromtimestamp(lines[i]["bar_open_ms"]/1000).strftime("%m-%d %H:%M")
    t_out = datetime.fromtimestamp(lines[i+4]["bar_open_ms"]/1000).strftime("%m-%d %H:%M")
    p_in = lines[i]["bar_close"]
    p_out = lines[i+4]["bar_close"]

    # 5% notional position size ($500 USDT, Half-Kelly / 5x leverage standard)
    pos_usdt = 500.0

    if d == "SELL":
        gross_return_pct = (p_in - p_out) / p_in
        gross_pnl = pos_usdt * gross_return_pct
        fees = pos_usdt * (fee_rate * 2)
        net_pnl = gross_pnl - fees
        trade_type = "SHORT"
    else:
        gross_return_pct = (p_out - p_in) / p_in
        gross_pnl = pos_usdt * gross_return_pct
        fees = pos_usdt * (fee_rate * 2)
        net_pnl = gross_pnl - fees
        trade_type = "LONG"

    equity += net_pnl
    trades.append({
        "bar_idx": i + 1,
        "type": trade_type,
        "t_in": t_in,
        "t_out": t_out,
        "p_in": p_in,
        "p_out": p_out,
        "gross_pct": gross_return_pct * 100,
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": net_pnl,
        "equity_after": equity
    })

winning_trades = [t for t in trades if t["net_pnl"] > 0]
losing_trades = [t for t in trades if t["net_pnl"] <= 0]
short_trades = [t for t in trades if t["type"] == "SHORT"]
long_trades = [t for t in trades if t["type"] == "LONG"]

gross_profit = sum(t["net_pnl"] for t in winning_trades)
gross_loss = abs(sum(t["net_pnl"] for t in losing_trades))
profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0
total_fees = sum(t["fees"] for t in trades)
net_profit = sum(t["net_pnl"] for t in trades)

short_wins = [t for t in short_trades if t["net_pnl"] > 0]
short_pnl = sum(t["net_pnl"] for t in short_trades)
long_wins = [t for t in long_trades if t["net_pnl"] > 0]
long_pnl = sum(t["net_pnl"] for t in long_trades)

print("=" * 70)
print("        VBT Mode 1 (50-Bar) 逐筆交易與盈虧深度統計報告         ")
print("=" * 70)
print(f"帳戶初始本金          : ${initial_capital:,.2f} USDT")
print(f"回測結束帳戶淨值      : ${equity:,.2f} USDT")
print(f"淨利潤 (Net PnL)      : ${net_profit:+,.2f} USDT ({net_profit/initial_capital*100:+.2f}%)")
print(f"總毛利 (Gross Profit) : ${gross_profit:+,.2f} USDT")
print(f"總毛損 (Gross Loss)   : -${gross_loss:,.2f} USDT")
print(f"盈虧比 (Profit Factor): {profit_factor:.2f}")
print(f"總手續費磨損 (Fees)   : ${total_fees:.2f} USDT")
print("-" * 70)
print(f"總交易次數 (Trades)   : {len(trades)} 筆")
print(f"盈利筆數 / 虧損筆數   : {len(winning_trades)} 勝 / {len(losing_trades)} 負")
print(f"總體勝率 (Win Rate)   : {len(winning_trades)/len(trades)*100:.1f}%")
if winning_trades:
    avg_win_pct = sum(t["gross_pct"] for t in winning_trades)/len(winning_trades)
    max_win_pct = max(t["gross_pct"] for t in winning_trades)
    print(f"平均盈利 (Avg Win)    : ${gross_profit/len(winning_trades):+.2f} USDT (+{avg_win_pct:.2f}%)")
    print(f"單筆最大盈利 (Max Win): ${max(t['net_pnl'] for t in winning_trades):+.2f} USDT (+{max_win_pct:.2f}%)")
if losing_trades:
    avg_loss_pct = sum(t["gross_pct"] for t in losing_trades)/len(losing_trades)
    max_loss_pct = min(t["gross_pct"] for t in losing_trades)
    print(f"平均虧損 (Avg Loss)   : -${gross_loss/len(losing_trades):.2f} USDT ({avg_loss_pct:.2f}%)")
    print(f"單筆最大虧損 (Max Loss): ${min(t['net_pnl'] for t in losing_trades):+.2f} USDT ({max_loss_pct:.2f}%)")
if winning_trades and losing_trades:
    payoff_ratio = (gross_profit/len(winning_trades))/(gross_loss/len(losing_trades))
    print(f"盈虧回報比 (Avg Win/Avg Loss): {payoff_ratio:.2f} : 1")
print("-" * 70)
print("[多空分項績效剖析]")
short_win_rate = len(short_wins)/len(short_trades)*100 if short_trades else 0
long_win_rate = len(long_wins)/len(long_trades)*100 if long_trades else 0
print(f"  * 做空交易 (SHORT)  : {len(short_trades)} 筆 | 勝率: {short_win_rate:.1f}% | 貢獻淨利: ${short_pnl:+,.2f} USDT")
print(f"  * 做多交易 (LONG)   : {len(long_trades)} 筆 | 勝率: {long_win_rate:.1f}% | 貢獻淨利: ${long_pnl:+,.2f} USDT")
print("=" * 70)
print("\n[代表性交易明細清單 Sample Trades]")
print(f"{'Bar':<4} {'方向':<6} {'進場時間':<12} {'進場價':<10} {'出場價':<10} {'毛收益率':<9} {'淨盈虧(USDT)':<12} {'淨值'}")
print("-" * 75)
for t in trades[:10]:
    print(f"{t['bar_idx']:<4} {t['type']:<6} {t['t_in']:<12} {t['p_in']:<10.2f} {t['p_out']:<10.2f} {t['gross_pct']:+6.2f}%   {t['net_pnl']:+8.2f} USDT   ${t['equity_after']:,.2f}")
print("...")
for t in trades[-5:]:
    print(f"{t['bar_idx']:<4} {t['type']:<6} {t['t_in']:<12} {t['p_in']:<10.2f} {t['p_out']:<10.2f} {t['gross_pct']:+6.2f}%   {t['net_pnl']:+8.2f} USDT   ${t['equity_after']:,.2f}")
