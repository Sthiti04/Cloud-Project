# 2. Requirements and submission evidence

[Start here](01-start-here.md) | Next: [design document](03-design.md)

## Source interpretation

This mapping comes from both pages of the supplied PDF and **S23 in the second
worksheet, ScenariosDomain**. It does not infer a group number from neighboring
cells or proficiency from earlier lab instructions. Common infrastructure
requirements still apply even though the domain logic is deliberately small.

## Exact eight-service mapping

| # | Required responsibility | Implementation | Required live evidence |
|---|---|---|---|
| 1 | Reproducible simulated readings | Separate Patient Simulator EKS Deployment | `generated: 12`; deterministic behavior is unit-tested |
| 2 | Manage simulated devices | Device Registry, RDS, REST/protobuf gRPC | Three rows; ingestion's gRPC request metric increases |
| 3 | Receive and validate readings | Public authenticated Vital Ingestion | Public URL; valid accepted, invalid/unregistered rejected |
| 4 | Threshold detection | Kafka-consuming Alert Rule Engine | Four alerts; tested boundaries 49/50/120/121 |
| 5 | Alert state and retry tracking | Two Queue Managers, DynamoDB, ZooKeeper | States, versions, dispatches; one scheduling owner |
| 6 | Delivery and transient retry | SQS-triggered Lambda Dispatcher | Four durable inbox messages; invocation/retry logs |
| 7 | Receipt and overdue escalation | Acknowledgement Service | One ACKNOWLEDGED and another ESCALATED alert |
| 8 | Readings, delivery and ack-delay summaries | Flink on EMR; Kafka results | Actual window JSON including delivery counts and average ack delay |

Delivery is **an in-app notification to `demo-operator`**, committed atomically
with delivery state in DynamoDB. `/notifications` retrieves the messages. Logs
are supplementary evidence, not the only delivery action. No real SMS/email is
claimed.

Six Python EKS Deployments + one Lambda + one Flink application = eight.
They reuse code but have separate processes, identities and responsibilities.
ZooKeeper, Kafka, monitoring and initialization/load jobs are not extra services.

## Tasks a-h

All live proof below is **pending until actually captured**.

| Task | Requirement | Implementation/source | Minimum convincing proof |
|---|---|---|---|
| a | All cloud infrastructure through IaC | [AWS Terraform](../infra/aws), [bootstrap Terraform](../infra/gitops) | Reviewed plans/applies; resources match state; no console-created clusters/databases/LB |
| b | Named async/event-driven serverless service; REST, gRPC and messaging all used | [Lambda handler](../s23/dispatcher.py), [proto](../proto/devices.proto), [APIs](../s23/app.py), MSK/SQS | SQS Lambda trigger; inbox/invocation; REST flow; gRPC metric; Kafka flow |
| c | Managed K8s; two CPU/memory HPAs; sustained load demonstrates scale-out | EKS, [HPAs](../deploy/app/templates/services.yaml), [k6](../load/k6.js), [verifier](../tools/verify_hpa.py) | Both targets start at one ready replica, then reach at least two; successful ten-minute load |
| d | GitOps tracks Git; no direct service apply | [Argo Applications](../deploy/platform/templates/applications.yaml) | Healthy/Synced revision; a harmless Git-only update reaches the cluster |
| e | One named service is managed-cluster Flink; Kafka input, stateful windows, separate result topic | [Flink](../analytics), [EMR](../infra/aws/streaming.tf) | EMR/YARN RUNNING; `clinical-events` input; `clinical-results` output; valid minute-window JSON |
| f | Apply/demo scenario concept | [election](../s23/coordination.py), [fencing](../s23/store.py) | One manager owner; different owner/higher term after failure; processing continues |
| g | Three distinct storage products | [storage](../infra/aws/storage.tf) | S3 raw JSON, RDS device rows, DynamoDB alert/inbox/window records |
| h | Prometheus/Grafana RPS/error/latency/cluster dashboard; logs from every service, including analytics | [dashboard](../deploy/app/dashboards/s23.json), [logging](../deploy/platform/templates/logging.yaml), [EMR agent](../infra/aws/emr-bootstrap.sh.tftpl) | Real dashboard data; CloudWatch logs from six EKS roles, Lambda and Flink |

### Do not confuse configuration with proof

- Local Docker is not EKS; local dispatcher is not Lambda; Docker Flink is not EMR.
- HPA YAML or already-existing replicas do not prove load-driven scale-out.
- A completed EMR submission step does not prove its long-running Flink job is healthy.
- Three tables/prefixes in one product are not three distinct storage products.
- Installing ZooKeeper is not the application-coordination demo.
- Console inspection is fine; creating infrastructure through wizards is not.
- Rendering/linting manifests is validation. Do not apply them manually.

## Communication evidence

| Mechanism | Where | Observe |
|---|---|---|
| REST | Gateway to simulator/manager/ack; rule engine to manager | API output and `s23_http_requests_total` |
| gRPC | Ingestion -> Registry GetDevice | `s23_grpc_requests_total` and protobuf contract |
| Kafka | Readings -> rules; clinical events -> Flink; results -> result worker | Topics, worker metrics and window output |
| SQS | Elected manager -> Lambda | Trigger, queue metrics and delivery/retry logs |

Cloud gRPC uses headless DNS and round-robin resolution so new registry replicas
can receive calls. It is actual protobuf gRPC, not a renamed REST endpoint.

## Deliverable checklist

- [ ] Reviewed [design document](03-design.md).
- [ ] GitHub service source, tests and dependency/build files.
- [ ] [AWS IaC](../infra/aws) and [GitOps bootstrap](../infra/gitops).
- [ ] [App manifests](../deploy/app) and [platform config](../deploy/platform).
- [ ] Correctly named [task_divison.txt](../task_divison.txt), actual names/IDs and
  assignments; approved solo arrangement if applicable.
- [ ] Current public URL and self-signed certificate explanation.
- [ ] Verified real eight-service smoke output.
- [ ] HPA baseline/scale-out JSON and successful full sustained-load output.
- [ ] ZooKeeper failover, Flink/window/result-topic and storage evidence.
- [ ] Metrics plus centralized logs from all eight application roles.
- [ ] Each actual member can demonstrate assigned work and answer questions.

The PDF specifies one Nalanda submission per group and a later demonstration.
Its deadline is only "as on Nalanda"; do not invent a date. Earlier lab video or
terminal-ID prompts are not automatically term-project deliverables. Check the
current portal for additional instructions.

## Suggested ignored evidence folder

| Future filename | What belongs there |
|---|---|
| `smoke-aws.json` | Automatically saved verified functional smoke |
| `hpa.json` | Actual snapshots; `verified: true` and baseline must be present |
| `k6.txt` | Full successful ten-minute Job output |
| `zookeeper-before.txt`, `zookeeper-after.txt` | Ownership/terms before and after real failure |
| `public-url.txt` | Current URL, certificate note, successful landing response |
| `storage.txt` | Sanitized S3/RDS/DynamoDB observations |
| `flink.txt` | EMR/YARN, topics and representative windows |
| `observability/` | Dashboard captures and logs from all eight roles |

These are organizational suggestions, not prefilled evidence. Keep cloud/local
reports separate. Never upload state, private keys, credentials or unredacted
interpolated Compose configuration.
