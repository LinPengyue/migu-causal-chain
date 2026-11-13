# Experiment B: Source-context Visual QA (image-only)

## Ownership and purpose

Implementation and code review: ChatGPT. Server paths, real MP4 extraction, offline pytest,
local zero-HTTP preflight and one explicitly authorized external Qwen call: Cursor.

This is a **bounded diagnostic for Experiment B**, not another FIRST_LIVE gate.
Its inputs are the source MP4, its independently checked SHA256, archived **real**
Stage3 original frame manifest + semantic log, and current story diagnosis.
Do not feed gold annotations, replay-labelled ground truth, or curated new video as
the model's inference input. Archived Stage3 evidence is DEV-only; do not use it
in a raw-only held-out benchmark.

The existing native MP4 `video_url` endpoint is **not supported** by the current
development platform. This experiment sends **only timestamped JPEG images**
via the already used `image_url` API. It does not pretend still images are a
continuous video signal.

## New implementation

- `algo/story_video_agent_v3/expb_context_visual_qa_cli.py`: independent CLI,
  default zero HTTP, Stage3 byte/PTS source re-verification, unique goal issue
  binding, source-PTS sampling around goal, evidence-citation validation, max
  one non-retrying paid image request on explicit opt-in.
- `tests/test_v3a_expb_context_visual_qa.py`: fake-provider tests (NO paid HTTP).
- Outputs `expb_context_visual_qa_report.json` and the JPEG source frames;
  on actual call, also `original_model_response.txt` with SHA256.

Possible *model-reported* status: `LIVE_SEQUENCE_SUPPORTED`,
`REPLAY_SUSPECTED`, or `INSUFFICIENT_EVIDENCE`.
A supported sequence is a **hypothesis based on image citations**, not independent
validation of visible cues or earlier same-action occurrence. Even positive
results always say `first_live_verified=false` and `edl_modified=false`.
This experiment does NOT run Story Critic, Planner, EDL, BEST, or video rendering.

## Server procedure (first offline)

On branch `story-va-v3a-p17-native-broadcast-observer`:

```bash
git pull --ff-only
cd 10.27scasual_chain
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_expb_context_visual_qa.py \
  tests/test_v3a_native_broadcast_observer.py \
  tests/test_v3a_continuous_broadcast_phase.py
```

Set these variables to the actual existing original source and archived B Stage3
evidence paths. Never copy or guess source paths from a previous run:

```bash
# Set all inputs using paths actually present on server:
# SOURCE_MP4=/.../B.mp4
# SOURCE_SHA256=<full source SHA256>
# ARCHIVED_MANIFEST=/.../original_frame_manifest.json
# ARCHIVED_LOG=/.../automated_semantic_log.json
# STORY_DIAGNOSIS=/.../story_diagnosis.json
# OUT_DIR=/.../new_unique_expB_context_preflight_dir

PYTHONPATH=algo python -m story_video_agent_v3.expb_context_visual_qa_cli \
  --source-mp4 "$SOURCE_MP4" \
  --source-sha256 "$SOURCE_SHA256" \
  --archived-frame-manifest "$ARCHIVED_MANIFEST" \
  --archived-semantic-log "$ARCHIVED_LOG" \
  --story-diagnosis "$STORY_DIAGNOSIS" \
  --out-dir "$OUT_DIR"
```

Preflight must report `READY_ZERO_HTTP_PREFLIGHT` and `n_real_http_calls=0`,
correct archived source SHA, true unique issue, source PTS and frame SHA.
Report the frame count and timestamps, total image bytes, and any error.
The preflight report is immutable (reruns require a new output directory).

## Real request is a separate explicit operation

Only after offline regressions and preflight have passed, check current
provider configuration, image payload compatibility and actual image-price
policy. The fee limiter is an **estimate and is not a guaranteed invoice cap**.

To make ONE model HTTP attempt (including failed attempt; no retries), use
a **different fresh output directory** and append:

```bash
  --execute-real --i-approve-budget --max-cost-usd 0.10
```

The CLI instantiates a standalone `ApiProvider` with `required_roles=['vision']`,
`max_calls=1`, and vision `max_retries=0`. It never invokes Critic or Planner.
A failed attempt does not automatically retry or fall back to mock. DO NOT
run this invocation until the server run is actually ready and paid execution
has been authorized. Do not increase `max-cost-usd` or switch model without
explicit authorization.

**Acceptance limit**: finite image citations with exact PTS, concrete cues, honest
UNKNOWNs; no invented SOURCE frame IDs. No status authorizes FIRST_LIVE
promotion. A stronger full-E2E experiment B result still requires independently
trustworthy earlier occurrence analysis and actual EDL repair. Do not let this
diagnostic block experiments A, C, or held-out generalization.
