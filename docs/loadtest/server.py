"""压测服务端：以 goldperf 为 cwd 启动 uvicorn，DB 路径全部落在 ./data。

启动前需要先跑 build_data.py 生成数据集。
"""

import os
import sys

BACKEND = r"C:\Programer\GoldPriceMonitor\backend"
sys.path.insert(0, BACKEND)

import uvicorn  # noqa: E402

from app import app  # noqa: E402

PORT = int(os.getenv("PERF_PORT", "8765"))

if __name__ == "__main__":
    print(f"[server] cwd={os.getcwd()} port={PORT}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning", access_log=False)
