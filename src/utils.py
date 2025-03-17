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
    logger.info("Attempting to extract line comments for GitHub PR review")
    
    try:
        # Make sure we're using the correct import
        try:
            from comment_extractor import CommentExtractor
        except ImportError:
            from src.comment_extractor import CommentExtractor
        
        # Get the diff for the PR to extract line information
        diff_text = get_pr_diff(repo, pr_number, token)
        if diff_text:
            # Parse the diff to get file and line information
            file_line_map = parse_diff_for_lines(diff_text)
            logger.info(f"Parsed diff with {len(file_line_map)} files")
            
            # Extract line-specific comments
            extractor = CommentExtractor()
            line_comments = extractor.extract_line_comments(review_text, file_line_map)
            
            if line_comments:
                logger.info(f"Extracted {len(line_comments)} line-specific comments - using new review API")
                
                # Post using the new implementation
                success = post_review_with_comments(repo, pr_number, token, line_comments, review_text)
                if success:
                    logger.info("Successfully posted review with comments using new API")
                    return True
                else:
                    logger.warning("Failed to post review with comments using new API - falling back")
            else:
                logger.warning("No line comments extracted from review text")
        else:
            logger.warning("Could not get PR diff")
    except Exception as e:
        logger.error(f"Failed to extract line comments: {str(e)}")
        # Continue with standard comment posting
    
    # If we couldn't extract line comments or there was an error, fall back to standard comment
    logger.info("Falling back to standard review comment")
    return post_review_comment(repo, pr_number, token, review_text)


def post_line_comments(repo: str, pr_number: str, token: str, comments: List[Dict], overview_text: Optional[str] = None) -> bool:
    """
    Post line-specific comments on a PR.
    
    Args:
        repo: The repository name in the format "owner/repo"
        pr_number: The pull request number
        token: GitHub API token
        comments: List of comment dictionaries with keys: path, line, position, body
        overview_text: Optional overview text to post at the top of the review
        
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Posting {len(comments)} line comments to PR #{pr_number} in {repo}")
    
    if not comments:
        logger.warning("No comments to post")
        return True
    
    try:
        # Group comments by file for better organization
        comments_by_file = {}
        for comment in comments:
            file_path = comment.get("path", "unknown")
            if file_path not in comments_by_file:
                comments_by_file[file_path] = []
            comments_by_file[file_path].append(comment)
            
        logger.info(f"Comments grouped by file: {len(comments_by_file)} files")
        
        # For most GitHub instances, use the draft review approach
        logger.info("Using draft review approach with file-specific grouping")
        return create_review_with_individual_comments(repo, pr_number, token, comments, overview_text)
    except Exception as e:
        logger.error(f"Error posting line comments: {str(e)}", exc_info=True)
        return False


def create_review_with_individual_comments(repo: str, pr_number: str, token: str, 
                                         comments: List[Dict], overview_text: Optional[str] = None) -> bool:
    """
    Create a review with individual comments through the GitHub API.
    This creates a draft review, adds comments to it, then submits it.
    
    Args:
        repo: The repository in format owner/repo
        pr_number: The PR number
        token: GitHub API token
        comments: List of comment dicts with keys: path, line, position, body
        overview_text: Optional overview text to include at the top of the review
        
    Returns:
        True if successful, False otherwise
    """
    logger.info("*** USING DRAFT REVIEW APPROACH: This creates a draft review, adds comments, then submits it ***")
    
    # Exponential backoff retry parameters
    max_attempts = 5
    base_wait_time = 2  # seconds
    
    for attempt in range(1, max_attempts + 1):
        try:
            # First, check for existing reviews
            existing_reviews_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28"
            }
            
            logger.info(f"Checking for existing reviews on PR #{pr_number}")
            
            existing_response = requests.get(existing_reviews_url, headers=headers)
            existing_response.raise_for_status()
            existing_reviews = existing_response.json()
            
            # Filter for pending reviews by the bot (assume github-actions[bot])
            pending_bot_reviews = [
                review for review in existing_reviews 
                if review.get("state") == "PENDING" and 
                review.get("user", {}).get("login") == "github-actions[bot]"
            ]
            
            # If we have a pending review, use it; otherwise create a new one
            if pending_bot_reviews:
                logger.info(f"Found {len(pending_bot_reviews)} pending bot reviews, using the most recent one")
                # Use the most recent pending review
                review_id = pending_bot_reviews[-1].get("id")
                logger.info(f"Using existing pending review ID: {review_id}")
            else:
                # Create a new draft review
                logger.info("Creating a new draft review")
                create_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
                
                # Start a new review
                create_data = {"event": "PENDING"}
                create_response = requests.post(create_url, headers=headers, json=create_data)
                create_response.raise_for_status()
                review_data = create_response.json()
                review_id = review_data.get("id")
                
                if not review_id:
                    logger.error("Failed to get review ID from response")
                    logger.debug(f"Response data: {review_data}")
                    return False
                
                logger.info(f"Created new review with ID: {review_id}")
                
                # Sleep briefly to ensure the review is created before we add comments
                time.sleep(1)
            
            # Now add comments to the review
            logger.info(f"Adding {len(comments)} comments to review")
            
            # Build the review comments by file
            comments_by_file = {}
            for comment in comments:
                file_path = comment.get("path", "unknown")
                if file_path not in comments_by_file:
                    comments_by_file[file_path] = []
                comments_by_file[file_path].append(comment)
            
            # Process each file's comments
            for file_path, file_comments in comments_by_file.items():
                for i, comment in enumerate(file_comments):
                    try:
                        add_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews/{review_id}/comments"
                        
                        comment_data = {
                            "path": comment.get("path"),
                            "position": comment.get("position"),
                            "body": comment.get("body"),
                            "line": comment.get("line")
                        }
                        
                        # Add side information (default to RIGHT)
                        if "side" in comment:
                            comment_data["side"] = comment.get("side")
                        else:
                            comment_data["side"] = "RIGHT"
                            
                        # Handle multi-line comments if start_line and start_side are provided
                        if "start_line" in comment and "start_side" in comment:
                            comment_data["start_line"] = comment.get("start_line")
                            comment_data["start_side"] = comment.get("start_side")

                        # Add the comment to the review
                        add_response = requests.post(add_url, headers=headers, json=comment_data)
                        add_response.raise_for_status()
                        
                        # Brief sleep to avoid rate limiting
                        if i > 0 and i % 10 == 0:
                            logger.debug(f"Added {i}/{len(file_comments)} comments for {file_path}, pausing briefly")
                            time.sleep(1)
                    except requests.exceptions.RequestException as e:
                        # Log the error but continue with other comments
                        logger.warning(f"Error adding comment {i+1}/{len(file_comments)} for {file_path}: {str(e)}")
                        if hasattr(e, 'response') and e.response is not None:
                            logger.debug(f"Response status: {e.response.status_code}, content: {e.response.text[:200]}")
                
                # Brief sleep after each file's comments
                logger.debug(f"Completed comments for {file_path}")
                time.sleep(0.5)
            
            # Finally, submit the review
            submit_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews/{review_id}/events"
            
            # Prepare the submission data with the body containing the overview text
            submit_data = {
                "body": overview_text if overview_text else "AI code review",
                "event": "COMMENT"  # Can be APPROVE, REQUEST_CHANGES, or COMMENT
            }
            
            logger.info("Submitting review with comments")
            submit_response = requests.post(submit_url, headers=headers, json=submit_data)
            submit_response.raise_for_status()
            
            logger.info("Successfully posted review with comments")
            return True
            
        except requests.exceptions.RequestException as e:
            wait_time = base_wait_time * (2 ** (attempt - 1))
            
            # Check if we're hitting rate limits
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 403:
                rate_limit_remaining = e.response.headers.get('X-RateLimit-Remaining', '?')
                rate_limit_reset = e.response.headers.get('X-RateLimit-Reset', '?')
                
                logger.warning(f"Possible rate limit hit: Remaining: {rate_limit_remaining}, Reset: {rate_limit_reset}")
                
                # If we know when the rate limit resets, wait until then plus a little buffer
                if rate_limit_reset != '?' and rate_limit_reset.isdigit():
                    reset_time = int(rate_limit_reset)
                    current_time = int(time.time())
                    if reset_time > current_time:
                        wait_time = min(max(reset_time - current_time + 5, wait_time), 300)  # Cap at 5 minutes
            
            if attempt < max_attempts:
                logger.warning(f"Attempt {attempt} failed: {str(e)}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"Failed after {max_attempts} attempts: {str(e)}")
                if hasattr(e, 'response') and e.response is not None:
                    logger.debug(f"Final error response: {e.response.status_code}, {e.response.text[:500]}")
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
    logger.info(f"*** CALLING post_review_with_comments with {len(comments)} comments ***")
    if overview_text:
        logger.info("Using provided overview text for the review")
    
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
            logger.debug(f"Calculated position {position} for {path}:{line_num}")
        
        if position is not None:
            review_comment = {
                "path": path,
                "position": position,
                "body": comment["body"],
                "side": "RIGHT"    # Always comment on the right side (new version)
            }
                
            # Handle multi-line comments if present
            if "start_line" in comment:
                review_comment["start_line"] = int(comment["start_line"])
                review_comment["start_side"] = comment.get("start_side", "RIGHT")
            
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
    
    # Use the draft review approach (Method 2) which is more reliable
    logger.info("Using draft review approach for posting comments")
    # Pass the overview text for use in the review
    return create_review_with_individual_comments(repo, pr_number, token, comments, latest_commit_sha, overview_text)


def test_github_review_methods(repo: str, pr_number: str, token: str, test_text: str = "Test comment") -> bool:
    """
    Test various methods for posting GitHub PR reviews with comments.
    This function tries multiple approaches to help diagnose issues.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        test_text: Test text to include in comments
        
    Returns:
        True if any test succeeded, False if all failed
    """
    logger.info("Starting GitHub review methods test")
    
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    # Test 1: Get the latest commit SHA and diff
    try:
        # Get commit SHA
        commits_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/commits"
        commits_response = requests.get(commits_url, headers=headers)
        commits_response.raise_for_status()
        commit_sha = commits_response.json()[-1]["sha"]
        
        # Get diff
        files_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
        files_response = requests.get(files_url, headers=headers)
        files_response.raise_for_status()
        files = files_response.json()
        
        if not files:
            logger.error("No files found in PR")
            return False
            
        # Select first file with a patch
        test_file = None
        for file in files:
            if file.get("patch"):
                test_file = file
                break
                
        if not test_file:
            logger.error("No file with patch found in PR")
            return False
            
        filename = test_file["filename"]
        patch = test_file["patch"]
        
        # Parse patch to find a suitable line number
        line_num = None
        position = None
        
        patch_lines = patch.split("\n")
        for i, line in enumerate(patch_lines):
            if line.startswith("+") and not line.startswith("+++"):
                # Found an added line - find its line number
                for j in range(i, -1, -1):
                    if patch_lines[j].startswith("@@"):
                        # Extract the line number from hunk header
                        parts = patch_lines[j].split(" ")
                        if len(parts) >= 3 and parts[2].startswith("+"):
                            new_info = parts[2][1:]
                            new_start = int(new_info.split(",")[0] if "," in new_info else new_info)
                            # Count lines from hunk start to our line
                            added_lines = 0
                            for k in range(j+1, i+1):
                                if not patch_lines[k].startswith("-"):
                                    added_lines += 1
                            line_num = new_start + added_lines - 1
                            position = i + 1  # Position in diff (1-indexed)
                            break
                if line_num:
                    break
        
        if not line_num or not position:
            logger.error("Could not find a suitable line to comment on")
            return False
            
        logger.info(f"Test will use file: {filename}, line: {line_num}, position: {position}")
        
        # Test 2: Method 1 - Review with inline comments
        try:
            logger.info("Testing Method 1: Review with inline comments")
            review_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
            
            review_data = {
                "commit_id": commit_sha,
                "body": f"Test review with inline comments - {test_text}",
                "event": "COMMENT",
                "comments": [{
                    "path": filename,
                    "position": position,
                    "body": f"Method 1 - Test inline comment - {test_text}"
                }]
            }
            
            response = requests.post(review_url, headers=headers, json=review_data)
            status_code = response.status_code
            logger.info(f"Method 1 status code: {status_code}")
            logger.debug(f"Method 1 response: {response.text}")
            
            if status_code < 400:
                logger.info("Method 1 succeeded")
        except Exception as e:
            logger.error(f"Method 1 error: {str(e)}")
        
        # Test 3: Method 2 - Draft review with comments
        try:
            logger.info("Testing Method 2: Draft review with comments")
            review_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
            
            # Create empty pending review
            draft_data = {
                "commit_id": commit_sha,
                "body": "",
                "event": "PENDING"
            }
            
            draft_response = requests.post(review_url, headers=headers, json=draft_data)
            if draft_response.status_code >= 400:
                logger.error(f"Method 2 failed to create draft review: {draft_response.status_code} - {draft_response.text}")
            else:
                review_id = draft_response.json().get("id")
                
                if not review_id:
                    logger.error("Method 2 failed to get review ID")
                else:
                    # Add a comment to the review
                    comment_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews/{review_id}/comments"
                    comment_data = {
                        "path": filename,
                        "position": position,
                        "body": f"Method 2 - Test comment on draft review - {test_text}"
                    }
                    
                    comment_response = requests.post(comment_url, headers=headers, json=comment_data)
                    if comment_response.status_code >= 400:
                        logger.error(f"Method 2 failed to add comment: {comment_response.status_code} - {comment_response.text}")
                    else:
                        # Submit the review
                        submit_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews/{review_id}/events"
                        submit_data = {
                            "body": f"Method 2 - Test draft review submission - {test_text}",
                            "event": "COMMENT"
                        }
                        
                        submit_response = requests.post(submit_url, headers=headers, json=submit_data)
                        status_code = submit_response.status_code
                        logger.info(f"Method 2 status code: {status_code}")
                        logger.debug(f"Method 2 response: {submit_response.text}")
                        
                        if status_code < 400:
                            logger.info("Method 2 succeeded")
        except Exception as e:
            logger.error(f"Method 2 error: {str(e)}")
        
        # Test 4: Method 3 - Direct comment on PR
        try:
            logger.info("Testing Method 3: Direct comments on PR")
            comment_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments"
            
            comment_data = {
                "body": f"Method 3 - Direct PR comment - {test_text}",
                "commit_id": commit_sha,
                "path": filename,
                "position": position
            }
            
            response = requests.post(comment_url, headers=headers, json=comment_data)
            status_code = response.status_code
            logger.info(f"Method 3 status code: {status_code}")
            logger.debug(f"Method 3 response: {response.text}")
            
            if status_code < 400:
                logger.info("Method 3 succeeded")
        except Exception as e:
            logger.error(f"Method 3 error: {str(e)}")
        
        return True
    except Exception as e:
        logger.error(f"Test failed: {str(e)}")
        return False