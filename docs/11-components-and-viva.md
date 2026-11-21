# 11. Understand the components: presentation and viva companion

[Simple overview](00-project-explained.md) | [Design diagrams](03-design.md)
| [Viva practice](09-viva-and-ai-help.md) | [Guide index](../README.md)

Read this after the simple overview. It explains **what each part does, why it
is here, and how to discuss it**. It is not another deployment checklist.
Use the linked source only when you want to explore further.

Descriptions below explain the implementation, not a claim that it has already
been deployed in your AWS account. Match presentation claims to your actual
[validation and demonstration evidence](10-validation-status.md).

## 1. Three layers to keep separate

1. **Application:** eight programs perform patient-monitoring tasks.
2. **Supporting systems:** databases, queues and ZooKeeper help them cooperate.
3. **Platform and tools:** AWS runs them; Terraform, GitOps, tests and monitoring
   help deploy, check and operate them.

Only the first layer counts toward the eight application services.
An **event** is a record that something happened, such as a reading arriving or
a notification being delivered. A **request** asks another component to do
something. Requests may return immediately; event processing can happen later.

## 2. The eight application services

### 1. Patient Simulator: the source of readings

- **Receives:** a simulation request with a run ID, seed, count and start time.
- **Does:** creates machine-generated readings for three example devices. A seed
  makes the chosen heart rates repeatable; the run ID keeps separate runs apart.
- **Sends:** readings to Ingestion using REST. In the standard 12-reading run,
  four values are deliberately abnormal.
- **Explain:** "We use a simulator instead of buying sensors or using patient
  data. It makes the demonstration repeatable."

Source: [simulation rules](../s23/domain.py), [API routes](../s23/app.py).

### 2. Device Registry: checks who sent a reading

- **Stores:** device ID, corresponding example patient ID and an active flag in
  RDS PostgreSQL. Bootstrap prepares three example device/patient pairs.
- **Does:** answers Ingestion's protobuf gRPC lookup. Ingestion rejects a reading
  if the device is inactive or its patient mapping does not match.
- **Also provides:** REST operations for inspecting/updating device records.
- **Explain:** "Registry manages structured device metadata; it does not store
  the stream of heart-rate readings."

Source: [Registry and gRPC implementation](../s23/registry.py),
[protobuf contract](../proto/devices.proto).

### 3. Vital Ingestion: the front door

- **Receives:** authenticated REST calls. A reading includes an event ID, device,
  patient, heart rate and observation time.
- **Does:** checks schema/time bounds and calls Registry. It archives the raw
  reading in S3, then publishes to Kafka's `vitals` and `clinical-events` topics.
- **Also provides:** the public gateway for simulation, alert queries,
  acknowledgement, inbox and analytics requests.
- **Explain:** "HTTP 202 means the reading was accepted, not that every
  notification and analytics result is already finished."

Source: [Ingestion routes](../s23/app.py), [archive adapter](../s23/adapters.py).
S3 and Kafka writes are not one atomic transaction; do not claim otherwise.

### 4. Alert Rule Engine: decides when an alert is needed

- **Receives:** readings from Kafka's `vitals` topic.
- **Does:** applies the demonstration rule: heart rate below 50 or above 120.
  Exactly 50 or 120 is not abnormal under this rule.
- **Sends:** a REST request to Queue Manager to create an alert. The reading ID
  becomes the alert ID, helping repeated processing identify the same alert.
- **Explain:** "This is a fixed teaching rule, not ML, diagnosis or medical advice."

Source: [rule worker](../s23/workers.py), [data/rules](../s23/domain.py).

### 5. Alert Queue Manager: schedules work

- **Stores:** alert status, version, dispatch attempts and due time in DynamoDB.
- **Does:** two copies run, but only the ZooKeeper-elected scheduling leader
  claims due work and sends notification requests to SQS.
- **Also does:** requests escalation for overdue delivered alerts and publishes
  saved lifecycle events to Kafka. Its alert API is distinct from leader-only
  background scheduling.
- **Explain:** "The manager decides what work is due; the dispatcher performs
  delivery. A second manager provides takeover, not doubled scheduling."

Source: [scheduler/business actions](../s23/services.py),
[election](../s23/coordination.py), [DynamoDB storage](../s23/store.py).

### 6. Notification Dispatcher: delivers a durable inbox message

- **Receives:** an SQS event that invokes AWS Lambda. Locally, a Python process
  polls the mocked queue instead; that is rehearsal, not real Lambda.
- **Does:** checks alert state/version, then commits delivered status, an inbox
  message and an analytics event together in DynamoDB.
- **On failure:** reports failed SQS records for retry. Already-completed or
  stale work is detected rather than blindly delivering again.
- **Explain:** "Delivery means a stored message for `demo-operator`, visible in
  the inbox API. It does not mean a real SMS or email."

Source: [Lambda/local entry points](../s23/dispatcher.py),
[delivery logic](../s23/services.py), [transactions](../s23/store.py).

### 7. Acknowledgement Service: records receipt and results

- **Receives:** REST requests to acknowledge an alert or mark it overdue.
- **Does:** changes a delivered alert to ACKNOWLEDGED, or an overdue delivered
  alert to ESCALATED. Queue Manager checks due times and requests escalation.
- **Also does:** consumes Flink summaries from `clinical-results`, stores them in
  DynamoDB, and serves analytics/inbox queries.
- **Explain:** "Escalation is a recorded state, not an actual emergency response.
  A late acknowledgement of an escalated alert is allowed."

Source: [routes](../s23/app.py), [state transitions](../s23/domain.py),
[results worker](../s23/workers.py).

### 8. Clinical Analytics: summarizes the stream

- **Receives:** reading and alert-lifecycle events from `clinical-events`.
- **Does:** Java Flink groups events by device and one-minute **event-time**
  windows. It keeps counts/state, removes repeated event IDs within a bounded
  period, and calculates averages.
- **Sends:** summaries to the separate `clinical-results` topic. Results include
  readings, deliveries, acknowledgements, escalations and average ack delay.
- **Explain:** "This is continuous, stateful processing, not a spreadsheet report.
  It runs on managed EMR in AWS, not inside an EKS application pod."

Source: [Flink program](../analytics/src/main/java/edu/bits/s23/ClinicalAnalytics.java),
[aggregation state](../analytics/src/main/java/edu/bits/s23/Stats.java).

**Flink words in plain English**

| Term | Meaning in this project |
|---|---|
| Event time | Time carried by the event, rather than when a worker happens to process it. |
| Tumbling window | Non-overlapping one-minute groups; events for the same device/minute are summarized together. |
| Watermark | An estimate of how far event time has progressed. The job allows five seconds of out-of-order arrival. |
| Allowed lateness | A further ten seconds for late window updates. Events beyond the permitted lateness are logged as dropped. |
| Checkpoint | A recovery snapshot of processing state, taken every 60 seconds; saved to S3 in AWS. |
| Deduplication | Repeated event IDs are filtered using state with a ten-minute lifetime, not forever. |

The demo sends normal heartbeat readings to advance event time. Windows are not
instantaneous, and lifecycle events can fall in later minutes than their reading.

## 3. Communication and coordination

### REST, gRPC and the two messaging systems

**REST** is an HTTP request/response interface, usually with JSON here.
**gRPC** uses a protobuf-defined contract for the Ingestion-to-Registry call.
Neither is a background queue: the caller waits for a response.

**Kafka** is a retained event stream. A topic names a stream; partitions divide
it, and consumer offsets record progress. Different consumer groups can process
events independently. Ordering is within a partition, not across the whole
system. **Amazon MSK is AWS's managed hosting for Kafka**, not another application.

| Kafka topic | Producer | Consumer |
|---|---|---|
| `vitals` | Ingestion | Rule Engine |
| `clinical-events` | Ingestion plus Manager publishing saved lifecycle events | Flink |
| `clinical-results` | Flink | Acknowledgement Service's results worker |

**SQS** is the notification work queue. While a message is being processed, its
visibility timeout temporarily hides it; unsuccessful work can reappear.
The configured dead-letter queue holds messages after repeated unsuccessful
receives. A dead-letter message does not repair itself: inspect its failure.
Kafka and SQS may redeliver, so the application must handle duplicates.

Source: [Kafka adapter](../s23/broker.py), [SQS adapter](../s23/adapters.py),
[queue infrastructure](../infra/aws/storage.tf).

### ZooKeeper: election, sessions and fencing

Managers create **ephemeral-sequential nodes**: small coordination records tied
to their sessions and numbered in order. The lowest candidate is the leader.
An expired session removes its candidate, allowing takeover; takeover is not
necessarily instantaneous. A disconnected manager stops treating itself as leader.

The sequence supplies a **term**, like an ownership ticket number. DynamoDB's
**fence** rejects old-owner dispatch transactions once a newer term is active.
Per-alert **versions** separately reject stale changes and queued deliveries.
Election chooses an owner; fencing helps enforce ownership during races.

The three ZooKeeper servers use a majority quorum, unlike the two application
managers competing for leadership. This smaller lab places them on two workers:
it is not three-AZ production high availability.

### Why the transactional outbox exists

Changing an alert and separately publishing its analytics event could leave one
without the other after a crash. A DynamoDB transaction saves the state change
and a pending event together. The elected Manager publishes that **outbox**
event to Kafka, then deletes the pending copy.

A crash after publishing but before deleting can publish twice. Versions and
bounded deduplication make repeats manageable; they do not justify a claim of
global exactly-once processing.

## 4. Storage: different products for different jobs

| Component | What it holds | Why it is separate |
|---|---|---|
| S3 object storage | Raw reading JSON, built Flink artifacts, checkpoints and EMR archives. | Suits files/objects, not relational device queries. |
| RDS PostgreSQL | Device/patient mapping and active flag. | Structured SQL data; Registry owns access. |
| DynamoDB | Alert state, versions/fence, inbox, pending outbox and summaries. | Keyed records and conditional/transactional state updates. |
| EBS volumes | Persistent files for ZooKeeper servers. | Disk attached to compute, not a replacement for the three required storage-product demonstrations. |

Data lives outside the Python application pods, so replacing a pod does not
require recovering a patient database from its memory.
Source: [storage IaC](../infra/aws/storage.tf), [ZooKeeper volumes](../infra/aws/zookeeper.tf).

## 5. Running, packaging and deploying

### Containers and AWS compute

| Component | What to understand |
|---|---|
| Docker image / container | Image = packaged program/dependencies; container = running copy. One shared Python image can run different roles using the `SERVICE` setting. |
| Docker Compose / Moto | Starts the connected Mac rehearsal; Moto imitates AWS APIs. Real local Kafka/ZooKeeper/Flink does not prove real AWS IAM/network behavior. |
| ECR | AWS repository holding the Python/Lambda images. A digest identifies the exact image; it is not the Git source repository. |
| EKS / EC2 | EKS manages the Kubernetes control plane. EC2 worker machines supply capacity for pods. Six Python roles run here; initially seven application pods because Manager has two copies. Helpers add more pods. |
| Lambda | Runs Dispatcher code when SQS supplies work; no dedicated dispatcher VM is managed by the student. It is still billable usage. |
| EMR / YARN | Managed cluster that runs the Flink application. YARN allocates its runtime resources; a successful submission step alone does not prove the job stays running. |

### Kubernetes words and real scaling

- **Pod:** a running unit containing the application container.
- **Deployment:** declares how an application should run and replaces failed pods.
- **Kubernetes Service:** a stable network address for pods. This object is not
  the same thing as one of the assignment's eight business services.
- **HPA:** adjusts pod copies from measured resource utilization. Here it targets
  Ingestion and Registry CPU, from one up to three copies each.
- **metrics-server:** supplies Kubernetes resource measurements used by the HPA.
  Installing Prometheus alone is not the HPA measurement setup in this project.
- **k6:** sends real sustained reading traffic. Both services must start at one
  ready copy and reach at least two; merely displaying HPA YAML is not proof.

HPAs use CPU relative to a pod's **CPU request**, not machine-wide CPU percentage.
Registry's headless DNS/round-robin gRPC lets calls reach its additional copies.
The worker-node count remains fixed: pod scaling cannot create unlimited capacity.

Source: [application deployments/HPAs](../deploy/app/templates/services.yaml),
[load test](../load/k6.js), [evidence verifier](../tools/verify_hpa.py).

### Terraform, Helm, Argo CD and GitHub Actions

| Tool | Its specific job |
|---|---|
| Terraform | Creates AWS resources from `.tf` files. `plan` previews changes; `apply` performs them. State maps configuration to existing resources and can contain secrets. |
| Helm | Turns reusable YAML templates plus values into Kubernetes configuration. A chart describes what should run; it does not itself watch Git. |
| Argo CD / GitOps | Watches the private repository and reconciles the desired Kubernetes configuration. Application changes go through Git, not direct service `kubectl apply`. |
| GitHub Actions / CI | Builds, lints, unit-tests code and checks rendered charts automatically. Terraform/PromQL checks and Docker smokes require manual full validation. It does not provision AWS or replace Argo CD. |

Deployment is deliberately phased: Terraform foundation, images and Git values,
Argo bootstrap, then Lambda/EMR runtime once app initialization/topics are ready.
Tests do not replace that deployment or its live evidence.

Sources: [AWS Terraform](../infra/aws), [Argo bootstrap](../infra/gitops),
[Helm charts](../deploy), [validation workflow](../.github/workflows/validate.yml).

## 6. Network, permissions and monitoring

| Component | Project role and a useful distinction |
|---|---|
| VPC, subnets, security groups | Define the network and permitted connections. Databases/brokers are private, not public endpoints for the student's laptop. |
| NAT gateway | Lets private resources initiate outbound internet access; it does not make the database publicly accessible. It charges while provisioned. |
| ALB and HTTPS certificate | Public entry point routing to Ingestion. The self-signed certificate is pinned by the helper; browser trust is not automatic. Other roles stay private. |
| IAM roles / IRSA | Decide which AWS actions a workload can perform. EKS service accounts assume dedicated roles rather than carrying shared long-lived AWS keys. |
| Secrets Manager / API key | Keeps secret values outside Git. The public data API requires a key; an account permission is different from API-key authentication. |
| Prometheus | Collects numeric measurements: request counts, errors, latency and resource/cluster data. |
| Grafana | Displays those measurements as dashboards. RPS = requests per second; p95 latency = 95% of observed requests finish within that duration. |
| Fluent Bit / CloudWatch | Fluent Bit ships EKS logs to CloudWatch; Lambda logs there directly; EMR uses a collection agent. Logs explain individual events, unlike aggregate metrics. |

HTTP latency is not the total time until notification/escalation/window results.
Show the business states as well as a fast HTTP response. Centralized logging
must include analytics, not just the public API.

Sources: [network](../infra/aws/network.tf), [public HTTPS](../infra/aws/public_api.tf),
[IAM](../infra/aws/iam.tf), [metrics](../s23/observability.py),
[dashboard](../deploy/app/dashboards/s23.json),
[log collection](../deploy/platform/templates/logging.yaml).

## 7. Build a five-minute presentation

| Time | Explain/show |
|---|---|
| 0:00-0:30 | Problem and scope: machine-generated readings, demo inbox, no clinical use. |
| 0:30-1:30 | Point to the eight services on the design diagram; follow one abnormal reading. |
| 1:30-2:15 | Explain REST/gRPC/Kafka/SQS, the three stores and why ZooKeeper elects one scheduler. |
| 2:15-3:00 | Explain EKS versus Lambda versus EMR, then Terraform versus Argo versus CI. |
| 3:00-4:30 | Show previously captured, successful functional, scaling, failover and monitoring evidence. |
| 4:30-5:00 | State limits, pending AWS checks and the cleanup/cost plan. |

The ten-minute load test and minute-window/escalation waits cannot be compressed
into five minutes. Present their genuine saved results; perform live parts
separately as required by the instructor. See the [demonstration guide](06-demonstration-and-observability.md).

## 8. Questions to answer without reading the document

1. **Trace one abnormal reading.** Simulator -> Ingestion/Registry -> S3/Kafka ->
   Rules -> Manager/SQS -> Dispatcher/inbox -> acknowledgement or escalation.
   Flink separately summarizes the reading and lifecycle events.
2. **What does "delivered" prove?** An inbox message was committed, not that a
   person read it. ACKNOWLEDGED is a separate action.
3. **What if the scheduling leader dies?** ZooKeeper session membership changes,
   another manager takes ownership, and fencing/version checks guard stale work.
4. **What if Kafka repeats an event?** Alert identity/version checks and bounded
   Flink deduplication help; no infinite or cross-product exactly-once guarantee.
5. **How do you prove scaling?** Real one-replica baseline, sustained successful
   k6 run, then at least two ready replicas for each target.
6. **What is tested versus deployed?** Unit tests isolate dependencies; Linux CI
   rehearses Docker with mocked AWS. Neither proves AWS Lambda/EMR/HPA/logging.
7. **Why use the paid account?** The Free-plan account blocked EMR. A normal
   pay-as-you-go account removes that plan restriction, not permissions/quotas
   or charges. Budget for full usage and clean up; idle resources still charge.

Practice by drawing the flow from memory, then point to the source file and
actual evidence for each claim. Use your own words rather than memorizing a script.
