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
            
            # Log the available files in the diff for debugging
            self.logger.debug(f"Available files in diff: {list(file_line_map.keys())}")
            
            # Primary pattern for file-specific comments with code suggestions
            primary_pattern = r'### ([^:\n]+):(\d+)\s*\n(.*?)(?=\n### [^:\n]+:\d+|\Z)'
            
            # Try to find all file-specific comments with the primary pattern
            primary_matches = list(re.finditer(primary_pattern, review_text, re.DOTALL))
            self.logger.debug(f"Found {len(primary_matches)} primary file-specific comments")
            
            # Process primary matches first (these are the most reliable)
            for match in primary_matches:
                file_path = match.group(1).strip()
                line_num = int(match.group(2))
                content = match.group(3).strip()
                
                self.logger.debug(f"Processing primary file-specific comment: {file_path}:{line_num}")
                
                # Check if the file exists in the diff
                if not self.validate_file_path(file_path, file_line_map):
                    self.logger.warning(f"File {file_path} not found in diff, checking for similar files")
                    # Try to find a similar file name
                    similar_files = [f for f in file_line_map.keys() if f.endswith(file_path) or file_path.endswith(f)]
                    if similar_files:
                        file_path = similar_files[0]
                        self.logger.info(f"Using similar file {file_path} instead")
                    else:
                        self.logger.warning(f"No similar file found for {file_path}, skipping comment")
                        continue
                
                # Find the corresponding position in the diff
                position = None
                for line, pos, _ in file_line_map[file_path]:
                    if line == line_num:
                        position = pos
                        break
                
                # Always include the line and side parameters, and optionally include position as a fallback
                comment_data = {
                    "path": file_path,
                    "line": line_num,
                    "side": "RIGHT",  # Always comment on the new version
                    "body": content
                }
                
                # Add position as a fallback but prefer line and side
                if position is not None:
                    comment_data["position"] = position
                
                comments.append(comment_data)
                self.logger.debug(f"Added comment for {file_path}:{line_num}" + 
                                 (f" at position {position}" if position else ""))
                
                # Process fallback for when position can't be found
                if position is None:
                    self.logger.warning(f"Could not find position for {file_path}:{line_num}, trying closest line")
                    # Try to find the closest line number
                    if file_line_map[file_path]:
                        closest_line = min(file_line_map[file_path], key=lambda x: abs(x[0] - line_num))
                        closest_line_num, closest_pos, _ = closest_line
                        self.logger.info(f"Using closest line {closest_line_num} as fallback")
                        # We'll still try the original line number but note the position mismatch
                        comments[-1]["position"] = closest_pos
            
            # Try alternative patterns if we didn't find enough primary matches
            if len(primary_matches) < 3:
                # Alternative patterns to try
                alternative_patterns = [
                    # "In file X, line Y:" format
                    r'(?:^|\n)(?:In|At) ([^,\n]+),\s*line (\d+):(.*?)(?=\n(?:In|At) [^,\n]+,\s*line \d+:|\Z)',
                    # "filename.ext line Y:" format
                    r'(?:^|\n)([^:\s\n]+)\s+line\s+(\d+):(.*?)(?=\n[^:\s\n]+\s+line\s+\d+:|\Z)',
                    # "File: filename.ext, Line: Y" format
                    r'(?:^|\n)File:\s*([^,\n]+),\s*Line:\s*(\d+)(.*?)(?=\n(?:File:|In|At)|\Z)'
                ]
                
                for pattern_idx, pattern in enumerate(alternative_patterns):
                    alt_matches = list(re.finditer(pattern, review_text, re.DOTALL))
                    self.logger.debug(f"Found {len(alt_matches)} matches with alternative pattern {pattern_idx+1}")
                    
                    for match in alt_matches:
                        file_path = match.group(1).strip()
                        line_num = int(match.group(2))
                        content = match.group(3).strip()
                        
                        self.logger.debug(f"Processing alternative match: {file_path}:{line_num}")
                        
                        # Check if the file exists in the diff
                        if not self.validate_file_path(file_path, file_line_map):
                            self.logger.warning(f"File {file_path} not found in diff, checking for similar files")
                            # Try to find a similar file name
                            similar_files = [f for f in file_line_map.keys() if f.endswith(file_path) or file_path.endswith(f)]
                            if similar_files:
                                file_path = similar_files[0]
                                self.logger.info(f"Using similar file {file_path} instead")
                            else:
                                self.logger.warning(f"No similar file found for {file_path}, skipping comment")
                                continue
                        
                        # Find the corresponding position in the diff
                        position = None
                        for line, pos, _ in file_line_map[file_path]:
                            if line == line_num:
                                position = pos
                                break
                        
                        # Always include the line and side parameters
                        comment_data = {
                            "path": file_path,
                            "line": line_num,
                            "side": "RIGHT",
                            "body": content
                        }
                        
                        # Add position as a fallback
                        if position is not None:
                            comment_data["position"] = position
                                
                        comments.append(comment_data)
                        self.logger.debug(f"Added comment for {file_path}:{line_num}" + 
                                         (f" at position {position}" if position else ""))
                        
                        # Process fallback for when position can't be found
                        if position is None:
                            self.logger.warning(f"Could not find position for {file_path}:{line_num}, trying closest line")
                            # Try to find the closest line number
                            if file_line_map[file_path]:
                                closest_line = min(file_line_map[file_path], key=lambda x: abs(x[0] - line_num))
                                closest_line_num, closest_pos, _ = closest_line
                                self.logger.info(f"Using closest line {closest_line_num} as fallback")
                                # We'll still try the original line number but note the position mismatch
                                comments[-1]["position"] = closest_pos
            
            # Process standard pattern matches
            for match in matches:
                file_path = match["file"]
                line_num = match["line"]
                
                # Skip if we already have a comment for this file and line
                if any(c["path"] == file_path and c["line"] == line_num for c in comments):
                    self.logger.debug(f"Skipping duplicate comment for {file_path}:{line_num}")
                    continue
                
                # Extract comment text
                comment_text = self.extract_comment_text(review_text, match)
                
                # Validate file path
                if not self.validate_file_path(file_path, file_line_map):
                    self.logger.warning(f"File {file_path} not found in diff, checking for similar files")
                    # Try to find a similar file name
                    similar_files = [f for f in file_line_map.keys() if f.endswith(file_path) or file_path.endswith(f)]
                    if similar_files:
                        file_path = similar_files[0]
                        self.logger.info(f"Using similar file {file_path} instead")
                    else:
                        self.logger.warning(f"No similar file found for {file_path}, skipping comment")
                        continue
                
                # Find the corresponding position in the diff
                position = None
                for line, pos, _ in file_line_map[file_path]:
                    if line == line_num:
                        position = pos
                        break
                
                # Always include the line and side parameters
                comment_data = {
                    "path": file_path,
                    "line": line_num,
                    "side": "RIGHT",
                    "body": comment_text
                }
                
                # Add position as a fallback
                if position is not None:
                    comment_data["position"] = position
                    
                comments.append(comment_data)
                self.logger.debug(f"Added comment for {file_path}:{line_num}" + 
                                 (f" at position {position}" if position else ""))
                
                # Process fallback for when position can't be found
                if position is None:
                    self.logger.warning(f"Could not find position for {file_path}:{line_num}, trying closest line")
                    # Try to find the closest line number
                    if file_line_map[file_path]:
                        closest_line = min(file_line_map[file_path], key=lambda x: abs(x[0] - line_num))
                        closest_line_num, closest_pos, _ = closest_line
                        self.logger.info(f"Using closest line {closest_line_num} as fallback")
                        # We'll still try the original line number but note the position mismatch
                        comments[-1]["position"] = closest_pos
            
            # Final check to ensure all comments have required fields
            for comment in comments:
                # Ensure line is an integer 
                if "line" in comment:
                    comment["line"] = int(comment["line"])
                else:
                    # If no line field, add it from position mapping if possible
                    if "path" in comment and "position" in comment:
                        for file_path, lines in file_line_map.items():
                            if file_path == comment["path"]:
                                matching_position = [line for line, pos, _ in lines if pos == comment["position"]]
                                if matching_position:
                                    comment["line"] = matching_position[0]
                                    comment["side"] = "RIGHT"
                                    break
                
                # Ensure side is specified
                if "line" in comment and "side" not in comment:
                    comment["side"] = "RIGHT"
                
                # For multi-line comments, ensure start_side is set if start_line is present
                if "start_line" in comment and "start_side" not in comment:
                    comment["start_side"] = "RIGHT"
            
            self.logger.info(f"Extracted {len(comments)} line-specific comments")
            return comments
            
        except Exception as e:
            error_message = f"Failed to extract line comments: {str(e)}"
            self.logger.error(error_message, exc_info=True)
            raise CommentExtractionError(error_message, error_code="EXTRACT_LINE_COMMENTS_ERROR") from e


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