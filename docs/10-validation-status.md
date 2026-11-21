# 10. Validation status and remaining live checks

[Viva/AI help](09-viva-and-ai-help.md) | [Guide index](../README.md)

## What this delivery is

Runnable source/build/configuration and a sequential guide set for S23. It is
**not an already-deployed AWS assignment**. Source/IaC checks cannot prove a live
public URL, managed Flink, load-driven scaling or cloud-log collection.

No AWS resources were provisioned. The kit was initially prepared locally and
later published to the private repository. The original assignment PDF,
workbook and previous lab document were not copied into this repository.
No real patient data or fabricated demo evidence is supplied.

## Current student walkthrough

The Mac, deployment and demonstration guides now use smaller follow-along
checkpoints with expected results, terminal labels and evidence to save.
They use the student's own **pay-as-you-go account**. EMR was reported
unavailable on the Free-plan account. The later paid-account attempt was
reported cleaned up after the startup failure below. The next run is a fresh
deployment, not recovery of that deleted cluster. Resource/billing cleanup,
permissions, quotas and the new deployment still require real verification.
Documentation changes are not new AWS execution evidence.

For this walkthrough revision, the original PDF and S23 worksheet entry were
rechecked. Five targeted documentation/portability tests passed; 82 shell blocks
parsed with zsh 5.9 under Linux/WSL, 21 inline Python snippets parsed, and 11
heading links resolved. The image build/upload/address sequence also ran with
fake Terraform/AWS/Docker commands. None of these checks used a real AWS account
or ran the deployment on a Mac.

## Reported AWS startup issue: 2026-11-20

The supplied student diagnostics show three ready ZooKeeper pods and completed
schema/topic Jobs, but no application Deployments. Both HPAs report
`FailedGetScale` because their Deployment targets are missing; Argo is retrying
and reports `Degraded`/`OutOfSync`. This is evidence of a partial deployment, not
proof that all eight cloud services ran.

The chart incorrectly placed HPAs in default wave 0 ahead of their wave-1
Deployments. The fix orders Deployments before HPAs and the optional load Job
after both, preserving the existing CPU targets and replica limits. New rendered
chart regressions reproduce the incorrect ordering before the fix.
After the fix, all 23 repository tests pass; both charts lint with the test
fixture and the published AWS values. The updated documentation's 32 shell
blocks parse in zsh and its 10 heading links resolve. These are offline checks,
not proof that Argo has recovered in AWS.
See [existing-stack recovery](07-troubleshooting.md#argo-stuck-hpas-say-deployment-not-found).
Live recovery must still be verified in the student's cluster; no AWS resources
were modified while investigating these logs.

### Follow-up: prepare to redeploy after cleanup

The student reported destroying the previous resources. The guides now reset
runtime/deletion flags, regenerate AWS values/images/certificates and require
cleanup even for failed attempts. The previous in-place recovery instructions
are only for a stack that still exists.

The supplied Fluent Bit snapshot matches the published launch-command fix, which
is retained. CloudWatch's ServiceMonitor is now rendered even before its CRD
exists, with a later sync wave and `SkipDryRunOnMissingResource=true`. This
avoids silently leaving it out of a fresh-cluster sync. Automatic CI now includes
fast chart regressions; the Docker rehearsal and Terraform checks remain opt-in.

Checks repeated before publishing this revision:

- **123 Python/repository tests passed**, including 27 repository contracts.
  Python branch-inclusive coverage is **94.55%**, with every source file >=80%.
- Ruff, mypy, Bandit and dependency consistency passed.
- **Seven Java tests**, Flink build and per-source coverage gate passed; the
  three deployment JARs were rebuilt.
- Both Terraform roots passed formatting/validation; **three fully mocked
  Terraform tests** passed, including the Lambda/EMR runtime configuration.
- Both Helm charts linted with fixtures and the previous deployment's values;
  those previous values still need regeneration for a new deployment.
- Actionlint passed. **85** documented shell blocks parsed in zsh, **21**
  inline Python snippets parsed and **22** heading links resolved.

These checks do not provision AWS or prove the managed runtimes will start in
the paid account. In particular, chart rendering tests ordering/configuration,
not a real EKS/Argo reconciliation. Account quotas, service permissions, image
pulls, CloudWatch collection and actual scaling must still pass the live gates.

## Current CI policy

Pushes and pull requests run only the fast Python and Java jobs. Unit tests,
coverage gates, lint/type/security checks, the Flink build and lightweight
Helm chart/documentation/workflow checks remain automatic. Terraform/PromQL validation and
the Docker rehearsal are **manual opt-in**, not required on every edit.

Use **Run full validation** in the Actions manual-run form for the complete
checks and downloadable artifacts; see [instructions](../README.md#lightweight-github-actions).
A green default run does not prove integration. Full-only jobs are intentionally
skipped unless selected. No mode deploys AWS.

## Latest successful full CI result

[Run 44762138875](https://github.com/Sthiti04/CC-Project/actions/runs/44762138875)
passed **all four jobs** against startup-fix commit `9eed62a` on 2026-11-20.
This was one manually requested full rehearsal; routine pushes remain lightweight.

- Python unit/coverage/lint checks and the fast chart/documentation checks passed;
  the Python job finished in **45 seconds**.
- Java tests/build, Terraform validation/mocked tests and all repository contracts
  passed.
- The integrated Docker stack became ready, Flink reached RUNNING and both
  normal and transient-retry smokes passed.
- Downloaded reports were independently checked: each has `verified: true`,
  12 readings, four alerts, four inbox messages, three device windows, and
  ACKNOWLEDGED/ESCALATED states.
- CI removed its own Compose stack and volumes afterwards.

This verifies real Kafka/ZooKeeper/Flink integration on Linux with **mocked AWS**,
not a new EKS/EMR deployment. No paid AWS resources were created. Follow the
redeployment readiness gates and clean up the paid attempt even if it fails.
The following documentation-only evidence commit does not change tested code.

## Earlier successful full CI result

[Run 42270472096](https://github.com/Sthiti04/CC-Project/actions/runs/42270472096)
**passed all four jobs** against code commit `ed1086e`:

- **96 isolated Python tests**, coverage gates, lint, types and dependency checks.
- **7 Java tests**, verified Flink build and runtime artifacts.
- Terraform/Helm/zsh validation and **20 repository contracts**.
- Both complete **normal and transient-retry Docker smokes**.

The downloaded smoke reports were checked: each records `verified: true`,
12 generated readings, four alerts, four durable notifications, acknowledgement,
escalation and real Flink window results. This proves the integrated Linux
rehearsal with real Kafka/ZooKeeper/Flink and mocked AWS products.

It does **not** prove Mac Docker operation, AWS deployment, real Lambda/EMR,
cloud HPA scaling or cloud logging. The failed attempts below are historical.
This result-recording documentation update does not change the tested code.

## Validation levels

| Level | What it proves | What it cannot prove |
|---|---|---|
| Python isolated tests | Domain/lifecycle/adapter/API/helper behavior with fakes/Moto | Real IAM/networking/managed runtime |
| Java Maven tests/build | Schema, state/window helpers, topology/build and runtime artifacts | Kafka/Flink on a real cluster |
| Helm contracts | Rendered eight-service mapping, two HPAs, GitOps ordering, PVCs, config | Scheduling/actual scale-out |
| Mocked Terraform tests | Foundation/runtime shape and spending guard | Regional availability/account quotas |
| Local Docker smoke | Integrated real Kafka/ZooKeeper/Flink + mock AWS | EKS/Lambda/EMR/cloud observability |
| AWS live proof | Actual rubric behavior/evidence | Production medical suitability or unlimited reliability |

## Verified delivery-time checks

These checks actually ran on the delivery Windows workstation. They are not
student-performed cloud proof. Host Python was **3.11.9** (supported by the
project); Docker/CI target Python 3.12. Host Java was 17.

| Check | Actual result |
|---|---|
| Isolated Python tests | **95 passed**; repository tests deliberately excluded in this run |
| Python coverage | **94.55% branch-inclusive overall**; every one of the 24 source files >=80% |
| Ruff | All lint checks passed; 37 files meet formatting |
| mypy | All 24 source files passed |
| Bandit | Medium/high-severity local scan passed |
| Dependency consistency | `pip check` passed; not a claim of a full dependency vulnerability audit |
| Java/Flink Maven verify | **7 tests passed**, build and source-file coverage gate passed |
| AWS/GitOps Terraform | Both validate and formatting checks pass |
| Mocked AWS Terraform tests | **3 passed**, including spending rejection, foundation plan and fully mocked runtime apply |
| Helm charts | Both lint successfully |
| Repository contracts | **15 passed** after the Mac review: manifests, guides/links, Compose, CI, three real PromQL cases and three Mac/portable-decoding regressions |
| Prometheus expression | Healthy, failing and idle request series evaluated with Prometheus 3.7.3 promtool |
| CI definition | actionlint passed; all 15 Bash run blocks syntax-checked without executing them |
| EMR bootstrap | Bash syntax passed |
| Windows-to-Linux shell payloads | Compiled bootstrap/Flink commands checked LF-only through mocked Terraform outputs |

Java main-source line coverage: Options.java 92.00%, ClinicalAnalytics.java
98.31%, Event.java 100.00%, Stats.java 97.22%. The three required runtime JARs
were produced by the verified Maven build.

The Python suite reports an HTTPX/Starlette deprecation warning, not a failed
test. No dependency change was made merely to hide that warning.

See [local walkthrough](04-local-walkthrough.md) for reproducible commands.
The optional full CI run includes these checks and an isolated Docker integration
job on a supported runner. Its actual first-run result is recorded below;
defining the workflow or passing its earlier jobs does not establish a successful full run.

## First GitHub Actions run: startup succeeded, integration gate failed

[Run 42265294790](https://github.com/Sthiti04/CC-Project/actions/runs/42265294790)
ran against commit `6a98dc5` on 2026-11-06:

- Python, Java and infrastructure jobs **passed** on the Linux runner.
- The integration stack built and started. Preserved Compose diagnostics show
  `bootstrap` and `flink-submit` both **Exited (0)**; service health checks passed,
  and the Flink logs show the analytics job reaching **RUNNING**.
- The readiness loop then finished, but `docker compose wait bootstrap
  flink-submit` failed with `no containers for project "s23-demo"`, because the
  named one-shot containers had already stopped.
- The corrected workflow looks up each container with `docker compose ps -a -q`,
  waits by ID using `docker wait`, and explicitly checks the returned container
  exit code. It still fails on missing containers, failed startup jobs or Docker
  errors; it does not skip validation to obtain a green result.

**The normal and retry smoke steps were not reached.** A new run of the corrected
workflow must pass both before claiming complete local integration success.
Rerunning the old commit alone does not include the fix. This CI startup is also
not an AWS deployment or a Mac Docker rehearsal.

### Follow-up run: basic smoke connection failure

[Run 42267341638](https://github.com/Sthiti04/CC-Project/actions/runs/42267341638)
against `915f1fc` passed the corrected one-shot gate, then started the basic
functional smoke. Simulation, four alert lookups, acknowledgement and inbox
retrieval worked. The next polling heartbeat failed with
`Remote end closed connection without response`; preserved diagnostics showed
the ingestion service still running and healthy.

The smoke sleeps five seconds between polls, matching Uvicorn's default
five-second idle keep-alive timeout. The failure is consistent with reuse of an
idle connection as the server closes it. The low-rate demo client now requests
`Connection: close` so each call uses a fresh connection. API authentication,
pinned HTTPS, error propagation and all functional assertions are unchanged.
There is no blanket retry of POST requests or success-shaped fallback, and k6
load behavior is unchanged. A new full CI run must validate this transport fix;
neither failed run establishes successful normal/retry smoke execution.

## macOS/zsh compatibility review

The student workflow now targets macOS zsh on Apple Silicon or Intel. The
recommended Flink build uses Docker, avoiding a separate host Java/Maven setup.
Versioned Homebrew Helm 3, native local builds, explicit x86_64 AWS builds,
private local project storage and new-terminal setup are documented.
No required service or task a-h was removed.

Additional checks actually performed on 2026-11-06:

- **75 documented shell blocks** parsed with real **zsh 5.9 under Linux/WSL**,
  using LF input. A deliberately incomplete loop was rejected as a negative
  control. This was not a macOS execution.
- The actual manager-pod loop and AWS image-build/tag/digest command block were
  executed in zsh with **fake kubectl/AWS/Docker functions**. Both pods were
  inspected and image arguments/digests were preserved. No real cloud/container
  actions were performed.
- The new portable Python password-decoding commands passed valid-input and
  invalid-base64 checks; invalid input fails rather than displaying success.
- Python **3.12** dependencies resolved with macOS-specific environment markers
  for both `aarch64-apple-darwin` and `x86_64-apple-darwin`: **66 packages per
  target**, with source builds disabled. This was resolution, not installation
  or runtime testing on a Mac. A Windows-host pip cross-platform attempt selected
  Windows-only `pywin32`; a target-aware resolver was used instead. No dependency
  was changed merely to work around that host-tool limitation.
- Upstream Docker tag metadata confirmed **linux/arm64 and linux/amd64**
  variants for all ten local external images/build stages:
  [Python 3.12-slim](https://hub.docker.com/v2/repositories/library/python/tags/3.12-slim),
  [k6 1.4.2](https://hub.docker.com/v2/repositories/grafana/k6/tags/1.4.2),
  [Maven 3.9.9/Java 17](https://hub.docker.com/v2/repositories/library/maven/tags/3.9.9-eclipse-temurin-17),
  [Flink 1.20.0/Java 17](https://hub.docker.com/v2/repositories/library/flink/tags/1.20.0-scala_2.12-java17),
  [PostgreSQL 16](https://hub.docker.com/v2/repositories/library/postgres/tags/16),
  [Moto 5.2.5](https://hub.docker.com/v2/repositories/motoserver/moto/tags/5.2.5),
  [Kafka 3.9.1](https://hub.docker.com/v2/repositories/apache/kafka/tags/3.9.1),
  [ZooKeeper 3.9.3](https://hub.docker.com/v2/repositories/library/zookeeper/tags/3.9.3),
  [Prometheus 3.7.3](https://hub.docker.com/v2/repositories/prom/prometheus/tags/v3.7.3),
  and [Grafana 12.2.1](https://hub.docker.com/v2/repositories/grafana/grafana/tags/12.2.1).
  Image availability is not evidence that the complete Mac stack ran.

The optional full CI run repeats the documentation zsh syntax check in its Linux
infrastructure job; no extra macOS runner or deployment job was added.
The student does **not** need WSL, Git Bash or the audit's cross-target resolver.
Use the normal Mac setup and pip commands in the local guide.

**Still required on her Mac:** install the tools, build the images, run the
complete Compose smoke and inspect the results. Real Apple Silicon/Intel Docker
startup, memory usage and AWS cross-build execution were not verified here.

## Explicitly not executed at delivery

The delivery environment has no Docker engine/CLI, so the complete Compose
Kafka/ZooKeeper/Flink smoke was not executed there. AWS provisioning was explicitly
not authorized and the budget remains unconfirmed.

Therefore all these live checks remain mandatory:

- [ ] Student runs a complete clean local smoke on her Mac, or reviews an actual successful
  isolated CI rehearsal.
- [ ] Instructor confirms S23 allocation, solo arrangement, concept interpretation,
  AI policy, deadline/demo date and public-URL/certificate expectations.
- [ ] Account owner approves budget/running period; regional/quota preflight passes.
- [ ] Terraform actually provisions the approved AWS foundation and runtime.
- [ ] Argo reads the private remote branch and all applications become Healthy/Synced.
- [ ] Public pinned HTTPS works; all eight services pass fresh AWS smoke.
- [ ] Real SQS invokes Lambda; notification/retry behavior is visible.
- [ ] Managed EMR/YARN Flink is RUNNING and publishes proper Kafka window results.
- [ ] Both HPAs record true one-replica baselines then ready scale-out under a
  successful full ten-minute sustained k6 run.
- [ ] ZooKeeper manager failure produces a different owner/higher term and
  continued processing.
- [ ] S3, RDS and DynamoDB contain the expected distinct data.
- [ ] Dashboard has real RPS/error/latency/cluster data.
- [ ] Central logs include all six EKS roles, Lambda **and analytics**; deployed
  EMR collection paths/reporter ports are verified.
- [ ] Actual contribution record/submission updated; individual viva practiced.
- [ ] Complete cleanup and resource/billing checks performed at the agreed time.

## Known limits to disclose

- Synthetic heart rate/demo inbox only, no medical recommendations or real SMS.
- Applied Apache ZooKeeper, not reimplementation of its protocol.
- Two workers/two AZs and single-AZ SQL; not production high availability.
- At-least-once boundaries and ten-minute dedup TTL; no cross-product exactly-once.
- S3 and Kafka ingestion are not one transaction.
- Self-signed public certificate pinned by the helper; browser trust is not automatic.
- Fixed EKS worker count; required HPAs scale pods, not nodes.
- Versions, quotas, IAM and live log paths require actual account verification.
- Paid resources continue until removed; opt-in/alerts are not monetary caps.

## Updating this page after real execution

For each live check record the actual date, commit/image digest, command,
exit status, run/resource ID and sanitized evidence location. Separate local
from AWS runs. Keep failed attempts historical and mark pending items pending.

Do not replace an unresolved check with "should work". Use
[troubleshooting](07-troubleshooting.md) and rerun the exact requirement.
