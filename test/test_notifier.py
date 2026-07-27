
import sys
from pathlib import Path

current_dir = str(Path(__file__).resolve().parent)
project_root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, project_root)

from notifier import Notifier

# 创建通知器实例
notifier = Notifier()

# 发送测试报警
notifier.send_alert(
    symbol="gds_AUTD",
    current_price=915.5,
    alert_messages=["价格低于阈值 915.0", "24 小时相对低点"]
)