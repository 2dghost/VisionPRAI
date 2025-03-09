#!/usr/bin/env python3
"""
Comment extraction module for the AI PR Reviewer.
Provides functionality to extract line-specific comments from review text.
"""

import re
import os
import yaml
import logging
from typing import Dict, List, Tuple, Any, Optional, Pattern

from src.custom_exceptions import (
    CommentExtractionError,
    DiffParsingError,
    InvalidConfigurationError,
    MissingConfigurationError
)
from src.logging_config import get_logger, with_context

# Set up logger
logger = get_logger(__name__)


class CommentExtractor:
    """
    A class to extract line-specific comments from AI review text.
    Follows the Single Responsibility Principle by separating pattern matching,
    comment extraction, and validation into distinct methods.
    """

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize the CommentExtractor with patterns from configuration.
        
        Args:
            config_path: Path to the configuration file
            
        Raises:
            MissingConfigurationError: If comment extraction configuration is missing
            InvalidConfigurationError: If patterns are incorrectly configured
        """
        self.logger = get_logger(__name__)
        self.config_path = config_path
        
        # Default patterns, will be overridden if present in config
        self.patterns = [
            r'In\s+([^,]+),\s+line\s+(\d+):', 
            r'([^:\s]+):(\d+):',
            r'([^:\s]+) line (\d+):',
            r'In file `([^`]+)` at line (\d+)'
        ]
        
        # Load patterns from configuration
        self._load_patterns()
        
        # Precompile regex patterns for efficiency
        self.compiled_patterns = [re.compile(pattern, re.MULTILINE) for pattern in self.patterns]
        
        self.logger.debug("CommentExtractor initialized", 
                          context={"patterns_count": len(self.patterns)})

    @with_context
    def _load_patterns(self) -> None:
        """
        Load comment extraction patterns from configuration.
        
        Raises:
            MissingConfigurationError: If the config file doesn't exist
            InvalidConfigurationError: If the patterns are not correctly defined
        """
        if not os.path.exists(self.config_path):
            error_msg = f"Config file not found: {self.config_path}"
            self.logger.error(error_msg)
            raise MissingConfigurationError("config_file", error_code=1001)
        
        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            error_msg = f"Failed to parse YAML in config file: {e}"
            self.logger.error(error_msg)
            raise InvalidConfigurationError("config_file", f"Invalid YAML format: {e}", error_code=1002)
        
        # Check for comment extraction patterns in config
        extraction_config = config.get("review", {}).get("comment_extraction", {})
        custom_patterns = extraction_config.get("patterns")
        
        if custom_patterns:
            if not isinstance(custom_patterns, list):
                error_msg = "Comment extraction patterns must be a list"
                self.logger.error(error_msg)
                raise InvalidConfigurationError("comment_extraction.patterns", 
                                              "Must be a list of regex patterns", 
                                              error_code=1002)
            self.patterns = custom_patterns
            self.logger.info("Loaded custom comment extraction patterns", 
                            context={"patterns_count": len(custom_patterns)})
        else:
            self.logger.info("Using default comment extraction patterns", 
                            context={"patterns_count": len(self.patterns)})

    @with_context
    def validate_file_path(self, file_path: str, file_line_map: Dict[str, List[Tuple[int, str]]]) -> bool:
        """
        Validate that a file path exists in the diff.
        
        Args:
            file_path: Path to the file
            file_line_map: Mapping of files to line numbers from the diff
            
        Returns:
            True if the file path exists in the diff, False otherwise
        """
        if not file_path:
            self.logger.warning("Empty file path received during validation")
            return False
        
        valid = file_path in file_line_map
        if not valid:
            self.logger.debug(f"File path not found in diff: {file_path}", 
                             context={"file_path": file_path, "available_files": list(file_line_map.keys())})
        
        return valid

    @with_context
    def validate_line_number(self, file_path: str, line_num: int, 
                            file_line_map: Dict[str, List[Tuple[int, str]]]) -> bool:
        """
        Validate that a line number exists in the specified file in the diff.
        
        Args:
            file_path: Path to the file
            line_num: Line number to validate
            file_line_map: Mapping of files to line numbers from the diff
            
        Returns:
            True if the line number is valid for the file, False otherwise
        """
        if not self.validate_file_path(file_path, file_line_map):
            return False
        
        valid_lines = [line for line, _ in file_line_map[file_path]]
        valid = line_num in valid_lines
        
        if not valid:
            self.logger.debug(f"Line number {line_num} not found in file {file_path}", 
                             context={"file_path": file_path, "line_num": line_num})
        
        return valid

    @with_context
    def match_comment_patterns(self, review_text: str) -> List[Dict[str, Any]]:
        """
        Match patterns in the review text to identify file paths and line numbers.
        
        Args:
            review_text: The review text from the AI
            
        Returns:
            List of dictionaries containing file path, line number, and comment position
        """
        matches = []
        
        # Find all matches for each pattern
        for i, pattern in enumerate(self.compiled_patterns):
            pattern_matches = list(pattern.finditer(review_text))
            
            for match in pattern_matches:
                try:
                    file_path = match.group(1).strip()
                    line_num = int(match.group(2))
                    
                    matches.append({
                        "pattern_index": i,
                        "file_path": file_path,
                        "line_num": line_num,
                        "match": match
                    })
                except (IndexError, ValueError) as e:
                    self.logger.warning(f"Failed to extract match from pattern {i}: {e}",
                                      context={"pattern": self.patterns[i], "match_text": match.group(0)})
        
        self.logger.debug(f"Found {len(matches)} potential comments in review", 
                         context={"matches_count": len(matches)})
        return matches

    @with_context
    def extract_comment_text(self, review_text: str, match: Dict[str, Any]) -> str:
        """
        Extract the comment text for a specific match.
        
        Args:
            review_text: The review text from the AI
            match: A dictionary containing match information
            
        Returns:
            The extracted comment text
        """
        start_pos = match["match"].end()
        
        # Search for the next pattern match
        next_match_pos = float('inf')
        for pattern in self.compiled_patterns:
            next_pattern_match = pattern.search(review_text[start_pos:], re.MULTILINE)
            if next_pattern_match:
                current_match_pos = start_pos + next_pattern_match.start()
                next_match_pos = min(next_match_pos, current_match_pos)
        
        # Extract comment text
        if next_match_pos != float('inf'):
            comment_text = review_text[start_pos:next_match_pos].strip()
        else:
            comment_text = review_text[start_pos:].strip()
        
        # Clean up the comment text by removing leading colons
        comment_text = re.sub(r'^:\s*', '', comment_text)
        
        return comment_text

    @with_context
    def extract_line_comments(self, review_text: str, 
                             file_line_map: Dict[str, List[Tuple[int, str]]]) -> List[Dict[str, Any]]:
        """
        Extract line-specific comments from the review text.
        
        Args:
            review_text: The review text from the AI
            file_line_map: Mapping of files to line numbers from the diff
            
        Returns:
            List of line comments in the format expected by GitHub API
            
        Raises:
            CommentExtractionError: If there's an error during comment extraction
        """
        if not review_text:
            self.logger.warning("Empty review text provided for comment extraction")
            return []
        
        if not file_line_map:
            self.logger.warning("Empty file line map provided for comment extraction")
            return []
        
        try:
            # Find all comment patterns in the review text
            matches = self.match_comment_patterns(review_text)
            
            # Extract comment text and validate file paths and line numbers
            comments = []
            for match in matches:
                file_path = match["file_path"]
                line_num = match["line_num"]
                
                # Validate file path and line number
                if not self.validate_line_number(file_path, line_num, file_line_map):
                    continue
                
                # Extract comment text
                comment_text = self.extract_comment_text(review_text, match)
                
                comments.append({
                    "path": file_path,
                    "line": line_num,
                    "body": comment_text
                })
            
            self.logger.info(f"Extracted {len(comments)} valid line comments from review",
                           context={"comments_count": len(comments)})
            return comments
        
        except Exception as e:
            error_msg = f"Failed to extract line comments: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise CommentExtractionError(error_msg) from e


# Legacy function for backward compatibility
def extract_line_comments(review_text: str, file_line_map: Dict[str, List[Tuple[int, str]]]) -> List[Dict[str, Any]]:
    """
    Legacy function to maintain backward compatibility with the original implementation.
    
    Args:
        review_text: The review text from the AI
        file_line_map: Mapping of files to line numbers from the diff
        
    Returns:
        List of line comments in the format expected by GitHub API
    """
    extractor = CommentExtractor()
    return extractor.extract_line_comments(review_text, file_line_map)