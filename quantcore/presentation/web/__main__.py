"""localhost 啟動：uv run python -m quantcore.presentation.web"""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("quantcore.presentation.web.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
