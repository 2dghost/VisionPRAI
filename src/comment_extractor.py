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

import sys
import os

# Add the parent directory to sys.path to support both local and GitHub Actions environments
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    # Try direct imports first (for GitHub Actions and package usage)
    from custom_exceptions import (
        CommentExtractionError,
        DiffParsingError,
        InvalidConfigurationError,
        MissingConfigurationError
    )
    from logging_config import get_logger, with_context
except ImportError:
    # Fall back to src-prefixed imports (for local development)
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
    def validate_file_path(self, file_path: str, file_line_map: Dict[str, List[Tuple[int, int, str]]]) -> bool:
        """
        Validate that a file path exists in the diff.
        
        Args:
            file_path: Path to the file
            file_line_map: Mapping of files to their line numbers and positions
            
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
                            file_line_map: Dict[str, List[Tuple[int, int, str]]]) -> bool:
        """
        Validate that a line number exists in the file's diff.
        
        Args:
            file_path: Path to the file
            line_num: Line number to validate
            file_line_map: Mapping of files to their line numbers and positions
            
        Returns:
            True if the line number is valid, False otherwise
        """
        if file_path not in file_line_map:
            return False
            
        # Check if the line number exists in the file's diff
        return any(line == line_num for line, _, _ in file_line_map[file_path])

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
                        "file": file_path,
                        "line": line_num,
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
                             file_line_map: Dict[str, List[Tuple[int, int, str]]]) -> List[Dict[str, Any]]:
        """
        Extract line-specific comments from review text.
        
        Args:
            review_text: The review text to extract comments from
            file_line_map: Mapping of files to their line numbers and positions
            
        Returns:
            List of comment dictionaries with 'path', 'line', 'position', and 'body' keys
            
        Raises:
            CommentExtractionError: If comment extraction fails
        """
        try:
            # Find all pattern matches
            matches = self.match_comment_patterns(review_text)
            
            # Extract and validate comments
            comments = []
            
            # Also look for file-specific sections with suggestions
            file_section_pattern = r'### ([^:\n]+):(\d+)\s*\n(.*?)(?=\n### |$)'
            for match in re.finditer(file_section_pattern, review_text, re.DOTALL):
                file_path = match.group(1).strip()
                line_num = int(match.group(2))
                section_content = match.group(3).strip()
                
                self.logger.debug(f"Found file section: {file_path}:{line_num}")
                
                # Check if the file and line exist in the diff
                if not self.validate_file_path(file_path, file_line_map):
                    self.logger.warning(f"File {file_path} not found in diff, skipping comment")
                    continue
                    
                if not self.validate_line_number(file_path, line_num, file_line_map):
                    self.logger.warning(f"Line {line_num} not found in {file_path} diff, skipping comment")
                    continue
                
                # Find the corresponding position in the diff
                position = None
                for line, pos, _ in file_line_map[file_path]:
                    if line == line_num:
                        position = pos
                        break
                
                if position is not None:
                    comments.append({
                        "path": file_path,
                        "line": line_num,
                        "position": position,
                        "body": section_content
                    })
                    self.logger.debug(f"Added comment for {file_path}:{line_num} at position {position}")
                else:
                    self.logger.warning(f"Could not find position for {file_path}:{line_num}")
            
            # Process standard line comments
            for match in matches:
                file_path = match["file"]
                line_num = match["line"]
                
                # Get the comment text
                comment_text = self.extract_comment_text(review_text, match)
                if not comment_text:
                    continue
                
                # Find the corresponding position in the diff
                position = None
                if file_path in file_line_map:
                    for line, pos, _ in file_line_map[file_path]:
                        if line == line_num:
                            position = pos
                            break
                
                if position is None:
                    self.logger.warning(
                        f"Could not find position for line {line_num} in {file_path}",
                        context={"file": file_path, "line": line_num}
                    )
                    continue
                
                comments.append({
                    "path": file_path,
                    "line": line_num,
                    "position": position,
                    "body": comment_text
                })
            
            self.logger.info(f"Extracted {len(comments)} line comments total")
            return comments
            
        except Exception as e:
            raise CommentExtractionError(
                f"Failed to extract line comments: {str(e)}",
                error_code="COMMENT_EXTRACTION_FAILED"
            ) from e


# Legacy function for backward compatibility
def extract_line_comments(review_text: str, file_line_map: Dict[str, List[Tuple[int, int, str]]]) -> List[Dict[str, Any]]:
    """
    Legacy function to maintain backward compatibility with the original implementation.
    
    Args:
        review_text: The review text from the AI
        file_line_map: Mapping of files to their line numbers and positions
        
    Returns:
        List of line comments in the format expected by GitHub API
    """
    extractor = CommentExtractor()
    return extractor.extract_line_comments(review_text, file_line_map)