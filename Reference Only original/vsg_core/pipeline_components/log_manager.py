# vsg_core/pipeline_components/log_manager.py
"""
Log management component.

Handles logger setup, file handlers, and log output routing.
"""

import logging
from collections.abc import Callable
from pathlib import Path


class LogManager:
    """Manages logging setup and cleanup for jobs."""

    @staticmethod
    def setup_job_log(
        job_name: str, log_dir: Path, gui_log_callback: Callable[[str], None]
    ) -> tuple[logging.Logger, logging.FileHandler, Callable[[str], None]]:
        """
        Sets up logging for a job.

        Args:
            job_name: Name of the job (used for log filename and logger name)
            log_dir: Directory where log file will be created
            gui_log_callback: Callback to send log messages to GUI

        Returns:
            Tuple of (logger, handler, log_to_all_function)
            - logger: Logger instance for this job
            - handler: File handler (needed for cleanup)
            - log_to_all: Function to log to both file and GUI
        """
        log_path = log_dir / f"{job_name}.log"
        logger = logging.getLogger(f"job_{job_name}")
        logger.setLevel(logging.INFO)

        # Remove any existing handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # Create file handler
        handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.propagate = False

        # Create unified log function
        def log_to_all(message: str):
            logger.info(message.strip())
            gui_log_callback(message)

        return logger, handler, log_to_all

    @staticmethod
    def cleanup_log(logger: logging.Logger, handler: logging.FileHandler):
        """
        Cleans up logger and handler resources.

        Args:
            logger: Logger instance to clean up
            handler: File handler to close
        """
        handler.close()
        logger.removeHandler(handler)
