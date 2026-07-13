"""密鑰讀取（設計文件 §5.2）。

優先讀 os.environ；若專案根有 .env 則先載入（python-dotenv）。
密鑰絕不寫入任何進版控檔案或 log。
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# import 時載入一次 .env（若存在）；不覆蓋既有環境變數。
load_dotenv(override=False)


class MissingSecretError(RuntimeError):
    """要求的密鑰不存在時拋出。"""


def get_secret(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingSecretError(
            f"缺少密鑰 {name}。請在專案根建立 .env（可複製 .env.example）"
            f" 並設定 {name}=…，或於 shell export {name}。"
        )
    return value
