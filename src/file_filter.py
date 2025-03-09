#!/usr/bin/env python3
"""
File filtering module for the AI PR Reviewer.
Provides functionality to filter files from the review based on patterns and size.
"""

import os
import fnmatch
from typing import Dict, List, Any, Optional

from src.custom_exceptions import InvalidConfigurationError
from src.logging_config import get_logger, with_context

# Set up logger
logger = get_logger(__name__)


class FileFilter:
    """
    A class to filter files from the PR review based on configured patterns and size limits.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the FileFilter with filtering configuration.
        
        Args:
            config: The configuration dictionary containing review settings
        """
        self.logger = get_logger(__name__)
        self.enabled = False
        self.exclude_patterns = []
        self.max_file_size = 0  # 0 means no limit
        
        self._load_config(config)
        
        self.logger.debug("FileFilter initialized", 
                         context={
                             "enabled": self.enabled,
                             "exclude_patterns": self.exclude_patterns,
                             "max_file_size": self.max_file_size
                         })

    @with_context
    def _load_config(self, config: Dict[str, Any]) -> None:
        """
        Load file filtering configuration.
        
        Args:
            config: The configuration dictionary
        """
        review_config = config.get("review", {})
        filter_config = review_config.get("file_filtering", {})
        
        self.enabled = filter_config.get("enabled", False)
        
        if not self.enabled:
            self.logger.info("File filtering is disabled")
            return
        
        # Load exclude patterns
        self.exclude_patterns = filter_config.get("exclude_patterns", [])
        if not isinstance(self.exclude_patterns, list):
            self.logger.warning("exclude_patterns is not a list, disabling file filtering",
                               context={"exclude_patterns": self.exclude_patterns})
            self.enabled = False
            return
        
        # Load max file size (in KB)
        self.max_file_size = filter_config.get("max_file_size", 0)
        if not isinstance(self.max_file_size, (int, float)):
            self.logger.warning("max_file_size is not a number, using default (0)",
                               context={"max_file_size": self.max_file_size})
            self.max_file_size = 0
        
        self.logger.info("File filtering configuration loaded", 
                        context={
                            "enabled": self.enabled,
                            "exclude_patterns_count": len(self.exclude_patterns),
                            "max_file_size": self.max_file_size
                        })

    @with_context
    def should_exclude_file(self, file_info: Dict[str, Any]) -> bool:
        """
        Determine if a file should be excluded from the review based on patterns and size.
        
        Args:
            file_info: Dictionary containing file information (filename, size, etc.)
            
        Returns:
            True if the file should be excluded, False otherwise
        """
        if not self.enabled:
            return False
        
        filename = file_info.get("filename", "")
        
        # Check for pattern matches
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(filename, pattern):
                self.logger.debug(f"Excluding file due to pattern match: {filename}",
                                context={"filename": filename, "pattern": pattern})
                return True
        
        # Check file size if available and max_file_size is set
        if self.max_file_size > 0 and "size" in file_info:
            # Convert size from bytes to KB
            size_kb = file_info["size"] / 1024
            if size_kb > self.max_file_size:
                self.logger.debug(f"Excluding file due to size: {filename}",
                                context={"filename": filename, 
                                        "size_kb": size_kb, 
                                        "max_size_kb": self.max_file_size})
                return True
        
        return False

    @with_context
    def filter_files(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter a list of files based on configured patterns and size limits.
        
        Args:
            files: List of file information dictionaries from GitHub API
            
        Returns:
            Filtered list of files to include in the review
        """
        if not self.enabled or not files:
            return files
        
        original_count = len(files)
        filtered_files = [file for file in files if not self.should_exclude_file(file)]
        excluded_count = original_count - len(filtered_files)
        
        if excluded_count > 0:
            self.logger.info(f"Excluded {excluded_count} files from review",
                           context={"original_count": original_count, 
                                   "filtered_count": len(filtered_files)})
        
        return filtered_files