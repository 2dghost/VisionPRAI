#!/usr/bin/env python3
"""
Main script for the AI PR Reviewer.
Fetches PR details, analyzes with an AI model, and posts review comments.
"""

import os
import sys
import argparse
import json
import logging
import re
import yaml
from typing import Dict, List, Optional, Any, Tuple

from src.model_adapters import ModelAdapter
from src.utils import (
    get_pr_diff,
    get_pr_files,
    post_review_comment,
    post_line_comments,
    parse_diff_for_lines,
    extract_code_blocks
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ai-pr-reviewer")


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """
    Load configuration from a YAML file.
    
    Args:
        config_path: Path to the config file
        
    Returns:
        Dictionary containing configuration
        
    Raises:
        FileNotFoundError: If the config file does not exist
        yaml.YAMLError: If the config file is not valid YAML
        ValueError: If the config is empty or missing required fields
    """
    # Validate the config path
    if not os.path.exists(config_path):
        logger.error(f"Config file not found: {config_path}")
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML in config file: {e}")
        raise
    
    # Validate minimum required configuration
    if not config:
        logger.error("Config file is empty or not valid YAML")
        raise ValueError("Config file is empty or not valid YAML")
        
    if "model" not in config:
        logger.error("Missing required 'model' section in config")
        raise ValueError("Missing required 'model' section in config")
    
    # Check for required model configuration
    model_config = config.get("model", {})
    required_fields = ["provider", "endpoint", "model"]
    missing_fields = [field for field in required_fields if field not in model_config]
    
    if missing_fields:
        logger.error(f"Missing required fields in model config: {', '.join(missing_fields)}")
        raise ValueError(f"Missing required fields in model config: {', '.join(missing_fields)}")
        
    return config


def get_environment_variables() -> Tuple[str, str, str]:
    """
    Get required environment variables.
    
    Returns:
        Tuple of (github_token, repo, pr_number)
    """
    # Get GitHub token from environment or config
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        logger.error("GITHUB_TOKEN environment variable is required")
        sys.exit(1)
        
    # Get repository and PR number
    if "GITHUB_REPOSITORY" in os.environ and "GITHUB_EVENT_NUMBER" in os.environ:
        # Running in GitHub Actions
        repo = os.environ["GITHUB_REPOSITORY"]
        pr_number = os.environ["GITHUB_EVENT_NUMBER"]
    else:
        # Running locally
        repo = os.environ.get("PR_REPOSITORY")
        pr_number = os.environ.get("PR_NUMBER")
        
        if not repo or not pr_number:
            logger.error(
                "When running locally, PR_REPOSITORY and PR_NUMBER environment variables are required"
            )
            sys.exit(1)
            
    return github_token, repo, pr_number


def generate_prompt(diff: str, files: List[Dict[str, Any]], config: Dict[str, Any]) -> str:
    """
    Generate a prompt for the AI model.
    
    Args:
        diff: The PR diff
        files: List of files changed in the PR
        config: Configuration dictionary
        
    Returns:
        Prompt for the AI model
    """
    # Get focus areas from config
    focus_areas = config.get("review", {}).get("focus_areas", "")
    
    # Extract relevant file info
    file_info = []
    for file in files:
        file_info.append({
            "filename": file["filename"],
            "status": file["status"],
            "additions": file["additions"],
            "deletions": file["deletions"],
            "changes": file["changes"]
        })
    
    # Create a comprehensive prompt
    prompt = (
        "You are an expert code reviewer following best practices. "
        "Analyze this PR diff and provide feedback on:\n"
        f"{focus_areas}\n\n"
        "Make your suggestions actionable, clear, and specific to the code changes.\n"
        "Focus on potential issues, improvements, and best practices.\n\n"
        f"Files changed in this PR:\n{json.dumps(file_info, indent=2)}\n\n"
        "PR Diff:\n"
        f"```diff\n{diff}\n```\n\n"
        "Format your review as a markdown document with sections for each major category of feedback.\n"
        "For specific issues, reference the file and line number when possible."
    )
    
    return prompt


def extract_line_comments(review_text: str, file_line_map: Dict[str, List[Tuple[int, str]]]) -> List[Dict[str, Any]]:
    """
    Extract line-specific comments from the review text.
    
    Args:
        review_text: The review text from the AI
        file_line_map: Mapping of files to line numbers from the diff
        
    Returns:
        List of line comments in the format expected by GitHub API
    """
    comments = []
    
    # Look for patterns like "In file.py, line 42:" or "file.py:42:"
    patterns = [
        r'In\s+([^,]+),\s+line\s+(\d+):', 
        r'([^:\s]+):(\d+):',
        r'([^:\s]+) line (\d+):',
        r'In file `([^`]+)` at line (\d+)'
    ]
    
    for pattern in patterns:
        matches = re.finditer(pattern, review_text, re.MULTILINE)
        for match in matches:
            file_path = match.group(1).strip()
            line_num = int(match.group(2))
            
            # Find the end of the comment (next line-specific comment or end of text)
            start_pos = match.end()
            next_match = re.search('|'.join(patterns), review_text[start_pos:], re.MULTILINE)
            if next_match:
                end_pos = start_pos + next_match.start()
                comment_text = review_text[start_pos:end_pos].strip()
            else:
                comment_text = review_text[start_pos:].strip()
            
            # Clean up the comment text by removing leading colons
            comment_text = re.sub(r'^:\s*', '', comment_text)
                
            # Verify file exists in the diff and line number is valid
            if file_path in file_line_map:
                valid_lines = [line for line, _ in file_line_map[file_path]]
                if line_num in valid_lines:
                    comments.append({
                        "path": file_path,
                        "line": line_num,
                        "body": comment_text
                    })
    
    return comments


def review_pr(config_path: Optional[str] = None, verbose: bool = False) -> bool:
    """
    Main function to review a pull request.
    
    Args:
        config_path: Path to the config file (default: "config.yaml")
        verbose: Enable verbose logging
        
    Returns:
        True if the review was completed successfully, False otherwise
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Load config
        config_file = config_path or "config.yaml"
        logger.info(f"Loading configuration from {config_file}")
        config = load_config(config_file)
        
        # Get environment variables
        logger.info("Retrieving environment variables")
        github_token, repo, pr_number = get_environment_variables()
        
        # Initialize model adapter
        logger.info(f"Initializing {config['model']['provider']} model adapter")
        model_config = config.get("model", {})
        model_adapter = ModelAdapter(model_config)
    except (FileNotFoundError, yaml.YAMLError, ValueError) as e:
        logger.error(f"Configuration error: {e}")
        return False
    except Exception as e:
        logger.error(f"Initialization error: {str(e)}")
        return False
    
    # Fetch PR diff
    logger.info(f"Fetching diff for PR #{pr_number} in {repo}")
    diff = get_pr_diff(repo, pr_number, github_token)
    if not diff:
        logger.error("No diff found. Exiting.")
        return False
    
    # Fetch PR files
    logger.info(f"Fetching files for PR #{pr_number} in {repo}")
    files = get_pr_files(repo, pr_number, github_token)
    if not files:
        logger.warning("No files found. Continuing with diff only.")
    
    # Generate prompt
    logger.info("Generating prompt for AI review")
    prompt = generate_prompt(diff, files, config)
    
    # Call AI for review
    try:
        logger.info(f"Sending PR to {model_config['provider']} {model_config['model']} for review")
        review_text = model_adapter.generate_response(prompt)
    except Exception as e:
        logger.error(f"Error generating review: {str(e)}")
        return False
    
    # Post general review comment
    logger.info("Posting general review comment")
    success = post_review_comment(repo, pr_number, github_token, review_text)
    if not success:
        logger.error("Failed to post review comment")
        return False
    
    # Check if we should post line-specific comments
    line_comments_enabled = config.get("review", {}).get("line_comments", True)
    if line_comments_enabled:
        try:
            logger.info("Processing line-specific comments")
            # Parse the diff to get file/line mapping
            file_line_map = parse_diff_for_lines(diff)
            
            # Extract line-specific comments
            line_comments = extract_line_comments(review_text, file_line_map)
            
            # Post line comments if any were found
            if line_comments:
                logger.info(f"Posting {len(line_comments)} line-specific comments")
                line_comment_success = post_line_comments(repo, pr_number, github_token, line_comments)
                if not line_comment_success:
                    logger.error("Failed to post line comments")
                    # Continue despite failure to post line comments
            else:
                logger.info("No line-specific comments found in the review")
        except Exception as e:
            logger.error(f"Error processing line comments: {str(e)}")
            # Continue despite errors in line comments
    
    logger.info("PR review completed successfully")
    return True


def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="AI PR Reviewer")
    parser.add_argument("-c", "--config", help="Path to config file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()
    
    success = review_pr(config_path=args.config, verbose=args.verbose)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()