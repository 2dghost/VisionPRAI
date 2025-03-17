#!/usr/bin/env python3
"""
Tests for the comment extractor functionality.
Verifies correct extraction of file-specific comments from review text.
"""

import unittest
import os
import sys
from typing import Dict, List, Tuple

# Add parent directory to path to make imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Try direct imports first (for GitHub Actions and package usage)
try:
    from src.comment_extractor import CommentExtractor
except ImportError:
    from comment_extractor import CommentExtractor


class TestCommentExtraction(unittest.TestCase):
    """Test the extraction of line-specific comments from review text."""

    def setUp(self):
        """Set up test environment."""
        self.extractor = CommentExtractor()
        
        # Mock file line map for testing
        self.file_line_map = {
            "src/utils.py": [(10, 1, "def test():"), (20, 2, "    pass"), (30, 3, "    return True")],
            "src/main.py": [(5, 1, "def main():"), (15, 2, "    test()"), (25, 3, "    print('done')")],
        }

    def test_github_style_comment_extraction(self):
        """Test extraction of GitHub-style '### filename.ext:line_number' comments."""
        review_text = """
## Summary
This is a test review.

## Detailed Feedback

### src/utils.py:10
Problem: This function lacks a docstring.

Suggestion: Add a docstring to explain what the function does.

Explanation: Docstrings improve code readability and maintainability.

### src/main.py:15
Problem: The function call doesn't handle errors.

Suggestion: Wrap the call in a try-except block.

```python
try:
    test()
except Exception as e:
    print(f"Error: {e}")
```

Explanation: Error handling prevents application crashes.
"""
        
        comments = self.extractor.extract_line_comments(review_text, self.file_line_map)
        
        # Verify we extracted 2 comments
        self.assertEqual(len(comments), 2, "Should extract 2 comments")
        
        # Verify first comment
        self.assertEqual(comments[0]["path"], "src/utils.py")
        self.assertEqual(comments[0]["line"], 10)
        self.assertEqual(comments[0]["side"], "RIGHT")
        self.assertIn("Problem: This function lacks a docstring.", comments[0]["body"])
        self.assertIn("Suggestion: Add a docstring", comments[0]["body"])
        
        # Verify second comment
        self.assertEqual(comments[1]["path"], "src/main.py")
        self.assertEqual(comments[1]["line"], 15)
        self.assertEqual(comments[1]["side"], "RIGHT")
        self.assertIn("Problem: The function call doesn't handle errors.", comments[1]["body"])
        self.assertIn("Wrap the call in a try-except block", comments[1]["body"])

    def test_multiple_comments_for_same_file(self):
        """Test extraction of multiple comments for the same file."""
        review_text = """
## Summary
This is a test review with multiple comments for the same file.

## Detailed Feedback

### src/utils.py:10
Problem: This function lacks a docstring.

Suggestion: Add a docstring to explain what the function does.

Explanation: Docstrings improve code readability and maintainability.

### src/utils.py:20
Problem: This function doesn't do anything useful.

Suggestion: Implement the function logic.

Explanation: Empty functions should be avoided or documented as stubs.
"""
        
        comments = self.extractor.extract_line_comments(review_text, self.file_line_map)
        
        # Verify we extracted 2 comments
        self.assertEqual(len(comments), 2, "Should extract 2 comments")
        
        # Verify both comments are for utils.py but different lines
        self.assertEqual(comments[0]["path"], "src/utils.py")
        self.assertEqual(comments[0]["line"], 10)
        
        self.assertEqual(comments[1]["path"], "src/utils.py")
        self.assertEqual(comments[1]["line"], 20)
        
        # Verify they have different content
        self.assertIn("lacks a docstring", comments[0]["body"])
        self.assertIn("doesn't do anything useful", comments[1]["body"])

    def test_split_problem_sections(self):
        """Test handling of multiple problem sections within a single comment."""
        review_text = """
## Detailed Feedback

### src/utils.py:30
Problem: The function always returns True without checking anything.

Suggestion: Add appropriate condition checks before returning.

Explanation: Unconditional returns can lead to logical errors.

Problem: The function name is too generic.

Suggestion: Rename the function to be more descriptive.

Explanation: Better naming improves code readability.
"""
        
        # This is verified in the review_pr.py file's extract_file_specific_comments function
        # which splits comments with multiple Problem sections into separate comments
        comments = self.extractor.extract_line_comments(review_text, self.file_line_map)
        
        # The extractor itself would return 1 comment, but review_pr.py would split it into 2
        self.assertEqual(len(comments), 1, "Extractor should return 1 comment")
        self.assertEqual(comments[0]["path"], "src/utils.py")
        self.assertEqual(comments[0]["line"], 30)
        
        # Verify both problems are in the content
        self.assertIn("always returns True", comments[0]["body"])
        self.assertIn("name is too generic", comments[0]["body"])


if __name__ == "__main__":
    unittest.main() 