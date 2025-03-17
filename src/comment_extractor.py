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
        Validate a file path exists in the diff.
        
        Args:
            file_path: The file path to validate
            file_line_map: Mapping of file paths to (line_num, position, content)
            
        Returns:
            True if the file path exists in the diff, False otherwise
        """
        # First check exact match
        if file_path in file_line_map:
            return True
            
        # Try with normalized path
        normalized_path = self.normalize_file_path(file_path)
        if normalized_path in file_line_map:
            return True
            
        # Try to find a matching file name
        for diff_file in file_line_map:
            if diff_file.endswith('/' + file_path) or diff_file.endswith('/' + normalized_path):
                return True
                
        self.logger.warning(f"File path '{file_path}' not found in diff")
        return False
    
    @with_context
    def normalize_file_path(self, file_path: str) -> str:
        """
        Normalize a file path by removing leading/trailing whitespace and quotes.
        
        Args:
            file_path: The file path to normalize
            
        Returns:
            Normalized file path
        """
        # Remove leading/trailing whitespace
        normalized = file_path.strip()
        
        # Remove quotes
        for quote in ['"', "'", "`"]:
            if normalized.startswith(quote) and normalized.endswith(quote):
                normalized = normalized[1:-1]
                break
                
        # Remove leading ./ or / if present
        if normalized.startswith('./'):
            normalized = normalized[2:]
        elif normalized.startswith('/'):
            normalized = normalized[1:]
            
        return normalized

    @with_context
    def find_matching_file_path(self, file_path: str, file_line_map: Dict[str, List[Tuple[int, int, str]]]) -> str:
        """
        Find a matching file path in the diff.
        
        Args:
            file_path: The file path to match
            file_line_map: Mapping of file paths to (line_num, position, content)
            
        Returns:
            The matching file path from the diff, or the original file path if no match
        """
        # First try exact match
        if file_path in file_line_map:
            return file_path
        
        # Normalize the file path
        normalized_path = self.normalize_file_path(file_path)
        if normalized_path in file_line_map:
            self.logger.debug(f"Found normalized match for '{file_path}': '{normalized_path}'")
            return normalized_path
            
        # Try to find a relative path match
        for diff_file in file_line_map:
            if diff_file.endswith('/' + file_path) or diff_file.endswith('/' + normalized_path):
                self.logger.debug(f"Found partial match for '{file_path}': '{diff_file}'")
                return diff_file
                
        # Try filename only match as a last resort
        file_name = os.path.basename(file_path)
        matching_files = [f for f in file_line_map.keys() if os.path.basename(f) == file_name]
        if len(matching_files) == 1:  # Only if there's a single unambiguous match
            self.logger.debug(f"Found filename match for '{file_path}': '{matching_files[0]}'")
            return matching_files[0]
            
        self.logger.warning(f"No matching file found for '{file_path}', using as is")
        return file_path

    @with_context
    def validate_line_number(self, file_path: str, line_num: int, file_line_map: Dict[str, List[Tuple[int, int, str]]]) -> int:
        """
        Validate and adjust line number if needed to ensure it exists in the diff.
        
        Args:
            file_path: File path
            line_num: Line number to validate
            file_line_map: Mapping of file paths to line information
            
        Returns:
            Adjusted line number that exists in the diff, or original if file not found
        """
        if file_path not in file_line_map:
            # Try to find a matching file
            matching_file = self.find_matching_file_path(file_path, file_line_map)
            if matching_file != file_path and matching_file in file_line_map:
                file_path = matching_file
            else:
                # File not found, can't validate line number
                self.logger.warning(f"Cannot validate line number for {file_path} - file not in diff")
                return line_num
            
        # Get line info for the file
        line_info = file_line_map[file_path]
        
        # Check if the exact line number exists
        for info in line_info:
            if info[0] == line_num:  # info[0] is the new line number
                return line_num
            
        # Find the closest valid line number
        valid_line_nums = [info[0] for info in line_info]
        if not valid_line_nums:
            self.logger.warning(f"No valid lines found for {file_path}")
            return line_num
        
        closest_line = min(valid_line_nums, key=lambda x: abs(x - line_num))
        self.logger.info(f"Adjusted line number for {file_path} from {line_num} to {closest_line}")
        return closest_line

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
    def extract_comments(self, review_text: str, file_line_positions: Dict[str, Dict[int, int]]) -> List[Dict[str, Any]]:
        """
        Extract line-specific comments from review text using the new position mapping format.
        
        Args:
            review_text: The text containing comments
            file_line_positions: Mapping of file paths to {line_number: position} dictionaries
            
        Returns:
            A list of comment dictionaries with path, line, position, and body keys
            
        Raises:
            CommentExtractionError: If comment extraction fails
        """
        if not review_text:
            self.logger.warning("Empty review text provided")
            return []
            
        if not file_line_positions:
            self.logger.warning("No file line positions provided, comments may not be correctly linked to lines")
            
        # First extract file-specific comment sections
        self.logger.info("Extracting file-specific comments from review text")
        
        # Match explicit file comment patterns (e.g. ### file.py:123)
        comment_matches = self.match_comment_patterns(review_text)
        self.logger.info(f"Found {len(comment_matches)} potential comment matches")
        
        # Extract and validate comments
        valid_comments = []
        
        for match in comment_matches:
            file_path = match.get("file_path", "")
            line_num = match.get("line_number", 0)
            
            # Normalize the file path
            file_path = self.normalize_file_path(file_path)
            
            # Find the matching file path in our map
            if file_path not in file_line_positions:
                # Try to find a similar file path
                file_path = self.find_matching_file_path(file_path, file_line_positions)
                if not file_path:
                    self.logger.warning(f"No matching file found for {match.get('file_path', 'unknown')}")
                    continue
            
            # Extract the comment text associated with this match
            comment_text = self.extract_comment_text(review_text, match)
            if not comment_text:
                self.logger.warning(f"Empty comment text for {file_path}:{line_num}")
                continue
                
            # Get position from our mapping
            if line_num in file_line_positions[file_path]:
                position = file_line_positions[file_path][line_num]
                self.logger.debug(f"Found position {position} for {file_path}:{line_num}")
            else:
                # Try to find the nearest line number with a position
                nearest_line = self.find_nearest_line(line_num, file_line_positions[file_path])
                if nearest_line is None:
                    self.logger.warning(f"No position found for {file_path}:{line_num}")
                    continue
                    
                position = file_line_positions[file_path][nearest_line]
                self.logger.info(f"Using nearest line {nearest_line} with position {position} for {file_path}:{line_num}")
                line_num = nearest_line  # Update line number to the one we found
            
            # Create comment object
            comment = {
                "path": file_path,
                "line": line_num,
                "position": position,
                "body": comment_text,
                "side": "RIGHT"  # Commenting on the new version
            }
            
            self.logger.debug(f"Added comment for {file_path}:{line_num} with position {position}")
            valid_comments.append(comment)
            
        self.logger.info(f"Extracted {len(valid_comments)} validated comments from {len(comment_matches)} matches")
        return valid_comments

    def find_nearest_line(self, target_line: int, line_positions: Dict[int, int]) -> Optional[int]:
        """
        Find the nearest line number in the map to the target line.
        
        Args:
            target_line: The line number to find
            line_positions: Dictionary mapping line numbers to positions
            
        Returns:
            The nearest line number or None if no lines are available
        """
        if not line_positions:
            return None
            
        if target_line in line_positions:
            return target_line
            
        # Find the closest line by absolute difference
        line_numbers = list(line_positions.keys())
        nearest_line = min(line_numbers, key=lambda x: abs(x - target_line))
        return nearest_line


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