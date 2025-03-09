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


def post_review_sections(repo: str, pr_number: str, token: str, review_text: str, 
                         split_sections: bool = False) -> bool:
    """
    Post a review on a pull request, optionally splitting into separate comments for sections.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        review_text: The review text to post
        split_sections: Whether to split the review into separate comments by section
        
    Returns:
        True if the comments were posted successfully, False otherwise
    """
    import time
    
    if not split_sections:
        return post_review_comment(repo, pr_number, token, review_text)
    
    # Extract sections using markdown headers
    section_pattern = r'^## (.+?)$(.*?)(?=^## |\Z)'
    matches = list(re.finditer(section_pattern, review_text, re.MULTILINE | re.DOTALL))
    
    overview_sections = []
    file_sections = {}
    recommendation_section = None
    other_sections = []
    
    # First pass: categorize sections
    for match in matches:
        section_title = match.group(1).strip()
        section_content = match.group(2).strip()
        
        if not section_content:
            continue
            
        section_text = f"## {section_title}\n\n{section_content}"
        
        # Identify overview sections
        if section_title in ["Summary", "Overview of Changes", "Overview"]:
            overview_sections.append(section_text)
        # Identify recommendations section
        elif section_title in ["Recommendations", "Next Steps"]:
            recommendation_section = section_text
        # Check if it's a file-specific section (contains filename)
        elif ":" in section_title or "/" in section_title or "." in section_title:
            # Extract the filename from the section title
            filename = section_title.split(":")[0].strip() if ":" in section_title else section_title.strip()
            
            # Clean up common prefixes like "File: " or "Analysis: "
            prefixes_to_remove = ["File", "Analysis", "Review", "Feedback"]
            for prefix in prefixes_to_remove:
                if filename.startswith(f"{prefix}:"):
                    filename = filename[len(prefix)+1:].strip()
            
            if filename not in file_sections:
                file_sections[filename] = []
            
            file_sections[filename].append(section_text)
        # Other sections go to a separate list
        else:
            other_sections.append(section_text)
    
    # Look for file mentions within other sections
    file_mention_pattern = r'([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]{1,5})'
    
    # Second pass: check for unlabeled code sections with file mentions
    for section_text in other_sections:
        section_lines = section_text.split("\n", 1)
        if len(section_lines) < 2:
            continue
            
        section_title = section_lines[0].replace("#", "").strip()
        section_content = section_lines[1].strip()
        
        # Try to find file mentions in the content
        file_mentions = re.findall(file_mention_pattern, section_content)
        if file_mentions:
            primary_file = file_mentions[0]  # Use the first file mention
            if primary_file not in file_sections:
                file_sections[primary_file] = []
            file_sections[primary_file].append(section_text)
        else:
            # If no file mentions found, add to overview
            overview_sections.append(section_text)
    
    success = True
    
    # Function to post with rate limit handling
    def post_with_retry(content, description):
        retries = 3
        for i in range(retries):
            try:
                success = post_review_comment(repo, pr_number, token, content)
                if success:
                    # Add a small delay to avoid rate limits
                    time.sleep(0.5)
                    return True
                elif i < retries - 1:
                    # Wait longer before retrying
                    time.sleep(2)
            except Exception as e:
                logger.error(f"Error posting {description} (attempt {i+1}/{retries}): {e}")
                if i < retries - 1:
                    time.sleep(2)
        return False
    
    # Limit the number of comments to post to avoid rate limits
    max_comments = 8  # GitHub has rate limits
    comment_count = 0
    
    # Post overview sections first
    if overview_sections:
        overview_text = "\n\n".join(overview_sections)
        # Truncate if too long
        if len(overview_text) > 65000:
            overview_text = overview_text[:65000] + "\n\n*(Comment truncated due to length)*"
        
        overview_success = post_with_retry(overview_text, "overview comment")
        success = success and overview_success
        comment_count += 1
    
    # Post file-specific sections (limit to avoid rate limits)
    file_items = list(file_sections.items())
    # If too many files, group some together
    if len(file_items) > max_comments - 2:  # Reserve space for overview and recommendations
        grouped_files = {}
        for filename, sections in file_items:
            # Use first directory component as a group key
            if "/" in filename:
                group = filename.split("/")[0]
            else:
                group = "Other Files"
            
            if group not in grouped_files:
                grouped_files[group] = []
            
            grouped_files[group].extend([f"### {filename}", *sections])
        
        # Post grouped comments
        for group, sections in grouped_files.items():
            if comment_count >= max_comments - 1:
                break
                
            group_text = f"## Feedback for files in `{group}`\n\n" + "\n\n".join(sections)
            # Truncate if too long
            if len(group_text) > 65000:
                group_text = group_text[:65000] + "\n\n*(Comment truncated due to length)*"
                
            group_success = post_with_retry(group_text, f"grouped files comment ({group})")
            success = success and group_success
            comment_count += 1
    else:
        # Post individual file comments
        for filename, sections in file_items:
            if comment_count >= max_comments - 1:
                break
                
            file_text = f"## Feedback for `{filename}`\n\n" + "\n\n".join(sections)
            # Truncate if too long
            if len(file_text) > 65000:
                file_text = file_text[:65000] + "\n\n*(Comment truncated due to length)*"
                
            file_success = post_with_retry(file_text, f"file comment ({filename})")
            success = success and file_success
            comment_count += 1
    
    # Post recommendations as their own comment if they exist
    if recommendation_section and comment_count < max_comments:
        # Truncate if too long
        if len(recommendation_section) > 65000:
            recommendation_section = recommendation_section[:65000] + "\n\n*(Comment truncated due to length)*"
            
        rec_success = post_with_retry(recommendation_section, "recommendations comment")
        success = success and rec_success
    
    return success


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