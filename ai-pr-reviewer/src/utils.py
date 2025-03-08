"""
Utility functions for the AI PR reviewer.
Handles GitHub API operations and other helper functions.
"""

import os
import re
import logging
from typing import Dict, List, Optional, Tuple, Any, Union

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ai-pr-reviewer")


def get_pr_diff(repo: str, pr_number: str, token: str) -> Optional[str]:
    """
    Fetch the diff for a pull request.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        
    Returns:
        The diff as a string, or None if the request failed
    """
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "Authorization": f"token {token}"
    }
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    
    try:
        logger.info(f"Fetching diff for PR #{pr_number} in {repo}")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error(f"Failed to fetch PR diff: {e}")
        return None


def get_pr_files(repo: str, pr_number: str, token: str) -> List[Dict[str, Any]]:
    """
    Get list of files changed in the PR.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        
    Returns:
        List of files with their details
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}"
    }
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
    
    try:
        logger.info(f"Fetching files for PR #{pr_number} in {repo}")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch PR files: {e}")
        return []


def post_review_comment(repo: str, pr_number: str, token: str, review_text: str) -> bool:
    """
    Post a review comment on a pull request.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        review_text: The review text to post
        
    Returns:
        True if the comment was posted successfully, False otherwise
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}"
    }
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    data = {"body": review_text, "event": "COMMENT"}
    
    try:
        logger.info(f"Posting review comment for PR #{pr_number} in {repo}")
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.status_code == 201
    except requests.RequestException as e:
        logger.error(f"Failed to post review comment: {e}")
        return False


def post_line_comments(
    repo: str, 
    pr_number: str, 
    token: str, 
    comments: List[Dict[str, Any]]
) -> bool:
    """
    Post line-specific comments on a pull request.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        comments: List of comments with file path, line number, and body
                 Format: [{"path": "file.py", "line": 10, "body": "Comment text"}]
        
    Returns:
        True if the comments were posted successfully, False otherwise
    """
    if not comments:
        return True
        
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}"
    }
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    
    # Convert our simplified format to GitHub's format
    gh_comments = []
    for comment in comments:
        gh_comments.append({
            "path": comment["path"],
            "line": comment["line"],
            "body": comment["body"]
        })
    
    data = {
        "comments": gh_comments,
        "event": "COMMENT"
    }
    
    try:
        logger.info(f"Posting {len(comments)} line comments for PR #{pr_number} in {repo}")
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.status_code == 201
    except requests.RequestException as e:
        logger.error(f"Failed to post line comments: {e}")
        return False


def parse_diff_for_lines(diff_text: str) -> Dict[str, List[Tuple[int, str]]]:
    """
    Parse a diff to extract file paths and line numbers.
    Useful for posting line-specific comments.
    
    Args:
        diff_text: The diff text from GitHub
        
    Returns:
        Dictionary mapping file paths to list of (line_number, line_content) tuples
    """
    result = {}
    current_file = None
    line_number = 0
    
    # Extract filename and line information from diff
    for line in diff_text.split('\n'):
        # New file in diff
        if line.startswith('+++'):
            path_match = re.match(r'\+\+\+ b/(.*)', line)
            if path_match:
                current_file = path_match.group(1)
                result[current_file] = []
                line_number = 0
        # Line numbers in hunk header
        elif line.startswith('@@'):
            match = re.search(r'@@ -\d+,\d+ \+(\d+),\d+ @@', line)
            if match:
                line_number = int(match.group(1)) - 1  # -1 because we'll increment before using
        # Added or context lines (not removed lines)
        elif line.startswith('+') or line.startswith(' '):
            if current_file is not None:
                line_number += 1
                # Only include added lines (not context lines)
                if line.startswith('+'):
                    result[current_file].append((line_number, line[1:]))
    
    return result


def extract_code_blocks(text: str) -> List[str]:
    """
    Extract code blocks from markdown text.
    
    Args:
        text: Markdown text with code blocks
        
    Returns:
        List of code blocks without the markdown backticks
    """
    code_blocks = []
    pattern = r'```(?:\w+)?\n(.*?)```'
    matches = re.finditer(pattern, text, re.DOTALL)
    
    for match in matches:
        code_blocks.append(match.group(1).strip())
    
    return code_blocks