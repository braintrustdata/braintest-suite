import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pydantic import ValidationError

from braintest_suite.config import (
    DEFAULT_LOG_PROFILE_CALLABLE,
    DEFAULT_LOG_PROFILE_OPTIONS,
    LogProfileConfig,
    _resolve_log_profile_reference,
)
from braintest_suite.loadtest.log_profile import (
    create_log_profile_task,
    load_log_profile_factory,
)
from braintest_suite.loadtest.log_profiles import default_multiturn_convo_profile


class LogProfileConfigTest(unittest.TestCase):
    def test_log_profile_uses_default_callable_when_omitted(self):
        validated = LogProfileConfig.model_validate({})

        self.assertEqual(
            validated.callable,
            DEFAULT_LOG_PROFILE_CALLABLE,
        )
        self.assertEqual(validated.options, DEFAULT_LOG_PROFILE_OPTIONS)

    def test_log_profile_accepts_callable_and_options(self):
        validated = LogProfileConfig.model_validate(
            {
                "callable": "profiles.customer:create_profile",
                "options": {"tool_probability": 0.4},
            }
        )

        self.assertEqual(
            validated.callable,
            "profiles.customer:create_profile",
        )
        self.assertEqual(validated.options, {"tool_probability": 0.4})

    def test_bundled_profile_options_are_validated(self):
        with self.assertRaisesRegex(ValidationError, "faker_pool_size"):
            LogProfileConfig.model_validate(
                {
                    "options": {
                        "faker_pool_size": "many",
                        "max_tokens": 1000,
                    }
                }
            )

    def test_log_profile_rejects_invalid_callable_reference(self):
        with self.assertRaisesRegex(ValidationError, "<module-or-file>:<factory>"):
            LogProfileConfig.model_validate({"callable": "customer_profile"})

    def test_relative_profile_path_is_resolved_from_config_directory(self):
        config_directory = Path("/tmp/customer-config")

        resolved = _resolve_log_profile_reference(
            "profiles/customer_profile.py:create_profile",
            config_directory=config_directory,
        )

        self.assertEqual(
            resolved,
            f"{config_directory.resolve()}/profiles/customer_profile.py:create_profile",
        )


class LogProfileLoaderTest(unittest.TestCase):
    def test_loads_factory_from_file_relative_to_config_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_directory = Path(temporary_directory)
            profile_path = base_directory / "customer_profile.py"
            profile_path.write_text(
                "def create_profile(config):\n    marker = config['marker']\n    return lambda: marker\n"
            )

            factory = load_log_profile_factory(
                f"{profile_path}:create_profile",
            )

            self.assertEqual(factory({"marker": "customer"})(), "customer")

    @patch("braintest_suite.loadtest.log_profile.load_log_profile_factory")
    def test_uses_factory_from_validated_config(self, load_factory):
        profile_task = Mock()
        factory = Mock(return_value=profile_task)
        load_factory.return_value = factory
        config = {"loadtest": {"log_profile": LogProfileConfig.model_validate({}).model_dump()}}

        result = create_log_profile_task(config)

        load_factory.assert_called_once_with(DEFAULT_LOG_PROFILE_CALLABLE)
        factory.assert_called_once_with(config)
        self.assertIs(result, profile_task)

    @patch("braintest_suite.loadtest.log_profile.load_log_profile_factory")
    def test_rejects_factory_that_does_not_return_callable(self, load_factory):
        load_factory.return_value = Mock(return_value=None)

        with self.assertRaisesRegex(TypeError, "must return a callable"):
            create_log_profile_task({"loadtest": {"log_profile": {"callable": "customer:create_profile"}}})


class DefaultLogProfileTest(unittest.TestCase):
    @patch.object(default_multiturn_convo_profile, "mock_multiturn_conversation")
    @patch.object(default_multiturn_convo_profile, "_build_response_pool")
    def test_response_pool_is_built_once_per_factory_initialization(self, build_response_pool, mock_conversation):
        response_pool = [{"content": "cached response", "output_size": 15}]
        build_response_pool.return_value = response_pool
        config = {
            "loadtest": {
                "log_profile": {
                    "options": {
                        "faker_pool_size": 20,
                        "max_tokens": 1000,
                    }
                }
            }
        }

        profile_task = default_multiturn_convo_profile.create_profile(config)
        profile_task()
        profile_task()

        build_response_pool.assert_called_once_with(20, 1000)
        self.assertEqual(mock_conversation.call_count, 2)
        for call in mock_conversation.call_args_list:
            self.assertIs(call.args[1], response_pool)


if __name__ == "__main__":
    unittest.main()
