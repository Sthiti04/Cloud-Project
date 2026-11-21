# 4. Prepare the Mac and try the project locally

[Start here](01-start-here.md) | Next: [AWS deployment](05-aws-deployment.md)

**This page does not use your AWS account or create an AWS bill.** Docker runs
a practice version on your Mac. Moto imitates AWS storage/queues; the local
dispatcher is not real Lambda, and local Flink is not EMR.

Do steps 1-7 in order. If a step already passed on this Mac, keep it rather than
reinstalling everything. Copy one command box at a time, wait, and check the
result. Extra developer checks are folded away at the end.

## 1. Install the tools once

Use macOS Terminal or VS Code -> **Terminal: Select Default Profile -> zsh**.
No Git Bash, PowerShell, host Java/Maven or local Kubernetes cluster is needed.
Do not separately install Kafka, ZooKeeper, PostgreSQL or Flink.

```zsh
zsh --version
uname -m
```

`arm64` means Apple Silicon; `x86_64` means Intel (or a Rosetta terminal).
On Apple Silicon use a native terminal, not "Open using Rosetta".

If Homebrew is missing, install it using [its official instructions](https://brew.sh/)
and follow the `brew shellenv` instructions it prints. Then:

```zsh
brew install git python@3.12 helm@3
brew install --cask docker
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
export PATH="$(brew --prefix helm@3)/bin:$PATH"
open -a Docker
```

| Tool | Why it is needed |
|---|---|
| Git | Download/publish project files |
| Python 3.12 | Run tests and helper commands |
| Docker Desktop | Run the practice system and package code for AWS |
| Terraform | Create/delete AWS resources later |
| Helm 3 | Work with the project's Kubernetes templates |

Finish Docker's first-run setup and wait until its engine is running.
Use Helm **3**, not the unversioned formula (which may install Helm 4).
The PATH line above selects the installed Helm 3.

```zsh
git --version
python3.12 --version
docker version
docker compose version
docker buildx version
helm version --short
terraform version
```

**Continue when:** Python is 3.12, Docker shows a working **Server**, Compose is
v2, Buildx is available, Helm is v3 and Terraform is >=1.8,<2.
Keep the repository's Terraform lockfiles; don't upgrade providers to hide errors.
AWS CLI and kubectl are installed later in the AWS guide.

**If the Mac struggles:** plan for roughly 16 GB RAM, 8 GB available to Docker
and 20 GB free disk (estimates, not measured minimums). On an 8 GB Mac, the full
stack may be too heavy. Use a reviewed
[manual full CI rehearsal](../README.md#lightweight-github-actions) instead of
steps 5-6 if needed. Still do the build/export in step 4 for AWS.
Default fast CI and a partial local stack are not full rehearsal evidence.

## 2. Open the existing project folder

If you already have `CC-Project`, open it in VS Code and open a terminal there.
**Do not clone another copy inside it.** Keep it in a local folder such as
`~/Developer`, not iCloud/Dropbox/OneDrive: later Terraform files contain secrets.

Only if you do not have the project yet:

```zsh
mkdir -p "$HOME/Developer"
cd "$HOME/Developer"
git clone git@github.com:Sthiti04/CC-Project.git
cd CC-Project
```

This uses your GitHub SSH access, not AWS credentials. If cloning is denied,
resolve your private-repository access first; don't make the repository public.
The project is already published, not an empty repository.

Create the Python environment once, **in this folder**:

```zsh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

If `.venv` already works on this Mac, just activate it. Do not copy a Windows
environment to the Mac.
**Continue when:** installation finishes without error and `python --version`
shows 3.12.

### In every new workstation terminal

Adjust the first line if your project is stored elsewhere:

```zsh
cd "$HOME/Developer/CC-Project"
setopt INTERACTIVE_COMMENTS
set -o pipefail
export PATH="$(brew --prefix helm@3)/bin:$PATH"
source .venv/bin/activate
```

This selects the folder/tools and makes pasted comments/pipes behave correctly.
If `cd` fails, stop and correct the folder before running anything else.
Keep the guide's quotes and backslashes. Never paste the whole guide at once.
For AWS work, also follow [the AWS sign-in block](05-aws-deployment.md#in-every-aws-terminal).

## 3. Check the Python code

```zsh
python -m pytest -m "not repository" --cov --cov-report=term-missing
```

**Continue when:** tests pass and coverage is at least 80%. These tests use fake
services, not AWS. A deprecation warning is not a failed test; a traceback or
failed assertion is. Don't suppress a failure to move on.

## 4. Build the Flink program once

Docker also builds the Java part; you do not need to understand Maven to do this.

```zsh
unset DOCKER_DEFAULT_PLATFORM
docker build -f analytics/Dockerfile -t s23-analytics:build .
```

After the build succeeds:

```zsh
python -m tools.export_analytics --image s23-analytics:build
ls -lh analytics/target/clinical-analytics.jar \
  analytics/target/runtime/flink-s3-fs-hadoop.jar \
  analytics/target/runtime/flink-metrics-prometheus.jar
```

**Continue when:** all three files exist. They are the packaged Flink program
and its storage/metrics plugins, needed later by EMR. Tests run during the build.
Do not also install host Java/Maven or use `java -jar` to run it.
Local builds use your Mac's native architecture; the AWS guide separately
specifies `linux/amd64` for cloud container images.

## 5. Start the practice system

First time only:

```zsh
python -m tools.setup_local
```

This creates a private ignored `.env`. If it says the file already exists,
reuse it; do not overwrite its passwords. Do not paste its contents into chats.

```zsh
docker compose config --quiet
docker compose up --build -d
docker compose ps -a
```

Downloads/startup take several minutes. Run the last command again to check.

| What you see | What it means |
|---|---|
| `bootstrap` and `flink-submit`: `Exited (0)` | Correct: these two setup tasks finished successfully |
| Application services/databases: `healthy` | Their health checks passed |
| Both Queue Managers running | Two copies are ready to coordinate |
| Dispatcher and Flink containers running | Expected, but verify the actual Flink job below |
| Exit code other than 0, `unhealthy`, repeated restarts | Stop and inspect the error |

```zsh
curl --fail http://127.0.0.1:8080/health/ready
curl --fail http://127.0.0.1:8081/jobs/overview
```

**Continue when:** API readiness succeeds and Flink's result contains a
`RUNNING` job. If not, inspect:

```zsh
docker compose logs --tail=100 bootstrap flink-submit
docker compose logs --tail=100 vital-ingestion device-registry
```

Use [troubleshooting](07-troubleshooting.md) for errors. A running container
alone isn't enough; setup must have succeeded too.

## 6. Run the practice demonstration

```zsh
python -m tools.demo smoke --timeout 360
```

Wait for it to finish. Local escalation takes about a minute; Flink results also
need time. The helper generates readings and performs acknowledgements for you.

**Continue when:** output has `verified: true`, `generated: 12`, `alert_count: 4`,
four inbox notifications, acknowledgement/escalation and analytics windows.
It saves `evidence/smoke-local.json` on success.
If it fails, an older report is not proof of this attempt.

```zsh
python -m tools.demo status
```

Read the example alerts, messages and summaries. They are machine-generated,
not real patient records. Do not repeat smokes rapidly in the same minute or
mix them with load tests.

Optional viewing while it runs:

| Local browser address | What it shows |
|---|---|
| `http://127.0.0.1:8080/docs` | API operations, not a patient app |
| `http://127.0.0.1:8081` | Flink job |
| `http://127.0.0.1:3000` | Grafana (`admin`; password privately in `.env`) |
| `http://127.0.0.1:9090` | Prometheus metrics |

Some Kubernetes/Lambda dashboard panels are empty locally because those AWS
services aren't running. This practice does not satisfy the cloud-log requirement.

## 7. Stop local containers, then move to AWS

From this project folder:

```zsh
docker compose down
```

This stops only this Compose project and preserves its named volumes. It stops
**no AWS resources**. For an intentional complete reset of this project's
synthetic local data only:

```zsh
docker compose down --volumes
```

Some local data is ephemeral, so a stopped/recreated system is not a durable
cloud deployment. If resetting, reset coherently rather than mixing old database
state with a fresh ZooKeeper sequence. Keep `.env` unless deliberately changing it.
Never use system-wide prune to clean up this project.

**Next:** [deploy to your paid account](05-aws-deployment.md).
After a cleanup, follow the AWS guide's new-attempt checklist rather than
reusing old cloud addresses or certificates. Local setup already completed on
this Mac does not need reinstalling.

## Extra checks for code or infrastructure changes

These are a maintainer reference, not another checklist to complete before every
demo. Full CI runs these checks; the quick CI run covers the fast code checks.

<details>
<summary>Open only when changing/debugging the implementation</summary>

```zsh
python -m ruff check s23 tools tests
python -m ruff format --check s23 tools tests
python -m mypy
python -m bandit -q -r s23 tools -ll
python -m pip check
docker pull prom/prometheus:v3.7.3
helm lint deploy/app deploy/platform -f tests/helm-values.yaml
python -m pytest -m repository -q
terraform -chdir=infra/aws init -backend=false
terraform -chdir=infra/aws validate
terraform -chdir=infra/aws test
terraform -chdir=infra/gitops init -backend=false
terraform -chdir=infra/gitops validate
```

Build the three JARs first; Terraform's tests use mocked providers, not AWS.
Repository tests use Helm and the real Prometheus expression checker in Docker.
An installed Prometheus 3.7.3 `promtool` can be selected through `PROMTOOL` instead.
Full CI also tests Windows-CRLF bootstrap input and verifies LF-only Linux output.
Rendering charts is a check, not permission to deploy services with `kubectl apply`.

</details>
