import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource

_CONFIG_FILE_ENV = "BRAINTEST_CONFIG_FILE"


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
    faker_pool_size: int
    max_tokens: int
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


class LoadTestConfig(StrictBaseModel):
    headless: bool
    web_ui_port: int
    processes: int
    connection_pool_size: int
    braintrust_logger: BraintrustLoggerConfig
    params: LoadTestParams
    logs: LogsConfig


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


def _resolve_yaml() -> Path:
    """Return the config path from env, or project-root braintest.yaml."""
    env_config_file = os.getenv(_CONFIG_FILE_ENV)
    candidate = env_config_file or "braintest.yaml"

    local = Path(candidate)
    if local.exists():
        return local

    raise FileNotFoundError(candidate)


def load_config() -> dict:
    resolved = _resolve_yaml()

    class _Settings(Settings):
        model_config = SettingsConfigDict(
            yaml_file=str(resolved),
            env_nested_delimiter="__",
            extra="forbid",
        )

    return _Settings().model_dump(by_alias=True)
