"""安全回归测试：SQL 注入、路径穿越、API 404 被 SPA 兜底吞掉。

这三个问题都是真实存在并且被 PoC 验证过的，不是理论风险：

1. `build_date_filter` 曾把 `start_date` 直接拼进 SQL：
   `start_date=2020-01-01' OR '1'='1` 可以短路过滤条件，
   `' UNION SELECT ...` 还能拼出可执行的子句读到别的表。
2. `serve_spa` 曾直接 `DIST_DIR / full_path`：
   请求 `/../../backend/data/prices.db` 会把整个数据库（含加密的 API Key）吐出去。
3. 未知的 `/api/xxx` 被 `/{full_path:path}` 兜住，返回首页 HTML 或 500。
"""

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from mapper.notification_stats_mapper import NotificationStatsMapper
from utils.date_filter import InvalidDateError, build_date_filter


class TestDateFilterInjection:
    """日期参数必须严格校验，否则就是 SQL 注入入口"""

    @pytest.mark.parametrize(
        "payload",
        [
            "2020-01-01' OR '1'='1",
            "2020-01-01' OR 1=1 --",
            "2020-01-01' UNION SELECT 1 --",
            "2020-01-01'; DROP TABLE notification_send_logs; --",
            "'; --",
            "2020-01-01' AND (SELECT 1)",
            "2020-01-01\n",
            "2020-01-01 00:00:00",
        ],
    )
    def test_start_date_rejects_injection(self, payload: str) -> None:
        with pytest.raises(InvalidDateError):
            build_date_filter(start_date=payload)

    @pytest.mark.parametrize(
        "payload",
        ["2020-01-01' OR '1'='1", "2020-01-01'--", "abc'"],
    )
    def test_end_date_rejects_injection(self, payload: str) -> None:
        with pytest.raises(InvalidDateError):
            build_date_filter(end_date=payload)

    @pytest.mark.parametrize("payload", ["2026-13-45", "2026-02-30", "0000-00-00"])
    def test_rejects_impossible_dates(self, payload: str) -> None:
        with pytest.raises(InvalidDateError):
            build_date_filter(start_date=payload)

    def test_empty_string_means_not_provided(self) -> None:
        """前端清空日期框会传空串，应当当作「没传」而不是 400"""
        assert build_date_filter(start_date="") == build_date_filter()
        assert build_date_filter(end_date="") == build_date_filter()

    def test_valid_date_still_builds_sql(self) -> None:
        sql = build_date_filter(start_date="2026-01-01", end_date="2026-01-31")
        assert sql == (
            "created_at >= '2026-01-01' AND created_at < date('2026-01-31', '+1 day')"
        )

    def test_time_column_must_be_identifier(self) -> None:
        with pytest.raises(ValueError):
            build_date_filter(start_date="2026-01-01", time_column="created_at; DROP")

    def test_injected_payload_cannot_widen_result_set(self, tmp_path) -> None:
        """端到端确认：带注入的输入根本走不到 SQL，正常输入行为不变"""
        db = tmp_path / "inj.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE notification_send_logs (id INTEGER, created_at TEXT, success INT)"
        )
        conn.executemany(
            "INSERT INTO notification_send_logs VALUES (?,?,?)",
            [(1, "2020-06-01 00:00:00", 1), (2, "2026-11-09 10:00:00", 1)],
        )
        conn.commit()

        with pytest.raises(InvalidDateError):
            build_date_filter(start_date="2020-01-01' OR '1'='1")
        conn.close()


class TestSpaRouteHardening:
    """静态文件路由：路径穿越 / API 404 / dist 缺失"""

    @pytest.fixture
    def dist_env(self, tmp_path, monkeypatch):
        import app as app_module

        dist = (tmp_path / "dist").resolve()
        dist.mkdir()
        (dist / "index.html").write_text("<html>index</html>", encoding="utf-8")
        (dist / "assets").mkdir()
        (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP-SECRET-DATA", encoding="utf-8")
        monkeypatch.setattr(app_module, "DIST_DIR", dist)
        return app_module, dist, secret

    def test_serves_file_inside_dist(self, dist_env) -> None:
        app_module, dist, _ = dist_env
        resp = app_module.serve_spa("assets/app.js")
        assert Path(resp.path) == dist / "assets" / "app.js"

    @pytest.mark.parametrize(
        "payload",
        [
            "../secret.txt",
            "../../secret.txt",
            "assets/../../secret.txt",
            "./../secret.txt",
        ],
    )
    def test_path_traversal_falls_back_to_index(self, dist_env, payload: str) -> None:
        """穿越尝试一律退回 index.html，绝不返回 dist 之外的文件"""
        app_module, dist, _ = dist_env
        resp = app_module.serve_spa(payload)
        assert Path(resp.path) == dist / "index.html"
        assert Path(resp.path).read_text(encoding="utf-8") != "TOP-SECRET-DATA"

    def test_unknown_route_serves_index(self, dist_env) -> None:
        app_module, dist, _ = dist_env
        resp = app_module.serve_spa("dashboard")
        assert Path(resp.path) == dist / "index.html"

    @pytest.mark.parametrize("path", ["api", "api/unknown", "api/foo/bar"])
    def test_api_paths_return_404(self, dist_env, path: str) -> None:
        """打错的 API 不能返回首页 HTML，否则前端会把 HTML 当 JSON 解析"""
        app_module, _, _ = dist_env
        with pytest.raises(HTTPException) as exc:
            app_module.serve_spa(path)
        assert exc.value.status_code == 404

    def test_missing_dist_returns_404_not_500(self, tmp_path, monkeypatch) -> None:
        import app as app_module

        monkeypatch.setattr(app_module, "DIST_DIR", (tmp_path / "nope").resolve())
        with pytest.raises(HTTPException) as exc:
            app_module.serve_spa("anything")
        assert exc.value.status_code == 404
        assert "dist" in str(exc.value.detail)


class TestTopFailuresPercentage:
    """失败原因占比的分母必须是「真实失败总数」，不是 top5 之和"""

    def _seed(self, db: Path, counts: dict[str, int]) -> NotificationStatsMapper:
        mapper = NotificationStatsMapper(str(db))
        mapper.init_tables()
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(db)
        rows = []
        rid = 0
        for error_type, n in counts.items():
            for _ in range(n):
                rid += 1
                rows.append(
                    (rid, "gds_AUTD", "email", 0, error_type, f"{error_type}-样例", now_str)
                )
        conn.executemany(
            "INSERT INTO notification_send_logs (id, symbol, channel_type, success, "
            "error_type, error_reason, created_at) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()
        return mapper

    def test_percentage_uses_true_total(self, tmp_path) -> None:
        # 7 种错误，前 5 名合计 22，真实总数 24 —— 旧实现分母是 22
        counts = {"a": 10, "b": 5, "c": 3, "d": 2, "e": 2, "f": 1, "g": 1}
        mapper = self._seed(tmp_path / "notify.db", counts)
        items = mapper.get_top_failures()
        assert len(items) == 5
        top = items[0]
        assert top["fail_count"] == 10
        assert top["percentage"] == pytest.approx(round(100 * 10 / 24, 1))

    def test_percentages_never_exceed_100(self, tmp_path) -> None:
        counts = {"a": 10, "b": 5, "c": 3, "d": 2, "e": 2, "f": 1, "g": 1}
        mapper = self._seed(tmp_path / "notify2.db", counts)
        items = mapper.get_top_failures()
        assert sum(item["percentage"] for item in items) <= 100.0

    def test_empty_result_is_safe(self, tmp_path) -> None:
        mapper = self._seed(tmp_path / "empty.db", {})
        assert mapper.get_top_failures() == []
