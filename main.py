import time
from datetime import datetime

from config import (
    AI_CONFIG,
    CHECK_INTERVAL,
    CHINA_TZ,
    LOG_CONFIG,
    MONITOR_SYMBOLS,
    SYMBOL,
)
from mapper.price_mapper import PriceMapper
from service.ai_service import AIAnalysisService
from service.alert_service import AlertService
from service.history_import_service import init_historical_data
from service.notification_service import NotificationService
from service.price_service import PriceService
from utils.logger import get_logger


def main():
    # 初始化日志
    logger = get_logger("GoldPriceMonitor")

    logger.info("=" * 50)
    logger.info("黄金价格智能监控系统启动")
    logger.info("=" * 50)

    # 0. 初始化历史数据（首次运行或数据不足时自动导入）
    logger.info("正在初始化历史数据...")
    init_historical_data()

    logger.info(f"监控品种：{SYMBOL}")
    logger.info(f"检查间隔：{CHECK_INTERVAL} 秒")
    logger.info("=" * 50)

    # 初始化各层模块（依赖注入）
    price_mapper = PriceMapper()
    price_service = PriceService()
    alert_service = AlertService(SYMBOL, price_mapper)
    notification_service = NotificationService()
    ai_service = AIAnalysisService()
    ai_check_interval = AI_CONFIG.get("check_interval_checks", 30)

    if ai_service.enabled:
        logger.info(f"AI 分析已启用，每 {ai_check_interval} 次检查调用一次")
    else:
        logger.info("AI 分析未启用（请设置环境变量 GLM_API_KEY）")

    # 显示当前数据库状态
    try:
        db_count = price_mapper.get_record_count(SYMBOL)
        logger.info(f"当前历史记录数：{db_count} 条")
    except Exception as e:
        logger.error(f"查询数据库失败：{e}", exc_info=e)

    logger.info("=" * 50)
    logger.info("开始实时监控...\n")

    # 记录启动时间
    start_time = datetime.now(CHINA_TZ)
    check_count = 0
    alert_count = 0

    while True:
        try:
            # 1. 获取当前价格
            prices_data = price_service.fetch_all_gold_prices(MONITOR_SYMBOLS)

            # 检查主监控品种是否获取成功
            main_symbol_data = prices_data.get(SYMBOL)
            if not main_symbol_data:
                logger.warning(
                    f"[{datetime.now(CHINA_TZ)}] 获取主品种 {SYMBOL} 价格失败，等待下次检查")
                time.sleep(CHECK_INTERVAL)
                continue

            current_price = main_symbol_data['price']
            logger.debug(
                f"[{datetime.now(CHINA_TZ).strftime('%H:%M:%S')}] {main_symbol_data['name']} 价格：{current_price}")

            # 2. 保存到历史记录
            price_mapper.save_price(SYMBOL, current_price)

            london_data = prices_data.get('hf_XAU')
            if london_data:
                price_mapper.save_price('hf_XAU', london_data['price'])

            # 3. 检查报警条件 (基于主品种)
            alerts, suggestions = alert_service.check_all_conditions(
                current_price)

            # 4. 如果有报警，发送通知
            extra_info = {}
            london_data_for_alert = prices_data.get('hf_XAU')
            if london_data_for_alert:
                extra_info['london_gold_usd'] = london_data_for_alert['price']
                extra_info['london_gold_cny'] = london_data_for_alert.get(
                    'converted_cny_price', 0)

            if alerts:
                alert_count += 1
                logger.warning(f"触发 {len(alerts)} 条报警")
                for alert in alerts:
                    logger.warning(f"  └─ {alert}")

                notification_service.send_alert(
                    SYMBOL,
                    current_price,
                    alerts,
                    suggestions,
                    extra_info=extra_info
                )
            else:
                logger.debug("  └─ 无报警")

            # 5. AI 分析（每 N 次检查调用一次）
            if check_count % ai_check_interval == 0 and ai_service.enabled:
                logger.info("正在调用 AI 分析行情...")
                snapshot = price_mapper.get_check_snapshot(SYMBOL)
                london_cny = london_data.get('converted_cny_price') if london_data else None
                london_usd = london_data['price'] if london_data else None

                ai_result = ai_service.analyze(
                    SYMBOL, current_price, snapshot, london_cny, london_usd)
                if ai_result and ai_result.get("should_alert"):
                    alert_count += 1
                    urgency = ai_result.get('urgency', 'unknown')
                    analysis_preview = ai_result.get('analysis', '')[:50]
                    logger.warning(f"AI 建议通知（{urgency}）：{analysis_preview}...")

                    ai_alerts = [ai_result.get("analysis", "")]
                    ai_suggestions = ai_result.get("suggestions", [])

                    ai_extra_info = dict(extra_info)
                    ai_extra_info["ai_model_info"] = (
                        f"{ai_result.get('provider', '')}/{ai_result.get('model', '')}")

                    notification_service.send_alert(
                        SYMBOL, current_price, ai_alerts, ai_suggestions,
                        extra_info=ai_extra_info)

            check_count += 1

            # 每 100 次检查输出统计
            if check_count % 100 == 0:
                run_time = (datetime.now(CHINA_TZ) - start_time).total_seconds() / 60
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
            logger.info("\n程序被用户中断")
            break
        except Exception as e:
            logger.error(f"主循环发生错误：{e}", exc_info=e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()