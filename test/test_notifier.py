# run_notifier.py
import sys
import os
import re

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..'))
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
