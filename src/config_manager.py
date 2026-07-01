"""設定ファイル(config.yaml)を読み込み、設定値を提供するモジュール。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class GmailConfig:
    target_address: str
    credentials_path: str
    token_path: str
    scopes: list[str]


@dataclass(frozen=True)
class WordPressConfig:
    url: str
    username: str
    application_password: str
    default_status: str
    default_category: str


@dataclass(frozen=True)
class PathsConfig:
    template: str
    temp_dir: str
    image_dir: str
    log_file: str
    history_file: str


@dataclass(frozen=True)
class RetryConfig:
    max_count: int
    initial_wait_seconds: int
    backoff: str


@dataclass(frozen=True)
class AppConfig:
    gmail: GmailConfig
    wordpress: WordPressConfig
    paths: PathsConfig
    retry: RetryConfig
    log_level: str


class ConfigManager:
    """config.yaml を読み込み AppConfig を提供する。"""

    def __init__(self, config_path: str | Path) -> None:
        self._config_path = Path(config_path)
        self._config: AppConfig | None = None

    def load(self) -> AppConfig:
        """設定ファイルを読み込んで AppConfig を返す。ファイルが存在しない場合は FileNotFoundError を送出する。"""
        if not self._config_path.exists():
            raise FileNotFoundError(f"設定ファイルが見つかりません: {self._config_path}")

        with self._config_path.open(encoding="utf-8") as f:
            raw: dict = yaml.safe_load(f)

        g = raw["gmail"]
        w = raw["wordpress"]
        p = raw["paths"]
        r = raw.get("retry", {})
        log_level = raw.get("logging", {}).get("level", "INFO")

        self._config = AppConfig(
            gmail=GmailConfig(
                target_address=g["target_address"],
                credentials_path=g["credentials_path"],
                token_path=g["token_path"],
                scopes=list(g["scopes"]),
            ),
            wordpress=WordPressConfig(
                url=w["url"],
                username=w["username"],
                application_password=w["application_password"],
                default_status=w["default_status"],
                default_category=w["default_category"],
            ),
            paths=PathsConfig(
                template=p["template"],
                temp_dir=p["temp_dir"],
                image_dir=p["image_dir"],
                log_file=p["log_file"],
                history_file=p["history_file"],
            ),
            retry=RetryConfig(
                max_count=int(r.get("max_count", 3)),
                initial_wait_seconds=int(r.get("initial_wait_seconds", 2)),
                backoff=r.get("backoff", "exponential"),
            ),
            log_level=log_level,
        )
        return self._config

    @property
    def config(self) -> AppConfig:
        """読み込み済みの設定を返す。load() 前に呼んだ場合は RuntimeError を送出する。"""
        if self._config is None:
            raise RuntimeError("load() を先に呼び出してください。")
        return self._config
