"""The Model Platform's MCP tools, sorted by what calling one can do to the user.

Two sets, and every guard that decides which tool may run without asking reads them from here, so
there is one list to change when the platform adds a tool rather than one per test.

READ_TOOLS only look. They list the catalog and the account's own jobs and runs, estimate a price,
wait on a job, or read a result back. None of them spends a credit, stops work or sends the user's
files anywhere, so a host may run them without a prompt -- and on Codex it has to be told to: a
tool the server marks with no annotations is asked about every time, and under
`approval_policy = never` (`codex exec`, scheduled tasks) it is refused outright.

SPEND_TOOLS are the ones a person decides on. `submit_job` and `submit_pipeline_run` spend credits;
`cancel_job` and `cancel_pipeline_run` throw away GPU time already paid for; `stage_file` uploads a
file from the user's disk to the platform. Nothing may pre-approve these on the user's behalf.

`get_profile` and `get_usage` are account reads and are pre-approved alongside job reads.

A tool in neither set is the platform's newest, and the hosts default it to asking, which is the
safe direction until it is sorted into one of these.
"""

READ_TOOLS = frozenset({
    "list_models",
    "describe_model",
    "get_model_readme",
    "list_pipelines",
    "describe_pipeline",
    "estimate_job",
    "get_usage",
    "get_profile",
    "list_jobs",
    "get_job",
    "wait_for_job",
    "read_artifact",
    "read_artifact_bytes",
    "fetch_artifact",
    "list_pipeline_runs",
    "get_pipeline_run",
    "wait_for_pipeline_run",
})

SPEND_TOOLS = frozenset({
    "submit_job",
    "submit_pipeline_run",
    "cancel_job",
    "cancel_pipeline_run",
    "stage_file",
})
