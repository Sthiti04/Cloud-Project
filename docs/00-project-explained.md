# What have we built?

[Guide index](../README.md) | Next: [start here](01-start-here.md)

**Read this for the big picture, not as another setup checklist.**
You do not need to understand every file before running the project.
For more detail before a presentation or viva, read
[the component companion](11-components-and-viva.md) after this overview.

## 1. The idea in one paragraph

We built a **practice patient-monitoring system**: invent heart-rate readings,
check them, create notifications and summarize the results. An operator can
acknowledge a notification; otherwise it becomes overdue. All data is fake:
no real patients, sensors, SMS or medical decisions. You use commands/API
responses, not a custom patient-facing app.

The demo's device/patient records and readings are machine-generated.
Notifications are produced by the application in response to those readings.

## 2. Follow one reading through the eight services

A **service** is a separately running program with one responsibility.
Think of eight staff members passing work to each other:

| Service | Its job |
|---|---|
| 1. Patient Simulator | Invents readings, such as a heart rate of 145. |
| 2. Device Registry | Checks that the sending device belongs to a known fake patient. |
| 3. Vital Ingestion | Receives readings, checks devices with Registry, saves raw data and publishes it. |
| 4. Alert Rule Engine | Spots readings below 50 or above 120 and requests an alert. These are demo thresholds, not medical guidance. |
| 5. Alert Queue Manager | Tracks alerts and schedules notification attempts. |
| 6. Notification Dispatcher | Writes a durable message into the demo operator's inbox. It retries temporary delivery failures. |
| 7. Acknowledgement Service | Records "I have seen this", or overdue escalation requested by the manager; also stores analytics results. |
| 8. Clinical Analytics | Uses Flink to summarize events in one-minute groups: readings, deliveries and acknowledgement delays. |

The standard demo creates **12 readings and four alerts**. It acknowledges one
and leaves others overdue, then checks the inbox and summaries.

Three ways of passing work are deliberately included:

- **REST:** ordinary web requests, such as asking to acknowledge an alert.
- **gRPC:** a structured program-to-program call; Ingestion asks Registry about a device.
- **Messaging:** Kafka carries reading/lifecycle events and analytics results.
  SQS holds notification work for the Dispatcher.

**ZooKeeper is the coordinator, not the patient database.** Two Queue Managers
run, but ZooKeeper selects one scheduling leader. If it fails, the other takes
over. Stored ownership/version checks help reject stale or duplicate work.

## 3. Where does everything run?

| On the Mac: rehearsal | On AWS: assignment deployment |
|---|---|
| Docker runs the programs in isolated containers. | EKS, AWS's managed Kubernetes service, runs six Python service roles. |
| Dispatcher is a local process; Flink runs in Docker. | Dispatcher becomes an event-triggered Lambda function; Flink runs on an EMR cluster. |
| Moto imitates AWS storage/queue APIs. | S3 stores raw readings, RDS stores device records, and DynamoDB stores alerts, inbox messages and summaries. |

Local success is practice, not proof of the AWS requirements.

**Why so many parts?** The assignment requires these eight services, communication
methods, cloud platforms, coordination, storage and monitoring. The small
medical example sits inside that required cloud setup.

## 4. What are the files for?

Think of the repository as **programs + packaging + deployment instructions +
tests**, not a hundred separate applications.

| Files/folder | Plain-English purpose |
|---|---|
| [s23/](../s23) | Python application: [app.py](../s23/app.py) receives API calls; [domain.py](../s23/domain.py) defines data/rules; [services.py](../s23/services.py) performs business actions; [workers.py](../s23/workers.py) runs background tasks. |
| Other files in [s23/](../s23) | Registry/store/broker/adapters connect to databases and messaging; coordination handles ZooKeeper; dispatcher handles notifications. Settings/resources connect everything; bootstrap prepares initial demo data. |
| [analytics/](../analytics) | Java Flink program/tests. [pom.xml](../analytics/pom.xml) describes its build, which produces JAR files: packaged Java code. |
| [proto/devices.proto](../proto/devices.proto) | The agreed request/response format for the Registry's gRPC calls. |
| [Dockerfile](../Dockerfile), [Dockerfile.lambda](../Dockerfile.lambda), [analytics/Dockerfile](../analytics/Dockerfile) | Packaging recipes. An image packages code/dependencies; a container is a running copy. |
| [compose.yaml](../compose.yaml), [local/](../local) | Start/connect the local rehearsal containers and configure local monitoring. |
| [infra/aws/](../infra/aws) | Terraform blueprints for AWS resources. Files ending in `.tf` are read together, not run one by one. |
| [infra/gitops/](../infra/gitops) | Installs Argo CD and connects it to the private Git repository. Argo watches Git and applies the desired Kubernetes configuration. |
| [deploy/app/](../deploy/app), [deploy/platform/](../deploy/platform) | Helm charts: YAML templates telling Kubernetes how to run the app, ZooKeeper and monitoring. Values supply settings such as image versions. |
| [tools/](../tools) | Helpers: setup_local creates credentials; configure_aws prepares settings; demo exercises/checks the system; verify_hpa records scaling; export_analytics extracts built JARs. |
| [tests/](../tests), [validate.yml](../.github/workflows/validate.yml) | Automated code and chart/startup checks. The full Docker rehearsal is manual/optional. GitHub Actions does **not** deploy AWS. |
| [requirements.txt](../requirements.txt), [requirements-dev.txt](../requirements-dev.txt), [pyproject.toml](../pyproject.toml) | Python dependencies and project/test-tool settings. |
| [load/k6.js](../load/k6.js) | Sends sustained traffic to prove two services add running copies under load. Prometheus measures, Grafana displays, and CloudWatch gathers AWS logs. |
| [docs/](.), [task_divison.txt](../task_divison.txt) | Instructions/design/evidence guidance, and the truthful record of who owns which assignment tasks. |

**Why not one folder per service?** Python services share code. Their `SERVICE`
setting selects each running copy's role. Separate folders are not required.

## 5. What should I edit or leave alone?

- **Read first:** this page, [start here](01-start-here.md), then the
  [Mac walkthrough](04-local-walkthrough.md). The [design](03-design.md) goes deeper.
- **Edit when instructed:** deployment settings copied from the Terraform
  examples, generated AWS chart values, and the contribution record.
- **Normally leave alone:** application source, templates and dependency pins
  unless making a specific, tested change.
- **Generated, not source:** `.venv` is installed Python packages;
  `analytics/target` contains built JARs; `artifacts` holds generated deployment
  files; `evidence` holds actual demo results. Their absence in a fresh clone is normal.
- **Never publish:** `.env`, private keys, actual `.tfvars` files or Terraform
  state. State records created resources and can contain secrets; keep it for
  later updates/cleanup. [`.gitignore`](../.gitignore) helps exclude these files.

One distinction to remember: **Terraform creates the cloud resources; Argo CD
keeps Kubernetes apps in sync with Git; GitHub Actions checks the code.**

Use your own **pay-as-you-go account**, not the Free-plan account that blocked
EMR. Plan for full usage costs and check permissions, budget and quotas before the
[AWS steps](05-aws-deployment.md), and read [cleanup](08-cleanup-and-cost.md).
