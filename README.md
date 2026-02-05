# Braintest Suite
Test suite for doing load testing on self-hosted data planes.

[WIP] Supports 2 functions:
- Load test with mock traces (no actual LLM calls are made). Params can be configured for number of simulated users, duration of traffic, ramp shape, and more.
- Large dataset eval execution. Creates a mock dataset of a specified size and executes an eval. (WIP)

