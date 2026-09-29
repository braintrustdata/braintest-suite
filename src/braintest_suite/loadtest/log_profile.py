import importlib
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

LogProfileTask = Callable[[], Any]
LogProfileFactory = Callable[[dict], LogProfileTask]


def _load_module(module_reference: str) -> ModuleType:
    is_file_reference = module_reference.endswith(".py") or any(
        separator in module_reference for separator in ("/", "\\")
    )
    if not is_file_reference:
        return importlib.import_module(module_reference)

    module_path = Path(module_reference).expanduser()
    if not module_path.is_file():
        raise ValueError(f"Log profile module does not exist: {module_path}")

    module_name = f"_braintest_log_profile_{abs(hash(module_path))}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Could not load log profile module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def load_log_profile_factory(
    callable_reference: str,
) -> LogProfileFactory:
    module_reference, _, attribute_name = callable_reference.rpartition(":")
    module = _load_module(module_reference)
    try:
        factory = getattr(module, attribute_name)
    except AttributeError as exc:
        raise ValueError(f"Log profile factory {attribute_name!r} was not found in {module_reference!r}") from exc

    if not callable(factory):
        raise TypeError(f"Log profile factory {callable_reference!r} is not callable")
    return factory


def create_log_profile_task(config: dict) -> LogProfileTask:
    callable_reference = config["loadtest"]["log_profile"]["callable"]
    factory = load_log_profile_factory(callable_reference)
    profile_task = factory(config)
    if not callable(profile_task):
        raise TypeError(f"Log profile factory {callable_reference!r} must return a callable")
    return profile_task
