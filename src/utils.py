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
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28"  # Use explicit API version
    }
    
    # Get the latest commit SHA for the PR - required for review comments
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
    
    # Get the diff for the PR to calculate positions correctly
    try:
        diff_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        diff_headers = {
            "Accept": "application/vnd.github.v3.diff",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        diff_response = requests.get(diff_url, headers=diff_headers)
        diff_response.raise_for_status()
        diff_content = diff_response.text
        
        # Also get the files modified in this PR
        files_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
        files_response = requests.get(files_url, headers=headers)
        files_response.raise_for_status()
        files = files_response.json()
        
        # Create a map of file paths to their positions in the diff
        file_positions = {}
        for file in files:
            file_positions[file["filename"]] = {
                "patch": file.get("patch", ""),
                "changes": file.get("changes", 0),
                "status": file.get("status", "")
            }
            
        logger.debug(f"Found {len(files)} files in PR: {', '.join(file_positions.keys())}")
    except Exception as e:
        logger.error(f"Failed to get diff information: {str(e)}")
        # Continue without diff position mapping - we'll use line numbers directly
    
    # Format comments for the API
    formatted_comments = []
    for comment in comments:
        path = comment["path"]
        line_num = int(comment.get("line", 1))
        
        formatted_comment = {
            "path": path,
            "body": comment["body"],
            "line": line_num,
            "side": comment.get("side", "RIGHT")
        }
        
        # For multi-line comments, add start_line and start_side
        if "start_line" in comment:
            formatted_comment["start_line"] = int(comment["start_line"])
            formatted_comment["start_side"] = comment.get("start_side", "RIGHT")
        
        formatted_comments.append(formatted_comment)
    
    # Create a review with comments in a single request
    try:
        review_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
        
        review_data = {
            "commit_id": latest_commit_sha,
            "event": "COMMENT",  # Submit the review immediately as a COMMENT
            "body": f"AI PR Review - I've reviewed the changes and left {len(comments)} specific comments on the code.",
            "comments": formatted_comments
        }
        
        logger.info(f"Creating review with {len(formatted_comments)} comments")
        logger.debug(f"Review data: commit_id={latest_commit_sha}, event=COMMENT, comments_count={len(formatted_comments)}")
        
        # Log a sample comment for debugging
        if formatted_comments:
            sample = formatted_comments[0]
            logger.debug(f"Sample comment: path={sample['path']}, line={sample['line']}, side={sample['side']}")
            
        review_response = requests.post(review_url, headers=headers, json=review_data)
        
        # Check if the request was successful
        if review_response.status_code >= 400:
            error_body = review_response.text
            logger.error(f"Failed to create review: HTTP {review_response.status_code}: {error_body}")
            
            # Try individual comments if bulk creation failed
            logger.info("Attempting to create review with comments one by one")
            return create_review_with_individual_comments(repo, pr_number, token, formatted_comments, latest_commit_sha)
        
        # Success!
        review_id = review_response.json().get("id")
        logger.info(f"Successfully created review #{review_id} with {len(formatted_comments)} comments")
        
        # Verify the review was created correctly by fetching it
        try:
            verify_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews/{review_id}"
            verify_response = requests.get(verify_url, headers=headers)
            
            if verify_response.status_code >= 400:
                logger.warning(f"Could not verify review creation: HTTP {verify_response.status_code}")
            else:
                review_data = verify_response.json()
                comments_count = len(review_data.get("comments", []))
                logger.info(f"Verified review #{review_id} has {comments_count} comments")
        except Exception as e:
            logger.warning(f"Error verifying review: {str(e)}")
        
        return True
            
    except Exception as e:
        logger.error(f"Error creating review: {str(e)}", exc_info=True)
        return False


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