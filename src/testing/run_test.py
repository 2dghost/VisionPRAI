#!/usr/bin/env python3
"""
Simple test script to verify GitHub PR comment functionality.
This script directly uses the environment variables to test the PR review comment system.
"""

import os
import sys
import logging

# Add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Import the utility functions
from src.utils import (
    post_review_with_comments, 
    create_review_with_individual_comments,
    get_pr_diff,
    parse_diff_for_lines
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    """Run a simple test of the GitHub PR comment functionality."""
    # Get GitHub token from environment
    token = os.environ.get("GH_TOKEN")
    if not token:
        logger.error("No GitHub token found in GH_TOKEN environment variable")
        return 1
    
    # Repository and PR information
    repo = "2dghost/VisionPRAI"
    pr_number = "8"
    
    # Log configuration
    logger.info(f"Testing GitHub PR comments on {repo} PR #{pr_number}")
    
    # Create test comments
    test_comments = [
        {
            "path": "src/utils.py",
            "line": 100,
            "body": "Test comment on utils.py using draft review method"
        },
        {
            "path": "src/comment_extractor.py",
            "line": 100,
            "body": "Test comment on comment_extractor.py using draft review method"
        }
    ]
    
    # Post comments using draft review method
    logger.info("Posting comments using draft review method...")
    
    # Get the latest commit SHA
    import requests
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    try:
        commits_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/commits"
        commits_response = requests.get(commits_url, headers=headers)
        commits_response.raise_for_status()
        commit_sha = commits_response.json()[-1]["sha"]
        
        # Try creating comments
        success = create_review_with_individual_comments(repo, pr_number, token, test_comments, commit_sha)
        
        if success:
            logger.info("Successfully posted comments!")
        else:
            logger.error("Failed to post comments")
            return 1
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 