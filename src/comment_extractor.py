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
        Validate that a file path exists in the PR diff.
        
        Args:
            file_path: File path to validate
            file_line_map: Mapping of file paths to line information
            
        Returns:
            True if the file path exists, False otherwise
        """
        # Direct match
        if file_path in file_line_map:
            return True
        
        # Check for partial matches (handle relative paths)
        for path in file_line_map.keys():
            if path.endswith(file_path) or file_path.endswith(path):
                return True
            
        # No match found
        return False

    @with_context
    def find_matching_file_path(self, file_path: str, file_line_map: Dict[str, List[Tuple[int, int, str]]]) -> str:
        """
        Find the best matching file path in the diff for a given file path.
        
        Args:
            file_path: File path to look for
            file_line_map: Mapping of file paths to line information
            
        Returns:
            The best matching file path, or the original if no match found
        """
        # Direct match
        if file_path in file_line_map:
            return file_path
        
        # Check for partial matches
        for path in file_line_map.keys():
            if path.endswith(file_path):
                self.logger.info(f"Found better match for {file_path}: {path}")
                return path
            elif file_path.endswith(path):
                self.logger.info(f"Found better match for {file_path}: {path}")
                return path
            
        # Try more fuzzy matching if needed
        best_match = None
        highest_similarity = 0
        
        for path in file_line_map.keys():
            # Simple similarity score - count of matching characters
            # Could be improved with more sophisticated algorithms
            similarity = sum(c1 == c2 for c1, c2 in zip(file_path, path)) / max(len(file_path), len(path))
            if similarity > 0.7 and similarity > highest_similarity:  # 70% similarity threshold
                highest_similarity = similarity
                best_match = path
            
        if best_match:
            self.logger.info(f"Found fuzzy match for {file_path}: {best_match} (similarity: {highest_similarity:.2f})")
            return best_match
        
        # No match found
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
        
        # Primary pattern to match GitHub-style comments: ### filename.ext:line_number
        github_pattern = re.compile(r'### ([^:\n]+):(\d+)\s*\n(.*?)(?=\n### [^:\n]+:\d+|\Z)', re.DOTALL)
        
        # Match patterns like:
        # - "file.py:10: This is a comment"
        # - "In file.py, line 10: This is a comment"
        # - "In `file.py` on line 10: This is a comment"
        primary_pattern = re.compile(r'(?:In\s+)?(?:`)?([^:`\s]+\.[a-zA-Z0-9]+)(?:`)?(?:,| on)?\s+(?:line\s+)?(\d+)(?:\s*:|\s*-\s*|\s+)(.*?)(?:\n\n|\Z)', re.DOTALL)
        
        # Match other file reference patterns
        secondary_pattern = re.compile(r'In\s+the\s+file\s+[`\'"]?([^:`\'"]+)[`\'"]?\s+(?:at|on)\s+line\s+(\d+)(?:\s*:|\s*-\s*)(.*?)(?:\n\n|\Z)', re.DOTALL)
        
        # Match code block patterns (```) with filename and line information
        code_block_pattern = re.compile(r'```(?:[a-zA-Z0-9]+:)?([^:]+):(\d+)[\s\S]*?```\s*(.*?)(?:\n\n|\Z)', re.DOTALL)
        
        # Collect all pattern matches
        github_matches = list(github_pattern.finditer(review_text))
        primary_matches = list(primary_pattern.finditer(review_text))
        secondary_matches = list(secondary_pattern.finditer(review_text))
        code_block_matches = list(code_block_pattern.finditer(review_text))
        
        self.logger.debug(f"Found {len(github_matches)} GitHub-style matches, {len(primary_matches)} primary matches, {len(secondary_matches)} secondary matches, {len(code_block_matches)} code block matches")
        
        # Extract comments
        comments = []
        
        # Process GitHub-style matches first (these are the most reliable)
        for match in github_matches:
            file_path = match.group(1).strip()
            line_num = int(match.group(2))
            content = match.group(3).strip()
            
            self.logger.debug(f"Processing GitHub-style file-specific comment: {file_path}:{line_num}")
            
            # Check if the file exists in the diff
            if not self.validate_file_path(file_path, file_line_map):
                self.logger.warning(f"File {file_path} not found in diff, checking for similar files")
                # Try to find a similar file name
                matched_file_path = self.find_matching_file_path(file_path, file_line_map)
                if matched_file_path != file_path:
                    self.logger.info(f"Using matched file {matched_file_path} instead of {file_path}")
                    file_path = matched_file_path
                else:
                    self.logger.warning(f"No similar file found for {file_path}, skipping comment")
                    continue
            
            # Validate and adjust the line number if needed
            adjusted_line_num = self.validate_line_number(file_path, line_num, file_line_map)
            if adjusted_line_num != line_num:
                self.logger.info(f"Adjusted line number from {line_num} to {adjusted_line_num} for {file_path}")
                line_num = adjusted_line_num
            
            # GitHub API requires 'path' and 'line' parameters
            comment_data = {
                "path": file_path,
                "line": line_num,
                "side": "RIGHT",  # Always comment on the new version
                "body": content
            }
            
            comments.append(comment_data)
            self.logger.debug(f"Added GitHub-style comment for {file_path}:{line_num}")
        
        # Process primary matches
        for match in primary_matches:
            file_path = match.group(1).strip()
            line_num = int(match.group(2))
            content = match.group(3).strip()
            
            self.logger.debug(f"Processing primary file-specific comment: {file_path}:{line_num}")
            
            # Check if the file exists in the diff
            if not self.validate_file_path(file_path, file_line_map):
                self.logger.warning(f"File {file_path} not found in diff, checking for similar files")
                # Try to find a similar file name
                matched_file_path = self.find_matching_file_path(file_path, file_line_map)
                if matched_file_path != file_path:
                    self.logger.info(f"Using matched file {matched_file_path} instead of {file_path}")
                    file_path = matched_file_path
                else:
                    self.logger.warning(f"No similar file found for {file_path}, skipping comment")
                    continue
            
            # Validate and adjust the line number if needed
            adjusted_line_num = self.validate_line_number(file_path, line_num, file_line_map)
            if adjusted_line_num != line_num:
                self.logger.info(f"Adjusted line number from {line_num} to {adjusted_line_num} for {file_path}")
                line_num = adjusted_line_num
            
            # GitHub API requires 'path' and 'line' parameters
            comment_data = {
                "path": file_path,
                "line": line_num,
                "side": "RIGHT",  # Always comment on the new version
                "body": content
            }
            
            comments.append(comment_data)
            self.logger.debug(f"Added primary comment for {file_path}:{line_num}")
        
        # Process secondary matches
        for match in secondary_matches:
            file_path = match.group(1).strip()
            line_num = int(match.group(2))
            content = match.group(3).strip()
            
            self.logger.debug(f"Processing secondary file-specific comment: {file_path}:{line_num}")
            
            # Check if the file exists in the diff
            if not self.validate_file_path(file_path, file_line_map):
                self.logger.warning(f"File {file_path} not found in diff, checking for similar files")
                # Try to find a similar file name
                matched_file_path = self.find_matching_file_path(file_path, file_line_map)
                if matched_file_path != file_path:
                    self.logger.info(f"Using matched file {matched_file_path} instead of {file_path}")
                    file_path = matched_file_path
                else:
                    self.logger.warning(f"No similar file found for {file_path}, skipping comment")
                    continue
            
            # Validate and adjust the line number if needed
            adjusted_line_num = self.validate_line_number(file_path, line_num, file_line_map)
            if adjusted_line_num != line_num:
                self.logger.info(f"Adjusted line number from {line_num} to {adjusted_line_num} for {file_path}")
                line_num = adjusted_line_num
            
            # GitHub API requires 'path' and 'line' parameters
            comment_data = {
                "path": file_path,
                "line": line_num,
                "side": "RIGHT",  # Always comment on the new version
                "body": content
            }
            
            comments.append(comment_data)
            self.logger.debug(f"Added secondary comment for {file_path}:{line_num}")
        
        # Process code block matches
        for match in code_block_matches:
            file_path = match.group(1).strip()
            line_num = int(match.group(2))
            content = match.group(3).strip()
            
            if not content:
                self.logger.debug(f"Skipping code block with empty comment: {file_path}:{line_num}")
                continue
            
            self.logger.debug(f"Processing code block file-specific comment: {file_path}:{line_num}")
            
            # Check if the file exists in the diff
            if not self.validate_file_path(file_path, file_line_map):
                self.logger.warning(f"File {file_path} not found in diff, checking for similar files")
                # Try to find a similar file name
                matched_file_path = self.find_matching_file_path(file_path, file_line_map)
                if matched_file_path != file_path:
                    self.logger.info(f"Using matched file {matched_file_path} instead of {file_path}")
                    file_path = matched_file_path
                else:
                    self.logger.warning(f"No similar file found for {file_path}, skipping comment")
                    continue
            
            # Validate and adjust the line number if needed
            adjusted_line_num = self.validate_line_number(file_path, line_num, file_line_map)
            if adjusted_line_num != line_num:
                self.logger.info(f"Adjusted line number from {line_num} to {adjusted_line_num} for {file_path}")
                line_num = adjusted_line_num
            
            # GitHub API requires 'path' and 'line' parameters
            comment_data = {
                "path": file_path,
                "line": line_num,
                "side": "RIGHT",  # Always comment on the new version
                "body": content
            }
            
            comments.append(comment_data)
            self.logger.debug(f"Added code block comment for {file_path}:{line_num}")
        
        # Log summary
        self.logger.info(f"Extracted {len(comments)} line-specific comments")
        
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