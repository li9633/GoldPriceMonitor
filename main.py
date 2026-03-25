import time
from datetime import datetime
from data_fetcher import fetch_current_price
from alert_engine import AlertEngine
from notifier import Notifier
from history_manager import HistoryManager
from data_importer import init_historical_data
from config import SYMBOL, CHECK_INTERVAL


def main():
    print("=" * 50)
    print("🏆 黄金价格智能监控系统启动")
    print("=" * 50)

    # 0. 初始化历史数据（首次运行或数据不足时自动导入）
    init_historical_data()

    print(f"📌 监控品种：{SYMBOL}")
    print(f"⏱️  检查间隔：{CHECK_INTERVAL} 秒")
    print("=" * 50)

    # 初始化各模块
    history_mgr = HistoryManager()
    alert_engine = AlertEngine(SYMBOL)
    notifier = Notifier()

    # 显示当前数据库状态
    conn = sqlite3.connect("gold_price_history.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM prices WHERE symbol = ?", (SYMBOL,))
    db_count = c.fetchone()[0]
    conn.close()
    print(f"📈 当前历史记录数：{db_count} 条")
    print("=" * 50)
    print("🚀 开始实时监控...\n")

    while True:
        try:
            # 1. 获取当前价格
            price_data = fetch_current_price(SYMBOL)
            if not price_data:
                print(f"[{datetime.now()}] 获取价格失败，等待下次检查")
                time.sleep(CHECK_INTERVAL)
                continue

            current_price = price_data['price']
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] {price_data['name']} 价格：{current_price}")

            # 2. 保存到历史记录
            history_mgr.save_price(SYMBOL, current_price)

            # 3. 检查报警条件
            alerts, suggestions = alert_engine.check_all_conditions(
                current_price)

            # 4. 如果有报警，发送通知
            if alerts:
                notifier.send_alert(SYMBOL, current_price, alerts, suggestions)

        except KeyboardInterrupt:
            print("\n⛔ 程序被用户中断")
            break
        except Exception as e:
            print(f"[{datetime.now()}] 主循环发生错误：{e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    import sqlite3
    main()
