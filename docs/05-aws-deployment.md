# 5. Put the project on AWS, one step at a time

[Mac preparation](04-local-walkthrough.md) | Next: [demonstration](06-demonstration-and-observability.md)

**Use your own normal, pay-as-you-go AWS account for this walkthrough.**
EMR was blocked on the Free-plan account you tried. That was an account-plan
restriction, not something to fix by changing the Flink code.
AWS distinguishes the restricted **Free account plan** from the **Paid account
plan**; having some Free Tier allowances is not the same as having a Free plan.
See [AWS's plan explanation](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html).
Paid access still needs the right permissions, quotas and available services.

**Budget as though you will pay the full usage cost.** Decide your spending limit
and cleanup time using [the cost guide](08-cleanup-and-cost.md) before starting.
Neither this guide nor `allow_paid_resources` caps the bill. We have not deployed
this in your account or verified your account's access.

## The route

| Step | What you are doing | Creates AWS charges? |
|---|---|---|
| 0-2 | Choose the right folder/account and check access | No project resources created |
| 3 | Terraform creates the network, databases and Kubernetes | **Yes, even while idle** |
| 4-5 | Package the code and publish its settings | Existing resources keep charging |
| 6 | Argo CD starts the Kubernetes apps from Git | Existing resources keep charging |
| 7 | Add Lambda and the EMR/Flink computers | **More charges** |
| 8 | Check the public URL, then demonstrate | Resources keep charging until cleanup |

Use one Mac zsh terminal for the main steps. **Copy one command box at a time.**
Wait for it to finish and read **Continue when** before moving on.
Replace text starting `REPLACE_` with your real value; do not run it unchanged.
If a command fails, stop at that step. Do not create replacements in the console.

## 0. Prepare a new attempt after cleanup

The previous paid-account attempt has been cleaned up. **Do not use the
existing-stack resync instructions against that deleted cluster.** Start the
deployment sequence again in the same `CC-Project` folder; no second clone,
account switch or Terraform state deletion is needed.

Before creating anything:

1. Select the paid-account profile from step 1 and verify its account ID.
2. Confirm both Terraform roots have no managed project resources left and
   check the exact AWS resources are gone using
   [cleanup verification](08-cleanup-and-cost.md#6-verify-cleanup-not-just-a-success-message).
   Keep the post-destroy state and protected backups; if cleanup is incomplete,
   finish it before another deployment.
3. Check `git status --short`. If there are edits, preserve/review them first.
   With a clean working tree on `main`, run `git pull --ff-only origin main`.
   Stop on conflicts; never force-reset your own deployment changes.
4. Treat the old generated AWS values, metadata, certificates, image addresses
   and screenshots as **historical**, not current configuration or proof.

Finish [Mac preparation](04-local-walkthrough.md), including the Python environment
and Flink build/export. If a step already passed in this folder, do not repeat its
installation just to start this guide.

**Continue when:** you are in the project folder, the build passed, and the local
smoke (or a reviewed full CI smoke for this code) passed. Fast/default CI alone
is not a full rehearsal. The next step signs into the same paid account.

**Each attempt is paid, even when it fails.** Plan a cleanup time before applying.
If blocked and stopping work, follow [cleanup after an unsuccessful attempt](08-cleanup-and-cost.md#if-the-attempt-failed-before-deployment-finished);
do not leave the foundation running while waiting for help.

## 1. Sign the Mac into the paid account

You need AWS CLI **v2** and kubectl for EKS **1.35** (within one minor version).
Use the macOS downloads for your Apple Silicon/Intel Mac:
[AWS CLI installation](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
and [kubectl installation](https://docs.aws.amazon.com/eks/latest/userguide/install-kubectl.html).
Do not use Linux downloads.

```zsh
aws --version
kubectl version --client
```

A **profile** is a locally saved sign-in configuration. Use the name `s23-paid`
for this account so it is easy to distinguish from the previous one.
Configure it **once**, using the sign-in method you actually have:

- **Existing IAM Identity Center/SSO access:** run `aws configure sso --profile
  s23-paid`, using the start URL/region/account/role supplied by its administrator.
- **An approved IAM user's CLI credentials:** run `aws configure --profile
  s23-paid` and enter them privately. Choose `ap-south-1` and `json` when asked.
  This does not create a user or grant permissions.
- **Neither is set up:** get help setting up a non-root deployment identity with
  the permissions listed in step 2. Do not use root keys or guess SSO values.

### In every AWS terminal

First use the [Mac new-terminal setup](04-local-walkthrough.md#in-every-new-workstation-terminal),
with your actual **CC-Project** folder. Then:

```zsh
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
export AWS_PROFILE=s23-paid
export AWS_REGION=ap-south-1
export AWS_DEFAULT_REGION=ap-south-1
export AWS_PAGER=""
```

The `unset` line removes credential overrides from this terminal, not saved
profiles. **Only if you chose SSO**, also run:

```zsh
aws sso login --profile "$AWS_PROFILE"
```

Now check:

```zsh
aws sts get-caller-identity
```

**Continue when:** `Account` is your paid account's 12-digit ID, matching the AWS
console account menu. Select **Mumbai (ap-south-1)** in the console too.
If it is the old account, root, or says AccessDenied, stop. Recheck after changing
profiles and before every apply/destroy. Never share keys or state in a screenshot.

## 2. Gather three values and check that AWS can run the project

Write these in a private note; you will paste them into one settings file:

| Value | How to get it |
|---|---|
| Account ID | The `Account` result above; used to check you are in the right account. |
| Deployment identity's **IAM ARN** | IAM console -> Users or Roles -> the identity you use -> copy ARN. For SSO, ask for the exact IAM role ARN including its path. |
| Current public IPv4 | Run the command below, then add `/32` to the returned address. |

```zsh
curl --fail https://checkip.amazonaws.com
```

IAM ARN example: `arn:aws:iam::123456789012:role/DeploymentRole`.
An `arn:aws:sts::...:assumed-role/...` sign-in result is **not** an IAM ARN;
do not edit that string to guess the correct one.
Use your public IPv4, not `192.168...` and never `0.0.0.0/0`.

### Permissions and capacity: check before spending

The deployment identity needs access to VPC/EC2, EKS, IAM/pass-role, ECR, RDS,
MSK, EMR, S3, DynamoDB, SQS, Lambda, ACM, Secrets Manager and CloudWatch logs.
Your student identity also needs EKS access, read access to the project's secrets,
and Session Manager access to inspect the EMR machines during the demonstration.
Paying for the account does not grant those permissions.

```zsh
aws service-quotas get-service-quota --service-code ec2 \
  --quota-code L-1216C47A --region ap-south-1 \
  --query 'Quota.Value' --output text
aws ec2 describe-instances --region ap-south-1 \
  --filters Name=instance-state-name,Values=pending,running \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType]' --output table
```

You need about **12 spare ordinary On-Demand EC2 vCPUs**: four for EKS and eight
for EMR. The quota number is the total, not the unused amount. If it is below 12,
or other machines consume that allowance, obtain a quota increase first.
Check service-specific EKS/MSK/EMR quotas too.

Check the versions the project actually uses:

```zsh
aws eks describe-cluster-versions --region ap-south-1 \
  --query "clusterVersions[?clusterVersion=='1.35']"
aws eks describe-addon-versions --region ap-south-1 --kubernetes-version 1.35 \
  --query 'addons[].addonName'
aws kafka list-kafka-versions --region ap-south-1 \
  --query "KafkaVersions[?Version=='3.9.x']"
aws emr list-release-labels --region ap-south-1 --filters Application=Flink \
  --query "ReleaseLabels[?@=='emr-7.14.0']"
```

**Continue when:** EKS 1.35 is in standard support, its add-ons are listed, Kafka
3.9.x is active and `emr-7.14.0` appears. Also confirm EMR opens without the old
Free-plan restriction in this paid account. These read-only checks do not prove
every create permission; errors during deployment still need attention.
Empty results, account restrictions or denied actions mean **stop**, not choose
random replacement versions. An unknown CLI command can mean the CLI is old.

## 3. Create the foundation -- BILLING STARTS HERE

Terraform reads all `.tf` files together. You edit **only the private settings
file** below, not each infrastructure file.

First deployment only (skip this copy if the private file already exists):

```zsh
umask 077
cp infra/aws/terraform.tfvars.example infra/aws/terraform.tfvars
```

Open `infra/aws/terraform.tfvars` in VS Code. Keep the example settings and fill
in the IP and IAM ARN. After deciding your budget and cleanup time, it should be:

```hcl
region                 = "ap-south-1"
project                = "s23-demo"
admin_cidr             = "REPLACE_CURRENT_PUBLIC_IPV4/32"
admin_principal_arn     = "REPLACE_ACTUAL_IAM_USER_OR_ROLE_ARN"
allow_paid_resources   = true
allow_delete_demo_data = false
enable_runtime         = false
lambda_image_uri       = ""
fail_first_delivery    = false
```

**After cleanup, explicitly reset** `allow_delete_demo_data` to `false`,
`enable_runtime` to `false`, `lambda_image_uri` to `""`, and `fail_first_delivery`
to `false`. Keep the correct paid-account IAM ARN, and refresh your public IP.
Do not leave the old runtime image or the deletion opt-in enabled.

Keep the same project name throughout. In a shared account, agree on an unused
name first. `true` permits paid resources; it does not limit their cost.

```zsh
terraform -chdir=infra/aws init
terraform -chdir=infra/aws validate
terraform -chdir=infra/aws plan
```

`init` downloads providers, `validate` checks configuration, and `plan` previews
changes. Check the region/names/sizes. **No EMR cluster or Lambda yet.**
If a fresh deployment proposes destroying/replacing anything, stop.

After reviewing the plan and checking the account:

```zsh
aws sts get-caller-identity
terraform -chdir=infra/aws apply
```

Read the plan again and type `yes` only when correct. This can take tens of
minutes. Do not start a second apply while the first is running.

**Continue when:** Terraform says `Apply complete!`. This has created the network,
EKS with two workers, databases, Kafka, storage, queues, image repositories and
public load balancer. The public API is not ready until step 6.
If apply fails, preserve `infra/aws/terraform.tfstate`: partial resources may
already cost money. Fix the first error or use cleanup; do not start over elsewhere.
Keep encrypted backups of both Terraform states and never put them in Git.

## 4. Upload the two packaged programs

Keep this terminal open through step 7. The uppercase variables below hold
addresses for later commands; they are not extra files you need to create.

```zsh
mkdir -p artifacts
terraform -chdir=infra/aws output -json deployment > artifacts/foundation.json
APP_REPO=$(python -c "import json; print(json.load(open('artifacts/foundation.json'))['app_repository'])")
LAMBDA_REPO=$(python -c "import json; print(json.load(open('artifacts/foundation.json'))['lambda_repository'])")
REGISTRY="${APP_REPO%%/*}"
TAG="demo-$(date -u +%Y%m%d%H%M%S)"
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin "$REGISTRY"
```

**Continue when:** Docker says `Login Succeeded`. Docker Desktop must be running.

Build/upload the Python services, then the Lambda dispatcher. After cleanup,
ECR's images were deleted too: repeat both pushes even if Docker reuses build
layers or the repository address looks unchanged.

```zsh
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  --load -f Dockerfile -t "${APP_REPO}:${TAG}" .
docker push "${APP_REPO}:${TAG}"
```

```zsh
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  --load -f Dockerfile.lambda -t "${LAMBDA_REPO}:${TAG}" .
docker push "${LAMBDA_REPO}:${TAG}"
```

These flags are intentional even on Apple Silicon: AWS runs x86_64 images.
Wait for each build/push to succeed. Now get their exact version addresses:

```zsh
APP_DIGEST=$(aws ecr describe-images --region ap-south-1 \
  --repository-name "${APP_REPO#*/}" --image-ids imageTag="$TAG" \
  --query 'imageDetails[0].imageDigest' --output text)
LAMBDA_DIGEST=$(aws ecr describe-images --region ap-south-1 \
  --repository-name "${LAMBDA_REPO#*/}" --image-ids imageTag="$TAG" \
  --query 'imageDetails[0].imageDigest' --output text)
APP_IMAGE="$APP_REPO@$APP_DIGEST"
LAMBDA_IMAGE="$LAMBDA_REPO@$LAMBDA_DIGEST"
printf '%s\n' "$APP_IMAGE" "$LAMBDA_IMAGE"
```

**Continue when:** two addresses from your paid account appear, each containing
`@sha256:` and 64 hexadecimal characters. The second is the dispatcher image.
Save both addresses in your private working note; step 7 needs the second one.
Do not use `latest` or another account's address. Review ECR scan findings.

## 5. Give Git the new account's settings

```zsh
python -m tools.configure_aws --image "$APP_IMAGE" \
  --repo git@github.com:Sthiti04/CC-Project.git --branch main
git diff -- deploy/app/values-aws.yaml deploy/platform/values-aws.yaml
```

The helper generates two **non-secret** AWS values files and saves local
deployment details/certificate in ignored `artifacts/`. Review the account,
resource names and image address. If the app values contain a `loadTest` section,
keep `enabled: false` for now. No keys/passwords belong in these Git files.
The generator preserves custom settings, so check that flag explicitly. It
must replace the old volume IDs, bucket/secret references, metadata and public
certificate with this attempt's outputs. Do not install Argo using stale values.

Publish only those two files:

```zsh
git add deploy/app/values-aws.yaml deploy/platform/values-aws.yaml
git diff --cached
git commit -m "Configure AWS" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin main
```

If Git reports a conflict or rejects the push, stop and resolve it without force
pushing. The repository remains private.
**Continue when:** both updated files are visible on GitHub `main`. Argo reads
GitHub, not changes sitting only on the Mac.

## 6. Let Argo CD start the apps -- foundation charges continue

Argo needs permission to **read** the private GitHub repository.
Create a dedicated key once:

```zsh
ssh-keygen -t ed25519 -N "" -C "s23-argocd-read-only" \
  -f artifacts/gitops_ed25519
```

If asked to overwrite an existing key, answer no and check its purpose.
If cleanup removed only its GitHub deploy-key entry and the dedicated local
keypair is still intact, skip `ssh-keygen` and re-add that public key below.
If its private key was lost or compromised, create a new dedicated keypair
instead; never use a mismatched public/private pair.
Open `artifacts/gitops_ed25519.pub` in VS Code. In GitHub, open this repository's
**Settings -> Deploy keys -> Add deploy key**. Paste only the `.pub` text,
use a title such as `S23 paid-account Argo`, and **leave write access unchecked**.
The file without `.pub` is private: never upload/share it.

```zsh
terraform -chdir=infra/gitops init
terraform -chdir=infra/gitops validate
terraform -chdir=infra/gitops plan
terraform -chdir=infra/gitops apply
```

Review and approve normally. This installs Argo and connects it to Git; Argo
starts the apps. Do not run `kubectl apply` or install the app with Helm yourself.

Connect kubectl (the cluster inspection tool) to this deployment:

```zsh
CLUSTER=$(python -c "import json; print(json.load(open('artifacts/deployment.json'))['cluster_name'])")
aws eks update-kubeconfig --name "$CLUSTER" --region ap-south-1
kubectl config current-context
kubectl get nodes
kubectl get applications -n argocd
kubectl get deployments,statefulsets,pods,hpa,pvc -n s23
```

### Open Argo on your Mac

In a **second terminal**, repeat the AWS terminal setup, then run:

```zsh
kubectl -n argocd port-forward svc/argocd-server 8082:80
```

Leave that terminal running. Open `http://127.0.0.1:8082` in the browser.
Username: `admin`. In the **main terminal**, obtain the password privately:

```zsh
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | \
  python -c "import base64; import sys; print(base64.b64decode(sys.stdin.buffer.read(), validate=True).decode())"
```

Do not screenshot the password. Port-forward means a temporary local connection;
it is not a public administration website. Ctrl-C in its terminal closes it.

**Continue only when:**

- Two nodes say `Ready`.
- `s23-root`, `s23-monitoring`, `s23-metrics-server`, `s23-application` all say
  `Synced` and `Healthy` at the intended Git revision.
- Six application Deployments are available; Queue Manager has two replicas.
- Three ZooKeeper pods are ready and their PVCs say `Bound`.
- Argo's initialization steps succeeded (they prepare device rows and Kafka
  topics). Successful setup pods may disappear; check Argo's sync result.
- Ingestion and Registry HPAs show CPU numbers, not persistent `<unknown>`.

Initial `Pending`/`Progressing` can be normal. Persistent failure means use
[troubleshooting](07-troubleshooting.md), not start EMR early.
If the HPAs specifically report `FailedGetScale` / `Deployment not found` and
there are no application Deployments, follow
[the startup-order recovery](07-troubleshooting.md#argo-stuck-hpas-say-deployment-not-found).
Do not rerun Terraform or delete the working ZooKeeper/storage to fix that error.

## 7. Start Lambda and EMR/Flink -- ADDS BILLABLE COMPUTERS

Check the three files from the Mac build exist:

```zsh
ls -lh analytics/target/clinical-analytics.jar \
  analytics/target/runtime/flink-s3-fs-hadoop.jar \
  analytics/target/runtime/flink-metrics-prometheus.jar
```

In the **same** `infra/aws/terraform.tfvars`, change only:

```hcl
enable_runtime   = true
lambda_image_uri = "REPLACE_WITH_THE_SECOND_IMAGE_ADDRESS_FROM_STEP_4"
```

Paste the dispatcher address, not the Python-service address. Keep your account,
IP, IAM ARN and project name unchanged.

```zsh
aws sts get-caller-identity
terraform -chdir=infra/aws plan
terraform -chdir=infra/aws apply
```

Expect Lambda, its SQS trigger, three JAR uploads and an EMR cluster. Stop if the
plan unexpectedly replaces the foundation. Wait for `Apply complete!`, then:

```zsh
python -m tools.configure_aws --image "$APP_IMAGE" \
  --repo git@github.com:Sthiti04/CC-Project.git --branch main
git diff -- deploy/app/values-aws.yaml deploy/platform/values-aws.yaml
```

This refreshes the local EMR ID. If the two Git files changed, publish them using
step 5; if not, no extra commit is needed. Do not commit `artifacts/`.

```zsh
FUNCTION=$(python -c "import json; print(json.load(open('artifacts/deployment.json'))['lambda_function'])")
EMR_ID=$(python -c "import json; print(json.load(open('artifacts/deployment.json'))['emr_cluster_id'])")
aws lambda get-function-configuration --function-name "$FUNCTION" \
  --region ap-south-1 --query '{State:State,Update:LastUpdateStatus}'
aws emr describe-cluster --cluster-id "$EMR_ID" --region ap-south-1 \
  --query 'Cluster.Status'
aws emr list-steps --cluster-id "$EMR_ID" --region ap-south-1 \
  --query 'Steps[].[Name,Status.State]'
```

**Continue when:** Lambda is `Active`/`Successful`, EMR has no failed launch step,
and the actual Flink application is `RUNNING`. Follow
[the short Flink check](06-demonstration-and-observability.md#2-check-that-flink-is-running).
A completed submission step alone is not enough. EMR `WAITING` still costs money.

## 8. Open the public endpoint

```zsh
PUBLIC_URL=$(python -c "import json; print(json.load(open('artifacts/deployment.json'))['public_url'])")
printf '%s\n' "$PUBLIC_URL"
curl --fail --cacert artifacts/demo-ca.pem "$PUBLIC_URL/"
curl --fail --cacert artifacts/demo-ca.pem "$PUBLIC_URL/health/ready"
```

**Continue when:** the first response includes `synthetic_only: true` and readiness
succeeds. This is an API returning JSON, not a patient website.
Its certificate is self-signed; the commands/helper trust the supplied matching
certificate. A browser may warn. Do not use `curl -k`; confirm instructor acceptance.

Now follow [the demonstration checklist](06-demonstration-and-observability.md).
Do its smoke there once; do not run another just because this guide ended.

## If you stop and return later

- **Closing the Mac does not stop AWS charges.** If you are done or blocked for
  the day, decide whether to [clean up](08-cleanup-and-cost.md), not leave it idle.
- Reopen this exact project folder. Repeat the AWS terminal setup, check
  account ID and current kubectl context. SSO may need a new login.
- Before step 5, restore the two image addresses from your private note, e.g.
  `export APP_IMAGE='REPLACE_WITH_SAVED_SERVICE_IMAGE_ADDRESS'`.
- After step 5, recover the service image from the current account's values:

```zsh
APP_IMAGE=$(python -c "import yaml; print(yaml.safe_load(open('deploy/app/values-aws.yaml'))['image'])")
```

- A changed Wi-Fi/VPN may change your public IP: update only `admin_cidr` through
  a reviewed Terraform apply; never open the endpoint to everyone.
- Do not clone again, overwrite tfvars/state or regenerate a deploy
  key for an existing stack. Resume at the last successful step.
- For new code/images or Flink changes, use
  [updating an existing deployment](07-troubleshooting.md#updating-an-existing-deployment).
