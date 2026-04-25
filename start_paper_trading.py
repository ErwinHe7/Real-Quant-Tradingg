"""
一键启动纸仓交易

运行方式:
    python start_paper_trading.py

做了什么:
    1. 用 ETF_SECTOR_11 (11只板块ETF) 作为交易标的
    2. 用 ONS 策略 (Online Newton Step，回测样本外均值 Sharpe 1.30)
    3. 热身：把策略在历史数据上跑一遍，让它"知道"现在市场在哪
    4. 模拟执行：每次 tick 计算目标仓位，经过风控层，输出买卖单
    5. 状态持久化到 live/state/，关掉再开会自动恢复

输出位置:
    live/state/sessions/YYYY-MM-DD.jsonl      每个 tick 的净值记录
    live/state/sessions/YYYY-MM-DD-summary.json  每日汇总
    live/state/paper/account.json             账户快照（持仓、现金）
"""

import subprocess
import sys
from pathlib import Path

SYMBOLS = [
    "XLB", "XLC", "XLE", "XLF", "XLI",
    "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
]

def main():
    print("=" * 60)
    print("  RealQuantTrading — 纸仓启动")
    print("=" * 60)
    print(f"  策略: ONS (Online Newton Step)")
    print(f"  标的: {', '.join(SYMBOLS)}")
    print(f"  初始资金: $10,000 (模拟)")
    print(f"  每次 tick 间隔: 15 分钟")
    print(f"  风控: 单名 10%上限 / 年化波动率目标 12% / 最大回撤 15% 熔断")
    print()
    print("  状态文件:")
    print("    live/state/sessions/   每日 tick 日志")
    print("    live/state/paper/      持仓与现金快照")
    print()
    print("  Ctrl+C 停止，下次运行自动续上")
    print("=" * 60)
    print()

    cmd = [
        sys.executable, "-m", "live.runner",
        "--strategy", "ons",
        "--broker", "paper",
        "--symbols", *SYMBOLS,
    ]

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n已停止。再次运行本脚本继续。")
    except subprocess.CalledProcessError as e:
        print(f"\n启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
