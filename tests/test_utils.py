import unittest
from unittest.mock import patch, MagicMock

import pytest
import responses

from src.utils import (
    get_pr_diff,
    post_review_comment,
    parse_diff_for_lines,
    extract_code_blocks
)
from src.review_pr import extract_line_comments


class TestUtilFunctions(unittest.TestCase):
    """Test utility functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.repo = "test-owner/test-repo"
        self.pr_number = "123"
        self.token = "test-token"
        self.sample_diff = """diff --git a/src/test.py b/src/test.py
index abcdef..ghijkl 100644
--- a/src/test.py
+++ b/src/test.py
@@ -10,6 +10,8 @@ def existing_function():
     return True
 
 def new_function():
+    # This is a new comment
+    value = 42
     return value
 """

    @responses.activate
    def test_get_pr_diff_success(self):
        """Test successful PR diff retrieval."""
        responses.add(
            responses.GET,
            f"https://api.github.com/repos/{self.repo}/pulls/{self.pr_number}",
            body=self.sample_diff,
            status=200
        )
        
        diff = get_pr_diff(self.repo, self.pr_number, self.token)
        
        self.assertEqual(diff, self.sample_diff)
        self.assertEqual(len(responses.calls), 1)
        
        # Check request headers
        request_headers = responses.calls[0].request.headers
        self.assertEqual(request_headers["Accept"], "application/vnd.github.v3.diff")
        self.assertEqual(request_headers["Authorization"], f"token {self.token}")

    @responses.activate
    def test_get_pr_diff_failure(self):
        """Test PR diff retrieval failure."""
        responses.add(
            responses.GET,
            f"https://api.github.com/repos/{self.repo}/pulls/{self.pr_number}",
            json={"message": "Not Found"},
            status=404
        )
        
        diff = get_pr_diff(self.repo, self.pr_number, self.token)
        
        self.assertIsNone(diff)

    @responses.activate
    def test_post_review_comment_success(self):
        """Test successful posting of review comment."""
        responses.add(
            responses.POST,
            f"https://api.github.com/repos/{self.repo}/pulls/{self.pr_number}/reviews",
            json={"id": 123456},
            status=201
        )
        
        review_text = "This is a test review"
        success = post_review_comment(self.repo, self.pr_number, self.token, review_text)
        
        self.assertTrue(success)
        self.assertEqual(len(responses.calls), 1)
        
        # Check request payload
        request_body = responses.calls[0].request.body.decode()
        self.assertIn(review_text, request_body)
        self.assertIn("COMMENT", request_body)

    @responses.activate
    def test_post_review_comment_failure(self):
        """Test failure in posting review comment."""
        responses.add(
            responses.POST,
            f"https://api.github.com/repos/{self.repo}/pulls/{self.pr_number}/reviews",
            json={"message": "Validation Failed"},
            status=422
        )
        
        review_text = "This is a test review"
        success = post_review_comment(self.repo, self.pr_number, self.token, review_text)
        
        self.assertFalse(success)

    def test_parse_diff_for_lines(self):
        """Test parsing diff to extract file paths and line numbers."""
        result = parse_diff_for_lines(self.sample_diff)
        
        # Check that the file was detected
        self.assertIn("src/test.py", result)
        
        # Check that added lines were detected with correct line numbers
        lines = result["src/test.py"]
        self.assertEqual(len(lines), 2)
        
        self.assertEqual(lines[0][0], 13)  # Line number
        self.assertEqual(lines[0][1], "    # This is a new comment")  # Line content
        
        self.assertEqual(lines[1][0], 14)  # Line number
        self.assertEqual(lines[1][1], "    value = 42")  # Line content

    def test_extract_code_blocks(self):
        """Test extracting code blocks from markdown text."""
        markdown_text = """
Here's some sample code:

```python
def test_function():
    return 42
```

And another example:

```javascript
function add(a, b) {
    return a + b;
}
```
"""
        blocks = extract_code_blocks(markdown_text)
        
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0], "def test_function():\n    return 42")
        self.assertEqual(blocks[1], "function add(a, b) {\n    return a + b;\n}")
    
    def test_extract_line_comments(self):
        """Test extracting line-specific comments from review text."""
        review_text = """
# Code Review

Overall, the code looks good, but there are a few issues to address:

In src/test.py, line 13:
This comment is unnecessary and should be removed.

src/test.py:14:
The variable name 'value' is too generic. Consider using a more descriptive name.

In file `src/utils.py` at line 42:
This function is missing proper error handling.
"""
        file_line_map = {
            "src/test.py": [(13, "    # This is a new comment"), (14, "    value = 42")],
            "src/utils.py": [(42, "def process_data():")]
        }
        
        comments = extract_line_comments(review_text, file_line_map)
        
        self.assertEqual(len(comments), 3)
        
        # Check first comment
        self.assertEqual(comments[0]["path"], "src/test.py")
        self.assertEqual(comments[0]["line"], 13)
        self.assertEqual(comments[0]["body"], "This comment is unnecessary and should be removed.")
        
        # Check second comment
        self.assertEqual(comments[1]["path"], "src/test.py")
        self.assertEqual(comments[1]["line"], 14)
        self.assertEqual(comments[1]["body"], "The variable name 'value' is too generic. Consider using a more descriptive name.")
        
        # Check third comment
        self.assertEqual(comments[2]["path"], "src/utils.py")
        self.assertEqual(comments[2]["line"], 42)
        self.assertEqual(comments[2]["body"], "This function is missing proper error handling.")


if __name__ == '__main__':
    unittest.main()