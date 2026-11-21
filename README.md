# S23: Synthetic Healthcare Monitoring

A beginner-oriented, AI-assisted implementation of scenario **S23** from the
BITS Pilani Cloud Computing assignment: eight services, Apache ZooKeeper
coordination, and an AWS deployment. Demo device/patient records and readings
are machine-generated; notifications are application-generated. No real people
or clinical data are used. This is not a medical system.

**New to the project? Read [What have we built?](docs/00-project-explained.md)
for the plain-English explanation and file map. Then follow
[the start-here guide](docs/01-start-here.md); do not start by running Terraform apply.**

## Important before starting

- **No AWS resources have been deployed by this delivery.**
- Use **your own pay-as-you-go AWS account**, in **ap-south-1 (Mumbai)**.
  EMR was blocked on the Free-plan account; this walkthrough now uses the paid
  account. After cleaning up an attempt, use the
  [redeployment checklist](docs/05-aws-deployment.md#0-prepare-a-new-attempt-after-cleanup).
  Budget for full usage charges; decide a spending limit and cleanup time before
  changing the default `allow_paid_resources = false`.
- Clean up **every** paid attempt when finished or abandoned, even if deployment
  failed. Closing the laptop or disabling only EMR does not stop all charges.
- Sthiti is currently the only identified contributor. The handout also describes
  equal task/service division. **Get instructor approval for the solo arrangement
  before treating it as a compliant submission.**
- Confirm the Nalanda deadline, group/topic allocation, AI-use policy and whether
  applying Apache ZooKeeper for coordination is the intended concept.
- Source, tests, infrastructure and guides are supplied. Passing offline checks
  is **not** evidence that AWS deployment, HPA scaling or the live demo succeeded.
  See [validation status](docs/10-validation-status.md).

## Guide order

**For following along, use just this route:**
[4. Prepare the Mac](docs/04-local-walkthrough.md) ->
[5. Deploy](docs/05-aws-deployment.md) ->
[6. Demonstrate](docs/06-demonstration-and-observability.md) ->
[8. Clean up](docs/08-cleanup-and-cost.md).
Each walkthrough has commands, expected results and stop points. Keep the
cost/cleanup page handy before creating anything. Use the design/component
guides as references; you do not need to study every file before starting.

| Step | Guide | Outcome |
|---|---|---|
| 0 | [What have we built?](docs/00-project-explained.md) | Plain-English walkthrough: services, files and what to edit |
| 1 | [Start here](docs/01-start-here.md) | Goal, stop points and work order |
| 2 | [Requirements and evidence](docs/02-requirements-and-evidence.md) | Exactly what proves tasks a-h |
| 3 | [Design document](docs/03-design.md) | Submission architecture and rationale |
| 4 | [Local walkthrough](docs/04-local-walkthrough.md) | Tools, tests and local rehearsal |
| 5 | [AWS deployment](docs/05-aws-deployment.md) | Preflight, images, phased Terraform and private GitOps |
| 6 | [Demo and observability](docs/06-demonstration-and-observability.md) | All eight services, scaling and ZooKeeper |
| 7 | [Troubleshooting](docs/07-troubleshooting.md) | Diagnose failures without unsafe shortcuts |
| 8 | [Cleanup and cost](docs/08-cleanup-and-cost.md) | Remove the complete project safely |
| 9 | [Viva and AI help](docs/09-viva-and-ai-help.md) | Explain the system and use AI carefully |
| 10 | [Validation status](docs/10-validation-status.md) | Delivered checks versus remaining live proof |
| Reference | [Components and viva](docs/11-components-and-viva.md) | Component explanations, terminology, presentation outline and practice questions |

## The eight application services

| # | Spreadsheet service | Implementation |
|---|---|---|
| 1 | Patient Simulator | Python/EKS; reproducible synthetic readings |
| 2 | Device Registry | Python/EKS; PostgreSQL metadata; REST and protobuf gRPC |
| 3 | Vital Ingestion Service | Python/EKS; public authenticated API; S3 and Kafka |
| 4 | Alert Rule Engine | Python/EKS; Kafka consumer; demonstration thresholds |
| 5 | Alert Queue Manager | Python/EKS; two replicas; ZooKeeper election and DynamoDB state |
| 6 | Notification Dispatcher | SQS-triggered Lambda; durable demo-operator inbox and retries |
| 7 | Acknowledgement Service | Python/EKS; acknowledgement/escalation; persists analytics |
| 8 | Clinical Analytics Service | Java Flink on EMR; stateful minute windows; Kafka results |

Only six application services run on EKS. Lambda and EMR supply the other two.
ZooKeeper, Kafka, initialization jobs, monitoring and the load test are
infrastructure/helpers, **not invented extra services**.

Python is used where practical. The small Java project supplies the managed
Flink/Kafka integration; no PyFlink workaround is substituted.

## Repository map

- [s23/](s23): shared Python domain code and independently deployed service roles.
- [analytics/](analytics): Flink source, tests, Maven build and runtime plugins.
- [proto/devices.proto](proto/devices.proto): protobuf gRPC contract.
- [infra/aws/](infra/aws): all AWS infrastructure and spending opt-in.
- [infra/gitops/](infra/gitops): Terraform-only Argo CD/credential bootstrap.
- [deploy/app/](deploy/app): application, ZooKeeper, HPAs, dashboard and load Job.
- [deploy/platform/](deploy/platform): Git-tracked monitoring/logging applications.
- [compose.yaml](compose.yaml): local rehearsal with mocked AWS, not cloud compliance.
- [tools/](tools): secret setup, configuration, demo, JAR export and HPA evidence.
- [tests/](tests): isolated unit tests and offline manifest/documentation contracts.
- [task_divison.txt](task_divison.txt): truthful contribution/assignment record.
- [.github/workflows/validate.yml](.github/workflows/validate.yml): validation only;
  **no automatic AWS deployment**.

The required text filename deliberately preserves the handout's spelling:
`task_divison.txt`, not `task_division.txt`.

## Lightweight GitHub Actions

Pushes and pull requests run only the fast Python and Java jobs in parallel:
lint/type/security checks, unit tests with the existing coverage gates, the Flink
build, and quick Helm-rendered chart/documentation/workflow checks. These cover
startup ordering, fresh-cluster monitoring and the Fluent Bit launch command.
They do **not** start Docker or download Terraform/Prometheus.
Build/report uploads are full-run only.

For the optional complete rehearsal, open **Actions -> Validate S23 without AWS
deployment -> Run workflow**, select the branch, check **Run full validation
(infrastructure and Docker rehearsal)**, and run it. Leave it unchecked for the
basic checks. Full validation adds infrastructure/manifests/zsh checks and both
Docker smokes; run it before deployment or after infrastructure/integration changes.
Skipped full-only jobs on a normal run are intentional, not integration evidence.

The full run waits for the two one-shot startup containers by their actual
container IDs and checks their exit codes, including when they have already completed.
Readiness alone is not a passed integration test: both functional/retry smokes
must also pass. See [the recorded CI status](docs/10-validation-status.md).
The low-rate demo client uses fresh HTTP connections between polls; it does not
automatically retry mutations. The sustained k6 load is unchanged.
The [verified Linux CI run](https://github.com/Sthiti04/CC-Project/actions/runs/44762138875)
passed both normal and retry smokes. Mac rehearsal and AWS proof remain separate.

## Safe first commands

The guides target **macOS Terminal/VS Code with zsh**, on Apple Silicon or Intel.
Follow [Mac setup](docs/04-local-walkthrough.md) first. Docker builds Flink, so
host Java/Maven, a local Kubernetes cluster and a host Kafka installation are
not needed for the recommended path.

From the repository root, after installing Python 3.12:

```zsh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -m "not repository" --cov --cov-report=term-missing
```

These tests use fakes/Moto and do not provision AWS. Do not paste credentials,
Terraform state, private keys or unredacted configuration into chats or Git.
Local Docker builds use the Mac's native architecture. The AWS guide separately
builds `linux/amd64` images for the x86_64 EKS workers and Lambda.

If Argo is stuck and HPAs say **`Deployment not found`**, use
[the existing-stack recovery steps](docs/07-troubleshooting.md#argo-stuck-hpas-say-deployment-not-found).
Startup ordering is initialization -> application Deployments -> HPAs -> optional
load Job. This manifest fix does not require recreating Terraform infrastructure
or rebuilding images.

## Scope and safety

- Delivery means a durable **in-application demo notification**, visible through
  `/notifications`, not a real SMS/email or clinical intervention.
- **S3, RDS PostgreSQL and DynamoDB** supply three distinct storage products.
- HPAs target **Vital Ingestion and Device Registry**, both exercised by every
  load request. Actual scale-out must be recorded.
- Kubernetes deployments/updates go through Argo CD tracking Git. No direct
  service `kubectl apply`, `kubectl scale` or `helm upgrade`.
- The ALB's HTTPS certificate is self-signed. The supplied client pins it; no
  domain purchase is needed. Confirm any browser-trusted HTTPS requirement.
- Local notifications are a Python process and local Flink runs in Docker:
  neither substitutes for Lambda, EKS and EMR evidence.