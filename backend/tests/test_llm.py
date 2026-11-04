"""Offline tests for the Bedrock LLM wrapper (unittest discover and pytest)."""

import os
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import llm  # noqa: E402


class FakeConverseClient:
    """Fake converse client recording calls and returning a canned response."""

    def __init__(self, response=None):
        self.last_model_id = None
        self.last_messages = None
        self.response = response or {
            "output": {
                "message": {
                    "content": [{"text": "enterprise "}, {"text": "answer"}]
                }
            },
            "usage": {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18},
            "stopReason": "end_turn",
        }

    def converse(self, model_id: str, messages: list) -> dict:
        self.last_model_id = model_id
        self.last_messages = messages
        return self.response


class BedrockWrapperOfflineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeConverseClient()

    def test_answer_returns_structured_result(self) -> None:
        client = llm.BedrockLLM(
            client=self.fake,
            settings=llm.LLMSettings(model_id="test-model", region="us-east-1"),
        )
        result = client.answer("ping")

        assert result.text == "enterprise answer"
        assert result.model_id == "test-model"
        assert result.usage == {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
        }
        assert self.fake.last_model_id == "test-model"
        assert self.fake.last_messages == [
            {"role": "user", "content": [{"text": "ping"}]}
        ]

    def test_empty_response_raises(self) -> None:
        empty = FakeConverseClient(response={"output": {"message": {"content": []}}})
        client = llm.BedrockLLM(
            client=empty,
            settings=llm.LLMSettings(model_id="test-model", region="us-east-1"),
        )
        with self.assertRaises(ValueError) as ctx:
            client.answer("ping")
        assert str(ctx.exception) == "Bedrock converse response has no text content"

    def test_no_boto3_imported_offline(self) -> None:
        assert "boto3" not in sys.modules


class SettingsTest(unittest.TestCase):
    def test_defaults_with_empty_environment(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            settings = llm.LLMSettings.from_env()
            assert settings.model_id == ""
            assert settings.region == "us-east-1"
            assert llm.integration_enabled() is False

    def test_values_read_from_environment(self) -> None:
        with unittest.mock.patch.dict(
            os.environ,
            {"BEDROCK_MODEL_ID": "x", "AWS_REGION": "eu-west-1", "AWS_INTEGRATION": "1"},
        ):
            settings = llm.LLMSettings.from_env()
            assert settings.model_id == "x"
            assert settings.region == "eu-west-1"
            assert llm.integration_enabled() is True

    def test_integration_disabled_when_zero(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"AWS_INTEGRATION": "0"}):
            assert llm.integration_enabled() is False

    def test_settings_fields_have_no_identity_material(self) -> None:
        assert list(llm.LLMSettings.from_env().__dict__.keys()) == ["model_id", "region"]


@unittest.skipUnless(
    os.environ.get("AWS_INTEGRATION") == "1",
    "integration test: set AWS_INTEGRATION=1 and install boto3 to run against "
    "real AWS Bedrock",
)
class IntegrationConverseTest(unittest.TestCase):
    def test_real_converse_call(self) -> None:
        try:
            client = llm.build_default_client()
        except ImportError:
            self.skipTest("boto3 not installed")

        model_id = os.environ.get("BEDROCK_MODEL_ID", "")
        if not model_id:
            self.skipTest("BEDROCK_MODEL_ID unset")

        settings = llm.LLMSettings(model_id=model_id, region=os.environ.get("AWS_REGION", "us-east-1"))
        result = llm.BedrockLLM(client=client, settings=settings).answer("ping")

        assert isinstance(result, llm.LLMResult)
        assert result.text != ""


if __name__ == "__main__":
    unittest.main()
