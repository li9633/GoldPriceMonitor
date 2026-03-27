import time
import sqlite3
from datetime import datetime
from data_fetcher import fetch_current_price
from alert_engine import AlertEngine
from notifier import Notifier
from history_manager import HistoryManager
from data_importer import init_historical_data
from config import SYMBOL, CHECK_INTERVAL, LOG_CONFIG
from logger import get_logger


def main():
    # 初始化日志
    logger = get_logger("GoldPriceMonitor")

    logger.info("=" * 50)
    logger.info("🏆 黄金价格智能监控系统启动")
    logger.info("=" * 50)

    # 0. 初始化历史数据（首次运行或数据不足时自动导入）
    logger.info("正在初始化历史数据...")
    init_historical_data()

    logger.info(f"📌 监控品种：{SYMBOL}")
    logger.info(f"⏱️  检查间隔：{CHECK_INTERVAL} 秒")
    logger.info("=" * 50)

    # 初始化各模块
    history_mgr = HistoryManager()
    alert_engine = AlertEngine(SYMBOL)
    notifier = Notifier()

    # 显示当前数据库状态
    try:
        conn = sqlite3.connect("gold_price_history.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM prices WHERE symbol = ?", (SYMBOL,))
        db_count = c.fetchone()[0]
        conn.close()
        logger.info(f"📈 当前历史记录数：{db_count} 条")
    except Exception as e:
        logger.error(f"查询数据库失败：{e}", exc_info=e)

    logger.info("=" * 50)
    logger.info("🚀 开始实时监控...\n")

    # 记录启动时间
    start_time = datetime.now()
    check_count = 0
    alert_count = 0

    while True:
        try:
            # 1. 获取当前价格
            price_data = fetch_current_price(SYMBOL)
            if not price_data:
                logger.warning(f"[{datetime.now()}] 获取价格失败，等待下次检查")
                time.sleep(CHECK_INTERVAL)
                continue

            current_price = price_data['price']
            logger.debug(
                f"[{datetime.now().strftime('%H:%M:%S')}] {price_data['name']} 价格：{current_price}")

            # 2. 保存到历史记录
            history_mgr.save_price(SYMBOL, current_price)

            # 3. 检查报警条件
            alerts, suggestions = alert_engine.check_all_conditions(
                current_price)

            # 4. 如果有报警，发送通知
            if alerts:
                alert_count += 1
                logger.warning(f"触发 {len(alerts)} 条报警")
                for alert in alerts:
                    logger.warning(f"  └─ {alert}")

                notifier.send_alert(SYMBOL, current_price, alerts, suggestions)
            else:
                logger.debug("  └─ 无报警")

            check_count += 1

            # 每 100 次检查输出统计
            if check_count % 100 == 0:
                run_time = (datetime.now() - start_time).total_seconds() / 60
                logger.info("=== 运行统计 ===")
                logger.info(f"运行时长：{run_time:.2f} 分钟")
                logger.info(f"检查次数：{check_count}")
                logger.info(f"报警次数：{alert_count}")
                logger.info(f"日志大小：{logger.get_log_size() / 1024:.2f} KB")
                logger.info("================")

            # 每天清理一次过期日志
            if check_count % (86400 // CHECK_INTERVAL) == 0:
                logger.cleanup_old_logs(LOG_CONFIG["keep_days"])

        except KeyboardInterrupt:
            logger.info("\n⛔ 程序被用户中断")
            break
        except Exception as e:
            logger.error(f"主循环发生错误：{e}", exc_info=e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
