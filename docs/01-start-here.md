# 1. Start here

[Guide index](../README.md) | Next: [requirements and evidence](02-requirements-and-evidence.md)

If the files and cloud terms are unfamiliar, read
[What have we built?](00-project-explained.md) first. It explains the system and
file roles without a line-by-line code tour.

## What this project does

Three fake monitoring devices generate heart-rate readings. The system validates
each reading, archives it, detects demonstration threshold violations, delivers
an in-app operator notification, and records an acknowledgement or an overdue
escalation. Flink summarizes data in one-minute windows.

For the standard simulation, **12 machine-generated readings produce four
alerts**. The demo acknowledges one and leaves the others to become overdue.
Device/patient records and readings are examples, not real health information.
Do not enter real names, patient identifiers, vital signs, phone numbers or
email addresses.

The simplest path is to keep the defaults. Do not add a mobile app, ML model,
diagnosis, real SMS provider, extra cloud provider or custom ZooKeeper
implementation. None is required by the supplied rubric.

## Three checks before spending money

### A. Academic arrangement

The handout is for CS/SS G527, I Semester 2025-2026. It says "maximum four", but
also describes equal division of a-h, two tasks and two services per student, and
individual demonstration marks. That does not establish that an eight-service
solo implementation is automatically accepted.

Get these answers from the instructor, preferably in writing:

1. Is S23 formally allocated to this submission/group?
2. Is a solo submission with all eight services and tasks a-h allowed?
3. Is applying Apache ZooKeeper for election/fencing sufficient for "ZooKeeper
   system", rather than recreating ZooKeeper?
4. What are the actual Nalanda deadline and live demonstration date?
5. What AI assistance and attribution are permitted?
6. Must the public URL remain running between submission and demonstration?
7. Is pinned self-signed HTTPS acceptable, or is browser-trusted HTTPS required?

Only Sthiti Swain, 2025H1030055P, is currently identified.
[task_divison.txt](../task_divison.txt) records that situation and unassigned
slots. Do not add fictitious teammates or invent completed contributions.

### B. Your paid AWS account and budget

The stack includes EKS, two EC2 workers, MSK, RDS, an ALB, NAT, EMR and
storage/logging. Several charge while idle. Use your own **pay-as-you-go account**:
EMR was unavailable on the Free-plan account you tried. Budget for full usage,
not assumed credits or Free Tier coverage. Paid access still needs permissions
and sufficient quotas.

The previous paid-account attempt was cleaned up. For the next attempt, keep
your existing project folder and follow the AWS guide's redeployment checklist.
Reset the cleanup/runtime flags and regenerate all cloud-specific values.
Every attempt needs complete cleanup when finished or abandoned, successful or not.

**Until the actual account, spending limit and running period are approved, do
only local/offline steps.** Keep `allow_paid_resources = false`.
The [cost guide](08-cleanup-and-cost.md) explains estimates and cleanup.

The flag is an intentional opt-in, not a monetary cap or automatic shutdown.
Turning off Lambda/EMR alone does not stop the foundation's charges.

### C. Tools and account

Follow [local setup](04-local-walkthrough.md) first. Later, the AWS guide checks
permissions, region versions and approximately **12 spare ordinary EC2 vCPUs**.
A normal paid account can still have a low initial quota or missing permissions.

## Work order: one checkpoint at a time

For the actual commands, follow **[Mac preparation](04-local-walkthrough.md) ->
[deployment](05-aws-deployment.md) -> [demonstration](06-demonstration-and-observability.md)
-> [cleanup](08-cleanup-and-cost.md)**. Read one step at a time and continue only
when its stated result matches yours. The table below is a progress map, not
another set of commands.

Use **macOS zsh** in Terminal or VS Code; no Windows shell is needed. The
[local guide](04-local-walkthrough.md) covers both Apple Silicon and Intel.
Use its Docker build path and skip host Java/Maven unless you already want them.

| Checkpoint | Do this | Move on only when |
|---|---|---|
| 0 | Read this guide and the a-h matrix | You understand the live proof requirements |
| 1 | Install tools and run isolated tests | Python checks and Flink build pass |
| 2 | Run local Docker stack | Local eight-service smoke verifies |
| 3 | Confirm academic arrangement and budget | Topic, solo arrangement, paid account, deadline and spending are clear |
| 4 | AWS read-only preflight | Correct account/region, permissions, quota and versions |
| 5 | Terraform foundation | EKS/MSK/RDS/network/storage exist; runtime remains disabled |
| 6 | Images and Git values | Real ECR digests; both AWS values files are committed/pushed |
| 7 | Terraform Argo bootstrap | Private Git access works; child Applications are healthy |
| 8 | Terraform runtime | Lambda exists; EMR runs the actual Flink job |
| 9 | Functional demo | Notifications, ack, escalation and windows verify |
| 10 | HPA and ZooKeeper | Actual scale-out and replacement leadership are recorded |
| 11 | Submit and practice | Every a-h proof and truthful contribution record is complete |
| 12 | Coordinated teardown | Complete project removed; resource/billing checks reviewed |

Do not start EMR before Kafka topics exist. Do not confuse an offline Terraform
plan, a local container, or green unit tests with a deployed cloud requirement.

### Keep the required system; skip extra work

- No host Kafka, ZooKeeper, PostgreSQL, Flink, k6 or Kubernetes installation:
  Docker supplies the local stack; AWS supplies the required managed services.
- Build Flink once using Docker and export its three JARs. Do not also follow
  the optional host Java/Maven route.
- Optional invalid-input and transient-failure demonstrations are extra
  rehearsals, not extra services. The main smoke, HPA, ZooKeeper failover,
  storage, managed Flink, dashboard and all-service log evidence remain required.
  Retain the dispatcher's retry behavior and its tests.
- Keep the two Terraform roots and foundation/GitOps/runtime order: they prevent
  starting Flink before Kafka topics exist and keep deployment reproducible.
- Do not remove EKS, Lambda, managed Flink, Kafka, GitOps, ZooKeeper, the three
  storage products or observability. Removing these would miss explicit
  requirements or the chosen concept. Replacing managed Kafka with self-hosted
  Kafka might reduce service charges, but adds broker operations and is not the
  simpler beginner workflow.

An 8 GB Mac may struggle with the complete Docker stack. Use a reviewed,
successful isolated CI rehearsal if necessary; it does not replace AWS proof.
Private-repository Actions usage can also incur charges.

## Habits that prevent mistakes

- Open the terminal in **CC-Project**, not its parent.
- Activate the Python virtual environment in each new terminal.
- Check the AWS account and ap-south-1 before cloud commands.
- Prefer an approved SSO/role session; never use root credentials.
- Identify whether each command is local validation, read-only inspection,
  provisioning, or deletion before running it.
- Do not use automatic Terraform approval while learning.
- Keep the repository private; give Argo a dedicated read-only deploy key.
- Review Git status and staged files before committing.
- Keep `.env`, `.secrets/`, `artifacts/`, `evidence/`, private keys, `*.tfvars` and
  every Terraform state file out of Git. An ARN is not a password; state is.
- Do not share the full workbook: its group tab can contain other students'
  information. Original assignment documents are not copied into this repo.
- Take evidence from real runs. Never fill missing proof with invented logs.

## What Sthiti needs to understand

She does not need to become an AWS expert before starting, but must explain:

1. Why there are eight distinct application services.
2. Where REST, gRPC and messaging happen.
3. Why the dispatcher actually runs on Lambda in AWS.
4. What the three storage products hold.
5. How Kafka events become stateful Flink minute-window results.
6. How ZooKeeper elects a scheduling owner and replaces a failed owner.
7. How Git changes reach Kubernetes through Argo CD.
8. How actual CPU HPA scale-out is proved.
9. How to find failures and safely remove the stack.

Practice [viva answers](09-viva-and-ai-help.md) in her own words. AI assistance is
useful but cannot perform her individual demonstration for her.

## Supplied work versus remaining work

Implementation, tests, IaC, GitOps manifests and guides are supplied. Delivery
checks are documented in [validation status](10-validation-status.md).
No billable deployment or fabricated evidence is included. The student must
perform real local/cloud rehearsals before representing the assignment as done.
