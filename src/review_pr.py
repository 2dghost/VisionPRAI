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
    from language_detector import LanguageDetector, detect_language, detect_issues
    from custom_exceptions import (
        VisionPRAIError,
        ConfigurationError,
        MissingConfigurationError,
        InvalidConfigurationError,
        CommentExtractionError,
        LanguageDetectionError
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
    from src.language_detector import LanguageDetector, detect_language, detect_issues
    from src.custom_exceptions import (
        VisionPRAIError,
        ConfigurationError,
        MissingConfigurationError, 
        InvalidConfigurationError,
        CommentExtractionError,
        LanguageDetectionError
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
    
    # Check if language detection is enabled
    language_detection_enabled = config.get("review", {}).get("language_detection", {}).get("enabled", False)
    
    # Get review format settings
    format_config = config.get("review", {}).get("format", {})
    include_summary = format_config.get("include_summary", True)
    include_overview = format_config.get("include_overview", True)
    include_recommendations = format_config.get("include_recommendations", True)
    template_style = format_config.get("template_style", "default")
    split_comments = format_config.get("split_comments", False)
    
    # Extract relevant file info
    file_info = []
    
    # If language detection is enabled, add language information to file info
    if language_detection_enabled:
        language_detector = LanguageDetector(config_path=config.get("config_path", "config.yaml"))
        
        for file in files:
            language = language_detector.detect_language(file["filename"])
            file_info_entry = {
                "filename": file["filename"],
                "status": file["status"],
                "additions": file["additions"],
                "deletions": file["deletions"],
                "changes": file["changes"],
                "language": language
            }
            
            # Only add detailed language analysis for non-binary files that can be analyzed
            if file.get("patch") and language != "unknown":
                try:
                    # Extract code from the patch
                    code_content = file.get("patch", "")
                    # Detect potential issues
                    detected_issues = language_detector.detect_issues(file["filename"], code_content)
                    
                    # Only add if there are issues
                    if detected_issues:
                        file_info_entry["potential_issues"] = {}
                        for category, issues in detected_issues.items():
                            issue_count = len(issues)
                            if issue_count > 0:
                                file_info_entry["potential_issues"][category] = issue_count
                except Exception as e:
                    logger.warning(f"Error detecting issues in {file['filename']}: {str(e)}")
            
            file_info.append(file_info_entry)
    else:
        # Default file info without language detection
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
    )
    
    # Add language-specific guidance if language detection is enabled
    if language_detection_enabled and file_info:
        # Collect detected languages
        languages = set()
        for file in file_info:
            if "language" in file and file["language"] != "unknown":
                languages.add(file["language"])
                
        # Add language-specific guidance section to the prompt
        if languages:
            prompt += "## Language-Specific Guidance\n\n"
            
            for language in sorted(languages):
                if language == "python":
                    prompt += "### Python Best Practices\n"
                    prompt += "- Use type hints for better maintainability and IDE support\n"
                    prompt += "- Prefer context managers (with statements) for resource management\n"
                    prompt += "- Use f-strings instead of older string formatting methods\n"
                    prompt += "- Follow PEP 8 style guidelines\n"
                    prompt += "- Use specific exception types rather than generic Exception or bare except\n"
                    prompt += "- Validate user inputs before using in SQL queries to prevent injection\n\n"
                elif language == "javascript" or language == "typescript":
                    prompt += f"### {language.capitalize()} Best Practices\n"
                    prompt += "- Prefer const and let over var\n"
                    prompt += "- Use === instead of == for comparisons\n"
                    prompt += "- Validate user inputs before adding to DOM or using in queries\n"
                    prompt += "- Avoid direct DOM manipulation when using frameworks\n"
                    prompt += "- Use async/await instead of raw Promises when possible\n"
                    if language == "typescript":
                        prompt += "- Avoid using 'any' type except when absolutely necessary\n"
                        prompt += "- Prefer interfaces for object shapes over type aliases\n"
                        prompt += "- Use non-null assertion operator (!.) sparingly\n"
                    prompt += "\n"
                elif language == "java":
                    prompt += "### Java Best Practices\n"
                    prompt += "- Use try-with-resources for AutoCloseable resources\n"
                    prompt += "- Prefer prepared statements for SQL queries\n"
                    prompt += "- Follow standard naming conventions (camelCase for methods/variables)\n"
                    prompt += "- Properly handle exceptions with specific catch blocks\n"
                    prompt += "- Use StringBuilder for string concatenation in loops\n\n"
                elif language == "csharp":
                    prompt += "### C# Best Practices\n"
                    prompt += "- Use 'using' statements for IDisposable resources\n"
                    prompt += "- Prefer async/await over Task.Continue patterns\n"
                    prompt += "- Use parameterized queries for database operations\n"
                    prompt += "- Prefer properties over public fields\n"
                    prompt += "- Follow standard naming conventions (PascalCase for public members)\n\n"
                elif language == "php":
                    prompt += "### PHP Best Practices\n"
                    prompt += "- Use prepared statements for SQL queries\n"
                    prompt += "- Always validate and sanitize user input\n"
                    prompt += "- Follow PSR standards for code formatting\n"
                    prompt += "- Use type declarations (PHP 7+)\n"
                    prompt += "- Avoid using the @ error suppression operator\n\n"
                elif language == "go":
                    prompt += "### Go Best Practices\n"
                    prompt += "- Handle errors explicitly, don't use _ to ignore them\n"
                    prompt += "- Use context for cancellation and timeouts\n"
                    prompt += "- Follow Go's standard formatting (gofmt)\n"
                    prompt += "- Prefer composition over inheritance\n"
                    prompt += "- Use meaningful variable names (not single letters)\n\n"
            
            prompt += "\n"
    
    prompt += (
        "CRITICAL: For each issue, you MUST format your line-specific comments exactly like this:\n\n"
        "### filename.ext:line_number\n"
        "Problem: <clear explanation of the issue>\n\n"
        "```suggestion\n"
        "<exact code that should replace the original code>\n"
        "```\n\n"
        "Explanation: <why this change improves the code, including technical rationale, potential bugs prevented, and relevant best practices>\n\n"
        "Guidelines:\n"
        "1. ALWAYS include the file name and line number in the header (### filename.ext:line_number)\n"
        "2. Each suggestion must be preceded by a clear explanation of the issue\n"
        "3. The suggestion block must contain the complete fixed code\n"
        "4. After each suggestion, provide a DETAILED explanation including:\n"
        "   - Technical reasoning behind the change\n"
        "   - Specific bugs or issues prevented\n"
        "   - How it follows best practices or patterns used elsewhere in the codebase\n"
        "   - Performance, security, or maintainability benefits\n"
        "   - Any relevant documentation or standards that support your suggestion\n"
        "   - Educational explanations of the concepts involved for less experienced developers\n"
        "   - Links to relevant documentation or resources when appropriate\n"
        "   - Alternative approaches that could also solve the issue and their trade-offs\n"
        "5. Make suggestions ONLY for lines that exist in the diff\n"
        "6. If you find ANY issues, you MUST provide at least one code suggestion\n"
        "7. IMPORTANT: Each file-specific comment MUST start with '### filename.ext:line_number' format\n"
        "8. Educational Context: For each issue, explain the underlying programming concepts to help developers learn\n"
        "9. Best Practices References: Cite specific industry standards, style guides, or documentation\n"
        "10. Security Implications: Always highlight security implications when relevant\n"
        "11. Performance Considerations: Include performance impacts of problematic code and improvements\n"
        "12. Alternative Approaches: Provide at least one alternative solution with pros and cons\n"
        "13. Code Quality Metrics: Explain how your suggestion improves maintainability, readability, or testability\n"
        "14. Common Pitfalls: Explain common mistakes related to the issue to help prevent similar problems\n"
        "15. Cross-Language Context: When applicable, compare how similar patterns work in other languages\n"
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
        "DO NOT provide general recommendations - ONLY specific code changes with file and line references.\n"
        "ENSURE each explanation is detailed and educational, including:\n"
        "- The technical reasoning behind the suggested change\n"
        "- Potential issues or bugs prevented by the change\n"
        "- How the change improves code quality, performance, or security\n"
        "- Any relevant best practices, patterns or standards that support the suggestion\n"
        "- Educational context to help less experienced developers understand WHY the change matters\n"
        "- References to documentation or resources when applicable\n"
        "- Alternative approaches that could also solve the issue with their trade-offs\n"
        "- Examples of how the issue could manifest in production environments\n"
        "- For security issues, explanation of attack vectors and mitigation strategies\n"
    )
    
    if include_recommendations:
        sections.append(
            "## Recommendations\n"
            "IMPORTANT: Do NOT provide general text recommendations here. Instead, for each recommendation:\n"
            "1. Identify the specific file and line number\n"
            "2. Format as '### filename.ext:line_number'\n"
            "3. Explain the issue\n"
            "4. Provide a code suggestion block with the exact code change\n"
            "5. Explain why your solution is better\n"
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
        "- NEVER provide general recommendations without specific code changes\n"
        "- ALL recommendations MUST be in the form of specific code changes with file and line references\n"
        "- Provide comprehensive explanations that help developers learn and improve their coding skills\n"
        "- Include context about why your suggestions follow best practices or improve the codebase\n"
        "- Make your explanations educational for programmers of all skill levels\n"
        "- Include specific examples, not just vague assertions\n"
        "- Cite relevant documentation, standards, or articles when appropriate\n"
        "- For each alternative approach mentioned, explain why you chose your suggested approach\n"
        "- Tailor your explanations to the apparent experience level of the developer\n"
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
            
            # Parse each file section match into a separate comment
            for match in file_section_matches:
                filename = match.group(1).strip()
                line_number = int(match.group(2))
                content = match.group(3).strip()
                
                logger.debug(f"Processing file section match: {filename}:{line_number}")
                logger.debug(f"Content preview: {content[:100]}...")
                
                # Check if we need to split the content further (if it has multiple problems for the same file+line)
                problem_sections = []
                problem_pattern = re.compile(r'(?:^|\n)(?:Problem|Issue):\s*(.*?)(?:\n\n|\n(?:Problem|Issue|Suggestion|Explanation):|$)', re.DOTALL)
                problem_matches = list(problem_pattern.finditer(content))
                
                # If there are explicit problem sections, split the content into separate comments
                if problem_matches:
                    logger.debug(f"Found {len(problem_matches)} problem sections in content for {filename}:{line_number}")
                    
                    for i, problem_match in enumerate(problem_matches):
                        problem_text = problem_match.group(1).strip()
                        
                        # Try to find matching suggestion and explanation
                        suggestion_pattern = re.compile(r'(?:^|\n)Suggestion:\s*(.*?)(?:\n\n|\n(?:Problem|Issue|Explanation):|$)', re.DOTALL)
                        explanation_pattern = re.compile(r'(?:^|\n)Explanation:\s*(.*?)(?:\n\n|\n(?:Problem|Issue|Suggestion):|$)', re.DOTALL)
                        
                        # Search for suggestion and explanation after this problem
                        start_pos = problem_match.end()
                        end_pos = len(content)
                        if i < len(problem_matches) - 1:
                            end_pos = problem_matches[i+1].start()
                        
                        section_content = content[start_pos:end_pos]
                        
                        suggestion_match = suggestion_pattern.search(section_content)
                        explanation_match = explanation_pattern.search(section_content)
                        
                        suggestion_text = suggestion_match.group(1).strip() if suggestion_match else ""
                        explanation_text = explanation_match.group(1).strip() if explanation_match else ""
                        
                        # Format as a complete comment
                        formatted_content = f"Problem: {problem_text}\n\n"
                        if suggestion_text:
                            formatted_content += f"Suggestion: {suggestion_text}\n\n"
                        if explanation_text:
                            formatted_content += f"Explanation: {explanation_text}\n\n"
                        
                        problem_sections.append(formatted_content)
                
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
                        
                        # If we have split the content into problem sections, create a separate comment for each
                        if problem_sections:
                            for i, section in enumerate(problem_sections):
                                section_key = f"{filename}:{line_number}:{i}"
                                file_sections[section_key] = {
                                    "path": filename,
                                    "line": line_number,
                                    "position": position,
                                    "body": section
                                }
                                logger.debug(f"Added split file section {i+1}/{len(problem_sections)} for {filename}:{line_number}")
                        else:
                            # Add the entire content as a single comment
                            file_sections[f"{filename}:{line_number}"] = {
                                "path": filename,
                                "line": line_number,
                                "position": position,
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
                            
                            # If we have split the content into problem sections, create a separate comment for each
                            if problem_sections:
                                for i, section in enumerate(problem_sections):
                                    section_key = f"{filename}:{closest_line_num}:{i}"
                                    file_sections[section_key] = {
                                        "path": filename,
                                        "line": closest_line_num,
                                        "position": closest_pos,
                                        "body": f"[Originally for line {line_number}] {section}"
                                    }
                                    logger.debug(f"Added split fallback file section {i+1}/{len(problem_sections)} for {filename}:{closest_line_num}")
                            else:
                                # Add the entire content as a single comment
                                file_sections[f"{filename}:{closest_line_num}"] = {
                                    "path": filename,
                                    "line": closest_line_num,
                                    "position": closest_pos,
                                    "body": f"[Originally for line {line_number}] {content}"
                                }
                                logger.debug(f"Added fallback file section for {filename}:{closest_line_num}")
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
                            
                            # If we have split the content into problem sections, create a separate comment for each
                            if problem_sections:
                                for i, section in enumerate(problem_sections):
                                    section_key = f"{similar_file}:{line_num}:{i}"
                                    file_sections[section_key] = {
                                        "path": similar_file,
                                        "line": line_num,
                                        "position": pos,
                                        "body": f"[Originally for {filename}:{line_number}] {section}"
                                    }
                                    logger.debug(f"Added split similar file section {i+1}/{len(problem_sections)} for {similar_file}:{line_num}")
                            else:
                                # Add the entire content as a single comment
                                file_sections[f"{similar_file}:{line_num}"] = {
                                    "path": similar_file,
                                    "line": line_num,
                                    "position": pos,
                                    "body": f"[Originally for {filename}:{line_number}] {content}"
                                }
                                logger.debug(f"Added similar file section for {similar_file}:{line_num}")
            
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
                    # Ensure all comments have the required fields for the GitHub API
                    for comment in all_comments:
                        # GitHub requires these fields: path, body, line, side
                        if "path" not in comment or "body" not in comment:
                            logger.error(f"Comment missing required fields: {comment}")
                            continue
                            
                        # Ensure line is an integer
                        if "line" in comment:
                            comment["line"] = int(comment["line"])
                        else:
                            logger.warning(f"Comment missing line number for {comment.get('path', 'unknown file')}")
                            comment["line"] = 1  # Default to line 1 if no line specified
                        
                        # Ensure side is always RIGHT (for new version)
                        comment["side"] = "RIGHT"
                        
                        # For multi-line comments, ensure start_side is set if start_line is present
                        if "start_line" in comment:
                            comment["start_line"] = int(comment["start_line"]) 
                            comment["start_side"] = "RIGHT"
                    
                    # Remove any comments that don't have the required fields
                    valid_comments = [c for c in all_comments if "path" in c and "body" in c and "line" in c and "side" in c]
                    
                    if len(valid_comments) < len(all_comments):
                        logger.warning(f"Filtered out {len(all_comments) - len(valid_comments)} invalid comments")
                    
                    # Log sample comments for debugging
                    if valid_comments:
                        sample = valid_comments[0]
                        logger.debug(f"Sample comment: path={sample['path']}, line={sample['line']}, side={sample['side']}")
                        
                        # Log number of comments per file
                        file_counts = {}
                        for c in valid_comments:
                            file_counts[c["path"]] = file_counts.get(c["path"], 0) + 1
                        logger.debug(f"Comments by file: {file_counts}")
                    
                    # Post the comments
                    if valid_comments:
                        logger.info("Posting line comments with overview_text - this should use the draft review approach")
                        line_comment_success = post_line_comments(
                            repo, 
                            pr_number, 
                            github_token, 
                            valid_comments,
                            overview_text=review_text  # Pass the review text as the overview
                        )
                        if not line_comment_success:
                            logger.error("Failed to post line comments - API call returned False",
                                        context={"repo": repo, "pr_number": pr_number})
                    else:
                        logger.warning("No valid comments to post")
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