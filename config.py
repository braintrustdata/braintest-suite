from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource


class BraintrustConfig(BaseModel):
    project_name: str = "load-testing-project"
    api_url: str = ""


class FunctionalTestConfig(BaseModel):
    run: bool = False
    name_prefix: str = "functional-test"


class DatasetConfig(BaseModel):
    name: str = "test-large-dataset"
    description: str = ""
    size: int = 100
    flush_batch_size: int = 25


class EvalTestConfig(BaseModel):
    run: bool = False
    project_id: str | None = None
    name: str = "test-large"
    trial_count: int = 1
    dataset: DatasetConfig = DatasetConfig()


class SmokeTestConfig(BaseModel):
    run: bool = False
    org: str | None = None
    api_url: str | None = None
    project_prefix: str = "topics-smoke"
    count: int = 105
    idle_seconds: int = 10
    topic_window: str = "1h"
    generation_cadence: str = "1h"
    relabel_overlap: str = "10m"
    allow_below_threshold: bool = False
    skip_facet_preflight: bool = False
    skip_running_check: bool = False
    timeout: int = 60
    facet_preflight_timeout: int = 30
    function_visibility_timeout: int = 60
    function_visibility_interval: int = 2
    running_check_timeout: int = 90
    running_check_interval: int = 3


class WaitTimeConfig(BaseModel):
    min: int = 5
    max: int = 10


class ReadTrafficConfig(BaseModel):
    peak_concurrency: int = 2
    btql_calls_per_min: float = 10


class LoadTestParams(BaseModel):
    faker_pool_size: int = 20
    max_tokens: int = 1000
    peak_concurrency: int = 20
    ramp_up: int = 2
    run_time: str = "1m"
    wait_time: WaitTimeConfig = WaitTimeConfig()
    read_traffic: ReadTrafficConfig = ReadTrafficConfig()


class BraintrustLoggerConfig(BaseModel):
    flush_size: int = 100
    queue_size: int = 25000


class LogsConfig(BaseModel):
    model_config = {"populate_by_name": True}

    html: bool = True
    csv: bool = False
    json_log: bool = Field(False, alias="json")


class LoadTestConfig(BaseModel):
    run: bool = False
    locustfile_path: str = "loadtest/run.py"
    headless: bool = False
    web_ui_port: int = 8089
    processes: int = 4
    connection_pool_size: int = 10
    braintrust_logger: BraintrustLoggerConfig = BraintrustLoggerConfig()
    params: LoadTestParams = LoadTestParams()
    logs: LogsConfig = LogsConfig()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file="braintest.yaml",
        env_nested_delimiter="__",
    )

    braintrust: BraintrustConfig = BraintrustConfig()
    functionaltest: FunctionalTestConfig = FunctionalTestConfig()
    evaltest: EvalTestConfig = EvalTestConfig()
    smoketest: SmokeTestConfig = SmokeTestConfig()
    loadtest: LoadTestConfig = LoadTestConfig()

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        return (
            kwargs["env_settings"],
            YamlConfigSettingsSource(settings_cls),
            kwargs["init_settings"],
        )


def load_config() -> dict:
    return Settings().model_dump(by_alias=True)
