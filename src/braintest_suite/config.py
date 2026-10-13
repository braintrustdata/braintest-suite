import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource

CONFIG_FILE_ENV = "BRAINTEST_CONFIG_FILE"
DEFAULT_CONFIG_FILE = "braintest.yaml"
DEFAULT_LOG_PROFILE_CALLABLE = "braintest_suite.loadtest.log_profiles.default_multiturn_convo_profile:create_profile"
PDF_PROCESSING_LOG_PROFILE_CALLABLE = "braintest_suite.loadtest.log_profiles.pdf_processing_profile:create_profile"
DEFAULT_LOG_PROFILE_OPTIONS = {
    "faker_pool_size": 20,
    "max_tokens": 1000,
}


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BraintrustConfig(StrictBaseModel):
    project_name: str
    api_url: str


class FunctionalTestConfig(StrictBaseModel):
    name_prefix: str


class DatasetConfig(StrictBaseModel):
    name: str
    description: str
    size: int
    flush_batch_size: int


class EvalTestConfig(StrictBaseModel):
    project_id: str | None
    name: str
    trial_count: int
    dataset: DatasetConfig


class WaitTimeConfig(StrictBaseModel):
    min: int
    max: int


class ReadTrafficConfig(StrictBaseModel):
    peak_concurrency: int
    btql_calls_per_min: float


class LoadTestParams(StrictBaseModel):
    peak_concurrency: int
    ramp_up: int
    run_time: str
    wait_time: WaitTimeConfig
    read_traffic: ReadTrafficConfig


class BraintrustLoggerConfig(StrictBaseModel):
    flush_size: int
    queue_size: int


class LogsConfig(StrictBaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    html: bool
    csv: bool
    json_log: bool = Field(alias="json")


class BundledLogProfileOptions(StrictBaseModel):
    faker_pool_size: int = Field(gt=0)
    max_tokens: int = Field(gt=0)


class LogProfileConfig(StrictBaseModel):
    callable: str = DEFAULT_LOG_PROFILE_CALLABLE
    options: dict[str, Any] = Field(default_factory=lambda: DEFAULT_LOG_PROFILE_OPTIONS.copy())

    @field_validator("callable")
    @classmethod
    def validate_callable_reference(cls, value: str) -> str:
        module_reference, separator, attribute_name = value.rpartition(":")
        if not separator or not module_reference or not attribute_name:
            raise ValueError("must use '<module-or-file>:<factory>' syntax")
        return value

    @model_validator(mode="after")
    def validate_bundled_profile_options(self):
        if self.callable in {
            DEFAULT_LOG_PROFILE_CALLABLE,
            PDF_PROCESSING_LOG_PROFILE_CALLABLE,
        }:
            self.options = BundledLogProfileOptions.model_validate(self.options).model_dump()
        return self


class LoadTestConfig(StrictBaseModel):
    headless: bool
    web_ui_port: int
    processes: int
    connection_pool_size: int
    braintrust_logger: BraintrustLoggerConfig
    params: LoadTestParams
    logs: LogsConfig
    log_profile: LogProfileConfig = Field(default_factory=LogProfileConfig)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        extra="forbid",
    )

    braintrust: BraintrustConfig
    functionaltest: FunctionalTestConfig
    evaltest: EvalTestConfig
    loadtest: LoadTestConfig

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        return (
            kwargs["env_settings"],
            YamlConfigSettingsSource(settings_cls),
            kwargs["init_settings"],
        )


def resolve_config_path() -> Path:
    """Return the config path from env, or project-root braintest.yaml."""
    env_config_file = os.getenv(CONFIG_FILE_ENV)
    candidate = env_config_file or DEFAULT_CONFIG_FILE

    local = Path(candidate)
    if local.exists():
        return local.resolve()

    raise FileNotFoundError(candidate)


def _resolve_log_profile_reference(
    callable_reference: str,
    *,
    config_directory: Path,
) -> str:
    module_reference, _, attribute_name = callable_reference.rpartition(":")
    is_file_reference = module_reference.endswith(".py") or any(
        separator in module_reference for separator in ("/", "\\")
    )
    if not is_file_reference:
        return callable_reference

    module_path = Path(module_reference).expanduser()
    if not module_path.is_absolute():
        module_path = config_directory / module_path
    return f"{module_path.resolve()}:{attribute_name}"


def load_config() -> dict:
    resolved = resolve_config_path()

    class _Settings(Settings):
        model_config = SettingsConfigDict(
            yaml_file=str(resolved),
            env_nested_delimiter="__",
            extra="forbid",
        )

    config = _Settings().model_dump(by_alias=True)
    profile_config = config["loadtest"]["log_profile"]
    profile_config["callable"] = _resolve_log_profile_reference(
        profile_config["callable"],
        config_directory=resolved.parent,
    )
    return config
