import unittest
from unittest.mock import patch, MagicMock

from src.file_filter import FileFilter


class TestFileFilter(unittest.TestCase):
    """Test the FileFilter class."""

    def setUp(self):
        """Set up test fixtures."""
        # Sample configuration for testing
        self.test_config = {
            "review": {
                "file_filtering": {
                    "enabled": True,
                    "exclude_patterns": [
                        "*.md",
                        "*.json",
                        "LICENSE"
                    ],
                    "max_file_size": 500
                }
            }
        }
        
        # Sample files for testing
        self.test_files = [
            {"filename": "src/main.py", "size": 1024},           # Small Python file - include
            {"filename": "src/large_file.py", "size": 600000},   # Large Python file - exclude (size)
            {"filename": "README.md", "size": 2048},             # Markdown file - exclude (pattern)
            {"filename": "package.json", "size": 1024},          # JSON file - exclude (pattern)
            {"filename": "LICENSE", "size": 512},                # LICENSE file - exclude (pattern)
            {"filename": "src/utils.js", "size": 2048}           # JS file - include
        ]
        
        # Mock the logger
        self.mock_logger_patcher = patch('src.file_filter.get_logger')
        self.mock_get_logger = self.mock_logger_patcher.start()
        self.mock_logger = MagicMock()
        self.mock_get_logger.return_value = self.mock_logger
        
        # Mock the with_context decorator
        self.mock_with_context_patcher = patch('src.file_filter.with_context', lambda f: f)
        self.mock_with_context = self.mock_with_context_patcher.start()
        
    def tearDown(self):
        """Clean up after tests."""
        self.mock_logger_patcher.stop()
        self.mock_with_context_patcher.stop()

    def test_init_with_config(self):
        """Test initialization with valid configuration."""
        file_filter = FileFilter(self.test_config)
        
        self.assertTrue(file_filter.enabled)
        self.assertEqual(len(file_filter.exclude_patterns), 3)
        self.assertEqual(file_filter.max_file_size, 500)

    def test_init_disabled(self):
        """Test initialization with disabled configuration."""
        config = {"review": {"file_filtering": {"enabled": False}}}
        file_filter = FileFilter(config)
        
        self.assertFalse(file_filter.enabled)

    def test_init_missing_config(self):
        """Test initialization with missing configuration."""
        config = {"review": {}}
        file_filter = FileFilter(config)
        
        self.assertFalse(file_filter.enabled)
        self.assertEqual(file_filter.exclude_patterns, [])
        self.assertEqual(file_filter.max_file_size, 0)

    def test_init_invalid_patterns(self):
        """Test initialization with invalid exclude_patterns."""
        config = {
            "review": {
                "file_filtering": {
                    "enabled": True,
                    "exclude_patterns": "*.md"  # Not a list
                }
            }
        }
        file_filter = FileFilter(config)
        
        # Should disable filtering when patterns are invalid
        self.assertFalse(file_filter.enabled)

    def test_should_exclude_file_pattern(self):
        """Test exclusion based on patterns."""
        file_filter = FileFilter(self.test_config)
        
        # Should exclude markdown file
        self.assertTrue(
            file_filter.should_exclude_file({"filename": "README.md", "size": 1024})
        )
        
        # Should exclude JSON file
        self.assertTrue(
            file_filter.should_exclude_file({"filename": "config.json", "size": 1024})
        )
        
        # Should include Python file
        self.assertFalse(
            file_filter.should_exclude_file({"filename": "src/main.py", "size": 1024})
        )

    def test_should_exclude_file_size(self):
        """Test exclusion based on file size."""
        file_filter = FileFilter(self.test_config)
        
        # Should exclude large Python file
        self.assertTrue(
            file_filter.should_exclude_file({"filename": "src/large.py", "size": 600000})
        )
        
        # Should include small Python file
        self.assertFalse(
            file_filter.should_exclude_file({"filename": "src/small.py", "size": 10240})
        )
        
        # Should handle missing size (include)
        self.assertFalse(
            file_filter.should_exclude_file({"filename": "src/unknown.py"})
        )

    def test_filter_files(self):
        """Test filtering a list of files."""
        file_filter = FileFilter(self.test_config)
        filtered_files = file_filter.filter_files(self.test_files)
        
        # Should include 2 files (small Python file and JS file)
        self.assertEqual(len(filtered_files), 2)
        
        # Check expected filenames
        filenames = [file["filename"] for file in filtered_files]
        self.assertIn("src/main.py", filenames)
        self.assertIn("src/utils.js", filenames)
        
        # Check excluded filenames
        self.assertNotIn("README.md", filenames)
        self.assertNotIn("package.json", filenames)
        self.assertNotIn("LICENSE", filenames)
        self.assertNotIn("src/large_file.py", filenames)

    def test_filter_files_disabled(self):
        """Test filtering when disabled."""
        config = {"review": {"file_filtering": {"enabled": False}}}
        file_filter = FileFilter(config)
        
        filtered_files = file_filter.filter_files(self.test_files)
        
        # Should include all files when disabled
        self.assertEqual(len(filtered_files), len(self.test_files))

    def test_filter_files_empty_list(self):
        """Test filtering an empty list of files."""
        file_filter = FileFilter(self.test_config)
        filtered_files = file_filter.filter_files([])
        
        # Should return empty list
        self.assertEqual(filtered_files, [])


if __name__ == '__main__':
    unittest.main()