import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
import tempfile
import yaml

import pytest

from src.comment_extractor import CommentExtractor
from src.custom_exceptions import MissingConfigurationError, InvalidConfigurationError, CommentExtractionError


class TestCommentExtractor(unittest.TestCase):
    """Test the CommentExtractor class."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary config file with test patterns
        self.test_config = {
            "review": {
                "comment_extraction": {
                    "patterns": [
                        r'In\s+([^,]+),\s+line\s+(\d+):',
                        r'([^:\s]+):(\d+):'
                    ]
                }
            }
        }
        
        # Sample file line map for testing
        self.file_line_map = {
            "src/test.py": [(13, "    # This is a comment"), (14, "    value = 42")],
            "src/utils.py": [(42, "def process_data():")]
        }
        
        # Sample review text for testing
        self.review_text = """
# Code Review

In src/test.py, line 13:
This comment is unnecessary and should be removed.

src/test.py:14:
The variable name 'value' is too generic. Consider using a more descriptive name.

In file `src/utils.py` at line 42:
This function is missing proper error handling.
"""

        # Patch the config.yaml file
        self.mock_config_patcher = patch('builtins.open', mock_open(read_data=yaml.dump(self.test_config)))
        self.mock_config = self.mock_config_patcher.start()
        
        # Create a temporary real config file for tests that need it
        self.temp_config_file = tempfile.NamedTemporaryFile(delete=False, suffix=".yaml")
        with open(self.temp_config_file.name, 'w') as f:
            yaml.dump(self.test_config, f)
    
    def tearDown(self):
        """Clean up after tests."""
        self.mock_config_patcher.stop()
        os.unlink(self.temp_config_file.name)

    def test_init_default_patterns(self):
        """Test that CommentExtractor initializes with default patterns."""
        with patch.object(CommentExtractor, '_load_patterns'):
            extractor = CommentExtractor()
            # Check that default patterns are set
            self.assertEqual(len(extractor.patterns), 4)
            self.assertIn(r'In\s+([^,]+),\s+line\s+(\d+):', extractor.patterns)
            self.assertIn(r'([^:\s]+):(\d+):', extractor.patterns)
            self.assertIn(r'([^:\s]+) line (\d+):', extractor.patterns)
            self.assertIn(r'In file `([^`]+)` at line (\d+)', extractor.patterns)

    def test_load_patterns_from_config(self):
        """Test loading patterns from configuration file."""
        extractor = CommentExtractor(config_path=self.temp_config_file.name)
        self.assertEqual(len(extractor.patterns), 2)
        self.assertEqual(extractor.patterns[0], r'In\s+([^,]+),\s+line\s+(\d+):')
        self.assertEqual(extractor.patterns[1], r'([^:\s]+):(\d+):')

    def test_missing_config_file(self):
        """Test that MissingConfigurationError is raised when config file is missing."""
        with self.assertRaises(MissingConfigurationError):
            CommentExtractor(config_path="nonexistent_file.yaml")

    def test_invalid_patterns_config(self):
        """Test that InvalidConfigurationError is raised with invalid patterns."""
        # Create a config with invalid patterns (not a list)
        invalid_config = {
            "review": {
                "comment_extraction": {
                    "patterns": "not a list"
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml") as f:
            yaml.dump(invalid_config, f)
        
        with self.assertRaises(InvalidConfigurationError):
            CommentExtractor(config_path=f.name)
        
        os.unlink(f.name)

    def test_validate_file_path(self):
        """Test validation of file paths."""
        extractor = CommentExtractor(config_path=self.temp_config_file.name)
        
        # Valid file path
        self.assertTrue(extractor.validate_file_path("src/test.py", self.file_line_map))
        
        # Invalid file path
        self.assertFalse(extractor.validate_file_path("src/nonexistent.py", self.file_line_map))
        
        # Empty file path
        self.assertFalse(extractor.validate_file_path("", self.file_line_map))

    def test_validate_line_number(self):
        """Test validation of line numbers."""
        extractor = CommentExtractor(config_path=self.temp_config_file.name)
        
        # Valid line number
        self.assertTrue(extractor.validate_line_number("src/test.py", 13, self.file_line_map))
        
        # Invalid line number
        self.assertFalse(extractor.validate_line_number("src/test.py", 99, self.file_line_map))
        
        # Invalid file path
        self.assertFalse(extractor.validate_line_number("src/nonexistent.py", 1, self.file_line_map))

    def test_match_comment_patterns(self):
        """Test matching comment patterns in review text."""
        extractor = CommentExtractor(config_path=self.temp_config_file.name)
        matches = extractor.match_comment_patterns(self.review_text)
        
        # Should find 2 matches (the third one doesn't match our patterns)
        self.assertEqual(len(matches), 2)
        
        # Check first match details
        self.assertEqual(matches[0]["file_path"], "src/test.py")
        self.assertEqual(matches[0]["line_num"], 13)
        
        # Check second match details
        self.assertEqual(matches[1]["file_path"], "src/test.py")
        self.assertEqual(matches[1]["line_num"], 14)

    def test_extract_comment_text(self):
        """Test extracting comment text from matches."""
        extractor = CommentExtractor(config_path=self.temp_config_file.name)
        matches = extractor.match_comment_patterns(self.review_text)
        
        # Extract comment for first match
        comment_text = extractor.extract_comment_text(self.review_text, matches[0])
        self.assertEqual(comment_text, "This comment is unnecessary and should be removed.")
        
        # Extract comment for second match
        comment_text = extractor.extract_comment_text(self.review_text, matches[1])
        self.assertEqual(comment_text, "The variable name 'value' is too generic. Consider using a more descriptive name.")

    def test_extract_line_comments(self):
        """Test extracting all line comments from review text."""
        extractor = CommentExtractor(config_path=self.temp_config_file.name)
        comments = extractor.extract_line_comments(self.review_text, self.file_line_map)
        
        # Should extract 2 comments (not 3 because the pattern for the third doesn't match)
        self.assertEqual(len(comments), 2)
        
        # Check first comment
        self.assertEqual(comments[0]["path"], "src/test.py")
        self.assertEqual(comments[0]["line"], 13)
        self.assertEqual(comments[0]["body"], "This comment is unnecessary and should be removed.")
        
        # Check second comment
        self.assertEqual(comments[1]["path"], "src/test.py")
        self.assertEqual(comments[1]["line"], 14)
        self.assertEqual(comments[1]["body"], "The variable name 'value' is too generic. Consider using a more descriptive name.")

    def test_extract_line_comments_empty_review(self):
        """Test extracting comments from an empty review."""
        extractor = CommentExtractor(config_path=self.temp_config_file.name)
        comments = extractor.extract_line_comments("", self.file_line_map)
        self.assertEqual(len(comments), 0)

    def test_extract_line_comments_empty_file_line_map(self):
        """Test extracting comments with an empty file line map."""
        extractor = CommentExtractor(config_path=self.temp_config_file.name)
        comments = extractor.extract_line_comments(self.review_text, {})
        self.assertEqual(len(comments), 0)

    @patch.object(CommentExtractor, 'match_comment_patterns')
    def test_extract_line_comments_exception(self, mock_match):
        """Test that CommentExtractionError is raised on extraction error."""
        # Make the match_comment_patterns method raise an exception
        mock_match.side_effect = Exception("Test exception")
        
        extractor = CommentExtractor(config_path=self.temp_config_file.name)
        
        with self.assertRaises(CommentExtractionError):
            extractor.extract_line_comments(self.review_text, self.file_line_map)

    def test_custom_patterns(self):
        """Test with custom patterns that match the third format."""
        custom_config = {
            "review": {
                "comment_extraction": {
                    "patterns": [
                        r'In file `([^`]+)` at line (\d+)'
                    ]
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml") as f:
            yaml.dump(custom_config, f)
        
        extractor = CommentExtractor(config_path=f.name)
        comments = extractor.extract_line_comments(self.review_text, self.file_line_map)
        
        # Should match the third comment format now
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["path"], "src/utils.py")
        self.assertEqual(comments[0]["line"], 42)
        self.assertEqual(comments[0]["body"], "This function is missing proper error handling.")
        
        os.unlink(f.name)


if __name__ == '__main__':
    unittest.main()