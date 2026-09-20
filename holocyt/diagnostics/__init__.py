"""Журнал, самодиагностика и разбор ошибок."""

from .logs import get_logger, setup_logging, log_path
from .errors import UserError, describe

__all__ = ["get_logger", "setup_logging", "log_path", "UserError", "describe"]
