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

import sys
import os

# Add the parent directory to sys.path to support both local and GitHub Actions environments
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    # Try direct imports first (for GitHub Actions and package usage)
    from model_adapters import ModelAdapter
    from utils import (
        get_pr_diff,
        get_pr_files,
        post_review_comment,
        post_review_sections,
        post_line_comments,
        parse_diff_for_lines,
        extract_code_blocks
    )
    from comment_extractor import CommentExtractor
    from file_filter import FileFilter
    from custom_exceptions import (
        VisionPRAIError,
        ConfigurationError,
        MissingConfigurationError,
        InvalidConfigurationError,
        CommentExtractionError
    )
    from logging_config import get_logger, with_context
except ImportError:
    # Fall back to src-prefixed imports (for local development)
    from src.model_adapters import ModelAdapter
    from src.utils import (
        get_pr_diff,
        get_pr_files,
        post_review_comment,
        post_review_sections,
        post_line_comments,
        parse_diff_for_lines,
        extract_code_blocks
    )
    from src.comment_extractor import CommentExtractor
    from src.file_filter import FileFilter
    from src.custom_exceptions import (
        VisionPRAIError,
        ConfigurationError,
        MissingConfigurationError, 
        InvalidConfigurationError,
        CommentExtractionError
    )
    from src.logging_config import get_logger, with_context

# Get structured logger
logger = get_logger("ai-pr-reviewer")


@with_context
def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """
    Load configuration from a YAML file and merge with cursor rules.
    
    Args:
        config_path: Path to the config file
        
    Returns:
        Dictionary containing configuration
        
    Raises:
        MissingConfigurationError: If the config file does not exist
        InvalidConfigurationError: If the config file is not valid YAML or missing required fields
    """
    # Validate the config path
    if not os.path.exists(config_path):
        logger.error(f"Config file not found: {config_path}", 
                    context={"config_path": config_path})
        raise MissingConfigurationError("config_file")
    
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML in config file: {e}",
                    context={"config_path": config_path, "error": str(e)})
        raise InvalidConfigurationError("config_file", f"Invalid YAML format: {e}")
    
    # Load cursor rules if they exist
    cursor_rules_path = os.path.join(os.getcwd(), ".cursor", "rules")
    if os.path.exists(cursor_rules_path):
        logger.info("Loading cursor rules", context={"rules_path": cursor_rules_path})
        try:
            rules = {}
            for rule_file in os.listdir(cursor_rules_path):
                if rule_file.endswith(".mdc"):
                    with open(os.path.join(cursor_rules_path, rule_file), "r") as f:
                        rule_content = f.read()
                        rules[rule_file[:-4]] = rule_content  # Remove .mdc extension
            
            # Add cursor rules to config
            if rules:
                config["cursor_rules"] = rules
                logger.info("Successfully loaded cursor rules", 
                           context={"rules_count": len(rules)})
        except Exception as e:
            logger.warning(f"Failed to load cursor rules: {e}",
                         context={"error": str(e)})
    
    # Validate minimum required configuration
    if not config:
        logger.error("Config file is empty or not valid YAML",
                    context={"config_path": config_path})
        raise InvalidConfigurationError("config_file", "Empty or invalid YAML")
        
    if "model" not in config:
        logger.error("Missing required 'model' section in config",
                    context={"config_path": config_path})
        raise MissingConfigurationError("model")
    
    # Check for required model configuration
    model_config = config.get("model", {})
    required_fields = ["provider", "endpoint", "model"]
    missing_fields = [field for field in required_fields if field not in model_config]
    
    if missing_fields:
        missing_fields_str = ", ".join(missing_fields)
        logger.error(f"Missing required fields in model config: {missing_fields_str}",
                    context={"config_path": config_path, "missing_fields": missing_fields})
        raise MissingConfigurationError(f"model.{missing_fields[0]}" if missing_fields else "model")
    
    logger.debug("Successfully loaded configuration", 
                context={"config_path": config_path, "provider": model_config.get("provider")})
    return config


@with_context
def get_environment_variables() -> Tuple[str, str, str]:
    """
    Get required environment variables.
    
    Returns:
        Tuple of (github_token, repo, pr_number)
        
    Raises:
        MissingConfigurationError: If required environment variables are missing
    """
    # Get GitHub token from environment or config
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        logger.error("GITHUB_TOKEN environment variable is required")
        raise MissingConfigurationError("GITHUB_TOKEN")
        
    # Get repository and PR number
    if "GITHUB_REPOSITORY" in os.environ and "GITHUB_EVENT_NUMBER" in os.environ:
        # Running in GitHub Actions
        repo = os.environ["GITHUB_REPOSITORY"]
        pr_number = os.environ["GITHUB_EVENT_NUMBER"]
        logger.debug("Running in GitHub Actions environment", 
                    context={"repo": repo, "pr_number": pr_number})
    else:
        # Running locally
        repo = os.environ.get("PR_REPOSITORY")
        pr_number = os.environ.get("PR_NUMBER")
        
        if not repo or not pr_number:
            missing_vars = []
            if not repo:
                missing_vars.append("PR_REPOSITORY")
            if not pr_number:
                missing_vars.append("PR_NUMBER")
                
            error_msg = "When running locally, PR_REPOSITORY and PR_NUMBER environment variables are required"
            logger.error(error_msg, context={"missing_variables": missing_vars})
            raise MissingConfigurationError(missing_vars[0] if missing_vars else "PR_REPOSITORY")
        
        logger.debug("Running in local environment", 
                    context={"repo": repo, "pr_number": pr_number})
            
    return github_token, repo, pr_number


@with_context
def generate_prompt(diff: str, files: List[Dict[str, Any]], config: Dict[str, Any]) -> str:
    """
    Generate a prompt for the AI model.
    
    Args:
        diff: The PR diff
        files: List of files changed in the PR (after filtering)
        config: Configuration dictionary
        
    Returns:
        Prompt for the AI model
    """
    # Get focus areas from config
    focus_areas = config.get("review", {}).get("focus_areas", "")
    
    # Get cursor rules if available
    cursor_rules = config.get("cursor_rules", {})
    
    # Check if file filtering is enabled
    file_filtering_enabled = config.get("review", {}).get("file_filtering", {}).get("enabled", False)
    exclude_patterns = config.get("review", {}).get("file_filtering", {}).get("exclude_patterns", [])
    
    # Get review format settings
    format_config = config.get("review", {}).get("format", {})
    include_summary = format_config.get("include_summary", True)
    include_overview = format_config.get("include_overview", True)
    include_recommendations = format_config.get("include_recommendations", True)
    template_style = format_config.get("template_style", "default")
    split_comments = format_config.get("split_comments", False)
    
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
        "Analyze this PR diff and provide feedback with concrete code improvements.\n"
        f"{focus_areas}\n\n"
        "IMPORTANT: For each issue you find, you MUST provide a code suggestion using this exact format:\n\n"
        "Problem: <clear explanation of the issue>\n\n"
        "```suggestion\n"
        "<exact code that should replace the original code>\n"
        "```\n\n"
        "Explanation: <why this change improves the code>\n\n"
        "Guidelines for suggestions:\n"
        "1. Each suggestion must be preceded by a clear explanation of the issue\n"
        "2. The suggestion block must contain the complete fixed code, not just the changed part\n"
        "3. After each suggestion, explain why your solution is better\n"
        "4. Make sure to reference specific line numbers from the diff\n"
        "5. The suggestion must match the exact indentation of the original code\n"
        "6. Do not include any additional formatting or comments in the suggestion block\n"
        "7. ALWAYS provide at least one code suggestion if you find any issues\n\n"
    )
    
    # Add cursor rules guidance if available
    if cursor_rules:
        prompt += "Follow these project-specific guidelines:\n\n"
        for rule_name, rule_content in cursor_rules.items():
            prompt += f"### {rule_name} Guidelines\n{rule_content}\n\n"
    
    # Add files and diff information
    prompt += (
        f"Files changed in this PR:\n{json.dumps(file_info, indent=2)}\n\n"
        "PR Diff:\n"
        f"```diff\n{diff}\n```\n\n"
    )
    
    # Format instructions
    prompt += (
        "Format your review as follows:\n\n"
        "1. Start with a brief summary of the changes\n"
        "2. For each file that needs improvements:\n"
        "   ### filename.ext:line_number\n"
        "   Problem: <clear explanation>\n\n"
        "   ```suggestion\n"
        "   <exact replacement code>\n"
        "   ```\n\n"
        "   Explanation: <why this improves the code>\n\n"
        "3. End with overall recommendations\n\n"
        "Remember:\n"
        "- ALWAYS include specific line numbers\n"
        "- Make suggestions ONLY for lines in the diff\n"
        "- Each suggestion must be complete and valid code\n"
        "- If you find ANY issues, you MUST provide at least one code suggestion\n"
    )
    
    return prompt


@with_context
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
        # Update log level in the structured logger
        os.environ["LOG_LEVEL"] = "DEBUG"
    
    try:
        # Load config
        config_file = config_path or "config.yaml"
        logger.info(f"Loading configuration from {config_file}", 
                   context={"config_path": config_file})
        config = load_config(config_file)
        
        # Get environment variables
        logger.info("Retrieving environment variables")
        github_token, repo, pr_number = get_environment_variables()
        
        # Initialize model adapter
        provider = config['model']['provider']
        model_name = config['model']['model']
        logger.info(f"Initializing AI model adapter", 
                   context={"provider": provider, "model": model_name})
        model_config = config.get("model", {})
        model_adapter = ModelAdapter(model_config)
    except VisionPRAIError as e:
        logger.error(f"Configuration error: {e.message}",
                   context={"error_code": e.error_code})
        return False
    except Exception as e:
        logger.error(f"Initialization error: {str(e)}",
                    context={"error_type": type(e).__name__},
                    exc_info=True)
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
        
    # Apply file filtering if files were found
    if files:
        logger.info("Applying file filtering rules")
        file_filter = FileFilter(config)
        original_file_count = len(files)
        files = file_filter.filter_files(files)
        
        if file_filter.enabled:
            filtered_count = original_file_count - len(files)
            if filtered_count > 0:
                logger.info(f"Filtered out {filtered_count} files based on configured rules", 
                           context={"original_count": original_file_count, 
                                   "filtered_count": len(files)})
    
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
    
    # Post summary overview as general comment
    logger.info("Posting overview comment")
    
    # Extract just summary and overview sections
    summary_pattern = r'(?:^|\n)## Summary\s*\n(.*?)(?=\n##|\Z)'
    overview_pattern = r'(?:^|\n)## Overview of Changes\s*\n(.*?)(?=\n##|\Z)'
    
    summary_match = re.search(summary_pattern, review_text, re.DOTALL)
    overview_match = re.search(overview_pattern, review_text, re.DOTALL)
    
    overview_text = "# AI Review Summary\n\n"
    if summary_match:
        overview_text += f"## Summary\n{summary_match.group(1).strip()}\n\n"
    if overview_match:
        overview_text += f"## Overview of Changes\n{overview_match.group(1).strip()}\n\n"
    
    # Add a note about code-specific comments
    overview_text += "\n\n> Detailed feedback has been added as review comments on specific code lines."
    
    overview_success = post_review_comment(repo, pr_number, github_token, overview_text)
    if not overview_success:
        logger.error("Failed to post overview comment")
        # Continue anyway to post line comments
    
    # Check if we should post line-specific comments
    line_comments_enabled = config.get("review", {}).get("line_comments", True)
    if line_comments_enabled:
        try:
            logger.info("Processing line-specific comments", 
                       context={"repo": repo, "pr_number": pr_number})
            
            # Parse the diff to get file/line mapping
            file_line_map = parse_diff_for_lines(diff)
            
            # First use the standard extractor for explicitly marked line comments
            comment_extractor = CommentExtractor(config_path=config_path or "config.yaml")
            standard_line_comments = comment_extractor.extract_line_comments(review_text, file_line_map)
            
            # Now extract file-specific sections and convert them to line comments for each file
            file_sections = {}
            file_section_pattern = r'(?:^|\n)### ([^\n:]+):(\d+)\s*\n(.*?)(?=\n### [^\n:]+:\d+|\Z)'
            
            for match in re.finditer(file_section_pattern, review_text, re.DOTALL):
                filename = match.group(1).strip()
                line_number = int(match.group(2))
                content = match.group(3).strip()
                
                if filename in file_line_map:
                    # Find the matching position for this line number
                    matching_lines = [
                        (line_num, pos, content) 
                        for line_num, pos, content in file_line_map[filename] 
                        if line_num == line_number
                    ]
                    if matching_lines:
                        # Use the first matching position
                        _, position, _ = matching_lines[0]
                        file_sections[filename] = {
                            "path": filename,
                            "line": position,  # Use position instead of line number
                            "body": content
                        }
            
            # Convert file sections to line comments 
            additional_comments = list(file_sections.values())
            
            # Combine standard and file-section comments
            all_comments = standard_line_comments + additional_comments
            
            # Post line comments if any were found
            if all_comments:
                logger.info(f"Posting {len(all_comments)} line-specific comments",
                           context={"comments_count": len(all_comments)})
                line_comment_success = post_line_comments(repo, pr_number, github_token, all_comments)
                if not line_comment_success:
                    logger.error("Failed to post line comments",
                                context={"repo": repo, "pr_number": pr_number})
                    # Continue despite failure to post line comments
            else:
                logger.info("No line-specific comments found in the review",
                           context={"repo": repo, "pr_number": pr_number})
        except CommentExtractionError as e:
            logger.error(f"Error extracting line comments: {str(e)}",
                        context={"error_code": e.error_code, "repo": repo, "pr_number": pr_number},
                        exc_info=True)
            # Continue despite errors in line comments
        except Exception as e:
            logger.error(f"Error processing line comments: {str(e)}",
                        context={"repo": repo, "pr_number": pr_number},
                        exc_info=True)
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