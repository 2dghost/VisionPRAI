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
    def extract_line_comments(self, review_text: str, 
                             file_line_map: Dict[str, List[Tuple[int, int, str]]]) -> List[Dict[str, Any]]:
        """
        Extract line-specific comments from a review text.
        
        Args:
            review_text: The review text containing code comments
            file_line_map: Mapping of file paths to (line_num, position, content)
            
        Returns:
            List of comment dictionaries with path, line, and body
        """
        # If no files in the diff, we can't extract line comments
        if not file_line_map:
            self.logger.warning("No files in the diff, can't extract line comments")
            return []
        
        # Log the files available in the diff
        self.logger.debug(f"Files in diff: {list(file_line_map.keys())}")
        
        # GitHub-style PR review comments: ### filename.ext:line_number
        github_pattern = re.compile(r'### ([^:\n]+):(\d+)\s*\n(.*?)(?=\n### [^:\n]+:\d+|\Z)', re.DOTALL)
        
        # Standard file:line pattern: file.py:10: comment
        standard_pattern = re.compile(r'([^:\s]+\.[a-zA-Z0-9]+):(\d+)(?:[:,]\s*|\s+-\s*)(.*?)(?=\n\n|\n[^\n]|$)', re.DOTALL)
        
        # Descriptive pattern: In file.py on line 10: comment
        descriptive_pattern = re.compile(r'(?:In\s+)?(?:`)?([^:`\s]+\.[a-zA-Z0-9]+)(?:`)?(?:,| on)?\s+(?:line\s+)?(\d+)(?:\s*:|\s*-\s*|\s+)(.*?)(?=\n\n|\n[^\s\n]|$)', re.DOTALL)
        
        # File reference pattern: In the file "filename.py" at line 10: comment
        file_ref_pattern = re.compile(r'In\s+(?:the\s+)?file\s+[`\'"]?([^:`\'"]+)[`\'"]?\s+(?:at|on)\s+line\s+(\d+)(?:\s*:|\s*-\s*)(.*?)(?=\n\n|\n[^\s\n]|$)', re.DOTALL)
        
        # Code block with filename: ```lang:filename.py:10
        code_block_pattern = re.compile(r'```(?:[a-zA-Z0-9]+:)?([^:]+):(\d+)[\s\S]*?```\s*(.*?)(?=\n\n|\n[^\s\n]|$)', re.DOTALL)
        
        # Collect all pattern matches
        patterns_and_names = [
            (github_pattern, "GitHub-style"),
            (standard_pattern, "standard file:line"),
            (descriptive_pattern, "descriptive"),
            (file_ref_pattern, "file reference"),
            (code_block_pattern, "code block")
        ]
        
        all_matches = []
        for pattern, name in patterns_and_names:
            matches = list(pattern.finditer(review_text))
            self.logger.debug(f"Found {len(matches)} {name} matches")
            all_matches.extend([(match, name) for match in matches])
        
        # Sort matches by their start position in the text
        all_matches.sort(key=lambda x: x[0].start())
        
        # Extract comments
        comments = []
        
        for match, pattern_name in all_matches:
            file_path = match.group(1).strip()
            try:
                line_num = int(match.group(2))
                content = match.group(3).strip()
                
                # Normalize and verify the file path
                normalized_path = self.normalize_file_path(file_path)
                actual_path = self.find_matching_file_path(normalized_path, file_line_map)
                
                # Validate and adjust line number if needed
                valid_line = self.validate_line_number(actual_path, line_num, file_line_map)
                if valid_line != line_num:
                    self.logger.debug(f"Adjusted line number for {actual_path} from {line_num} to {valid_line}")
                    line_num = valid_line
                
                # Create the comment
                comment = {
                    "path": actual_path,
                    "line": line_num,
                    "body": content,
                    "pattern": pattern_name  # For debugging
                }
                
                self.logger.debug(f"Extracted comment for {actual_path}:{line_num} using {pattern_name} pattern")
                comments.append(comment)
                
            except (ValueError, IndexError) as e:
                self.logger.warning(f"Failed to parse comment match: {e}")
                continue
        
        self.logger.info(f"Extracted {len(comments)} line-specific comments from review text")
        return comments


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