# Async scorer load test

Repro for logging root spans into a project with a 100% online ExactMatch scorer. Brainstore scores the new rows. Not part of `braintest run all`.

```bash
uv run braintest run asyncscorer
```

Needs `BRAINTRUST_API_KEY`. Logs go to `braintrust.api_url`.

`peak_concurrency` is how many log flushes are in flight. `flush_batch_size` is how many new root spans each flush writes.

Setup creates the project and an online rule named `async-scorer-loadtest`. If that rule already exists with different scorers, delete it or match `asyncscorer.scorers`. An earlier version of this suite put ExactMatch and Levenshtein on that rule.
