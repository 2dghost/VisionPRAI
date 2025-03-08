import unittest
from unittest.mock import patch, MagicMock

import pytest
import responses

from src.model_adapters import ModelAdapter


class TestModelAdapter(unittest.TestCase):
    """Test the ModelAdapter class."""

    def setUp(self):
        """Set up test fixtures."""
        self.openai_config = {
            "provider": "openai",
            "api_key": "test-key-openai",
            "endpoint": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-4",
            "max_tokens": 1000
        }
        
        self.anthropic_config = {
            "provider": "anthropic",
            "api_key": "test-key-anthropic",
            "endpoint": "https://api.anthropic.com/v1/messages",
            "model": "claude-3-opus-20240229",
            "max_tokens": 1000
        }

    def test_init_provider_lowercase(self):
        """Test that provider is converted to lowercase."""
        config = self.openai_config.copy()
        config["provider"] = "OPENAI"
        adapter = ModelAdapter(config)
        self.assertEqual(adapter.provider, "openai")

    @patch.dict('os.environ', {'OPENAI_API_KEY': 'env-key-openai'})
    def test_init_api_key_from_env(self):
        """Test that API key is taken from environment if not in config."""
        config = self.openai_config.copy()
        del config["api_key"]
        adapter = ModelAdapter(config)
        self.assertEqual(adapter.api_key, "env-key-openai")

    def test_init_missing_api_key(self):
        """Test that ValueError is raised if API key is missing."""
        config = self.openai_config.copy()
        del config["api_key"]
        with self.assertRaises(ValueError):
            ModelAdapter(config)

    @responses.activate
    def test_call_openai_chat(self):
        """Test OpenAI chat API call."""
        # Setup mock response
        responses.add(
            responses.POST,
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "Review response"}}]},
            status=200
        )
        
        adapter = ModelAdapter(self.openai_config)
        response = adapter.generate_response("Test prompt")
        
        self.assertEqual(response, "Review response")
        self.assertEqual(len(responses.calls), 1)
        
        # Check request payload
        request_body = responses.calls[0].request.body.decode()
        self.assertIn("Test prompt", request_body)
        self.assertIn(self.openai_config["model"], request_body)

    @responses.activate
    def test_call_anthropic(self):
        """Test Anthropic API call."""
        # Setup mock response
        responses.add(
            responses.POST,
            "https://api.anthropic.com/v1/messages",
            json={"content": [{"text": "Review response"}]},
            status=200
        )
        
        adapter = ModelAdapter(self.anthropic_config)
        response = adapter.generate_response("Test prompt")
        
        self.assertEqual(response, "Review response")
        self.assertEqual(len(responses.calls), 1)
        
        # Check request payload
        request_body = responses.calls[0].request.body.decode()
        self.assertIn("Test prompt", request_body)
        self.assertIn(self.anthropic_config["model"], request_body)

    def test_unsupported_provider(self):
        """Test that ValueError is raised for unsupported provider."""
        config = self.openai_config.copy()
        config["provider"] = "unsupported"
        adapter = ModelAdapter(config)
        
        with self.assertRaises(ValueError):
            adapter.generate_response("Test prompt")

    @responses.activate
    def test_api_error_handling(self):
        """Test error handling for API calls."""
        # Setup mock error response
        responses.add(
            responses.POST,
            "https://api.openai.com/v1/chat/completions",
            json={"error": {"message": "API error"}},
            status=400
        )
        
        adapter = ModelAdapter(self.openai_config)
        
        with self.assertRaises(RuntimeError):
            adapter.generate_response("Test prompt")


if __name__ == '__main__':
    unittest.main()