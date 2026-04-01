# About This Load Test Suite

This repository is for exercising a self-hosted Braintrust data plane under controlled load.

It is intended to help answer practical capacity questions:

- Can the deployment handle the traffic pattern you expect in production?
- At what request rate do queues, pods, or upstream dependencies start to degrade?
- What resource changes are required to support that load at an acceptable cost?

## Load Testing Goal

The goal is not to build the most robust infrastructure possible in isolation.

The goal is to model expected real-world traffic patterns and verify that the deployed infrastructure can handle them while balancing:

- capacity
- reliability
- latency
- cost

In practice, this means tuning the test to resemble the traffic you expect to serve, then scaling components only where the observed bottlenecks require it.

## What This Suite Covers

This suite is not exhaustive.

It does not attempt to validate every part of the Braintrust data plane. Its current focus is:

- log ingestion driven by simulated user traffic via sustained load that ramps
- large spans, including attachment conversion for oversized outputs
- BTQL query load - one expensive query (span aggregation) and one simpler query to retrieve the latest logs from a page load

It does not test irregular traffic patterns such as traffic spikes or custom load profiles.

It also does not make real LLM calls. The purpose is to load the Braintrust infrastructure, not an LLM provider.

## Core Load Controls

The main load-shaping parameters live under `loadtest.params` in [`braintest.yaml`](/Users/yash/Projects/load_test_suite/braintest.yaml):

- `peak_concurrency`
  - Number of simulated write users
- `wait_time.min` and `wait_time.max`
  - Delay between requests for each simulated user
- `ramp_up`
  - User spawn rate
- `run_time`
  - Total duration of the run
- `read_traffic.*`
  - Optional read-side traffic for BTQL queries

### Calculating RPS

The most useful first-order indicator is requests per second (RPS). Normally, the RPS calculation would follow the below math:

```text
RPS = num_users / avg_cycle_time
avg_cycle_time = avg_response_time + avg_wait_time
```

Where:

- `num_users` is the number of simulated users generating the traffic you are measuring (concurrency)
- `avg_cycle_time` measures total execution time for a simulated task
- `avg_wait_time` is the average delay between requests, in seconds

However, RPS calculation in this test suite is more nuanced. That is because the Braintrust logger writes back to the data plane asynchronously from a queue. This flush interval is influenced by several parameters, including spans per trace, flush size, and response times.

Given this complexity, use the calculation above as a max RPS. Divide this by ~3-5 to get an estimate of expected RPS. Bear in mind this will be heavily influenced by response times.

RPS is a very good indicator of how the system is performing. It will be inversely correlated to response times.
- If you see response times increasing, RPS will go down. This is an indicator that the system is at load. 
- If you RPS flat lining while load is ramping up, that's a sign that the system is overloaded. 

## Span Size and Payload Shape

`max_tokens` is a control over span size.

Larger `max_tokens` values simulate larger LLM responses. When spans exceed the configured threshold in the mocked tasks, they are automatically converted into attachments instead of being logged inline.

Operational implications:

- larger `max_tokens` increases payload size and memory pressure
- very large outputs are useful when you need to test attachment-heavy behavior
- attachments are logged synchronously and separately from the Braintrust logger queue

`faker_pool_size` controls how many synthetic responses are pre-generated for reuse.

If your configured outputs are several MB in size, reduce `faker_pool_size` to lower memory consumption during the test run.

## Queueing and Flushing

The Braintrust logger behavior is mainly shaped by:

- `braintrust_logger.flush_size`
- `braintrust_logger.queue_size`

If you see an error like:

```text
Dropped 1 elements due to full queue
```

the logger is filling faster than it is being drained.

Recommended adjustments:

- reduce `flush_size`
- increase `queue_size`
- increase `processes`
- lower offered load if the queue still cannot drain fast enough

Treat this as a signal that the client-side logging pipeline is saturated relative to the current workload. Increasing processes will distribute the load over more logical CPUs on load test server. You can think of this as adding extra queues.

## Connection Pooling

`connection_pool_size` controls the HTTP connection pool used while draining logs.

If you see connection pool timeout errors:

- increase `connection_pool_size`
- confirm the downstream service can actually consume the higher parallelism

Increasing the pool size can relieve client-side contention, but it will not fix a saturated backend by itself.

## Interpreting Common Failures

### `429` responses

Usually indicates the API layer is overloaded for the current traffic pattern.

Recommended steps:

- scale API pods
- rerun with the same workload
- verify whether latency and error rate stabilize

### `500` responses

A `500` is not specific to a single bottleneck.

It can indicate problems in different parts of the data plane, including:

- API pod scaling
- Pressure on Brainstore writers
- Postgres congestion

When `500`s appear:

- inspect service logs
- inspect CPU, memory, network, and queue metrics on the data plane services
- identify which component is being degraded
- Note: seeing `503 - SlowDown` errors is likely on S3 buckets. If these SlowDowns are on the tantivy prefix, this is expected under normal operation. The system will retry.
 
## How To Conduct A Load Test

Use a repeatable process instead of jumping directly to maximum load.

1. Define the target scenario.
   - Estimate expected concurrency, request mix, payload size, and runtime.
2. Configure the workload in [`braintest.yaml`](/Users/yash/Projects/load_test_suite/braintest.yaml).
   - Set concurrency, wait time, ramp-up, logger queue settings, payload size, and dataset size.
3. Start with a realistic baseline.
   - Run a workload close to expected production levels before testing higher headroom.
4. Increase load gradually.
   - Change one major variable at a time so the bottleneck remains attributable.
5. Observe the data plane during the run.
   - Watch latency, error rate, pod health, queue depth, resource usage, and any storage or database metrics.
6. Diagnose the first bottleneck.
   - Do not assume the first visible error is the root cause.
7. Adjust the system or the workload.
   - Scale components, change pool or queue settings, or reshape the test if it no longer matches the intended scenario.
8. Repeat the same run.
   - Compare results against the previous baseline to verify that the change addressed the bottleneck.

## Observability Expectations

As the test runs, rely on your data plane observability to determine how the system is handling the offered load.

At minimum, monitor:

- API response codes and latency
- pod and node CPU and memory
- queue growth and drain behavior
- request throughput
- storage, database, or object-store latency
- component logs across the data plane

The useful output from a load test is not only whether the run "passed".

It is the combination of:

- the applied traffic profile
- the observed saturation point
- the component that limited throughput first
- the infrastructure changes required to support the target workload
