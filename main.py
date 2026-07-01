"""エントリーポイント。"""

from __future__ import annotations

import sys

from src.application import create_application


def main() -> None:
    app = create_application()
    app.run()


if __name__ == "__main__":
    main()
