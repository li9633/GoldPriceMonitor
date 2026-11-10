"""生成压测用 mock 数据集。

隔离方式：以 goldperf 目录为 cwd 运行，config.py 里的相对路径
(data/prices.db 等) 全部解析到 goldperf/data/，不会碰项目真实数据。

规模（可通过环境变量调整）：
  PERF_DAYS=365      价格历史天数
  PERF_INTERVAL=10   采样间隔（秒）
  PERF_ADVICE=120000 建议记录数
  PERF_NOTIFY=300000 通知发送日志数
  PERF_AI=200000     AI 调用日志数
"""

import os
import random
import sqlite3
import sys
import time
from datetime import timedelta

BACKEND = r"C:\Programer\GoldPriceMonitor\backend"
sys.path.insert(0, BACKEND)

os.makedirs("data", exist_ok=True)
os.makedirs("logs", exist_ok=True)

from utils.time_utils import CHINA_TZ, now  # noqa: E402

DAYS = int(os.getenv("PERF_DAYS", "365"))
INTERVAL = int(os.getenv("PERF_INTERVAL", "10"))
N_ADVICE = int(os.getenv("PERF_ADVICE", "120000"))
N_NOTIFY = int(os.getenv("PERF_NOTIFY", "300000"))
N_AI = int(os.getenv("PERF_AI", "200000"))
N_RATE = int(os.getenv("PERF_RATE", "100000"))

RNG = random.Random(20261109)


def _q(sql, params, n=1000):
    return [sql] * (n // 1000) if False else None


def human(n):
    return f"{n:,}"


def build_settings():
    """用真实 service 初始化系统设置（含各项默认值，触发器配置依赖它）"""
    from service.system_settings_service import SystemSettingsService

    svc = SystemSettingsService()
    cfg = svc.get_monitor_config()
    print(f"  settings 初始化完成 main_symbol={cfg.get('main_symbol')} "
          f"symbols={cfg.get('monitor_symbols')}")
    return svc


def build_prices():
    from mapper.price_mapper import PriceMapper, _resolve_bucket  # noqa: F401

    db = "data/prices.db"
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.remove(db + suffix)

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute(
        "CREATE TABLE prices (id INTEGER PRIMARY KEY, "
        "timestamp INTEGER NOT NULL, symbol TEXT, price REAL)"
    )

    end = int(now().timestamp())
    start = end - DAYS * 86400
    total_ticks = (end - start) // INTERVAL

    specs = [("gds_AUTD", 600.0, 0.03, 560.0, 660.0), ("hf_XAU", 2600.0, 0.18, 2300.0, 2950.0)]

    t0 = time.perf_counter()
    inserted = 0
    for symbol, base, vol, lo, hi in specs:
        price = base
        batch = []
        ts = start
        for i in range(total_ticks):
            price += RNG.gauss(0, vol)
            if price < lo:
                price = lo + abs(RNG.gauss(0, vol))
            elif price > hi:
                price = hi - abs(RNG.gauss(0, vol))
            batch.append((ts, symbol, round(price, 2)))
            ts += INTERVAL
            if len(batch) >= 100_000:
                conn.executemany("INSERT INTO prices (timestamp, symbol, price) VALUES (?,?,?)", batch)
                inserted += len(batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT INTO prices (timestamp, symbol, price) VALUES (?,?,?)", batch)
            inserted += len(batch)
        print(f"  {symbol}: {human(total_ticks)} 行 ({time.perf_counter() - t0:.1f}s)")
    conn.commit()
    conn.close()

    # 用真实 mapper 建索引（与生产 DDL 完全一致）
    t1 = time.perf_counter()
    PriceMapper(db)
    print(f"  索引创建完成 ({time.perf_counter() - t1:.1f}s)")

    conn = sqlite3.connect(db)
    t2 = time.perf_counter()
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()
    print(f"  ANALYZE 完成 ({time.perf_counter() - t2:.1f}s)")

    size = os.path.getsize(db) / 1024 / 1024
    print(f"  prices.db = {size:.0f} MB，共 {human(inserted)} 行")
    return inserted


def build_portfolio():
    from mapper.advice_mapper import AdviceMapper
    from mapper.portfolio_mapper import PortfolioMapper

    for suffix in ("", "-wal", "-shm"):
        p = "data/portfolio.db" + suffix
        if os.path.exists(p):
            os.remove(p)

    PortfolioMapper()
    AdviceMapper()

    end = now()
    conn = sqlite3.connect("data/portfolio.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")

    # 买入批次：两年内 400 笔
    lots = []
    for i in range(400):
        day = end - timedelta(days=RNG.randint(0, 720))
        lots.append((
            "gds_AUTD", day.strftime("%Y-%m-%d"), round(RNG.uniform(1, 20), 2),
            round(RNG.uniform(560, 660), 2), round(RNG.uniform(0, 5), 2),
            "icbc", None, "", 0,
            day.strftime("%Y-%m-%d %H:%M:%S"),
        ))
    conn.executemany(
        "INSERT INTO purchase_lots (symbol, trade_date, grams, price_per_gram, fee, "
        "channel, plan_id, note, is_opening, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        lots,
    )

    sales = []
    for _ in range(150):
        day = end - timedelta(days=RNG.randint(0, 700))
        sales.append((
            "gds_AUTD", day.strftime("%Y-%m-%d"), round(RNG.uniform(1, 15), 2),
            round(RNG.uniform(580, 680), 2), 0.0, "icbc", "",
            day.strftime("%Y-%m-%d %H:%M:%S"),
        ))
    conn.executemany(
        "INSERT INTO sale_records (symbol, sale_date, grams, price_per_gram, fee, "
        "channel, note, created_at) VALUES (?,?,?,?,?,?,?,?)",
        sales,
    )

    for i in range(6):
        conn.execute(
            "INSERT INTO purchase_plans (symbol, target_grams, budget, tranches, tranche_grams, "
            "trigger_policy, start_date, end_date, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("gds_AUTD", 100.0, 60000.0, 5, 20.0,
             '{"type":"drop_pct","pct":2.0}', "2025-01-01", None,
             "active" if i < 2 else "done",
             end.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
        )

    # 建议记录：每 5 分钟一条，共一年
    kinds = ["pre_purchase", "post_purchase", "plan_execution", "review"]
    actions = ["BUY_NOW", "BUY_PARTIAL", "WAIT", "AVOID", "HOLD", "ADD", "TAKE_PROFIT", "STOP_LOSS"]
    statuses = ["delivered"] * 6 + ["suppressed"] * 3 + ["acted", "acknowledged"]
    rows = []
    span = N_ADVICE
    for i in range(span):
        created = end - timedelta(seconds=(span - i) * 300)
        age_days = (end - created).days
        row = (
            created.strftime("%Y-%m-%d %H:%M:%S"),
            kinds[i % len(kinds)] if i % 7 else "review",
            actions[i % len(actions)],
            "gds_AUTD",
            round(RNG.uniform(0, 30), 2) if actions[i % len(actions)] in ("BUY_NOW", "BUY_PARTIAL") else None,
            round(RNG.uniform(560, 600), 2),
            round(RNG.uniform(600, 660), 2),
            round(RNG.uniform(0.3, 0.95), 2),
            "市场处于近 3 个月低位区间，波动率处于历史 30% 分位，建议分批建仓。",
            # 必须满足 models.advice.Signal 的必填字段（id/category/summary），
            # 否则 /api/advice/history 会在 Pydantic 校验处 500 —— 那是造数错，不是服务端问题。
            '[{"id":"long_term_low_3m","category":"market","severity":"notice",'
            '"summary":"现价处于近 3 个月低位区间（+1.2%）",'
            '"metrics":{"pct_from_3m_low":1.2,"min_3m":592.4}}]',
            '{"market":{"current_price":600.12,"avg_24h":601.3},"position":{"total_grams":120.0}}',
            "deepseek-v3" if i % 3 == 0 else "",
            statuses[i % len(statuses)],
            "duplicate" if statuses[i % len(statuses)] == "suppressed" else "",
            None,
            round(RNG.uniform(560, 660), 2),
            # 老记录回访价已回填，最近 35 天留空（模拟待回访）
            round(RNG.uniform(560, 660), 2) if age_days > 1 else None,
            round(RNG.uniform(560, 660), 2) if age_days > 7 else None,
            round(RNG.uniform(560, 660), 2) if age_days > 30 else None,
            created.strftime("%Y-%m-%d %H:%M:%S") if age_days > 30 else None,
            None,
            (1, 7, 30)[i % 3] if i % 7 == 0 else None,
        )
        rows.append(row)
        if len(rows) >= 20_000:
            conn.executemany(
                "INSERT INTO advice_records (created_at, kind, action, symbol, target_grams, "
                "price_band_low, price_band_high, confidence, rationale, signals, evidence, "
                "model_info, status, suppressed_reason, acted_lot_id, price_at_advice, price_t1, "
                "price_t7, price_t30, reviewed_at, subject_lot_id, review_horizon) "
                "VALUES (" + ",".join("?" * 22) + ")",
                rows,
            )
            rows.clear()
    if rows:
        conn.executemany(
            "INSERT INTO advice_records (created_at, kind, action, symbol, target_grams, "
            "price_band_low, price_band_high, confidence, rationale, signals, evidence, "
            "model_info, status, suppressed_reason, acted_lot_id, price_at_advice, price_t1, "
            "price_t7, price_t30, reviewed_at, subject_lot_id, review_horizon) "
            "VALUES (" + ",".join("?" * 22) + ")",
            rows,
        )
    conn.commit()
    conn.close()
    print(f"  portfolio.db: lots=400 sales=150 plans=6 advice={human(span)}")


def build_stats():
    from mapper.ai_stats_mapper import AiStatsMapper
    from mapper.exchange_rate_mapper import ExchangeRateMapper
    from mapper.notification_stats_mapper import NotificationStatsMapper

    AiStatsMapper().init_tables()
    NotificationStatsMapper().init_tables()
    ExchangeRateMapper().init_table()

    end = now()

    conn = sqlite3.connect("data/system_settings.db")
    conn.execute("PRAGMA synchronous=OFF")
    channels = ["email", "wechat_work", "webhook"]
    errors = ["timeout", "auth_failed", "rate_limited", ""]
    rows = []
    for i in range(N_NOTIFY):
        created = end - timedelta(seconds=RNG.randint(0, 365 * 86400))
        ch = channels[i % 3]
        err = errors[i % 4]
        rows.append((
            "warning" if i % 5 else "critical",
            RNG.choice(["gds_AUTD", "hf_XAU"]),
            "黄金", round(RNG.uniform(560, 660), 2),
            "黄金下跌 +1.2%", ch, ch, f"chain{i // 10}",
            i % 3, 3 if i % 3 == 0 else 1,
            0 if err else 1, round(RNG.uniform(50, 3000), 1),
            err, err, created.strftime("%Y-%m-%d %H:%M:%S"),
        ))
        if len(rows) >= 20_000:
            conn.executemany(
                "INSERT INTO notification_send_logs (alert_level, symbol, symbol_name, "
                "current_price, alert_summary, channel_type, channel_name, chain_id, "
                "chain_position, chain_total, success, latency_ms, error_type, error_reason, "
                "created_at) VALUES (" + ",".join("?" * 15) + ")", rows)
            rows.clear()
    if rows:
        conn.executemany(
            "INSERT INTO notification_send_logs (alert_level, symbol, symbol_name, "
            "current_price, alert_summary, channel_type, channel_name, chain_id, "
            "chain_position, chain_total, success, latency_ms, error_type, error_reason, "
            "created_at) VALUES (" + ",".join("?" * 15) + ")", rows)
    conn.commit()

    rows = []
    for i in range(N_RATE):
        ts = int(end.timestamp()) - RNG.randint(0, 730 * 86400)
        rows.append((round(RNG.uniform(7.0, 7.4), 5), ts, "exchangerate_dev", "primary", ts))
        if len(rows) >= 20_000:
            conn.executemany(
                "INSERT INTO exchange_rate_history (rate, timestamp, source, provider, data_updated_at) "
                "VALUES (?,?,?,?,?)", rows)
            rows.clear()
    if rows:
        conn.executemany(
            "INSERT INTO exchange_rate_history (rate, timestamp, source, provider, data_updated_at) "
            "VALUES (?,?,?,?,?)", rows)
    conn.commit()

    # AI 调用日志
    conn2 = sqlite3.connect("data/model_pool.db")
    conn2.execute("PRAGMA synchronous=OFF")
    providers = [("deepseek", "deepseek-v3"), ("moonshot", "kimi-k2"), ("openai", "gpt-4o-mini")]
    rows = []
    for i in range(N_AI):
        prov, model = providers[i % 3]
        call_time = end - timedelta(seconds=RNG.randint(0, 365 * 86400))
        success = 0 if i % 17 == 0 else 1
        pt, ct = RNG.randint(400, 2500), RNG.randint(100, 900)
        rows.append((
            prov, model, call_time.strftime("%Y-%m-%d %H:%M:%S"), success,
            RNG.randint(300, 12000), "" if success else RNG.choice(["timeout", "429", "500"]),
            1 if i % 6 == 0 else 0, "", '{"ok":true}' if success else None,
            pt, ct, pt + ct, call_time.strftime("%Y-%m-%d %H:%M:%S"),
        ))
        if len(rows) >= 20_000:
            conn2.executemany(
                "INSERT INTO ai_call_logs (provider_name, model_name, call_time, success, "
                "latency_ms, error_reason, from_cache, triggered_alerts, raw_response, "
                "prompt_tokens, completion_tokens, total_tokens, created_at) "
                "VALUES (" + ",".join("?" * 13) + ")", rows)
            rows.clear()
    if rows:
        conn2.executemany(
            "INSERT INTO ai_call_logs (provider_name, model_name, call_time, success, "
            "latency_ms, error_reason, from_cache, triggered_alerts, raw_response, "
            "prompt_tokens, completion_tokens, total_tokens, created_at) "
            "VALUES (" + ",".join("?" * 13) + ")", rows)
    conn2.commit()
    conn2.close()
    conn.close()
    print(f"  notification_send_logs={human(N_NOTIFY)} exchange_rate={human(N_RATE)} "
          f"ai_call_logs={human(N_AI)}")


def main():
    t0 = time.perf_counter()
    print(f"=== 造数：{DAYS} 天 × {INTERVAL}s 采样，建议 {human(N_ADVICE)} 条 ===")
    print("[1/4] 系统设置")
    build_settings()
    print("[2/4] 价格历史")
    build_prices()
    print("[3/4] 持仓与建议")
    build_portfolio()
    print("[4/4] 统计日志")
    build_stats()
    total = sum(os.path.getsize(os.path.join("data", f)) for f in os.listdir("data"))
    print(f"\n=== 完成，data/ 共 {total / 1024 / 1024:.0f} MB，"
          f"耗时 {time.perf_counter() - t0:.1f}s ===")
    for f in sorted(os.listdir("data")):
        print(f"  {f:<26} {os.path.getsize(os.path.join('data', f)) / 1024 / 1024:>7.1f} MB")


if __name__ == "__main__":
    main()
