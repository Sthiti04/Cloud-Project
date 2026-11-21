# 8. Cost controls and complete cleanup

[Troubleshooting](07-troubleshooting.md) | Next: [viva and AI help](09-viva-and-ai-help.md)

**Read this before deploying; run cleanup when finished or abandoning an attempt.**
The previous attempt was reported cleaned up. Apply this checklist to **every
new attempt** in your own pay-as-you-go account, whether it succeeds or fails.
Verify that cleanup finished before creating the next stack.

Use the [AWS terminal setup](05-aws-deployment.md#in-every-aws-terminal), the same
project folder and the same protected local Terraform state as deployment.
Confirm your paid account ID before every apply/destroy.

## Budget first

Decide your spending ceiling and running period before
`allow_paid_resources = true`. That flag is **not a monetary cap**.
No AWS deployment was performed for this delivery.

Use [AWS Pricing Calculator](https://calculator.aws/) and current **Mumbai
ap-south-1** pricing. Do not rely on an old dollar estimate, free-tier promise or
credits without checking eligibility and the actual bill. For this walkthrough,
assume full pay-as-you-go charges. The Free-plan account blocked EMR; switching
accounts fixes that plan limitation, not the cost of running the stack.

### Estimate these components

| Component | Quantity/default | Main charge |
|---|---|---|
| EKS control plane | One, standard support | Cluster hours |
| EKS workers | Two t3.large, 30 GiB root each | EC2, EBS, possible burst-credit surplus |
| MSK | Two kafka.t3.small, 10 GiB each | Broker hours/storage |
| RDS PostgreSQL | One db.t4g.small, 20 GiB | Instance hours/storage/burst behavior |
| EMR | One m5.xlarge primary + one core, 32 GiB roots | **EC2 plus EMR surcharge**, EBS |
| ALB | One public HTTPS | LB hours, LCU, public IPv4 |
| NAT | One gateway/EIP | Gateway hours, processed data, public IPv4 |
| ZooKeeper EBS | Three encrypted 2 GiB gp3 volumes | Volume storage |
| S3 | Raw data/artifacts/checkpoints/archive | Requests/storage |
| DynamoDB | On-demand alert/inbox/outbox/window work | Read/write transactions and storage |
| SQS/Lambda | Actual requests/invocations | Usage |
| Logs/ECR/Secrets | Retention/images/secrets | Ingestion/storage/API charges |
| Transfer | Cross-AZ/internet/NAT where applicable | Processed/transferred bytes |

A ten-minute 90-RPS load produces about **54,000 raw objects**, plus Kafka,
SQL lookups and alert/analytics work. Retries increase this. Run only necessary
tests, one load Job at a time; avoid leaving it enabled unintentionally.

Foundation hours + runtime hours must both be counted. `enable_runtime=false`
removes Lambda/EMR but **EKS/MSK/RDS/NAT/ALB still charge**. EMR WAITING is not
free. Closing a terminal/laptop, stopping local Docker or deleting an application
pod does not stop AWS charges.

Use your account's billing/alert controls; alerts can lag and do
not automatically shut the project down. Do not create ad-hoc cloud
infrastructure outside IaC.

## Before cleanup

1. Agree teardown timing with the instructor: the required public URL/demo may
   need to remain available.
2. Save actual functional, HPA/k6, failover, storage/Flink and observability proof.
3. Keep a protected backup of both local Terraform states until cleanup is verified.
4. Confirm the exact account, region, project and current state.
5. Understand that all stored data is synthetic and intended for deletion.
   Do not use this procedure against real/shared patient data.

```zsh
aws sts get-caller-identity
kubectl config current-context
terraform -chdir=infra/aws state list
terraform -chdir=infra/gitops state list
```

Do not delete state, broad directories or other users' resources. A failed apply
still requires cleanup of whatever its state actually created.

## If the attempt failed before deployment finished

**Do not finish provisioning just to clean up.** A normal `terraform apply`
against an incomplete stack can create the missing paid resources.

1. Save the first error and inspect `terraform state list` in both roots.
   Missing state in a root you never applied is different from lost state:
   if a root was applied but its state is missing, stop and recover it.
2. If GitOps was created, destroy it using section 3 below while EKS still works.
   If it was never created, skip that section. There is no need to make the apps
   healthy before removing the Argo applications.
3. Skip the runtime-off normal apply. A reviewed **AWS destroy** removes any
   Lambda/EMR that actually exists along with the foundation.
4. If the project S3 bucket exists and has contents, it still needs permission
   to empty during destroy. Set `allow_delete_demo_data=true` in the same
   private AWS tfvars and preview **only that existing bucket**:

```zsh
terraform -chdir=infra/aws plan -target=aws_s3_bucket.data
```

   Proceed only if this changes the existing project's `force_destroy` setting,
   without creating/replacing resources. This targeted exception is for cleanup,
   not normal deployment. If the preview contains new resources or unrelated
   changes, stop and get help with the actual state.

```zsh
terraform -chdir=infra/aws apply -target=aws_s3_bucket.data
```

5. Follow sections **5-7** below: preview/destroy AWS, verify resources are gone
   and revoke the dedicated deploy key. If the bucket was never created, skip
   step 4 above. Don't run a broad apply to create it.

Keep `allow_paid_resources=true` while reviewing cleanup if its guard requires
it; it is not an instruction to create more resources. Keep state until deletion
and resource checks finish. If cleanup itself fails, use the failure table or
get help immediately rather than leaving the paid resources unattended.

## Recommended teardown order

This sequence is for a fully created stack. For a partial/failed attempt use
the section above instead.

Do one numbered section at a time. `plan` previews; `apply` makes the settings
change; `destroy` deletes resources. Read the proposed names and type `yes` only
when they belong to this project.

| Step | What should happen | Charges afterwards |
|---|---|---|
| 1 | Stop the load through Git | Infrastructure still bills |
| 2 | Remove Lambda and terminate EMR | Foundation still bills |
| 3 | Remove Argo-managed apps while EKS still works | Foundation still bills |
| 4 | Permit deletion of this project's machine-generated S3 data | Foundation still bills |
| 5 | Delete the foundation | Verify all resources are gone |
| 6-7 | Check leftovers/billing, remove the dedicated deploy key | Past usage remains payable |

**Do not stop after step 2.** Closing Terminal or turning off EMR is not complete
cleanup. If a step fails, keep the state files and use the failure table below.

### 1. Stop load through Git

Save k6 logs first. Set `loadTest.enabled: false` in the app AWS values,
review/commit/push and wait for Argo pruning. Stop local port-forwards.
Do not delete an active Job before saving evidence and then call the run complete.

### 2. Remove runtime with a reviewed AWS apply

In the **same ignored AWS tfvars**, set:

```hcl
enable_runtime = false
```

Leave approved `allow_paid_resources=true` and all foundation settings unchanged:

```zsh
terraform -chdir=infra/aws plan
terraform -chdir=infra/aws apply
```

Expected removals: Lambda/mapping, EMR and runtime artifact objects.
Check EMR reaches TERMINATED; no other project should be touched.
Foundation charges continue.

### 3. Remove GitOps-managed workloads before EKS/volumes

The root and child Applications have cascading finalizers. Keep the cluster,
Argo controller and AWS credentials working during deletion:

```zsh
terraform -chdir=infra/gitops plan -destroy
terraform -chdir=infra/gitops destroy
```

Review names first; approve manually. The root is removed before its dependency,
Argo CD, allowing child cleanup. It can take time while finalizers prune resources.

Verify no project application pods remain and ZooKeeper volumes detach:

```zsh
kubectl get pods,pvc -n s23
kubectl get applications -n argocd
```

Namespace/PVC objects can remain briefly. Inspect finalizers/events if deletion
stalls; do not blindly strip finalizers or destroy the cluster first.
Wait for volume attachments to disappear before the foundation destroy.

### 4. Explicitly allow deleting synthetic bucket contents

S3's `force_destroy` defaults to false. The nonempty project bucket intentionally
blocks accidental loss. For the agreed final cleanup, edit AWS tfvars:

```hcl
allow_delete_demo_data = true
enable_runtime         = false
```

Then persist that permission in state with a reviewed apply:

```zsh
terraform -chdir=infra/aws plan
terraform -chdir=infra/aws apply
```

This is permission for Terraform to empty **this exact project's synthetic
bucket** during destroy, not an instruction to recursively delete arbitrary S3.
Do not turn off the paid opt-in during these applies: its precondition would
block them.

### 5. Destroy the foundation

```zsh
terraform -chdir=infra/aws plan -destroy
terraform -chdir=infra/aws destroy
```

Review the account/resource names; manually approve. Expect deletion of the
complete project, including EKS/workers, MSK/RDS, NAT/EIP/ALB, EBS, DynamoDB/SQS,
S3, IAM, ECR images, secrets and log groups. Destruction can take many minutes.
Do not abandon a still-running destroy.

RDS skips final snapshots and backup retention is zero because data is
synthetic. ECR repositories permit deleting their demo images. Those defaults
are not suitable for real data.

### 6. Verify cleanup, not just a success message

```zsh
terraform -chdir=infra/aws state list
terraform -chdir=infra/gitops state list
```

Both should have no managed project resources; data-source remnants alone are
not billable resources. Check read-only console/API views for the **exact**
project-owned:

- EKS/worker instances and Auto Scaling group.
- EMR (TERMINATED, no running EC2 primary/core).
- MSK, RDS, ALB, NAT gateways/EIPs.
- The three captured EBS IDs and root volumes.
- S3 bucket, DynamoDB table, SQS/DLQ and ECR repositories.
- Secrets/log groups and any explicitly created snapshots.

Use Project tags/names and captured IDs. Do not use account-wide deletion scripts
or name-based process/resource deletion in a shared account.

Billing is delayed; review Cost Explorer/Billing later. Historical billed usage
does not disappear. A green destroy result is not a promise of zero current bill.
If a resource remains, resolve its actual dependency with the correct state/IaC.

### 7. Revoke the private deploy key and archive status

Remove the **dedicated S23 read-only deploy key** from GitHub after Argo is gone.
Do not revoke personal or another deployment's key.

Keep evidence/state backups protected according to institution/account policy.
Mark generated AWS values as historical; a redeploy must regenerate fresh
resource IDs/digests/certificate. The submitted public URL is now offline.
For another attempt, follow [the reset checklist](05-aws-deployment.md#0-prepare-a-new-attempt-after-cleanup)
including `allow_delete_demo_data=false` and `enable_runtime=false` before
the next foundation plan.
Never commit old state/private keys "for backup".

## If destruction fails

| Failure | Safe response |
|---|---|
| Nonempty S3 bucket | Confirm synthetic bucket; persist `allow_delete_demo_data=true`, then retry |
| EBS volume in use | Wait for pod/attachment teardown; inspect exact volume and CSI/finalizers |
| ENI/security group dependency | Wait for EKS/EMR/MSK/LB service cleanup; retry same state |
| GitOps finalizer stuck | Keep controller/cluster alive; inspect Argo operation and dependent resources |
| AccessDenied/expired SSO | Refresh approved session/permissions; retry, no root workaround |
| Partial state/resources | Preserve state and reconcile exact resources; do not start a second stack |

Do not "solve" a destroy failure by deleting Terraform state or turning off only
runtime and forgetting the foundation.

## Local cleanup is separate

From this Compose project only:

```zsh
docker compose down
# Only for intentional complete synthetic local-data reset:
docker compose down --volumes
```

No system prune, broad directory deletion or unrelated process killing. These
commands have no effect on the AWS bill.
