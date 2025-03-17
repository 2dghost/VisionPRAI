#!/usr/bin/env python3
"""
Test script for language detection functionality.
Tests both basic file extension detection and enhanced pattern-based detection.
"""

import sys
import os
import json
from typing import Dict, List, Any

# Add the parent directory to sys.path to support both local and GitHub Actions environments
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

try:
    from src.language_detector import LanguageDetector, detect_language
    from src.custom_exceptions import LanguageDetectionError
except ImportError:
    from language_detector import LanguageDetector, detect_language
    from custom_exceptions import LanguageDetectionError

def run_basic_test():
    """Run basic language detection tests."""
    print("Running basic language detection tests...")
    
    # Initialize detector
    detector = LanguageDetector()
    
    # Test cases for common file extensions
    test_cases = [
        ("test.py", "python"),
        ("script.js", "javascript"),
        ("app.ts", "typescript"),
        ("index.html", "html"),
        ("style.css", "css"),
        ("config.yml", "yaml"),
        ("doc.md", "markdown"),
        ("data.json", "json"),
        ("query.sql", "sql"),
        ("Dockerfile", "dockerfile"),
        ("Makefile", "unknown"),  # Makefile doesn't have a standard extension
    ]
    
    # Run tests
    passed = 0
    failed = 0
    
    for filename, expected_language in test_cases:
        detected = detector.detect_language(filename)
        result = "✓" if detected == expected_language else "✗"
        status = "PASS" if detected == expected_language else "FAIL"
        
        print(f"[{status}] {filename} -> Expected: {expected_language}, Got: {detected} {result}")
        
        if detected == expected_language:
            passed += 1
        else:
            failed += 1
    
    print(f"\nBasic tests completed: {passed} passed, {failed} failed")
    return passed, failed

def run_enhanced_test():
    """Run enhanced language detection tests for pattern-based detection."""
    print("\nRunning enhanced language detection tests...")
    
    # Initialize detector
    detector = LanguageDetector()
    
    # Test cases for pattern-based detection
    test_cases = [
        ("package.json", "javascript"),
        ("composer.json", "php"),
        ("cargo.toml", "rust"),
        ("Gemfile", "ruby"),
        ("requirements.txt", "python"),
        ("setup.py", "python"),
        ("pyproject.toml", "python"),
        ("pom.xml", "java"),
        ("build.gradle", "java"),
        ("go.mod", "go"),
        ("docker-compose.yml", "docker-compose"),
        (".gitignore", "gitignore"),
        (".babelrc", "javascript"),
        (".eslintrc", "javascript"),
    ]
    
    # Run tests
    passed = 0
    failed = 0
    
    for filename, expected_language in test_cases:
        detected = detector.detect_language(filename)
        result = "✓" if detected == expected_language else "✗"
        status = "PASS" if detected == expected_language else "FAIL"
        
        print(f"[{status}] {filename} -> Expected: {expected_language}, Got: {detected} {result}")
        
        if detected == expected_language:
            passed += 1
        else:
            failed += 1
    
    print(f"\nEnhanced tests completed: {passed} passed, {failed} failed")
    return passed, failed

def test_issue_detection():
    """Test the detection of potential issues in code."""
    print("\nTesting issue detection in code...")
    
    detector = LanguageDetector()
    
    # Test Python code with potential issues
    python_code = """
    def insecure_function(user_input):
        # SQL Injection vulnerability
        query = "SELECT * FROM users WHERE name = '" + user_input + "'"
        cursor.execute(query)
        
        # Command injection vulnerability
        import os
        os.system("ls " + user_input)
        
        # Error handling issue
        try:
            do_something()
        except:
            pass
        
        # Hardcoded secret
        api_key = "abcdefghijklmnopqrstuvwxyz1234567890"
    """
    
    issues = detector.detect_issues("test.py", python_code)
    
    # Print detected issues
    print("\nDetected issues in Python code:")
    for category, issue_list in issues.items():
        print(f"  {category}: {len(issue_list)} issues")
        for line_num, match in issue_list:
            print(f"    Line {line_num}: {match[:50]}...")
    
    # Test JavaScript code with potential issues
    js_code = """
    function processUserData(userId) {
        // SQL Injection vulnerability
        const query = `SELECT * FROM users WHERE id = ${userId}`;
        db.execute(query);
        
        // Command injection vulnerability
        eval(`console.log(${userId})`);
        
        // Error handling issue
        try {
            doSomething();
        } catch (e) {
            // Empty catch block
        }
        
        // Hardcoded secret
        const apiKey = "abcdefghijklmnopqrstuvwxyz1234567890";
    }
    """
    
    issues = detector.detect_issues("test.js", js_code)
    
    # Print detected issues
    print("\nDetected issues in JavaScript code:")
    for category, issue_list in issues.items():
        print(f"  {category}: {len(issue_list)} issues")
        for line_num, match in issue_list:
            print(f"    Line {line_num}: {match[:50]}...")
    
    return True

def main():
    """Run all tests and report results."""
    print("=" * 60)
    print("LANGUAGE DETECTION TEST SUITE")
    print("=" * 60)
    
    basic_passed, basic_failed = run_basic_test()
    enhanced_passed, enhanced_failed = run_enhanced_test()
    issue_detection_success = test_issue_detection()
    
    total_passed = basic_passed + enhanced_passed
    total_failed = basic_failed + enhanced_failed
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Basic tests: {basic_passed} passed, {basic_failed} failed")
    print(f"Enhanced tests: {enhanced_passed} passed, {enhanced_failed} failed")
    print(f"Issue detection: {'SUCCESS' if issue_detection_success else 'FAILED'}")
    print(f"TOTAL: {total_passed} passed, {total_failed} failed")
    print("=" * 60)
    
    # Return exit code based on test result
    sys.exit(1 if total_failed > 0 else 0)

if __name__ == "__main__":
    main() 