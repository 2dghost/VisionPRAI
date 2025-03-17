#!/usr/bin/env python3
"""
Test cases for the PR review testing system.

This module contains predefined test cases for evaluating the effectiveness
of the PR AI Reviewer in detecting issues and posting comments correctly.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test suites with specific focus areas
TEST_SUITES = {
    "bugs": [
        "missing_error_handling",
        "null_pointer",
        "off_by_one",
        "resource_leak",
        "race_condition"
    ],
    "style": [
        "code_style",
        "naming_convention",
        "documentation",
        "code_organization"
    ],
    "security": [
        "sql_injection",
        "xss_vulnerability",
        "insecure_auth",
        "hardcoded_secrets",
        "path_traversal",
        "command_injection"
    ],
    "all": []  # Will be populated with all test cases
}

# Populate the "all" suite
for suite_tests in TEST_SUITES.values():
    for test in suite_tests:
        if test not in TEST_SUITES["all"]:
            TEST_SUITES["all"].append(test)

def load_test_cases(test_suite: str = "all") -> List[Dict[str, Any]]:
    """
    Load test cases from the test suite.
    
    Args:
        test_suite: Name of the test suite to load (bugs, style, security, all)
        
    Returns:
        List of test case dictionaries
    """
    if test_suite not in TEST_SUITES:
        logger.error(f"Invalid test suite: {test_suite}. Using 'all' instead.")
        test_suite = "all"
    
    # Get the list of test cases for the suite
    suite_test_cases = TEST_SUITES[test_suite]
    
    # Load test case details from JSON files
    test_cases = []
    test_dir = os.path.join(os.path.dirname(__file__), "test_cases")
    os.makedirs(test_dir, exist_ok=True)
    
    # If specific suite selected, only load those test cases
    # If "all" is selected, load all test cases
    for root, dirs, files in os.walk(test_dir):
        for file in files:
            if not file.endswith(".json"):
                continue
                
            case_name = os.path.splitext(file)[0]
            
            # Skip if not in the selected suite and not using "all"
            if test_suite != "all" and case_name not in suite_test_cases:
                continue
                
            try:
                with open(os.path.join(root, file), "r") as f:
                    test_case = json.load(f)
                    test_cases.append(test_case)
            except Exception as e:
                logger.error(f"Error loading test case {file}: {str(e)}")
    
    # If no test cases found, load default test cases
    if not test_cases:
        logger.info("No test case files found, loading default test cases")
        test_cases = generate_default_test_cases(suite_test_cases if test_suite != "all" else None)
    
    logger.info(f"Loaded {len(test_cases)} test cases from suite '{test_suite}'")
    return test_cases

def generate_default_test_cases(case_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Generate default test cases when no files are found.
    
    Args:
        case_names: Optional list of case names to generate, or None for all
        
    Returns:
        List of test case dictionaries
    """
    default_cases = [
        {
            "name": "missing_error_handling",
            "description": "Code missing proper error handling",
            "files": {
                "example.py": [
                    "def process_data(data):",
                    "    # Missing try-except blocks",
                    "    result = data['key'] * 10",
                    "    return process_result(result)"
                ]
            },
            "expected_comments": [
                {
                    "path": "example.py",
                    "line": 3,
                    "body": "This code lacks error handling. Consider adding try-except blocks to handle potential KeyError exceptions."
                }
            ]
        },
        {
            "name": "code_style",
            "description": "Code with style issues",
            "files": {
                "style_example.py": [
                    "def badlyNamedFunction( a,b ):",
                    "    x=a+b",
                    "    return x"
                ]
            },
            "expected_comments": [
                {
                    "path": "style_example.py",
                    "line": 1,
                    "body": "Function naming doesn't follow PEP 8 style guidelines. Consider using snake_case for function names."
                },
                {
                    "path": "style_example.py",
                    "line": 2,
                    "body": "Missing spaces around operators. Add spaces around the '+' operator and the '=' assignment."
                }
            ]
        },
        {
            "name": "sql_injection",
            "description": "Code with SQL injection vulnerability",
            "files": {
                "database.py": [
                    "def get_user(username):",
                    "    cursor.execute(f\"SELECT * FROM users WHERE username = '{username}'\")",
                    "    return cursor.fetchone()"
                ]
            },
            "expected_comments": [
                {
                    "path": "database.py",
                    "line": 2,
                    "body": "SQL Injection vulnerability detected. Use parameterized queries instead of string formatting."
                }
            ]
        }
    ]
    
    # Filter by case names if provided
    if case_names:
        default_cases = [case for case in default_cases if case["name"] in case_names]
    
    # Save default cases to files for future use
    test_dir = os.path.join(os.path.dirname(__file__), "test_cases")
    os.makedirs(test_dir, exist_ok=True)
    
    for case in default_cases:
        filename = os.path.join(test_dir, f"{case['name']}.json")
        if not os.path.exists(filename):
            try:
                with open(filename, "w") as f:
                    json.dump(case, f, indent=2)
                logger.info(f"Saved default test case to {filename}")
            except Exception as e:
                logger.error(f"Error saving default test case {case['name']}: {str(e)}")
    
    return default_cases

def create_test_pr_content(test_case: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare content for creating a test PR based on a test case.
    
    Args:
        test_case: Test case dictionary
        
    Returns:
        Dictionary with PR creation details
    """
    files = test_case.get("files", {})
    description = test_case.get("description", "Test PR for PR reviewer")
    
    return {
        "title": f"Test PR: {test_case['name']}",
        "body": f"## Test Case: {test_case['name']}\n\n{description}\n\n*This is an automated test PR.*",
        "files": files
    }

def get_expected_comments(test_case: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Get expected comments from a test case.
    
    Args:
        test_case: Test case dictionary
        
    Returns:
        List of expected comment dictionaries
    """
    return test_case.get("expected_comments", [])

def save_test_results(test_case: Dict[str, Any], results: Dict[str, Any]) -> None:
    """
    Save test results to a file.
    
    Args:
        test_case: Test case that was executed
        results: Results of the test
    """
    os.makedirs("test-results", exist_ok=True)
    
    # Create a result object with test case info and results
    result_obj = {
        "test_case": test_case["name"],
        "description": test_case.get("description", ""),
        "timestamp": results.get("timestamp", ""),
        "results": results
    }
    
    # Save to a file named with the test case name and timestamp
    filename = f"test-results/{test_case['name']}-{results.get('timestamp', 'unknown')}.json"
    try:
        with open(filename, "w") as f:
            json.dump(result_obj, f, indent=2)
        logger.info(f"Saved test results to {filename}")
    except Exception as e:
        logger.error(f"Error saving test results: {str(e)}")

def main():
    """Function to test this module directly."""
    print("Loading test cases...")
    test_cases = load_test_cases()
    print(f"Loaded {len(test_cases)} test cases")
    for i, case in enumerate(test_cases):
        print(f"\nTest Case {i+1}: {case['name']}")
        print(f"Description: {case.get('description', 'No description')}")
        print(f"Expected comments: {len(case.get('expected_comments', []))}")

if __name__ == "__main__":
    main() 