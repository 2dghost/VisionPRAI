#!/usr/bin/env python3
"""
Security and error handling focused test runner for the PR AI Reviewer.

This script helps test the enhanced security issue and error handling detection
capabilities by focusing on those specific test cases.
"""

import os
import sys
import argparse
import logging
from typing import List, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

try:
    from src.testing.run_test_loop import run_test_loop
    from src.testing.test_cases import TEST_SUITES
except ImportError:
    from testing.run_test_loop import run_test_loop
    from testing.test_cases import TEST_SUITES

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SECURITY_ERROR_TESTS = [
    # Security test cases
    "sql_injection",
    "path_traversal",
    "command_injection",
    "hardcoded_secrets",
    # Error handling test cases
    "missing_error_handling"
]

def main():
    """
    Run the security and error handling focused tests.
    """
    parser = argparse.ArgumentParser(description="Run security and error handling tests for the AI PR Reviewer")
    parser.add_argument("--ui-only", action="store_true", help="Test only UI integration (GitHub comment placement)")
    parser.add_argument("--save-results", action="store_true", help="Save test results to files")
    args = parser.parse_args()
    
    logger.info("Starting security and error handling focused testing")
    logger.info(f"Tests to run: {', '.join(SECURITY_ERROR_TESTS)}")
    
    # Set up test environment variables if not already set
    if "TEST_REPO" not in os.environ:
        test_repo = input("Enter test repository (format: owner/repo): ")
        os.environ["TEST_REPO"] = test_repo
    
    if "TEST_PR_NUMBER" not in os.environ:
        test_pr = input("Enter test PR number: ")
        os.environ["TEST_PR_NUMBER"] = test_pr
    
    # Create test results directory
    os.makedirs("test-results", exist_ok=True)
    
    # Run the test loop with our specific test cases
    run_test_loop(
        test_cases=SECURITY_ERROR_TESTS,
        ui_only=args.ui_only,
        save_results=args.save_results
    )
    
    logger.info("Security and error handling testing completed")

if __name__ == "__main__":
    main() 