"""
Audit logging — writes security and activity events to logs/audit.log.
Never logs full access codes, student writing content, or API keys.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "audit.log")


def _build_logger() -> logging.Logger:
    os.makedirs(_LOG_DIR, exist_ok=True)
    logger = logging.getLogger("co_intel.audit")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    ))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


_logger = _build_logger()


def log_login_success(user_id: int, role: str) -> None:
    _logger.info("event=login_success  user_id=%s  role=%s", user_id, role)


def log_login_failed(code: str) -> None:
    safe = (code[:2] + "****") if len(code) >= 2 else "???"
    _logger.warning("event=login_failed  code_prefix=%s", safe)


def log_dev_reset(user_id: int) -> None:
    _logger.info("event=dev_reset  triggered_by_user_id=%s", user_id)


def log_instructor_views_student(instructor_id: int, student_id: int) -> None:
    _logger.info(
        "event=instructor_views_student  instructor_id=%s  student_id=%s",
        instructor_id, student_id,
    )


def log_session_summary_generated(student_id: int, assignment_id: int) -> None:
    _logger.info(
        "event=session_summary_generated  student_id=%s  assignment_id=%s",
        student_id, assignment_id,
    )


def log_reflection_submitted(student_id: int, assignment_id: int) -> None:
    _logger.info(
        "event=reflection_submitted  student_id=%s  assignment_id=%s",
        student_id, assignment_id,
    )


def log_output_submitted(student_id: int, assignment_id: int) -> None:
    _logger.info(
        "event=output_submitted  student_id=%s  assignment_id=%s",
        student_id, assignment_id,
    )
