#!/usr/bin/env python3
"""
Test script for diagnosing GitHub PR review comment issues.
This script directly tests different methods of creating PR review comments.
"""

import os
import sys
import argparse
import logging
from dotenv import load_dotenv

# Add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Import the utility functions
from src.utils import (
    test_github_review_methods,
    post_review_with_comments,
    calculate_position_in_diff,
    get_pr_diff,
    parse_diff_for_lines
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('github_comment_test.log')
    ]
)

logger = logging.getLogger(__name__)

def main():
    """Run GitHub PR review comment tests"""
    parser = argparse.ArgumentParser(description="Test GitHub PR review comment API")
    parser.add_argument("--repo", help="Repository in owner/repo format")
    parser.add_argument("--pr", help="PR number to test")
    parser.add_argument("--token", help="GitHub token (or set GH_TOKEN env var)")
    parser.add_argument("--method", choices=["all", "test", "review"], default="all", 
                         help="Test method (all, test, review)")
    args = parser.parse_args()
    
    # Load environment variables
    load_dotenv()
    
    # Get GitHub token
    token = args.token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        logger.error("No GitHub token provided. Use --token or set GH_TOKEN env var")
        return 1
    
    # Get repo and PR number
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY")
    pr_num = args.pr or os.environ.get("PR_NUMBER")
    
    if not repo or not pr_num:
        logger.error("Repository and PR number required")
        return 1
    
    # Run the tests
    if args.method in ["all", "test"]:
        logger.info(f"Running full test suite on {repo} PR #{pr_num}")
        success = test_github_review_methods(repo, pr_num, token, f"Test at {import_time}")
        if success:
            logger.info("Test methods complete - check the GitHub PR for results")
        else:
            logger.error("Test methods failed")
    
    if args.method in ["all", "review"]:
        logger.info(f"Testing review with comments on {repo} PR #{pr_num}")
        
        # Get diff and process it
        diff_text = get_pr_diff(repo, pr_num, token)
        if not diff_text:
            logger.error("Failed to get PR diff")
            return 1
        
        file_line_map = parse_diff_for_lines(diff_text)
        if not file_line_map:
            logger.error("Failed to parse diff")
            return 1
        
        # Create test comments for each modified file
        test_comments = []
        for filename, lines in file_line_map.items():
            if lines:
                # Use the first modified line
                line_num, _, _ = lines[0]
                test_comments.append({
                    "path": filename,
                    "line": line_num,
                    "body": f"Test comment on {filename}:{line_num} at {import_time}"
                })
        
        if not test_comments:
            logger.error("No suitable files for test comments")
            return 1
        
        # Post review with comments
        overview_text = f"Test review created at {import_time}"
        success = post_review_with_comments(repo, pr_num, token, test_comments, overview_text)
        
        if success:
            logger.info("Successfully posted review with comments")
        else:
            logger.error("Failed to post review with comments")
    
    return 0

if __name__ == "__main__":
    import_time = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sys.exit(main()) 