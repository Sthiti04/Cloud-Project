# 9. Understand the project and use AI safely

[Cleanup/cost](08-cleanup-and-cost.md) | Next: [validation status](10-validation-status.md)

The handout reserves 12 marks for individual contribution. A repository that
someone else/AI prepared is not proof that the student performed or understands
the work. Practice the real commands and explain the observed outputs honestly.

For step-by-step explanations of all eight services and their supporting
technology, read [Components and viva](11-components-and-viva.md). It includes a
five-minute presentation outline; this page is the shorter practice checklist.

## One-minute explanation

"S23 monitors only simulated heart-rate readings. Six Python services run on
EKS, an SQS-triggered Lambda delivers durable in-app notifications, and Flink
on EMR creates stateful minute-window results. Device validation uses protobuf
gRPC; orchestration uses REST; event flow uses Kafka and SQS. S3 archives raw
readings, RDS stores device metadata, and DynamoDB stores alert/inbox/results
state. ZooKeeper elects one of two scheduling managers, and DynamoDB fencing
rejects an old owner. Terraform provisions infrastructure; Argo CD tracks Git
for Kubernetes; Prometheus/Grafana and CloudWatch provide observability."

Say this in her own words, not as a memorized claim that everything is verified.

## Questions and short answers

| Question | Answer to understand |
|---|---|
| Why exactly eight services? | They match S23's eight responsibilities; helpers don't count |
| Why six EKS services instead of eight? | Dispatcher is Lambda; Analytics is managed EMR/Flink |
| Is one image still microservices? | Shared code/image, but separate role processes/Deployments/identities |
| What is a managed service? | AWS manages part of the platform; application correctness remains ours |
| What makes Lambda serverless? | No dispatcher VM/pod provisioning; SQS invokes the function |
| What is asynchronous here? | Queue/event producers need not wait for notification or window results |
| What does delivery mean? | A durable demo-operator inbox message, not real SMS/email |
| How is gRPC real? | Protobuf GetDevice method on HTTP/2 gRPC, not a REST label |
| What are the REST calls? | Ingestion gateway/simulator, rules -> manager, ack/escalation |
| Why Kafka and SQS? | Kafka streams domain/analytics events; SQS drives Lambda retryable delivery |
| Why three storage products? | Raw object data, relational registry, semi-structured transactional state |
| What does stateless mean? | App replicas keep durable business data outside the process |
| What is an HPA? | Kubernetes adjusts pod replicas from measured resource utilization |
| Why these two HPAs? | Every reading exercises ingestion and registry; both can get real load |
| Does more YAML replicas prove scaling? | No; capture baseline then real ready scale-out under sustained load |
| Why CPU requests matter? | Utilization is usage relative to requested CPU; no request means no valid target |
| Why headless gRPC discovery? | Resolver sees pod addresses; round-robin can use scaled registry replicas |
| What does GitOps track? | Git's desired manifests/config; Argo reconciles the cluster |
| Why not kubectl apply? | The assignment forbids direct service deployment; use Git/Argo |
| What does ZooKeeper coordinate? | Exactly one manager owns scheduling/outbox/escalation work |
| Why ephemeral-sequential nodes? | Session-bound membership plus ordered candidates for ownership |
| What happens when leader fails? | Session/candidate disappears; next candidate becomes owner |
| What is fencing? | Durable term check rejects stale-owner dispatch transactions |
| Why alert versions too? | They reject stale/duplicate queued deliveries and concurrent writes |
| What is event time? | Timestamp carried by the event, not the worker's processing wall clock |
| What is a watermark? | Estimated progress allowing bounded out-of-order window completion |
| Why send tick readings? | Idle streams otherwise may not advance event time enough to close windows |
| What is stateful Flink? | Keyed dedup/window state survives recovery via checkpoints |
| Input/output topics? | clinical-events in; separate clinical-results out |
| Exactly-once delivery? | Not claimed across external products; bounded dedup/idempotent transitions |
| What is the outbox? | Transition + analytics event committed together, then asynchronously published |
| Why may outbox duplicate? | Crash between Kafka publication and deleting its persisted event |
| Why self-signed HTTPS? | Avoid domain dependency; supplied client pins matching cert; disclose trust limit |
| Does runtime false stop AWS cost? | No; foundation charges remain until complete teardown |

## Trace one alert on paper

Use an actual smoke ID, not invented evidence:

1. Simulator creates reading `run-0` for a seeded device.
2. gRPC registry confirms active patient/device mapping.
3. S3 retains raw JSON; Kafka receives reading/clinical events.
4. Rule engine sees abnormal heart rate and creates deterministic-ID alert.
5. Current manager claims it with a version and leadership term, then sends SQS.
6. Lambda atomically commits delivered state, inbox message and clinical outbox.
7. Manager publishes the outbox to Kafka.
8. Receipt becomes ACKNOWLEDGED, or overdue becomes ESCALATED.
9. Flink's device-keyed window summarizes events and publishes the result.
10. Results worker stores it in DynamoDB; the public API retrieves it.

Also trace a first-attempt transient failure, a duplicate queue delivery and a
manager failover. Explain what is retried and what prevents state corruption.

## What to practice directly

- Open architecture and point to the eight services/three storage products.
- Run a successful smoke; locate its exact alerts/messages/windows.
- Show real gRPC and Kafka/Lambda activity.
- Show actual Git revision/pod rollout.
- Run a complete HPA proof/load and interpret both reports.
- Demonstrate one-manager failure and new ownership.
- Find a real application error in centralized logs.
- Explain and execute only approved cleanup of this project.

Keep [the evidence checklist](02-requirements-and-evidence.md) and actual
[contribution record](../task_divison.txt) consistent. Instructor-approved solo
ownership does not remove the individual understanding requirement.

## AI-use rules

Confirm the institution's policy. Use only approved AI tools and non-sensitive
assignment material you are authorized to share. Do not upload confidential
workplace/private third-party code, real patient information, the full student
workbook, credentials, state, deploy private keys or unredacted logs.

AI can explain an error, propose a focused test/fix, or help interpret a
sanitized result. It cannot certify that a command ran, approve the budget,
invent teammates or answer the student's viva for her.

### Safe troubleshooting prompt

```text
This is the S23 synthetic assignment, not a medical system.
I am in CC-Project and using [local Docker / approved AWS phase].
My workstation is macOS with zsh; uname -m reports [arm64 / x86_64].
Give me macOS/zsh commands; distinguish any remote EMR/Linux commands.
The first sanitized error is: [exact error without credentials].
The failing command was: [command with sensitive values replaced].
Relevant file and line: [specific assignment file].
I actually tried: [real actions and observed results].

Explain the cause first. Make only the related fix and a failing-first test.
Preserve the eight services, REST/gRPC/messaging, Lambda, EMR/Flink/Kafka,
ZooKeeper, three storage products, GitOps and the two CPU HPAs.
Do not deploy AWS, commit/push, delete resources, disable TLS or weaken load
thresholds without my explicit approval. Do not fabricate execution evidence.
Tell me the targeted command that verifies the fix.
```

Only provide code snippets to an approved tool when that material is authorized
and non-sensitive. The prompt is a template, not an instruction to share secrets.

### Safe explanation prompt

```text
Explain [one named service or concept] using this synthetic assignment.
Show its input, output, storage, failure behavior and the exact demo evidence.
Use simple language. Ask me a short comprehension question afterwards.
Do not change code or claim any unexecuted deployment/test result.
```

### Before accepting an AI fix

1. Does it address the actual first error?
2. Does it preserve the a-h requirements and synthetic-only scope?
3. Does it add/keep a meaningful isolated failing-first test?
4. Did the targeted test/type/lint/build check really pass?
5. Is the diff small/understandable and free of secrets?
6. Is a required live test still pending?
7. Has documentation/actual evidence been updated truthfully?

Never accept "remove Flink", "use only local Docker", "hardcode credentials",
"disable TLS", "kubectl scale to three" or "edit a success JSON" as a way to
meet this rubric.

## Honest attribution

Update actual contribution dates/actions after performing them. Acknowledge AI
assistance as permitted by policy; do not claim independent authorship or live
proof that did not happen. Keep members 2-4 unassigned unless real teammates
join and agree to the work.
