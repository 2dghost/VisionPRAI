#!/usr/bin/env python3
"""
Test runner for language detection functionality.
Tests the language detector against predefined test cases.
"""

import os
import sys
import json
import logging
import argparse
from typing import Dict, List, Any, Tuple

# Add the parent directory to sys.path to support both local and GitHub Actions environments
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

try:
    # Try direct imports first (for GitHub Actions and package usage)
    from language_detector import LanguageDetector, detect_language, detect_issues
except ImportError:
    # Fall back to src-prefixed imports (for local development)
    from src.language_detector import LanguageDetector, detect_language, detect_issues

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_test_cases(test_file: str) -> Dict[str, Any]:
    """
    Load test cases from a JSON file.
    
    Args:
        test_file: Path to the test file
        
    Returns:
        Dictionary containing test cases
    """
    try:
        with open(test_file, 'r') as f:
            test_data = json.load(f)
        return test_data
    except Exception as e:
        logger.error(f"Failed to load test cases from {test_file}: {str(e)}")
        return {}


def run_tests(test_data: Dict[str, Any]) -> Tuple[int, int]:
    """
    Run tests against the language detector.
    
    Args:
        test_data: Dictionary containing test cases
        
    Returns:
        Tuple of (passed_tests, total_tests)
    """
    if not test_data or "test_cases" not in test_data:
        logger.error("Invalid test data format")
        return 0, 0
    
    test_cases = test_data.get("test_cases", [])
    passed = 0
    total = len(test_cases)
    
    # Initialize detector
    detector = LanguageDetector()
    
    for i, test_case in enumerate(test_cases, 1):
        logger.info(f"Running test {i}/{total}: {test_case.get('name', 'Unnamed')}")
        
        # Extract test case data
        name = test_case.get("name", "unnamed")
        language = test_case.get("language", "unknown")
        code = test_case.get("code", "")
        expected_issues = test_case.get("expected_issues", [])
        
        # Create a temporary file for testing
        temp_file = f"temp_test_{name}.{language}"
        
        try:
            # Write code to temporary file
            with open(temp_file, 'w') as f:
                f.write(code)
            
            # Detect language
            detected_language = detector.detect_language(temp_file)
            
            # Check language detection
            if detected_language != language:
                logger.warning(f"Language detection failed for {name}: "
                              f"Expected {language}, got {detected_language}")
            
            # Detect issues
            detected_issues = detector.detect_issues(temp_file, code)
            
            # Flatten detected issues to get category names
            detected_categories = list(detected_issues.keys())
            
            # Check if all expected issues were detected
            all_expected_detected = all(issue in detected_categories for issue in expected_issues)
            
            if all_expected_detected:
                logger.info(f"Test {name} PASSED - All expected issues detected")
                passed += 1
            else:
                logger.warning(f"Test {name} FAILED - Not all expected issues detected")
                logger.warning(f"Expected: {expected_issues}")
                logger.warning(f"Detected: {detected_categories}")
            
            # Show detailed detection results
            logger.info(f"Detailed detection results for {name}:")
            for category, issues in detected_issues.items():
                logger.info(f"  {category}: {len(issues)} issue(s)")
                for line_num, line_text in issues[:3]:  # Show first 3 issues max
                    logger.info(f"    Line {line_num}: {line_text[:50]}...")
                if len(issues) > 3:
                    logger.info(f"    ... and {len(issues) - 3} more")
        
        except Exception as e:
            logger.error(f"Error running test {name}: {str(e)}")
        
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file):
                os.remove(temp_file)
    
    # Print summary
    success_rate = (passed / total * 100) if total > 0 else 0
    logger.info(f"Test summary: {passed}/{total} tests passed ({success_rate:.1f}%)")
    
    return passed, total


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Test language detection functionality")
    parser.add_argument("--test-file", default="test_cases/language_detection.json",
                        help="Path to the test case file")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging")
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    
    # Determine test file path
    test_file = args.test_file
    if not os.path.isabs(test_file):
        test_file = os.path.join(os.path.dirname(__file__), test_file)
    
    logger.info(f"Testing language detector using test file: {test_file}")
    
    # Load and run tests
    test_data = load_test_cases(test_file)
    passed, total = run_tests(test_data)
    
    # Return non-zero exit code if any tests failed
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main()) 