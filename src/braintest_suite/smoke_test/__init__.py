from importlib import import_module

run_module = import_module("braintest_suite.smoke_test.run")
run = run_module.run

__all__ = ["run", "run_module"]
