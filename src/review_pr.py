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
import time

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
        "Analyze this PR diff and provide detailed, constructive feedback with concrete code improvements.\n"
        f"{focus_areas}\n\n"
        "CRITICAL: For each issue, you MUST format your line-specific comments exactly like this:\n\n"
        "### filename.ext:line_number\n"
        "Problem: <clear explanation of the issue>\n\n"
        "```suggestion\n"
        "<exact code that should replace the original code>\n"
        "```\n\n"
        "Explanation: <why this change improves the code>\n\n"
        "Guidelines:\n"
        "1. ALWAYS include the file name and line number in the header (### filename.ext:line_number)\n"
        "2. Each suggestion must be preceded by a clear explanation of the issue\n"
        "3. The suggestion block must contain the complete fixed code\n"
        "4. After each suggestion, explain why your solution is better\n"
        "5. Make suggestions ONLY for lines that exist in the diff\n"
        "6. If you find ANY issues, you MUST provide at least one code suggestion\n"
        "7. IMPORTANT: Each file-specific comment MUST start with '### filename.ext:line_number' format\n"
        "8. DO NOT use any other format for file-specific comments\n"
        "9. ALWAYS include file-specific comments in the 'File-Specific Comments' section\n"
        "10. NEVER skip providing file-specific comments - they are the most important part of the review\n\n"
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
    
    # Format instructions - IMPORTANT: Keep the exact format consistent for regex extraction
    prompt += (
        "Your review MUST follow this EXACT format with these EXACT section headers:\n\n"
    )
    
    # Add sections with consistent headers that match our regex patterns
    sections = []
    
    if include_summary:
        sections.append(
            "## Summary\n"
            "Provide a concise summary of the PR, including its purpose and overall quality.\n"
        )
    
    if include_overview:
        sections.append(
            "## Overview of Changes\n"
            "List the key changes and their impact. Highlight any architectural decisions.\n"
        )
    
    # Always include detailed feedback section
    sections.append(
        "## Detailed Feedback\n"
        "Provide detailed analysis of the code changes. Include specific issues and recommendations.\n"
    )
    
    # Add a dedicated section for file-specific comments
    sections.append(
        "## File-Specific Comments\n"
        "Include all line-specific comments here, using the exact format specified above (### filename.ext:line_number).\n"
        "This section MUST contain at least one file-specific comment for each file with issues.\n"
        "IMPORTANT: This section is required and will be used to post comments on specific lines of code.\n"
    )
    
    if include_recommendations:
        sections.append(
            "## Recommendations\n"
            "Summarize your key recommendations for improving the PR.\n"
        )
    
    # Add numbered sections to the prompt
    for i, section in enumerate(sections, 1):
        prompt += f"{i}. {section}"
    
    prompt += (
        "IMPORTANT REMINDERS:\n"
        "- ALWAYS include specific line numbers in the format 'filename.ext:line_number'\n"
        "- Make suggestions ONLY for lines in the diff\n"
        "- Each suggestion must be complete and valid code\n"
        "- If you find ANY issues, you MUST provide at least one code suggestion\n"
        "- Use the EXACT section headers shown above (## Summary, ## Overview of Changes, etc.)\n"
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
        
        # Log the first part of the response for debugging
        logger.debug(f"AI response first 500 chars: {review_text[:500]}")
        
        # Verify that we received a non-empty response
        if not review_text or len(review_text.strip()) < 10:
            logger.error("Received empty or very short response from AI model")
            return False
    except Exception as e:
        logger.error(f"Error generating review: {str(e)}")
        return False
    
    # Post summary overview as general comment
    logger.info("Posting overview comment")
    
    # Extract just summary and overview sections
    summary_pattern = r'(?:^|\n)## Summary\s*\n(.*?)(?=\n##|\Z)'
    overview_pattern = r'(?:^|\n)## Overview of Changes\s*\n(.*?)(?=\n##|\Z)'
    recommendations_pattern = r'(?:^|\n)## Recommendations\s*\n(.*?)(?=\n##|\Z)'
    
    summary_match = re.search(summary_pattern, review_text, re.DOTALL)
    overview_match = re.search(overview_pattern, review_text, re.DOTALL)
    recommendations_match = re.search(recommendations_pattern, review_text, re.DOTALL)
    
    # Log the review text for debugging
    logger.debug(f"Review text received (first 1000 chars): {review_text[:1000]}...")
    logger.debug(f"Review text received (last 1000 chars): {review_text[-1000:]}...")
    
    overview_text = "# AI Review Summary\n\n"
    
    if summary_match:
        overview_text += f"## Summary\n{summary_match.group(1).strip()}\n\n"
        logger.debug("Summary section found and extracted")
    else:
        logger.warning("No summary section found in the review text")
        # Add a fallback summary if none was found
        overview_text += "## Summary\nThis PR contains code changes that have been reviewed by the AI.\n\n"
    
    if overview_match:
        overview_text += f"## Overview of Changes\n{overview_match.group(1).strip()}\n\n"
        logger.debug("Overview section found and extracted")
    else:
        logger.warning("No overview section found in the review text")
        # Add a fallback overview if none was found
        overview_text += "## Overview of Changes\n- Code changes were analyzed\n- See detailed comments for specific feedback\n\n"
    
    if recommendations_match:
        overview_text += f"## Recommendations\n{recommendations_match.group(1).strip()}\n\n"
        logger.debug("Recommendations section found and extracted")
    
    # Add a note about code-specific comments
    overview_text += "\n\n> Detailed feedback has been added as review comments on specific code lines."
    
    # Try to post the overview comment
    try:
        logger.info("Attempting to post overview comment")
        overview_success = post_review_comment(repo, pr_number, github_token, overview_text)
        if not overview_success:
            logger.error("Failed to post overview comment - API call returned False")
            # Try an alternative approach - post a simpler comment
            simple_overview = "# AI Review\n\nThe AI has reviewed this PR. See the detailed comments for feedback."
            logger.info("Attempting to post simplified overview comment")
            simple_success = post_review_comment(repo, pr_number, github_token, simple_overview)
            if not simple_success:
                logger.error("Failed to post simplified overview comment")
        else:
            logger.info("Successfully posted overview comment")
    except Exception as e:
        logger.error(f"Exception while posting overview comment: {str(e)}", exc_info=True)
        # Continue anyway to try posting line comments
    
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
            logger.debug(f"Extracted {len(standard_line_comments)} standard line comments")
            
            # Now extract file-specific sections and convert them to line comments for each file
            file_sections = {}
            
            # Look for comments in both the main review and the Detailed Feedback section
            detailed_feedback_pattern = r'(?:^|\n)## Detailed Feedback\s*\n(.*?)(?=\n##|\Z)'
            detailed_feedback_match = re.search(detailed_feedback_pattern, review_text, re.DOTALL)
            
            # If we found a Detailed Feedback section, extract comments from there
            detailed_feedback_text = ""
            if detailed_feedback_match:
                detailed_feedback_text = detailed_feedback_match.group(1).strip()
                logger.debug("Detailed Feedback section found")
            else:
                # If no Detailed Feedback section, use the whole review text
                detailed_feedback_text = review_text
                logger.warning("No Detailed Feedback section found, using entire review text")
                
            # Also check for a File-Specific Comments section
            file_comments_pattern = r'(?:^|\n)## File-Specific Comments\s*\n(.*?)(?=\n##|\Z)'
            file_comments_match = re.search(file_comments_pattern, review_text, re.DOTALL)
            
            if file_comments_match:
                file_comments_text = file_comments_match.group(1).strip()
                logger.debug("File-Specific Comments section found")
                # Append to detailed feedback text
                detailed_feedback_text += "\n\n" + file_comments_text
            
            # Extract file-specific comments
            file_section_pattern = r'(?:^|\n)### ([^\n:]+):(\d+)\s*\n(.*?)(?=\n### [^\n:]+:\d+|\Z)'
            
            file_section_matches = list(re.finditer(file_section_pattern, detailed_feedback_text, re.DOTALL))
            logger.debug(f"Found {len(file_section_matches)} file section matches")
            
            # Log the detailed feedback text for debugging
            logger.debug(f"Detailed feedback text (first 1000 chars): {detailed_feedback_text[:1000]}")
            
            # If no file section matches were found, try a more lenient pattern
            if not file_section_matches:
                logger.warning("No file section matches found with primary pattern, trying alternative pattern")
                alt_file_section_pattern = r'(?:^|\n)(?:In|File|At) ([^\n:,]+)[,:]? (?:line|at line) (\d+)[:]?\s*\n(.*?)(?=\n(?:In|File|At) [^\n:,]+[,:]? (?:line|at line) \d+[:]?|\Z)'
                file_section_matches = list(re.finditer(alt_file_section_pattern, detailed_feedback_text, re.DOTALL))
                logger.debug(f"Found {len(file_section_matches)} file section matches with alternative pattern")
            
            for match in file_section_matches:
                filename = match.group(1).strip()
                line_number = int(match.group(2))
                content = match.group(3).strip()
                
                logger.debug(f"Processing file section match: {filename}:{line_number}")
                logger.debug(f"Content preview: {content[:100]}...")
                
                if filename in file_line_map:
                    # Find the matching position for this line number
                    matching_lines = [
                        (line_num, pos, line_content) 
                        for line_num, pos, line_content in file_line_map[filename] 
                        if line_num == line_number
                    ]
                    if matching_lines:
                        # Use the first matching position
                        _, position, _ = matching_lines[0]
                        file_sections[f"{filename}:{line_number}"] = {
                            "path": filename,
                            "line": line_number,
                            "position": position,  # Store position separately from line number
                            "body": content
                        }
                        logger.debug(f"Added file section for {filename}:{line_number} at position {position}")
                    else:
                        logger.warning(f"No matching position found for {filename}:{line_number}")
                        # Try to find the closest line number as a fallback
                        if file_line_map[filename]:
                            closest_line = min(file_line_map[filename], key=lambda x: abs(x[0] - line_number))
                            closest_line_num, closest_pos, _ = closest_line
                            logger.info(f"Using closest line {closest_line_num} at position {closest_pos} as fallback")
                            file_sections[f"{filename}:{closest_line_num}"] = {
                                "path": filename,
                                "line": closest_line_num,
                                "position": closest_pos,
                                "body": f"[Originally for line {line_number}] {content}"
                            }
                else:
                    logger.warning(f"File {filename} not found in file_line_map")
                    # Try to find a similar filename as a fallback
                    similar_files = [f for f in file_line_map.keys() if filename in f or f in filename]
                    if similar_files:
                        similar_file = similar_files[0]
                        logger.info(f"Using similar file {similar_file} as fallback")
                        # Use the first line of the similar file
                        if file_line_map[similar_file]:
                            first_line = file_line_map[similar_file][0]
                            line_num, pos, _ = first_line
                            file_sections[f"{similar_file}:{line_num}"] = {
                                "path": similar_file,
                                "line": line_num,
                                "position": pos,
                                "body": f"[Originally for {filename}:{line_number}] {content}"
                            }
            
            # Convert file sections to line comments 
            additional_comments = list(file_sections.values())
            logger.debug(f"Added {len(additional_comments)} additional comments from file sections")
            
            # Combine standard and file-section comments
            all_comments = standard_line_comments + additional_comments
            
            # Post line comments if any were found
            if all_comments:
                logger.info(f"Posting {len(all_comments)} line-specific comments",
                           context={"comments_count": len(all_comments)})
                try:
                    line_comment_success = post_line_comments(repo, pr_number, github_token, all_comments)
                    if not line_comment_success:
                        logger.error("Failed to post line comments - API call returned False",
                                    context={"repo": repo, "pr_number": pr_number})
                        # Try posting comments one by one as a fallback
                        logger.info("Attempting to post comments one by one")
                        for i, comment in enumerate(all_comments):
                            try:
                                single_success = post_line_comments(repo, pr_number, github_token, [comment])
                                if single_success:
                                    logger.info(f"Successfully posted comment {i+1}/{len(all_comments)}")
                                else:
                                    logger.error(f"Failed to post comment {i+1}/{len(all_comments)}")
                                # Add a delay to avoid rate limits
                                time.sleep(2)
                            except Exception as e:
                                logger.error(f"Error posting comment {i+1}: {str(e)}")
                except Exception as e:
                    logger.error(f"Exception while posting line comments: {str(e)}", exc_info=True)
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