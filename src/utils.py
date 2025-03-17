"""
Utility functions for the AI PR reviewer.
Handles GitHub API operations and other helper functions.
"""

import os
import re
import logging
import json
import time
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
        "Authorization": f"Bearer {token}"
    }
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
    
    try:
        logger.info(f"Fetching diff for PR #{pr_number} in {repo}")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        # Extract patch content from each file
        files = response.json()
        diff_content = []
        
        for file in files:
            if 'patch' in file:
                diff_content.append(f"diff --git a/{file['filename']} b/{file['filename']}\n{file['patch']}")
        
        return '\n'.join(diff_content) if diff_content else None
    except requests.RequestException as e:
        logger.error(f"Failed to fetch PR diff: {e}")
        return None


def get_pr_files(repo: str, pr_number: str, token: str) -> List[Dict[str, Any]]:
    """
    Fetch the list of files changed in a pull request.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        
    Returns:
        List of file information dictionaries
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}"
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
        True if successful, False otherwise
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}"
    }
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    
    data = {
        "body": review_text,
        "event": "COMMENT"
    }
    
    try:
        logger.info(f"Posting review comment on PR #{pr_number} in {repo}")
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return True
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
    
    # Try to extract line-specific comments from the review text
    try:
        from comment_extractor import CommentExtractor
        
        # Get the diff for the PR to extract line information
        diff_text = get_pr_diff(repo, pr_number, token)
        if diff_text:
            # Parse the diff to get file and line information
            file_line_map = parse_diff_for_lines(diff_text)
            
            # Extract line-specific comments
            extractor = CommentExtractor()
            line_comments = extractor.extract_line_comments(review_text, file_line_map)
            
            if line_comments:
                logger.info(f"Extracted {len(line_comments)} line-specific comments from review text")
                
                # Post the line comments using the new implementation
                return post_review_with_comments(repo, pr_number, token, line_comments, review_text)
    except Exception as e:
        logger.error(f"Failed to extract line comments: {e}")
        # Continue with standard comment posting
    
    # If we couldn't extract line comments or there was an error, fall back to standard comment
    if not split_sections:
        return post_review_comment(repo, pr_number, token, review_text)
    
    # Use a single comment approach - much simpler and more reliable
    if True:  # Make this the default behavior
        # Post a standard review comment with all content
        return post_review_comment(repo, pr_number, token, review_text)


def post_line_comments(
    repo: str, 
    pr_number: str, 
    token: str, 
    comments: List[Dict[str, Any]],
    overview_text: str = ""
) -> bool:
    """
    Post line-specific review comments on a pull request.
    
    This function wraps post_review_with_comments to maintain backward compatibility.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        comments: List of comment dictionaries with 'path', 'line', and 'body' keys
        overview_text: Optional text for the overall review summary
        
    Returns:
        True if successful, False otherwise
    """
    return post_review_with_comments(repo, pr_number, token, comments, overview_text)


def create_review_with_individual_comments(repo, pr_number, token, comments, commit_sha):
    """Helper function to create a review and add comments one by one."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    # First create an empty review to add comments to
    try:
        review_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
        
        # Create an empty review - this gives us a review_id to add comments to
        review_data = {
            "commit_id": commit_sha,
            "event": "PENDING",  # Create a draft review
            "body": f"AI PR Review - Creating individual comments..."
        }
        
        logger.info("Creating empty review for individual comments")
        
        review_response = requests.post(review_url, headers=headers, json=review_data)
        
        if review_response.status_code >= 400:
            error_body = review_response.text
            logger.error(f"Failed to create empty review: HTTP {review_response.status_code}: {error_body}")
            return False
            
        review_id = review_response.json().get("id")
        if not review_id:
            logger.error("Failed to get review ID from response")
            return False
            
        logger.info(f"Created empty review #{review_id}")
    except Exception as e:
        logger.error(f"Error creating empty review: {str(e)}")
        return False
    
    # Add comments to the review one by one
    comments_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews/{review_id}/comments"
    success = True
    
    for i, comment in enumerate(comments):
        try:
            # Each comment needs the commit_id
            comment_data = {
                "path": comment["path"],
                "body": comment["body"],
                "line": comment["line"],
                "side": comment["side"]
            }
            
            # Add optional fields if present
            if "start_line" in comment:
                comment_data["start_line"] = comment["start_line"]
                comment_data["start_side"] = comment.get("start_side", "RIGHT")
            
            logger.debug(f"Adding comment {i+1}/{len(comments)}: {comment['path']}:{comment['line']}")
            
            comment_response = requests.post(comments_url, headers=headers, json=comment_data)
            
            if comment_response.status_code >= 400:
                logger.error(f"Failed to add comment {i+1}: HTTP {comment_response.status_code}: {comment_response.text}")
                # Don't fail immediately - try to add other comments
                success = False
            else:
                logger.debug(f"Successfully added comment {i+1}/{len(comments)}")
                
            # Add a delay to avoid rate limits
            time.sleep(1.0)  # Increased delay to avoid rate limiting
        except Exception as e:
            logger.error(f"Error adding comment {i+1}: {str(e)}")
            success = False
    
    # Submit the review to publish the comments
    try:
        submit_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews/{review_id}/events"
        
        submit_data = {
            "body": f"AI PR Review - I've reviewed the changes and left {len(comments)} specific comments on the code.",
            "event": "COMMENT"
        }
        
        logger.info(f"Submitting review #{review_id}")
        
        submit_response = requests.post(submit_url, headers=headers, json=submit_data)
        
        if submit_response.status_code >= 400:
            logger.error(f"Failed to submit review: HTTP {submit_response.status_code}: {submit_response.text}")
            return False
            
        logger.info(f"Successfully submitted review with {len(comments)} comments")
        
        # Verify the comments were created correctly
        try:
            verify_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews/{review_id}"
            verify_response = requests.get(verify_url, headers=headers)
            
            if verify_response.status_code >= 400:
                logger.warning(f"Could not verify review: HTTP {verify_response.status_code}")
            else:
                review_data = verify_response.json()
                comments_count = len(review_data.get("comments", []))
                logger.info(f"Verified review #{review_id} has {comments_count} comments")
        except Exception as e:
            logger.warning(f"Error verifying review: {str(e)}")
        
        return success
    except Exception as e:
        logger.error(f"Failed to submit review: {str(e)}")
        return False


def parse_diff_for_lines(diff_text: str) -> Dict[str, List[Tuple[int, int, str]]]:
    """
    Parse a diff to extract file paths and line numbers.
    Useful for posting line-specific comments.
    
    Args:
        diff_text: The diff text from GitHub
        
    Returns:
        Dictionary mapping file paths to list of (line_number, position, line_content) tuples
        where position is the line's position in the diff
    """
    result = {}
    current_file = None
    line_number = 0
    position = 0  # Track position in the diff (still useful for debugging)
    
    # Extract filename and line information from diff
    lines = diff_text.split('\n')
    
    # Process the diff to extract file paths and line numbers
    for line in lines:
        # New file in diff
        if line.startswith('diff --git'):
            position = 0  # Reset position counter for each new file
            continue
            
        # New file path
        if line.startswith('+++'):
            path_match = re.match(r'\+\+\+ b/(.*)', line)
            if path_match:
                current_file = path_match.group(1)
                result[current_file] = []
                line_number = 0
                logger.debug(f"Processing file: {current_file}")
            position += 1
            continue
            
        # Skip old file path marker
        if line.startswith('---'):
            position += 1
            continue
            
        # Parse hunk header for line numbers
        if line.startswith('@@'):
            match = re.search(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if match:
                line_number = int(match.group(1)) - 1  # -1 because we increment before using
                logger.debug(f"Found hunk header, new line number start: {line_number + 1}")
            position += 1
            continue
            
        # Increment position for each line in the diff
        position += 1
        
        # Skip removal lines (-)
        if line.startswith('-'):
            continue
            
        # Process addition and context lines
        if line.startswith('+') or not line.startswith('\\'):  # Skip "No newline" markers
            if current_file:
                line_number += 1
                content = line[1:] if line.startswith('+') else line
                # Store line number, position, and content
                result[current_file].append((line_number, position, content))
    
    # Log file mapping summary
    for file_path, lines in result.items():
        logger.debug(f"Mapped {len(lines)} lines for file {file_path}")
    
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


def calculate_position_in_diff(patch: str, target_line: int) -> Optional[int]:
    """
    Calculate the position in a diff for a given line number.
    
    The position is the line number in the diff, not the line number in the file.
    This is required by GitHub's API for line comments.
    
    Args:
        patch: The patch string from GitHub's API
        target_line: The line number in the new file to find the position for
        
    Returns:
        The position in the diff, or None if the line is not found
    """
    if not patch:
        return None
    
    # Split the patch into lines
    lines = patch.split('\n')
    
    # Start at position 1 (GitHub's API is 1-indexed for positions)
    position = 1
    current_line = 0
    
    # Parse the hunk headers to find the right position
    for line in lines:
        position += 1  # Increment position for each line in the diff
        
        # Check if this is a hunk header
        if line.startswith('@@'):
            # Extract the new file start line number (format: @@ -old,count +new,count @@)
            parts = line.split(' ')
            if len(parts) >= 3 and parts[2].startswith('+'):
                new_info = parts[2][1:]  # Remove the + sign
                new_start = int(new_info.split(',')[0] if ',' in new_info else new_info)
                current_line = new_start
                continue
        
        # Skip removed lines (starting with '-')
        if line.startswith('-'):
            position -= 1  # Don't count removed lines in position
            continue
        
        # For context/added lines, check if we found the target
        if not line.startswith('@@'):
            if current_line == target_line:
                return position - 1  # Return position (adjust for GitHub indexing)
            
            # Only increment line number for non-removed lines
            if not line.startswith('-'):
                current_line += 1
    
    # If we get here, the target line was not found in the diff
    logger.warning(f"Line {target_line} not found in the diff")
    return None


def post_review_with_comments(repo: str, pr_number: str, token: str, comments: List[Dict[str, Any]], overview_text: str = "") -> bool:
    """
    Post a GitHub review with line-specific comments.
    
    This function creates a single review with all comments attached to specific lines,
    ensuring they appear properly in the 'Files Changed' tab.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        comments: List of comment dictionaries with 'path', 'line', and 'body' keys
        overview_text: Optional text for the overall review summary
        
    Returns:
        True if successful, False otherwise
    """
    if not comments:
        return post_review_comment(repo, pr_number, token, overview_text)
        
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    # Get the latest commit SHA
    try:
        commits_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/commits"
        commits_response = requests.get(commits_url, headers=headers)
        commits_response.raise_for_status()
        latest_commit_sha = commits_response.json()[-1]["sha"]
        logger.debug(f"Using latest commit SHA: {latest_commit_sha}")
    except Exception as e:
        logger.error(f"Failed to get latest commit SHA: {str(e)}")
        return False
    
    # Get file patches for position calculation
    try:
        files_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
        files_response = requests.get(files_url, headers=headers)
        files_response.raise_for_status()
        files = files_response.json()
        
        # Map files to their patches
        file_patches = {file["filename"]: file.get("patch", "") for file in files}
        logger.debug(f"Found {len(files)} files in PR: {', '.join(file_patches.keys())}")
    except Exception as e:
        logger.error(f"Failed to get file patches: {str(e)}")
        return False
    
    # Format comments with correct positions
    review_comments = []
    for comment in comments:
        path = comment["path"]
        line_num = int(comment.get("line", 1))
        
        # Calculate position from patch
        position = None
        if path in file_patches:
            position = calculate_position_in_diff(file_patches[path], line_num)
        
        if position is not None:
            review_comment = {
                "path": path,
                "position": position,
                "body": comment["body"]
            }
            # Handle multi-line comments if present
            if "start_line" in comment:
                review_comment["start_line"] = int(comment["start_line"])
                review_comment["start_side"] = comment.get("start_side", "RIGHT")
                review_comment["side"] = comment.get("side", "RIGHT")
            
            review_comments.append(review_comment)
            logger.debug(f"Added comment for {path}:{line_num} at position {position}")
        else:
            logger.warning(f"Could not calculate position for {path}:{line_num}, skipping comment")
    
    # If we didn't create any valid review comments, post a regular comment
    if not review_comments:
        logger.warning("No valid review comments could be created, posting regular comment instead")
        combined_text = overview_text
        if comments:
            combined_text += "\n\n" + "\n\n".join([f"**{c['path']}:{c['line']}**\n{c['body']}" for c in comments])
        return post_review_comment(repo, pr_number, token, combined_text)
    
    # Create the review with all comments
    try:
        review_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
        review_data = {
            "commit_id": latest_commit_sha,
            "body": overview_text,
            "event": "COMMENT",
            "comments": review_comments
        }
        
        logger.info(f"Creating review with {len(review_comments)} comments")
        response = requests.post(review_url, headers=headers, json=review_data)
        
        if response.status_code >= 400:
            error_body = response.text
            logger.error(f"Failed to create review: HTTP {response.status_code}: {error_body}")
            return False
        
        logger.info(f"Successfully created review with {len(review_comments)} comments")
        return True
    except Exception as e:
        logger.error(f"Error creating review: {str(e)}")
        return False