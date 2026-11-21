# 6. Demonstrate the project and save the proof

[Deployment](05-aws-deployment.md) | [Requirements](02-requirements-and-evidence.md)
| Finish with: [cleanup](08-cleanup-and-cost.md)

This is a **follow-along checklist**, not a script to memorize. Do one section,
check the result, and save it before continuing. Use your **paid AWS account**,
Mumbai region and the same project folder used for deployment.

There is no separate patient website. You will show JSON results in Terminal,
Argo/Grafana in the browser, and resources/logs in the AWS console.
For explanations to say aloud, use [the component guide](11-components-and-viva.md).

## What you need to show

| Section | Simple question it answers | Assignment |
|---|---|---|
| 1-2 | Are the cloud apps and managed Flink actually running? | c/e |
| 3 | Do readings become alerts, notifications and summaries? | All eight services |
| 4 | Are three different cloud storage products used? | g |
| 5 | Are Lambda, REST, gRPC and Kafka actually used? | b/e |
| 6 | Does a Git change reach the running app? | a/d |
| 7 | Can we see metrics and logs from all eight services? | h |
| 8 | Does load make two services add copies? | c |
| 9 | Does a second manager take over after failure? | f |

Allow a separate rehearsal session. The load test alone takes **10 minutes**;
startup, two-minute escalation, window results and scale-down also take time.
Save genuine results for the presentation; don't try to rush all of this into
five minutes. Resources charge throughout, so agree a cleanup time.

## 1. Prepare the terminal and check readiness

Repeat [the AWS terminal setup](05-aws-deployment.md#in-every-aws-terminal).
Check the paid account ID before proceeding. Then:

```zsh
mkdir -p evidence
CLUSTER=$(python -c "import json; print(json.load(open('artifacts/deployment.json'))['cluster_name'])")
aws eks update-kubeconfig --name "$CLUSTER" --region ap-south-1
kubectl config current-context
kubectl get nodes
kubectl get applications -n argocd
kubectl get deployments,statefulsets,pods,hpa,pvc -n s23
```

**Check:** two `Ready` nodes, all Argo applications `Healthy`/`Synced`, six
available application Deployments, two Queue Manager copies, three ready
ZooKeeper pods and three `Bound` PVCs. Persistent errors mean stop and use
[troubleshooting](07-troubleshooting.md).

Keep `evidence/` private/ignored by Git. Save screenshots there with clear names,
but exclude passwords, tokens, keys and full Terraform state. A screenshot of
configuration alone does not prove the configured feature worked.

## 2. Check that Flink is running

In the **Mac terminal**:

```zsh
EMR_ID=$(python -c "import json; print(json.load(open('artifacts/deployment.json'))['emr_cluster_id'])")
aws emr describe-cluster --cluster-id "$EMR_ID" --region ap-south-1 \
  --query 'Cluster.Status'
aws emr list-steps --cluster-id "$EMR_ID" --region ap-south-1 \
  --query 'Steps[].[Name,Status.State]'
MASTER_ID=$(aws emr list-instances --cluster-id "$EMR_ID" \
  --instance-group-types MASTER --region ap-south-1 \
  --query 'Instances[0].Ec2InstanceId' --output text)
printf '%s\n' "$EMR_ID" "$MASTER_ID"
```

If the EMR ID is missing/null, return to deployment step 7. If a step failed,
stop and inspect that error. `WAITING` can describe an EMR cluster after job
submission; it does **not** by itself tell you Flink is running.

Use a browser connection so no Mac Session Manager plugin is needed:

1. AWS console -> **EC2 -> Instances**, in Mumbai.
2. Select the exact instance ID printed second above (the EMR primary).
3. Choose **Connect -> Session Manager -> Connect**.
4. In that **remote browser terminal**, not the Mac terminal, run:

```bash
sudo -u hadoop yarn application -list -appStates RUNNING
```

**Check:** the Flink application appears as `RUNNING`. Copy its actual
`application_...` ID and use it in the next command:

```bash
sudo -u hadoop yarn application -status REPLACE_WITH_ACTUAL_APPLICATION_ID
sudo systemctl status amazon-cloudwatch-agent --no-pager
```

**Save:** the cluster ID, application ID/name and `RUNNING` status in a screenshot
or `evidence/flink.txt`. Check the logging agent is active too.
Type `exit` in the remote terminal when done.

If Session Manager is unavailable, check session permissions and instance
connectivity with help; do not open public SSH ports or start a second Flink job.
A completed EMR submission step is not a substitute for this check.

## 3. Run the main demonstration once

Return to the **Mac terminal**. Do not run sustained load at the same time.

### Show the public URL

```zsh
PUBLIC_URL=$(python -c "import json; print(json.load(open('artifacts/deployment.json'))['public_url'])")
printf '%s\n' "$PUBLIC_URL"
curl --fail --cacert artifacts/demo-ca.pem "$PUBLIC_URL/"
```

**Check:** JSON includes `synthetic_only: true`. Save the URL and successful
response as `evidence/public-url.txt` or a screenshot.
Explain that HTTPS uses the supplied self-signed certificate; a normal browser
may warn. Do not bypass verification with `curl -k`.

### Run the helper

```zsh
python -m tools.demo --aws smoke --timeout 420
```

This helper performs the sequence for you. Let it finish; it waits for
notifications, roughly two-minute escalation and Flink window results.

**Check for all of these:**

- `verified: true`, `generated: 12`, `alert_count: 4`.
- Four stored notifications for `demo-operator` (not real SMS/email).
- One alert acknowledged and at least one unacknowledged alert escalated.
- Analytics windows with reading/delivery/acknowledgement/escalation counts.

**Save:** the helper writes `evidence/smoke-aws.json` only on success. Preserve
this first successful run before the later failover test overwrites it:

```zsh
cp evidence/smoke-aws.json evidence/smoke-aws-first.json
python -m tools.demo --aws status
```

Show `ACKNOWLEDGED`, `ESCALATED`, notification entries and
`average_ack_delay_ms` in the output. Heartbeat readings sent while waiting can
make window counts greater than 12; that is expected.

If the helper errors, do not use an old JSON file as proof of this attempt.
Check the run ID/time and resolve the error before retrying. Avoid rapid repeated
smokes in the same minute: windows group by device/minute, not smoke run ID.

**Say:** "A simulated abnormal reading becomes an alert. Lambda writes a real
demo inbox entry. We acknowledge one; an overdue one escalates. Flink summarizes
the readings and alert events."

## 4. Show the three storage products

Use the successful smoke from section 3. These commands inspect its actual data.

### S3: raw reading files

```zsh
BUCKET=$(python -c "import json; print(json.load(open('artifacts/deployment.json'))['bucket'])")
TABLE=$(python -c "import json; print(json.load(open('artifacts/deployment.json'))['environment']['ALERT_TABLE'])")
RUN_ID=$(python -c "import json; print(json.load(open('evidence/smoke-aws.json'))['run_id'])")
aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "readings/$RUN_ID-" \
  --max-keys 12 --region ap-south-1 --query 'Contents[].[Key,Size]'
aws s3api get-object --bucket "$BUCKET" --key "readings/$RUN_ID-0.json" \
  --region ap-south-1 evidence/raw-example.json
```

**Check:** the 12 raw reading JSON objects are listed. Open the downloaded
`evidence/raw-example.json` in VS Code.

### RDS: device records

Copy this whole line. It asks the running Registry to read its database using
its existing secure connection; you do not need a database password:

```zsh
kubectl exec -n s23 deployment/device-registry -- python -c "from s23.registry import connection; from s23.settings import Settings; c=connection(Settings.from_env()); print(c.execute('SELECT device_id, patient_id, active FROM devices ORDER BY device_id').fetchall()); c.close()"
```

**Check:** three example device/patient rows. In AWS -> RDS, show the project's
private PostgreSQL instance too; the output is not an in-memory table.

### DynamoDB: alerts, inbox and summaries

```zsh
aws dynamodb get-item --table-name "$TABLE" --consistent-read \
  --key "{\"pk\":{\"S\":\"alert#$RUN_ID-0\"}}" --region ap-south-1
```

**Check:** an alert record for the same run. In AWS -> DynamoDB -> Explore items,
select the table printed by `printf '%s\n' "$TABLE"` and inspect records starting
`notification#` and `result#`. Recently added indexed records may take a moment
to appear. Do not edit or delete them.

**Save:** S3 list/example, RDS rows and DynamoDB records in `evidence/storage.txt`
or screenshots. **Say:** "S3 stores files, RDS stores device mappings, DynamoDB
stores changing alert state and results." Three tables in one product would not
meet this requirement.

## 5. Show the communication and Lambda

### REST and gRPC

The public HTTP call and smoke demonstrate REST. For the internal gRPC calls:

```zsh
kubectl exec -n s23 deployment/device-registry -- python -c "import requests; print(requests.get('http://127.0.0.1:8080/metrics',timeout=5).text)"
```

**Check:** `s23_grpc_requests_total` has successful `GetDevice` calls.
**Say:** "Ingestion asks Registry to verify the device using gRPC before saving
the reading." The message format is in [devices.proto](../proto/devices.proto).

### Kafka and Flink results

Copy the whole line to inspect the separate results topic:

```zsh
kubectl exec -n s23 deployment/acknowledgement-service -- python -c "from s23.settings import Settings; from s23.broker import kafka_config; from confluent_kafka.admin import AdminClient; s=Settings.from_env(); t=AdminClient(kafka_config(s.brokers,s.mode,s.region)).list_topics(topic='clinical-results',timeout=10).topics['clinical-results']; print({'topic':t.topic,'partitions':len(t.partitions),'error':str(t.error)})"
```

**Check:** `clinical-results`, six partitions, error `None`. Combine this with
the actual windows from section 3 and running Flink from section 2.
**Say:** "`vitals` feeds rules, `clinical-events` feeds Flink's stateful
one-minute windows, and `clinical-results` carries summaries back."
Do not start another consumer using an application's consumer group.

### Lambda's SQS trigger

```zsh
FUNCTION=$(python -c "import json; print(json.load(open('artifacts/deployment.json'))['lambda_function'])")
aws lambda get-function-configuration --function-name "$FUNCTION" \
  --region ap-south-1 --query '{State:State,Update:LastUpdateStatus}'
aws lambda list-event-source-mappings --function-name "$FUNCTION" \
  --region ap-south-1 --query 'EventSourceMappings[].[EventSourceArn,State]'
```

**Check:** Lambda `Active`/`Successful`; the project's SQS mapping is `Enabled`.
In AWS -> Lambda -> this function, show the SQS trigger and recent invocation
logs alongside the four inbox messages from the smoke.

**Save:** gRPC counter, topic output, trigger and delivery logs as screenshots.
For extra practice only, [transient-retry instructions](07-troubleshooting.md#optional-cloud-retry-practice)
are available; don't add an intentional failure to the first walkthrough.

## 6. Show a Git change reaching Kubernetes

Open Argo using [deployment step 6](05-aws-deployment.md#open-argo-on-your-mac).
In VS Code open `deploy/app/values-aws.yaml`. Add just this one key **inside the
existing `environment:` section**, with the same indentation as its other keys:

```yaml
  DEMO_REVISION: gitops-demo-1
```

Do not replace the section or add a second `environment:` heading. On a repeat,
use `gitops-demo-2`, etc. Then:

```zsh
git diff -- deploy/app/values-aws.yaml
git add deploy/app/values-aws.yaml
git diff --cached
git commit -m "Show GitOps" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin main
git rev-parse HEAD
```

Wait for Argo to read Git. Compare the commit above with:

```zsh
kubectl get application s23-application -n argocd \
  -o jsonpath='{.status.sync.revision}{"\n"}'
kubectl rollout status deployment/vital-ingestion -n s23 --timeout=300s
kubectl get applications -n argocd
kubectl get deployments -n s23
```

**Check:** matching Git revision, `Healthy`/`Synced`, all six Deployments available.
In Argo, show the replacement pods/new environment checksum. Wait for recovery
before more tests.

**Save:** commit/revision and healthy rollout screenshot. For IaC, show the
Terraform files and resource names from `terraform -chdir=infra/aws state list`,
alongside matching AWS resources. Never display full state.
**Say:** "Terraform creates the infrastructure; Argo deploys app changes from
Git. I did not deploy services with `kubectl apply`."

## 7. Open the dashboard and collect all-service logs

If this project's local Docker rehearsal is running, stop it with
`docker compose down` from this folder first. It uses the same Grafana port.
This does **not** stop AWS or its bill.

In a **second Mac terminal**, repeat the AWS terminal setup, then:

```zsh
kubectl -n observability port-forward svc/s23-observability-grafana 3000:80
```

Leave it running. In the **main terminal**, get the password privately:

```zsh
kubectl -n observability get secret s23-grafana-admin \
  -o jsonpath='{.data.admin-password}' | \
  python -c "import base64; import sys; print(base64.b64decode(sys.stdin.buffer.read(), validate=True).decode())"
```

Open `http://127.0.0.1:3000`, username `admin`. Open **S23 Synthetic Monitoring**
and choose the last 15-30 minutes. Never screenshot the password.

**Save real data**, not empty panels:

- Requests per second, server-error fraction and p95 response time.
- Two Ready nodes, application replicas and exactly one queue leader.
- gRPC/processed events, Lambda invocations and Flink records received.
- CPU/replica changes **during the load test in section 8**.

Lambda's failed-record metric is `s23_notifications_failed_records_sum`;
an invocation can succeed while an individual record needs retry.
CloudWatch-derived panels may lag a minute or two. If targets/metrics are
missing, use [observability troubleshooting](07-troubleshooting.md#observability-gaps).

### CloudWatch logs: all eight roles

```zsh
PROJECT=$(python -c "import json; print(json.load(open('artifacts/deployment.json'))['project'])")
aws logs tail "/s23/$PROJECT/eks" --since 30m --region ap-south-1
aws logs tail "/aws/lambda/$PROJECT-dispatcher" --since 30m --region ap-south-1
aws logs tail "/s23/$PROJECT/analytics" --since 30m --region ap-south-1
```

You can also use AWS -> CloudWatch -> Log groups with those exact names.
For the EKS group, filter streams/records by service/pod metadata.

Check off each role in your screenshots/notes:

- [ ] Patient Simulator
- [ ] Device Registry
- [ ] Vital Ingestion
- [ ] Alert Rule Engine
- [ ] Alert Queue Manager
- [ ] Acknowledgement Service
- [ ] Lambda Notification Dispatcher
- [ ] Clinical Analytics: actual Flink/YARN output, including `analytics_window`

An idle role may show `service_started`; use its safe demo action if more output
is needed. An empty analytics group does not pass: inspect the EMR logging agent
and real log paths using the troubleshooting guide.
Save captures in `evidence/observability/`. Logs for one service are not enough.

## 8. Show two services scaling under load

**Use two main working terminals**, plus the Grafana forwarding terminal if open.
This test adds traffic and usage costs. Do not run multiple load jobs or smokes.

### A. Start the observer before the load

In **Terminal A** (with AWS setup complete):

```zsh
python -m tools.verify_hpa --timeout 900
```

Wait for **"Recorded both HPAs at one ready replica"**.
Leave it running. If it never appears, stop old load through Git and wait for
natural scale-down (at least five minutes). Do not force replicas to one.

### B. Turn on the load through Git

In VS Code, edit the existing `loadTest` section in `deploy/app/values-aws.yaml`.
If absent, add it once at the top level. Do not duplicate it:

```yaml
loadTest:
  enabled: true
  runId: hpa-001
  rate: 90
```

Use a fresh ID each attempt (`hpa-002`, etc.); replace `hpa-001` in the commands
below to match. In **Terminal B**, review and publish:

```zsh
git diff -- deploy/app/values-aws.yaml
git add deploy/app/values-aws.yaml
git diff --cached
git commit -m "Run load test" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin main
```

Wait for Argo to sync that revision, then:

```zsh
kubectl get job load-test-hpa-001 -n s23
kubectl logs -n s23 job/load-test-hpa-001 -f
```

If the Job is not found yet, wait for Argo; do not create it yourself.
It sends real readings for **10 minutes at 90 requests/second**, with 1% abnormal.
Watch Grafana's CPU and replicas while it runs.

### C. Save both results

After the load finishes:

```zsh
kubectl wait -n s23 --for=condition=complete job/load-test-hpa-001 --timeout=900s
kubectl logs -n s23 job/load-test-hpa-001 > evidence/k6.txt
```

**Pass only if both are true:**

1. Terminal A succeeded; `evidence/hpa.json` has `verified: true`,
   `baseline_seen: true`, and both Ingestion/Registry reached at least two ready
   copies from one.
2. The full k6 Job completed successfully: failure rate <5%, p95 <2000ms,
   checks >95%, zero dropped iterations.

The observer can finish early; still let k6 complete all ten minutes. If either
fails, keep the failed output, fix the cause and repeat with a fresh run ID.
Do not reduce pass thresholds just to obtain a green result.

### D. Turn the load off

**Save the Job logs first.** Set only `loadTest.enabled: false`, then review,
commit and push the same file as above (message: `Stop load test`).
Argo removes the Job. Let both HPAs return to one naturally before section 9.

## 9. Show ZooKeeper takeover

In the Mac terminal, query both Queue Manager pods:

```zsh
for pod in $(kubectl get pods -n s23 -l app=alert-queue-manager \
  -o jsonpath='{.items[*].metadata.name}'); do
  printf '%s\n' "$pod"
  kubectl exec -n s23 "$pod" -- python -c "import requests; print(requests.get('http://127.0.0.1:8080/leader',timeout=5).json())"
done
kubectl exec -n s23 zookeeper-0 -- \
  zkCli.sh -server 127.0.0.1:2181 ls /s23/escalation
```

**Check:** exactly one `leader: true` with an integer term (zero is valid), one
follower, and two candidate entries in ZooKeeper.
Save the pod names/terms as `evidence/zookeeper-before.txt` or a screenshot.

1. In Argo's application resource tree, find the exact **leader Pod** above.
2. Delete **only that Pod** to simulate failure. Do not delete its Deployment,
   ZooKeeper, storage volumes, worker nodes or namespace.
3. Repeat the same queries. Wait for the surviving manager to become leader
   with a higher term and the replacement pod to rejoin.
4. Save the new names/terms as `evidence/zookeeper-after.txt`, then run:

```zsh
kubectl logs -n s23 -l app=alert-queue-manager --prefix --tail=100
python -m tools.demo --aws smoke --timeout 420
```

After that smoke succeeds:

```zsh
cp evidence/smoke-aws.json evidence/smoke-aws-after-failover.json
```

**Check:** different leader/higher term, `queue_leadership` logs, and another
successful smoke showing continued notification/escalation.
**Say:** "ZooKeeper chooses one scheduling owner. When its session goes away,
another takes over. Increasing terms and DynamoDB checks reject stale work."
Deleting a Pod here simulates failure; app configuration remains Git-managed.

## 10. Finish without leaving a bill running

- Check every requirement in [the evidence matrix](02-requirements-and-evidence.md).
- Keep real screenshots/reports; never fill missing results with sample output.
- Update [task_divison.txt](../task_divison.txt) with work actually performed.
- Practice explaining the flow using [the viva companion](11-components-and-viva.md).
- Agree whether the public URL must stay live for assessment.
- When allowed, follow [all cleanup steps](08-cleanup-and-cost.md), not just
  switching off EMR or closing the laptop.
