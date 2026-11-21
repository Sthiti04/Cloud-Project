# 7. Troubleshooting without unsafe shortcuts

[Demonstration](06-demonstration-and-observability.md) | Next: [cleanup and cost](08-cleanup-and-cost.md)

Read the first actual error, not only "exit code 1". Identify the phase:
local build, local runtime, foundation, GitOps, Lambda/EMR, or proof.
Change one identified cause, run its targeted check, then repeat the failing step.

Never paste secrets/full state/interpolated Compose output into a chat.
Do not bypass failures with disabled TLS, AdministratorAccess everywhere,
direct service apply/scale, or invented evidence.

## First diagnostic commands

Local, from this repository:

```zsh
docker compose ps -a
docker compose logs --tail=100 bootstrap flink-submit
docker compose logs --tail=100 vital-ingestion device-registry alert-rule-engine
```

AWS, correct approved session/context:

```zsh
aws sts get-caller-identity
kubectl config current-context
kubectl get applications -n argocd
kubectl get pods -n s23 -o wide
kubectl get events -n s23 --sort-by=.lastTimestamp
kubectl logs -n s23 deployment/vital-ingestion --tail=100
```

For a specific crashed pod, inspect `kubectl describe pod NAME -n s23` and
`kubectl logs NAME -n s23 --previous --tail=100`. These are inspections, not
deployment shortcuts.

## Argo stuck: HPAs say Deployment not found

**If the old attempt has already been destroyed, skip recovery below.** Use
[the redeployment checklist](05-aws-deployment.md#0-prepare-a-new-attempt-after-cleanup)
with the corrected charts. There is no old cluster left to refresh/resync.

**Use this section for this exact combination:** ZooKeeper is running, both
initialization Jobs completed, no application Deployments exist, and
`kubectl describe hpa vital-ingestion device-registry -n s23` reports
`FailedGetScale` with `deployments.apps "vital-ingestion" not found` (or
`device-registry`).

This is one startup-order problem, not three separate failures. The old chart
put the HPAs in Argo's default wave **0** and the application Deployments in wave
**1**. Argo waited for the HPAs to become healthy before moving to wave 1, but
the HPAs needed those missing Deployments. More waiting or installing another
metrics-server cannot break that loop.

The corrected order is:

1. Wave 0: ZooKeeper and the database/topic initialization.
2. Wave 1: the six application Deployments.
3. Wave 2: the two HPAs, after their target Deployments are healthy.
4. Wave 3: the optional load Job, after the services/autoscalers are ready.

### Recover the existing deployment

**No Terraform destroy/apply, image rebuild, new key or new cluster is needed
for this fix.** Keep the existing state, AWS values, volumes and data.

1. A maintainer must first publish the corrected
   [services template](../deploy/app/templates/services.yaml) and
   [load template](../deploy/app/templates/load-test.yaml) to the branch Argo
   tracks (normally `main`). Local file edits alone do not reach the cluster.
   The HPA metadata must have `argocd.argoproj.io/sync-wave: "2"` and the load
   Job must have wave `"3"`. Do not replace your generated AWS values.
2. Use [the AWS terminal setup](05-aws-deployment.md#in-every-aws-terminal) for
   the existing paid account. Check `aws sts get-caller-identity` and
   `kubectl config current-context`.
3. Open Argo using [the existing port-forward/login instructions](05-aws-deployment.md#open-argo-on-your-mac)
   and select **s23-application**, not the root/monitoring application.
4. If an old sync still says **Running/Retrying**, use its **Terminate** operation
   control. This stops that sync operation; **do not choose Delete application**
   or delete any pods/HPAs/volumes.
5. Choose **Refresh -> Hard Refresh**. Confirm the displayed desired Git revision
   includes the published fix. Then choose **Sync** for the whole application
   at the latest `main` revision and **Synchronize**. Use normal sync options:
   no resource-only selection, Force, Replace, deletion or health overrides.
   If auto-sync already started that revision, let it finish rather than
   launching another operation.

Wait a few minutes. In the Mac terminal, run:

```zsh
kubectl get deployments -n s23
kubectl get pods -n s23
kubectl get hpa -n s23
kubectl describe hpa vital-ingestion device-registry -n s23
kubectl get applications -n argocd
```

**Continue only when:** all six application Deployments are available (Manager
has two copies), the HPAs no longer report missing targets, CPU metrics appear
and Argo is `Synced`/`Healthy`. Old warning Events can remain after recovery;
check the current Conditions and timestamps. Do not expect exactly one replica
under all activity: both HPAs are allowed to scale from one to three.

If Deployments now exist but pods fail or CPU stays `<unknown>`, that is a
different next error. Capture `kubectl get pods -n s23`, the current HPA
Conditions and the failing pod's Events; use the relevant sections below.
Do not assume the initial ordering fix proves the whole AWS deployment.

Resume at [deployment step 6's readiness checklist](05-aws-deployment.md#open-argo-on-your-mac),
then start Lambda/EMR only when it passes. If runtime is already enabled, don't
create it again. The existing AWS foundation continues charging while blocked.

## Local/tools

| Symptom | Likely cause | Safe response |
|---|---|---|
| Docker command missing/engine unavailable | Docker Desktop not installed/running | Install official Docker, start Linux engine; offline checks alone are not integration |
| `brew`, `python3.12` or `helm` missing in a new terminal | Homebrew or versioned-tool PATH not loaded | Follow Homebrew's printed `shellenv` instructions and the local guide's new-terminal block; use native Homebrew, not a mixed Rosetta installation |
| Helm reports v4 | Unversioned formula selected | Install `helm@3` and prepend its bin directory as documented; do not upgrade charts to work around this |
| zsh treats `#` as an argument or says `command not found: #` | Interactive comments not enabled | Run `setopt INTERACTIVE_COMMENTS`; paste one reviewed block at a time |
| zsh says `no matches found` for a query/JSON argument | Copied without its quotes | Restore the guide's exact quotes; do not globally disable glob checking |
| Apple Silicon build requests AMD64 unexpectedly | Global platform override or old Intel-tagged local image | Follow `unset DOCKER_DEFAULT_PLATFORM` and rebuild local images natively; only AWS image builds use explicit `linux/amd64` |
| `exec format error` or `no matching manifest` | Wrong architecture/image variant | Confirm `uname -m` and image platform; keep native local builds separate from x86_64 AWS builds; do not substitute arbitrary image versions |
| Docker bind mount denied | Project location not shared with Docker | Keep it in a local `~/Developer` folder and review Docker Desktop file sharing; do not move secrets into a cloud-synced folder |
| `No module named ...` | Wrong/inactive environment or missing declared dependency | Activate `.venv`; install declared requirements after that failure |
| Helpers fail relative imports | Running a file standalone | Use `python -m tools.demo`, etc., from the root |
| `.env` missing | Local setup not run | `python -m tools.setup_local`; keep generated values private |
| Setup refuses existing `.env` | Deliberate overwrite protection | Reuse it; regenerate only after an intentional local reset |
| Bootstrap exit nonzero | Mock/SQL/Kafka initialization error | Inspect bootstrap logs; do not continue to smoke |
| `bootstrap`/`flink-submit` exit 0 | Expected one-shot completion | Not a crash; separately verify the actual running Flink job |
| Container exits 137/OOM | Insufficient Docker memory | Allocate enough memory, restart only this stack; do not call partial stack success |
| Port 8080/8081/3000/9090 occupied | Local rehearsal or another process | Stop this project's Compose stack before cloud port-forwards; identify other owners with `lsof -nP -iTCP:3000 -sTCP:LISTEN` (adjust port); do not stop unrelated workloads |
| Maven uses Java 21/other version | Incorrect JAVA_HOME/PATH | Select Java 17 or use the supplied Docker build/export |
| Terraform mocked runtime test missing JAR | Build/export step skipped | Produce all three exact artifacts before `terraform test` |
| Helm render asks for volumes/image | Wrong/default values | Offline tests use the fixture; cloud uses generated AWS values, never placeholders |
| Local Kafka data lost but old app data retained | Partial reset | Stop and coherently reset synthetic local stack; do not mix generations |

If local ZooKeeper was recreated but older DynamoDB fence data survived, new
low sequence terms can be rejected. Reset the whole **local synthetic** stack,
not just one container's data. Do not delete cloud data to silence a fence.

## Terraform/account/GitOps

| Symptom | Check | Fix |
|---|---|---|
| EMR says it is unavailable on the Free plan | Account plan and selected account | Use the intended normal pay-as-you-go account/profile; changing Flink code won't remove a plan restriction. Paid access still needs permissions/quotas. |
| Caller identity shows the previous account | `AWS_PROFILE` and credential overrides | Repeat the AWS guide's sign-in block for `s23-paid`; confirm the account ID before any apply/destroy. |
| Cost guard says STOP | `allow_paid_resources` | Get approval; opt in only afterwards |
| AccessDenied | Caller identity, exact denied action/resource | Account owner grants reviewed required permissions; no root workaround |
| `admin_principal_arn` rejected | STS versus IAM ARN | Use the actual IAM user/role ARN, including SSO path |
| InsufficientInstanceCapacity/vCPU limit | Spare quota and regional offerings | Resolve approved quota/capacity before retry; don't randomly change architecture |
| Unsupported version/add-on | Read-only version checks | Confirm compatible supported versions and rerun tests |
| EKS API timeout after changing network | Public IPv4 `/32` | Update approved IaC CIDR and apply; never open endpoint to the world |
| Nodes NotReady | aws-node/CNI, control-plane/node SGs, IAM | Fix IaC; CNI role must exist before compute; do not attach ad-hoc console policies |
| State lock exists | A running/interrupted apply | Confirm no active writer first; do not force-unlock an active apply |
| GitOps cannot read AWS state | Local backend/file location | Restore protected correct foundation state, not a newly created empty state |
| `values-aws.yaml` missing in Argo | Actual remote branch files | Review/commit/push both files and charts; local files are not GitOps source |
| SSH repository permission denied | Deploy key/repo URL | Dedicated public key installed read-only; private counterpart at expected ignored path |
| Wrong Argo revision | repo/branch consistency | Generator, bootstrap and pushed branch must agree |
| Monitoring stays unhealthy | Chart/operator/CRDs and events | Let ordered Argo sync complete; inspect failures, don't manually install app charts |
| Schema/topic hook fails | Job logs, IAM/DB/Kafka connectivity | Fix source/IaC and retry through Argo |
| Successful hook pods disappear | Hook deletion policy | Expected; check Argo's operation results |
| PVC Pending/volume attachment error | IDs/zones, EBS CSI role, worker placement | All three Terraform volume IDs/zones must match; don't invent PV IDs |
| ImagePullBackOff | Correct digest/account/ECR permissions | Build/push real linux/amd64 digest; update Git values |

A partially failed Terraform apply can still cost money. Keep state and inspect
what exists. Use the same project/state to retry or clean up; do not recreate
everything in a second directory.

## Public API and state

| Result | Meaning | Response |
|---|---|---|
| TLS certificate verification fails | Old/missing pinned cert or wrong URL | Refresh metadata/CA after IaC change; use current matching URL |
| ALB 503 before GitOps app | No healthy ingestion target yet | Complete GitOps; inspect NodePort/target readiness |
| 401 | Missing/wrong API key | Use supplied AWS client/approved secret access; never publish the key |
| 422 | Invalid schema/time/registration | Current milliseconds; seeded active mapping; valid integer types |
| 404 on specific alert | Not created/unknown | Smoke tolerates only its expected pending IDs; inspect rule worker if persistent |
| 409 | Conflicting ID or invalid/stale transition | Reload state; don't acknowledge PENDING; don't reuse an ID with different data |
| 503 dependency unavailable | SQL/gRPC/S3/Kafka/etc. failure | Inspect responsible service and IAM/network logs, then retry safely |
| Worker readiness 503 | Worker exited/failed | Inspect original exception; pod running alone is not healthy |
| PENDING remains | No elected scheduler | Check manager session/quorum/fence |
| IN_FLIGHT remains | Lambda/SQS not delivering | Runtime enabled? Lambda Active? Mapping enabled? Inspect logs/DLQ/versions |
| ESCALATED | Delivered, receipt overdue | Expected demo state; later acknowledgement is allowed |
| FAILED | Dispatch attempts exhausted | Fix underlying persistent failure; don't rewrite state to fake success |

Immutable S3 retries compare exact payloads. Retrying the same reading ID/data is
allowed within time bounds; changing it is rejected. If archive succeeded but
Kafka failed, identical retry can republish because the two products are not one
transaction.

## Lambda/SQS

1. Check runtime true and correct dispatcher ECR digest.
2. Read `get-function-configuration`, mapping and recent Lambda logs.
3. Confirm queue URL/region/table and least-privilege role.
4. Inspect queue visible/in-flight/DLQ counts, not destructive purge/receive.
5. Recognize intentional first-failure mode and 60-second redelivery wait.

`ReportBatchItemFailures` returns failed records for retry. A function invocation
can be successful while a record fails; inspect FailedRecords/logs rather than
only AWS/Lambda Errors.

Do not use `receive-message` during the main proof just to inspect production
work: it changes visibility and can steal a pending notification. Prefer queue
attributes/logs. Do not delete/purge messages to hide failures.

Stale/duplicate delivery logs can be legitimate after retries/failover. Versions
must prevent an old delivery from overwriting current state.

## Flink/EMR/windows

| Symptom | Safe diagnosis/fix |
|---|---|
| Local submit exit 0 but no results | Check RUNNING job, TaskManager and Kafka connectivity |
| EMR WAITING, failed step | Read step status/stderr; cluster remains billable |
| `/bin/bash^M` or carriage-return shell errors | Use current IaC, which normalizes uploaded shell payloads; recreate the demo runtime after the fix |
| Unsupported `run -d -t yarn-application` | Use supplied `run-application -t yarn-application` |
| Missing S3 filesystem | Build/upload plugin; correct `/usr/lib/flink/plugins/s3-fs-hadoop/` |
| Missing Prometheus reporter | Build/upload reporter; correct Flink lib/classpath |
| IAM token/authorization failure | Region, MSK IAM/TLS, role and bootstrap brokers |
| `BufferRecycler.releaseToPool`/Jackson linkage | Use supplied BOM/shaded JAR; remove stale locally built image/JAR by rebuilding, not random extra JARs |
| Windows don't appear immediately | Event time needs advancing data; `python -m tools.demo --aws tick` |
| Too-late event dropped | Five-second watermarks/ten-second lateness are intentional; inspect timestamps and delayed outbox |
| New JAR uploaded but old job remains | Existing EMR step is ignored; planned runtime-off/on recreates demo job |
| TaskManagers cannot reach checkpoint store | S3 IAM/network/plugin and checkpoint URI |
| Analytics CloudWatch group empty | Inspect real YARN log paths and agent on primary/core via SSM; fix bootstrap and recreate runtime |

For SSM and live YARN checks use [the demo instructions](06-demonstration-and-observability.md).
Do not open public SSH/8081/8088 or manually launch a second Flink job as a
submission shortcut.

## Updating an existing deployment

Skip this section for the first deployment. Keep using the **same folder,
account, Terraform state and project name** when making changes later.

- **Python services:** test, build/push a new immutable image tag/digest,
  regenerate values, review and push. Argo rolls the pods.
- **Lambda:** build/push its new dispatcher digest, change `lambda_image_uri`
  in ignored tfvars, then review/apply Terraform.
- **Flink/bootstrap:** rebuild/export all three artifacts. The existing EMR
  submission step is intentionally ignored by Terraform; uploading a new JAR
  alone does not restart Flink. For this demo, review/apply
  `enable_runtime=false`, then review/apply `enable_runtime=true` to recreate
  EMR with the new artifacts. This also recreates Lambda/its mapping; queues and
  stored data remain. Refresh metadata with `tools.configure_aws`, then re-smoke.
- **Infrastructure:** edit IaC, review a plan, then apply. Do not console-create
  replacement resources as a shortcut.

Never change the supplied Flink launcher
`flink run-application -t yarn-application` to `flink run -d -t yarn-application`.
After a runtime recreation, use fresh EMR IDs/certificate/metadata, not old notes.

## Optional cloud retry practice

Do this only after a normal demonstration succeeds, with enough budget/time.
The first SQS redelivery takes about 60 seconds.

1. In ignored AWS tfvars set `fail_first_delivery = true`, leaving runtime on.
2. Review/apply Terraform in the correct paid account.
3. Run `tools.configure_aws` with the existing service digest as in the AWS guide;
   review/push any generated Git changes and wait for Healthy/Synced.
4. Run `python -m tools.demo --aws smoke --timeout 480`.
5. Show `delivery_transient_failure`, then `synthetic_notification_delivered`
   for the same alert in Lambda logs.
6. Restore the flag to false through the same Terraform/GitOps sequence.

Do not lower queue visibility or the dispatch lease to shorten the wait.
For a local-only practice, change `.env`'s `FAIL_FIRST_DELIVERY` to `true`,
recreate only `notification-dispatcher` with Docker Compose, and run the local
smoke; restore it to false afterwards. This local process is not real Lambda.

## HPA or k6 failure

```zsh
kubectl top pods -n s23
kubectl describe hpa vital-ingestion -n s23
kubectl describe hpa device-registry -n s23
kubectl get pods -n s23 -o wide
```

- `unknown` CPU: metrics-server readiness/cert/version, requests and pod metrics.
- Already >=2 before observation: stop load through Git and wait for natural
  downscale; the baseline verifier correctly refuses existing replicas.
- Desired >=2 but available stays one: inspect Pending/OOM/scheduling/capacity.
- Registry second pod sees no calls: confirm **headless DNS round-robin target**
  from generated environment and current image; don't restore ClusterIP-only gRPC.
- k6 drops iterations: source/service capacity is insufficient. Inspect actual
  bottleneck, VU counts, latency, CPU and cloud-service failures.
- Failed k6 threshold: do not relax it solely to claim success.
- Insufficient genuine traffic: adjust reviewed `loadTest.rate` through Git,
  repeat a **full ten-minute** run with a new ID and fresh baseline.
- Idle CPU already exceeds tiny requests: tune measured requests in source through
  Git, rerun manifest tests and prove genuine subsequent scale-out. Do not use an
  artificial CPU endpoint or manual replicas.

Save failed evidence honestly, fix the cause and repeat. A fresh watcher report
can be `verified: false`; old JSON or only HPA YAML is not scaling proof.

## Observability gaps

- Confirm Grafana's time range and Prometheus Targets.
- `kubectl get svc -n observability` reveals actual service names for forwarding.
- HTTP 5xx fraction is separate from deliberate 401/422 validation tests.
- Worker services may have no public HTTP traffic; inspect processed events.
- CloudWatch exporter needs API permissions and a minute or two of metric delay.
- Confirm `s23_notifications_failed_records_sum`; do not incorrectly prepend
  `aws_` to that custom namespace's name.
- EC2-discovered Flink metrics need propagated Project/Workload tags, private
  reachability and actual reporter ports. Inspect 9249/9250; update Git scraping
  if real deployed process ports require more.
- Fluent Bit errors require its own logs, namespace metadata and log-write role.
- **Task h remains incomplete if one application role or analytics has no
  centralized logs**, even if a dashboard screenshot exists.

If still blocked, capture the first sanitized error, exact command, phase,
relevant file/line and what was actually tried. Use [AI-help guidance](09-viva-and-ai-help.md)
without sharing credentials or claiming unexecuted fixes.
