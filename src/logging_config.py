"""
Structured logging configuration for the Vision PR AI project.
Provides machine-readable logging in production and human-readable logging in development,
with rich contextual information and appropriate log levels.
"""

import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union, cast


# Type variable for decorator
F = TypeVar('F', bound=Callable[..., Any])


# Default log format
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Default log level from environment or INFO
DEFAULT_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# App environment (development or production)
APP_ENV = os.environ.get("APP_ENV", "development").lower()

# Log directory
LOG_DIR = os.environ.get("LOG_DIR", "logs")

# Maximum log file size (10 MB default)
MAX_LOG_SIZE = int(os.environ.get("MAX_LOG_SIZE", 10 * 1024 * 1024))

# Maximum number of backup log files
BACKUP_COUNT = int(os.environ.get("BACKUP_LOG_COUNT", 5))

# Sensitive keys that should be redacted in logs
SENSITIVE_KEYS = [
    "api_key", "token", "password", "secret", "authorization", 
    "access_token", "auth", "credentials"
]


class StructuredLogRecord(logging.LogRecord):
    """Enhanced LogRecord that includes structured data for context."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context = getattr(self, "context", {})
        self.timestamp = datetime.utcnow().isoformat() + "Z"
        
        # Add trace info if exception
        if self.exc_info:
            self.traceback = traceback.format_exception(*self.exc_info)
        else:
            self.traceback = None


class JsonFormatter(logging.Formatter):
    """
    Formatter that outputs JSON formatted logs for machine consumption.
    Each log message is a single line JSON object with structured context.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a JSON string."""
        record = cast(StructuredLogRecord, record)
        log_obj = {
            "timestamp": record.timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": record.thread,
            "process": record.process
        }
        
        # Add context if available
        if hasattr(record, "context") and record.context:
            context = self._redact_sensitive_info(record.context)
            log_obj["context"] = context
        
        # Add traceback if available
        if hasattr(record, "traceback") and record.traceback:
            log_obj["traceback"] = record.traceback
        
        return json.dumps(log_obj)
    
    def _redact_sensitive_info(self, obj: Any) -> Any:
        """Redact sensitive information from logs."""
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                # Check if key contains any sensitive words
                if any(sensitive_key in key.lower() for sensitive_key in SENSITIVE_KEYS):
                    result[key] = "[REDACTED]"
                else:
                    result[key] = self._redact_sensitive_info(value)
            return result
        elif isinstance(obj, list):
            return [self._redact_sensitive_info(item) for item in obj]
        return obj


class HumanReadableFormatter(logging.Formatter):
    """
    Formatter that outputs human-readable logs for development.
    Includes context in a readable format.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the log record in a human-readable format."""
        record = cast(StructuredLogRecord, record)
        log_str = super().format(record)
        
        # Add context as a formatted string if available
        if hasattr(record, "context") and record.context:
            context = self._redact_sensitive_info(record.context)
            context_str = "\n".join(f"    {k}: {v}" for k, v in context.items())
            log_str += f"\n  Context:\n{context_str}"
        
        return log_str
    
    def _redact_sensitive_info(self, obj: Any) -> Any:
        """Redact sensitive information from logs."""
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                # Check if key contains any sensitive words
                if any(sensitive_key in key.lower() for sensitive_key in SENSITIVE_KEYS):
                    result[key] = "[REDACTED]"
                else:
                    result[key] = self._redact_sensitive_info(value)
            return result
        elif isinstance(obj, list):
            return [self._redact_sensitive_info(item) for item in obj]
        return obj


class ContextAdapter(logging.LoggerAdapter):
    """
    Logger adapter that allows passing context with each log call.
    Merges the context into the log record.
    """
    
    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        """Process the log message to add context."""
        if "context" not in kwargs:
            kwargs["context"] = {}
        elif not isinstance(kwargs["context"], dict):
            kwargs["context"] = {"value": kwargs["context"]}
        
        if self.extra:
            kwargs["context"].update(self.extra)
        
        return msg, kwargs


def with_context(func: F) -> F:
    """
    Decorator that adds function arguments as context to log messages
    and logs entry/exit from the function.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        
        # Create context from function arguments
        context = {
            "function": func.__name__,
            "args": [str(arg) for arg in args],
            "kwargs": {k: str(v) for k, v in kwargs.items() if not any(
                sensitive in k.lower() for sensitive in SENSITIVE_KEYS)}
        }
        
        # Log function entry
        logger.debug(f"Entering {func.__name__}", context=context)
        
        try:
            # Call the original function
            start_time = time.time()
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            # Log function exit
            exit_context = {**context, "execution_time_ms": int(execution_time * 1000)}
            logger.debug(f"Exiting {func.__name__}", context=exit_context)
            
            return result
        except Exception as e:
            # Log exception with context
            error_context = {**context, "error": str(e), "error_type": type(e).__name__}
            logger.exception(f"Error in {func.__name__}", context=error_context)
            raise
    
    return cast(F, wrapper)


def setup_logging(module_name: str = "vision-prai", 
                  log_level: str = DEFAULT_LOG_LEVEL) -> logging.Logger:
    """
    Set up logging with appropriate formatters and handlers.
    
    Args:
        module_name: The name of the module
        log_level: The log level to use
        
    Returns:
        Configured logger instance
    """
    # Create logger
    logger = logging.getLogger(module_name)
    
    # Set log level
    level = getattr(logging, log_level, logging.INFO)
    logger.setLevel(level)
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Set up console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # Create formatters
    if APP_ENV == "production":
        formatter = JsonFormatter()
    else:
        formatter = HumanReadableFormatter(DEFAULT_LOG_FORMAT)
    
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Set up file handler if log directory exists or can be created
    try:
        log_dir = Path(LOG_DIR)
        log_dir.mkdir(exist_ok=True, parents=True)
        
        log_file = log_dir / f"{module_name}.log"
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=MAX_LOG_SIZE, 
            backupCount=BACKUP_COUNT
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except (OSError, IOError) as e:
        # Don't fail initialization if log file can't be created
        console_handler.setLevel(logging.WARNING)
        logger.warning(f"Could not set up log file: {e}")
    
    # Customize record factory to use our StructuredLogRecord
    old_factory = logging.getLogRecordFactory()
    
    def record_factory(*args, **kwargs):
        record = StructuredLogRecord(*args, **kwargs)
        return record
    
    logging.setLogRecordFactory(record_factory)
    
    return logger


def get_logger(name: Optional[str] = None) -> ContextAdapter:
    """
    Get a logger instance with context support.
    
    Args:
        name: Logger name (defaults to caller's module name)
        
    Returns:
        Context-aware logger
    """
    if name is None:
        # Get the module name of the caller
        frame = sys._getframe(1)
        name = frame.f_globals.get('__name__', 'vision-prai')
    
    logger = setup_logging(name)
    return ContextAdapter(logger, {})