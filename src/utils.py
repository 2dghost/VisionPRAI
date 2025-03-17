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
    
    if not split_sections:
        return post_review_comment(repo, pr_number, token, review_text)
    
    # Use a single comment approach - much simpler and more reliable
    if True:  # Make this the default behavior
        # Post a standard review comment with all content
        return post_review_comment(repo, pr_number, token, review_text)
    
    # The following multi-comment approach is currently disabled but kept for reference
    
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
        # Only try once, don't retry automatically
        try:
            logger.info(f"Posting {description}")
            
            # Check content length - GitHub has a hard limit around 65536 chars
            if len(content) > 65000:
                content = content[:65000] + "\n\n*(Comment truncated due to length)*"
                logger.warning(f"{description} was truncated due to length")
            
            # Add a longer delay before posting the last comments to avoid rate limits
            if comment_count >= 4:  # Later comments are more likely to hit rate limits
                logger.info(f"Adding extra delay before posting comment #{comment_count+1}")
                time.sleep(2)
            
            success = post_review_comment(repo, pr_number, token, content)
            # Add a delay to avoid rate limits
            time.sleep(1)
            return success
        except Exception as e:
            logger.error(f"Error posting {description}: {e}")
            return False
    
    # Limit the number of comments to post to avoid rate limits
    max_comments = 5  # Reduced from 8 to avoid hitting GitHub limits
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
    
    # Always group files to reduce comment count
    grouped_files = {}
    
    # Group files by directory
    for filename, sections in file_items:
        # Use first directory component as a group key
        if "/" in filename:
            group = filename.split("/")[0]
        else:
            # Group by file extension
            parts = filename.split(".")
            if len(parts) > 1:
                group = f"{parts[-1].upper()} Files"
            else:
                group = "Other Files"
        
        if group not in grouped_files:
            grouped_files[group] = []
        
        grouped_files[group].extend([f"### {filename}", *sections])
    
    # If still too many groups, consolidate further
    if len(grouped_files) > max_comments - 2:  # Reserve space for overview and recommendations
        # Find smallest groups to consolidate
        groups_by_size = sorted(grouped_files.items(), key=lambda x: len(x[1]))
        
        # Keep the largest groups separate, consolidate the rest
        keep_separate = max_comments - 2
        consolidated = []
        
        for i, (group, sections) in enumerate(groups_by_size):
            if i >= len(groups_by_size) - keep_separate:
                # Keep larger groups separate
                continue
            
            # Add to consolidated group
            consolidated.extend([f"### {group}", *sections])
            # Remove from grouped_files
            grouped_files.pop(group)
        
        # Add consolidated group if it has content
        if consolidated:
            grouped_files["Other Feedback"] = consolidated
    
    # Post grouped comments
    for group, sections in grouped_files.items():
        if comment_count >= max_comments - 1:
            logger.warning(f"Skipping remaining {len(grouped_files) - comment_count + 1} file groups due to comment limit")
            break
            
        group_text = f"## Feedback for {group}\n\n" + "\n\n".join(sections)
        group_success = post_with_retry(group_text, f"grouped files comment ({group})")
        success = success and group_success
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
    Post line-specific review comments on a pull request.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        comments: List of comment dictionaries with 'path', 'line', and 'body' keys
        
    Returns:
        True if successful, False otherwise
    """
    if not comments:
        logger.warning("No comments to post")
        return True
        
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}"
    }
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    
    # Get the latest commit SHA for the PR
    try:
        commits_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/commits"
        commits_response = requests.get(commits_url, headers=headers)
        commits_response.raise_for_status()
        commits = commits_response.json()
        if not commits:
            logger.error("No commits found for PR")
            return False
        latest_commit_sha = commits[-1]["sha"]
        logger.debug(f"Using latest commit SHA: {latest_commit_sha}")
    except Exception as e:
        logger.error(f"Failed to get latest commit SHA: {str(e)}")
        return False
    
    # Format comments for the API
    formatted_comments = []
    for i, comment in enumerate(comments):
        # Extract suggestion if present
        body = comment["body"]
        suggestion_pattern = r"```suggestion\n(.*?)```"
        suggestion_match = re.search(suggestion_pattern, body, re.DOTALL)
        
        # Log the comment details for debugging
        logger.debug(f"Comment {i+1}/{len(comments)}: {comment['path']}:{comment.get('line', 'unknown')}")
        
        formatted_comment = {
            "path": comment["path"],
            "body": body,
            "line": int(comment.get("line", 1)),  # Ensure line is an integer
            "side": "RIGHT"  # Comment on the new version of the file
        }
        
        # For multi-line comments, add start_line and start_side if available
        if "start_line" in comment:
            formatted_comment["start_line"] = int(comment["start_line"])
            formatted_comment["start_side"] = comment.get("start_side", "RIGHT")
            
        # Only use position as a fallback for older API compatibility
        if "position" in comment and "line" not in comment:
            formatted_comment["position"] = comment["position"]
            # Remove line and side if using position
            if "line" in formatted_comment:
                del formatted_comment["line"]
            if "side" in formatted_comment:
                del formatted_comment["side"]
            logger.debug(f"Using position {comment['position']} for comment on {comment['path']}")
        else:
            logger.debug(f"Using line {formatted_comment['line']} with side RIGHT for comment on {comment['path']}")
        
        formatted_comments.append(formatted_comment)
    
    # Create a summary of the review
    review_body = "AI PR Review - Line Comments\n\n"
    review_body += f"I've reviewed the changes and left {len(comments)} specific comments on the code."
    
    # Create the review with comments
    data = {
        "commit_id": latest_commit_sha,
        "body": review_body,
        "event": "COMMENT",  # Can be APPROVE, REQUEST_CHANGES, or COMMENT
        "comments": formatted_comments
    }
    
    try:
        logger.info(f"Creating review with {len(comments)} line comments on PR #{pr_number} in {repo}")
        
        # Log the request payload for debugging (excluding large bodies)
        debug_data = {
            "commit_id": data["commit_id"],
            "event": data["event"],
            "body_length": len(data["body"]),
            "comments": [
                {
                    "path": c["path"],
                    "line" if "line" in c else "position": c.get("line", c.get("position")),
                    "body_length": len(c["body"])
                }
                for c in data["comments"]
            ]
        }
        logger.debug(f"Request payload: {json.dumps(debug_data)}")
        
        response = requests.post(url, headers=headers, json=data)
        
        # Log response details for debugging
        logger.debug(f"GitHub API response status: {response.status_code}")
        if response.status_code >= 400:
            logger.error(f"GitHub API error: {response.text}")
            
            # If we get a 422 error (validation failed), try posting comments individually
            if response.status_code == 422:
                logger.info("Received 422 error, trying to post individual reviews")
                success = True
                
                # Try posting individual reviews for each comment
                for i, comment in enumerate(formatted_comments):
                    try:
                        individual_data = {
                            "commit_id": latest_commit_sha,
                            "body": f"Comment {i+1}/{len(formatted_comments)}",
                            "event": "COMMENT",
                            "comments": [comment]
                        }
                        
                        individual_response = requests.post(url, headers=headers, json=individual_data)
                        if individual_response.status_code >= 400:
                            logger.error(f"Failed to post individual review {i+1}: {individual_response.text}")
                            
                            # As a last resort, try posting as a direct comment
                            try:
                                direct_comment_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments"
                                direct_data = {
                                    "body": comment["body"],
                                    "commit_id": latest_commit_sha,
                                    "path": comment["path"],
                                }
                                
                                # Add line and side parameters for direct comments
                                if "line" in comment:
                                    direct_data["line"] = comment["line"]
                                    direct_data["side"] = comment.get("side", "RIGHT")
                                    
                                    # Add start_line and start_side for multi-line comments
                                    if "start_line" in comment:
                                        direct_data["start_line"] = comment["start_line"]
                                        direct_data["start_side"] = comment.get("start_side", "RIGHT")
                                # Only use position as a fallback
                                elif "position" in comment:
                                    direct_data["position"] = comment["position"]
                                
                                direct_response = requests.post(direct_comment_url, headers=headers, json=direct_data)
                                if direct_response.status_code >= 400:
                                    logger.error(f"Failed to post direct comment {i+1}: {direct_response.text}")
                                    success = False
                                else:
                                    logger.info(f"Successfully posted direct comment {i+1}/{len(formatted_comments)}")
                            except Exception as e:
                                logger.error(f"Error posting direct comment {i+1}: {str(e)}")
                                success = False
                        else:
                            logger.info(f"Successfully posted individual review {i+1}/{len(formatted_comments)}")
                        
                        # Add a delay to avoid rate limits
                        time.sleep(2)
                    except Exception as e:
                        logger.error(f"Error posting individual review {i+1}: {str(e)}")
                        success = False
                
                return success
            
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to post line comments: {e}")
        return False


def parse_diff_for_lines(diff_text: str) -> Dict[str, List[Tuple[int, int, str]]]:
    """
    Parse a diff to extract file paths and line numbers.
    Useful for posting line-specific comments.
    
    Args:
        diff_text: The diff text from GitHub
        
    Returns:
        Dictionary mapping file paths to list of (line_number, position, line_content) tuples
        where position is the line's position in the diff (required for GitHub API)
    """
    result = {}
    current_file = None
    line_number = 0
    position = 0  # Track position in the diff
    
    # Extract filename and line information from diff
    for line in diff_text.split('\n'):
        # Reset position counter for each new file
        if line.startswith('diff --git'):
            position = 0
            continue
            
        # New file in diff
        if line.startswith('+++'):
            path_match = re.match(r'\+\+\+ b/(.*)', line)
            if path_match:
                current_file = path_match.group(1)
                result[current_file] = []
                line_number = 0
            position += 1
            continue
            
        # Skip removal marker lines
        if line.startswith('---'):
            position += 1
            continue
            
        # Line numbers in hunk header
        if line.startswith('@@'):
            match = re.search(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if match:
                line_number = int(match.group(1)) - 1  # -1 because we increment before using
            position += 1
            continue
            
        # Track actual diff lines
        position += 1
        
        # Skip removal lines but still count position
        if line.startswith('-'):
            continue
            
        # Process addition and context lines
        if line.startswith('+'):
            line_number += 1
            if current_file:
                # Store both the line number and position for API flexibility
                result[current_file].append((line_number, position, line[1:]))
        elif not line.startswith('\\'):  # Skip "No newline" markers
            line_number += 1
            if current_file:
                # Store both the line number and position for API flexibility
                result[current_file].append((line_number, position, line))
    
    # Log the mapping for debugging
    for file_path, lines in result.items():
        logger.debug(f"Mapped {len(lines)} lines for file {file_path}")
        if lines and len(lines) > 0:
            logger.debug(f"First few mappings: {lines[:min(3, len(lines))]}")
    
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