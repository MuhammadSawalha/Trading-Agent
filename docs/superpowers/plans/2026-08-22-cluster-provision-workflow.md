# Cluster Provision & Bootstrap Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `workflow_dispatch` GitHub Actions workflow that recreates the dev k3s cluster (whether stopped by the budget-keeper or fully `terraform destroy`d), reinstalls every cluster add-on, and leaves `KUBECONFIG_DEV`/`DEV_HOST` correct — with zero manual commands.

**Architecture:** Two jobs. `provision` detects stopped EC2 instances and runs `terraform apply` (with `-replace` on anything stopped) against `infra/terraform/envs/dev`. `bootstrap` waits for cloud-init, copies a new `infra/k8s/cluster-bootstrap.sh` + existing manifests to the control plane, runs it over SSH to install ingress-nginx/ArgoCD/kube-prometheus-stack, then fetches the fresh kubeconfig and pushes it (plus the ELB DNS name) back into repo secrets/variables via the GitHub API.

**Tech Stack:** GitHub Actions, Terraform (AWS provider), k3s, Helm, kubectl, ArgoCD, `gh` CLI, bash.

## Global Constraints

- Only `infra/terraform/envs/dev` is ever touched — `envs/prod` has never been applied and stays that way (see design doc Non-Goals).
- The workflow authenticates to AWS with static keys (`TF_AWS_ACCESS_KEY_ID`/`TF_AWS_SECRET_ACCESS_KEY`), not the existing `AWS_CI_ROLE_ARN` OIDC role — that role is ECR-only by design.
- Every install step must be safe to re-run (`helm upgrade --install`, `kubectl apply`, idempotent namespace creation) — no step may assume it's running against a blank cluster.
- ingress-nginx must land on NodePort `30080` exactly — this is hardcoded in `infra/terraform/modules/cluster/main.tf`'s `aws_elb.ingress` listener and cannot be changed without also editing that Terraform resource (out of scope here).
- Reuse existing local secret material (`~/.ssh/stock-research-dev*`) rather than generating new keys/tokens — avoids invalidating anything already baked into running infrastructure.

---

### Task 1: Fix the placeholder ECR registry in prod Helm values

**Files:**
- Modify: `infra/k8s/helm/api-backend/values-prod.yaml`
- Modify: `infra/k8s/helm/frontend/values-prod.yaml`
- Modify: `infra/k8s/helm/mcp-server/values-prod.yaml`
- Modify: `infra/k8s/helm/scheduler/values-prod.yaml`
- Modify: `infra/k8s/helm/stock-scanner-mcp/values-prod.yaml`
- Modify: `infra/k8s/helm/tradingview-mcp/values-prod.yaml`

**Interfaces:**
- Produces: valid `image:` values these 6 files' ArgoCD `Application`s (`infra/k8s/argocd/applications/*-prod.yaml`) resolve into real, pullable ECR image references. Later tasks' bootstrap/sync steps depend on this being correct before any `argocd app sync` can succeed.

Every `values-prod.yaml` currently has `image: "<ECR_REPO>/<service>"` — a literal, never-filled-in placeholder (confirmed by reading all 6 files). `promote-prod.yml` only ever `sed`s the `tag:` line, never `image:`, so this placeholder would silently break the very first prod sync. This blocks the "show prod deployed" part of tomorrow's demo, so it's fixed here before anything else.

- [ ] **Step 1: Confirm the real ECR registry URI**

Run: `aws sts get-caller-identity --query Account --output text`
Expected: `228281126655` (matches every ECR ARN already seen in `deploy-dev.yml` and `envs/shared/main.tf`) — so the real registry is `228281126655.dkr.ecr.us-east-1.amazonaws.com`.

- [ ] **Step 2: Replace the placeholder in all 6 files**

```bash
for chart in api-backend frontend mcp-server scheduler stock-scanner-mcp tradingview-mcp; do
  sed -i 's#<ECR_REPO>#228281126655.dkr.ecr.us-east-1.amazonaws.com#' \
    "infra/k8s/helm/$chart/values-prod.yaml"
done
```

- [ ] **Step 3: Verify every file now has a real image reference**

Run: `grep -H '^image:' infra/k8s/helm/*/values-prod.yaml`
Expected: 6 lines, each `image: "228281126655.dkr.ecr.us-east-1.amazonaws.com/<service>"`, no `<ECR_REPO>` left anywhere.

Run: `grep -rl '<ECR_REPO>' infra/k8s/helm/ || echo "clean"`
Expected: `clean` (no matches).

- [ ] **Step 4: Commit**

```bash
git add infra/k8s/helm/*/values-prod.yaml
git commit -m "fix(helm): resolve the placeholder ECR registry in prod values files

Every values-prod.yaml shipped with a literal <ECR_REPO> placeholder that
promote-prod.yml never touches (it only bumps tag:) -- the first ArgoCD prod
sync would have pulled a nonexistent image forever."
```

---

### Task 2: Write the cluster add-on bootstrap script

**Files:**
- Create: `infra/k8s/cluster-bootstrap.sh`

**Interfaces:**
- Consumes: `GRAFANA_ADMIN_PASSWORD` env var (required, script fails fast if unset). Assumes it is run from a directory containing sibling `argocd/applications/*.yaml`, `monitoring/values.yaml`, `monitoring/servicemonitors.yaml`, `monitoring/rules/alerts.yaml`, `monitoring/dashboards/system-health.json` — the exact layout Task 4's SCP steps produce on the control plane.
- Produces: a cluster with ingress-nginx (NodePort 30080), ArgoCD (with the prod `Application`s registered), and kube-prometheus-stack all installed — the state Task 4's SSH step depends on existing afterward.

- [ ] **Step 1: Write the script**

```bash
#!/bin/bash
# One-time (but safe to re-run) cluster add-on bootstrap for the dev k3s cluster. Run on the
# control-plane node after Terraform has provisioned it and k3s itself is already installed
# via infra/terraform/modules/cluster/bootstrap.sh.tpl's EC2 user-data.
#
# Usage:
#   - From CI: .github/workflows/provision-cluster.yml scp's this script and its sibling
#     manifests (argocd/applications/, monitoring/) over, preserving this layout, and runs
#     it via SSH with GRAFANA_ADMIN_PASSWORD exported.
#   - Manually: copy this file plus infra/k8s/argocd/applications/, monitoring/prometheus/*
#     (as monitoring/), and monitoring/grafana/dashboards/system-health.json (as
#     monitoring/dashboards/system-health.json) to the control plane in that same relative
#     layout, then run `GRAFANA_ADMIN_PASSWORD=... ./cluster-bootstrap.sh`.
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD must be set before running this script}"

# --- wait for both worker nodes to register ---
# Workers join automatically at boot (K3S_URL/K3S_TOKEN, set in bootstrap.sh.tpl), in
# parallel with the control plane's own install rather than after it, so wait for their
# Node objects instead of racing them -- ingress-nginx and kube-prometheus-stack below are
# meant to run across the real 3-node topology, not a single control-plane-only cluster.
echo "Waiting for both worker nodes to register..."
for i in $(seq 1 60); do
  worker_count=$(kubectl get nodes -l '!node-role.kubernetes.io/control-plane' --no-headers 2>/dev/null | wc -l)
  if [ "$worker_count" -ge 2 ]; then
    echo "Both worker nodes have registered."
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "Timed out waiting for worker nodes to join (saw $worker_count/2)." >&2
    exit 1
  fi
  echo "Saw $worker_count/2 worker nodes, retrying in 10s... ($i/60)"
  sleep 10
done

# --- helm CLI (k3s bundles a Helm *controller* CRD, not the helm binary itself) ---
if ! command -v helm >/dev/null 2>&1; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

# --- ingress-nginx, pinned to the ELB's target NodePort ---
# infra/terraform/modules/cluster/main.tf's aws_elb.ingress listener targets NodePort 30080
# on both workers -- this must match exactly (docs/plan.md Task 49).
helm upgrade --install ingress-nginx ingress-nginx \
  --repo https://kubernetes.github.io/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.service.type=NodePort \
  --set controller.service.nodePorts.http=30080 \
  --wait --timeout 5m

# --- dev/prod namespaces ---
# helm --create-namespace (deploy-dev.yml) would create `dev` on its own, but ArgoCD's
# Application objects for prod (applied below) have no CreateNamespace=true sync option --
# an `argocd app sync` against a namespace that doesn't exist yet fails outright. Create both
# up front so neither deploy path has to special-case this.
kubectl get namespace dev >/dev/null 2>&1 || kubectl create namespace dev
kubectl get namespace prod >/dev/null 2>&1 || kubectl create namespace prod

# --- ArgoCD ---
kubectl get namespace argocd >/dev/null 2>&1 || kubectl create namespace argocd
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deployment/argocd-server --timeout=300s

# --- register the prod Applications ---
# Each Application's own syncPolicy is deliberately non-automated (see promote-prod.yml) --
# this only makes ArgoCD aware of them. Nothing lands in the prod namespace until a real
# `argocd app sync` (via promote-prod.yml) runs against an image tag that's already been
# built and verified in dev.
kubectl apply -f "$SCRIPT_DIR/argocd/applications/"

# --- kube-prometheus-stack (Prometheus + Grafana + Alertmanager) ---
helm upgrade --install kube-prometheus-stack kube-prometheus-stack \
  --repo https://prometheus-community.github.io/helm-charts \
  --namespace monitoring --create-namespace \
  -f "$SCRIPT_DIR/monitoring/values.yaml" \
  --set grafana.adminPassword="$GRAFANA_ADMIN_PASSWORD" \
  --set grafana.sidecar.dashboards.enabled=true \
  --wait --timeout 10m

# The ServiceMonitor/PrometheusRule CRDs these depend on only exist once the chart above has
# installed them, so this must come after, not before.
kubectl apply -f "$SCRIPT_DIR/monitoring/servicemonitors.yaml"
kubectl apply -f "$SCRIPT_DIR/monitoring/rules/alerts.yaml"

# --- Grafana dashboard, auto-imported ---
# The chart's Grafana sidecar (just enabled above) watches for ConfigMaps labeled
# grafana_dashboard: "1" in this namespace and loads them automatically -- this replaces the
# manual "Dashboards -> Import -> Upload JSON file" step the README currently documents.
kubectl create configmap system-health-dashboard \
  --from-file=system-health.json="$SCRIPT_DIR/monitoring/dashboards/system-health.json" \
  -n monitoring --dry-run=client -o yaml \
  | kubectl label --local -f - grafana_dashboard=1 -o yaml \
  | kubectl apply -f -

echo "Cluster bootstrap complete."
echo "ArgoCD initial admin password:"
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 --decode
echo
```

- [ ] **Step 2: Syntax-check the script**

Run: `bash -n infra/k8s/cluster-bootstrap.sh`
Expected: no output, exit code 0.

- [ ] **Step 3: Lint the script**

Run: `sudo apt-get install -y shellcheck && shellcheck infra/k8s/cluster-bootstrap.sh`
Expected: no errors (informational notices about the `for i in $(seq ...)` pattern are fine — the rest of this repo's own scripts, e.g. `scripts/smoke_test.sh`, use the identical pattern).

- [ ] **Step 4: Make it executable and commit**

```bash
chmod +x infra/k8s/cluster-bootstrap.sh
git add infra/k8s/cluster-bootstrap.sh
git commit -m "feat(cluster): add the post-boot add-on bootstrap script

Installs ingress-nginx (NodePort 30080), ArgoCD + registers the prod
Applications, and kube-prometheus-stack with auto-imported Grafana dashboard.
Consolidates docs/plan.md Tasks 49/52/54's manual install commands into one
idempotent script the new provision workflow runs over SSH."
```

---

### Task 3: Write the `provision` job

**Files:**
- Create: `.github/workflows/provision-cluster.yml`

**Interfaces:**
- Produces: job outputs `control_plane_ip`, `elb_dns_name` — Task 4's `bootstrap` job consumes both by name via `needs.provision.outputs.*`.

- [ ] **Step 1: Write the workflow file with just the `provision` job**

```yaml
name: Provision & Bootstrap Cluster

on:
  workflow_dispatch: {}

permissions:
  contents: read

# Guards against two runs racing the same dev Terraform state.
concurrency:
  group: provision-cluster-dev
  cancel-in-progress: false

env:
  TF_IN_AUTOMATION: "true"
  TF_INPUT: "false"

jobs:
  provision:
    runs-on: ubuntu-latest
    outputs:
      control_plane_ip: ${{ steps.tf-output.outputs.control_plane_ip }}
      elb_dns_name: ${{ steps.tf-output.outputs.elb_dns_name }}
    defaults:
      run:
        working-directory: infra/terraform/envs/dev
    steps:
      - uses: actions/checkout@v4

      # Static keys, not the existing AWS_CI_ROLE_ARN OIDC role -- that role only carries
      # ECR permissions (infra/terraform/envs/shared/main.tf), and broadening it to
      # EC2/VPC/IAM-creation scope would widen a CI role's reach on this shared,
      # multi-student AWS account. These keys are this repo's own IAM user, scoped to this
      # one workflow's use.
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.TF_AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.TF_AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.7.5"
          terraform_wrapper: false

      - name: Terraform init
        run: terraform init

      # aws-learning-budget-keeper-function (this shared account's cost-control Lambda)
      # stops EC2 instances on a schedule -- `terraform apply` alone is a no-op against a
      # stopped-but-still-present instance, since Terraform only tracks that the resource
      # exists, not its power state. This instance also has no Elastic IP (account is over
      # its EIP quota, see infra/terraform/modules/cluster/bootstrap.sh.tpl), so its public
      # IP and the TLS cert baked in at install time go stale on every stop/start. Detecting
      # "stopped" here and forcing -replace recreates the instance with a fresh IP/cert
      # baked in together, instead of leaving it stopped or racing that same staleness a
      # plain `start-instances` would hit.
      - name: Detect stopped instances that need replacing
        id: detect
        run: |
          set -euo pipefail
          REPLACE_ARGS=""
          for NAME in stock-research-dev-control-plane stock-research-dev-worker-0 stock-research-dev-worker-1; do
            FOUND=$(aws ec2 describe-instances \
              --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=stopped,stopping" \
              --query 'Reservations[].Instances[].InstanceId' --output text)
            if [ -n "$FOUND" ]; then
              case "$NAME" in
                stock-research-dev-control-plane) ADDR="module.cluster.aws_instance.control_plane" ;;
                stock-research-dev-worker-0)       ADDR="module.cluster.aws_instance.worker[0]" ;;
                stock-research-dev-worker-1)       ADDR="module.cluster.aws_instance.worker[1]" ;;
              esac
              echo "Found $NAME stopped ($FOUND) -- will replace $ADDR"
              REPLACE_ARGS="$REPLACE_ARGS -replace=$ADDR"
            fi
          done
          echo "replace_args=$REPLACE_ARGS" >> "$GITHUB_OUTPUT"

      - name: Terraform apply
        run: |
          terraform apply -auto-approve ${{ steps.detect.outputs.replace_args }} \
            -var="cluster_token=${{ secrets.TF_CLUSTER_TOKEN }}" \
            -var="ssh_public_key=${{ secrets.TF_SSH_PUBLIC_KEY }}"

      - name: Read Terraform outputs
        id: tf-output
        run: |
          echo "control_plane_ip=$(terraform output -raw control_plane_public_ip)" >> "$GITHUB_OUTPUT"
          echo "elb_dns_name=$(terraform output -raw elb_dns_name)" >> "$GITHUB_OUTPUT"
```

- [ ] **Step 2: Validate the YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/provision-cluster.yml'))" && echo "valid YAML"`
Expected: `valid YAML`.

- [ ] **Step 3: Validate the embedded Terraform commands locally**

Run:
```bash
cd infra/terraform/envs/dev
terraform validate
terraform plan \
  -var="cluster_token=$(cat ~/.ssh/stock-research-dev-cluster-token)" \
  -var="ssh_public_key=$(cat ~/.ssh/stock-research-dev.pub)"
```
Expected: `terraform validate` reports `Success!`; `terraform plan` runs without error (it will show a real diff if instances are currently stopped/destroyed — that's expected, this step only confirms the config and vars are well-formed, it does not apply anything).

- [ ] **Step 4: Dry-run the stopped-instance detection logic against real AWS state**

Run:
```bash
for NAME in stock-research-dev-control-plane stock-research-dev-worker-0 stock-research-dev-worker-1; do
  aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=stopped,stopping" \
    --query 'Reservations[].Instances[].InstanceId' --output text
done
```
Expected: prints the instance IDs of any currently-stopped `stock-research-dev-*` instances (confirms the filter syntax the workflow step uses is correct against this account's real tags).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/provision-cluster.yml
git commit -m "ci: add the provision job for automated dev cluster recreation

Detects EC2 instances stopped by this shared account's budget-keeper and
forces terraform apply -replace on just those, or creates everything fresh
after a full terraform destroy -- either way ending with a running cluster
and no manual -replace command needed."
```

---

### Task 4: Add the `bootstrap` job

**Files:**
- Modify: `.github/workflows/provision-cluster.yml`

**Interfaces:**
- Consumes: `needs.provision.outputs.control_plane_ip`, `needs.provision.outputs.elb_dns_name` (Task 3); runs `infra/k8s/cluster-bootstrap.sh` (Task 2) over SSH.
- Produces: an updated `KUBECONFIG_DEV` secret and `DEV_HOST` variable on this repo — the exact two values `deploy-dev.yml` already reads, so no change to that file is needed.

- [ ] **Step 1: Append the `bootstrap` job**

```yaml
  bootstrap:
    needs: provision
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # terraform apply returns once the instance is `running`, not once its user-data
      # (k3s install, several minutes on t3.medium) has actually finished -- jumping
      # straight to SSH here would race it. cloud-init status --wait is the OS's own
      # purpose-built signal for "user-data is done".
      - name: Wait for control-plane initialization to finish
        env:
          HOST: ${{ needs.provision.outputs.control_plane_ip }}
        run: |
          set -e
          mkdir -p ~/.ssh
          echo "${{ secrets.TF_SSH_PRIVATE_KEY }}" > ~/.ssh/control-plane.pem
          chmod 600 ~/.ssh/control-plane.pem

          echo "Waiting for SSH and cloud-init to finish on $HOST..."
          for i in $(seq 1 60); do
            if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i ~/.ssh/control-plane.pem \
                 "ubuntu@$HOST" 'sudo cloud-init status --wait' 2>/dev/null; then
              echo "Control plane is ready."
              exit 0
            fi
            echo "Attempt $i/60 - not ready yet, retrying in 10s..."
            sleep 10
          done
          echo "Timed out waiting for the control plane to finish initializing." >&2
          exit 1

      - name: Copy bootstrap script
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ needs.provision.outputs.control_plane_ip }}
          username: ubuntu
          key: ${{ secrets.TF_SSH_PRIVATE_KEY }}
          source: "infra/k8s/cluster-bootstrap.sh"
          target: "/home/ubuntu/cluster-bootstrap"
          strip_components: 2

      - name: Copy ArgoCD Applications
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ needs.provision.outputs.control_plane_ip }}
          username: ubuntu
          key: ${{ secrets.TF_SSH_PRIVATE_KEY }}
          source: "infra/k8s/argocd/applications/*.yaml"
          target: "/home/ubuntu/cluster-bootstrap/argocd/applications"
          strip_components: 4

      - name: Copy Prometheus values and ServiceMonitors
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ needs.provision.outputs.control_plane_ip }}
          username: ubuntu
          key: ${{ secrets.TF_SSH_PRIVATE_KEY }}
          source: "monitoring/prometheus/values.yaml,monitoring/prometheus/servicemonitors.yaml"
          target: "/home/ubuntu/cluster-bootstrap/monitoring"
          strip_components: 2

      - name: Copy alert rules
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ needs.provision.outputs.control_plane_ip }}
          username: ubuntu
          key: ${{ secrets.TF_SSH_PRIVATE_KEY }}
          source: "monitoring/prometheus/rules/alerts.yaml"
          target: "/home/ubuntu/cluster-bootstrap/monitoring/rules"
          strip_components: 3

      - name: Copy Grafana dashboard
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ needs.provision.outputs.control_plane_ip }}
          username: ubuntu
          key: ${{ secrets.TF_SSH_PRIVATE_KEY }}
          source: "monitoring/grafana/dashboards/system-health.json"
          target: "/home/ubuntu/cluster-bootstrap/monitoring/dashboards"
          strip_components: 3

      - name: Run cluster bootstrap
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ needs.provision.outputs.control_plane_ip }}
          username: ubuntu
          key: ${{ secrets.TF_SSH_PRIVATE_KEY }}
          command_timeout: 30m
          envs: GRAFANA_ADMIN_PASSWORD
          script: |
            chmod +x /home/ubuntu/cluster-bootstrap/cluster-bootstrap.sh
            /home/ubuntu/cluster-bootstrap/cluster-bootstrap.sh
        env:
          GRAFANA_ADMIN_PASSWORD: ${{ secrets.GRAFANA_ADMIN_PASSWORD }}

      # k3s writes its kubeconfig pointed at 127.0.0.1 (correct for use from the node
      # itself) -- swap in the real public IP so this file works from anywhere, exactly
      # like the manual `scp ... && sed -i "s/127.0.0.1/.../"` step this replaces.
      - name: Fetch kubeconfig and update repo secrets/variables
        env:
          HOST: ${{ needs.provision.outputs.control_plane_ip }}
          ELB_DNS: ${{ needs.provision.outputs.elb_dns_name }}
          GH_TOKEN: ${{ secrets.REPO_ADMIN_PAT }}
        run: |
          set -euo pipefail
          scp -o StrictHostKeyChecking=no -i ~/.ssh/control-plane.pem \
            "ubuntu@$HOST:/etc/rancher/k3s/k3s.yaml" /tmp/k3s.yaml
          sed -i "s/127.0.0.1/$HOST/" /tmp/k3s.yaml
          base64 -w0 /tmp/k3s.yaml > /tmp/k3s.yaml.b64

          gh secret set KUBECONFIG_DEV --repo "${{ github.repository }}" < /tmp/k3s.yaml.b64
          gh variable set DEV_HOST --repo "${{ github.repository }}" --body "$ELB_DNS"

          rm -f /tmp/k3s.yaml /tmp/k3s.yaml.b64 ~/.ssh/control-plane.pem

      - name: Job summary
        env:
          HOST: ${{ needs.provision.outputs.control_plane_ip }}
          ELB_DNS: ${{ needs.provision.outputs.elb_dns_name }}
        run: |
          {
            echo "## Cluster provisioned"
            echo "- Control plane: \`$HOST\`"
            echo "- ELB DNS (DEV_HOST): \`$ELB_DNS\`"
            echo "- ArgoCD admin password: see the 'Run cluster bootstrap' step log above"
            echo "- KUBECONFIG_DEV and DEV_HOST have been updated -- deploy-dev.yml needs no manual changes"
          } >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 2: Validate the full workflow's YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/provision-cluster.yml'))" && echo "valid YAML"`
Expected: `valid YAML`.

- [ ] **Step 3: Cross-check every SCP `strip_components` value against its `source` path depth**

Run:
```bash
python3 - <<'EOF'
import yaml
wf = yaml.safe_load(open(".github/workflows/provision-cluster.yml"))
for step in wf["jobs"]["bootstrap"]["steps"]:
    if step.get("uses", "").startswith("appleboy/scp-action"):
        for src in step["with"]["source"].split(","):
            depth = src.count("/") - src.count("*/")  # dirs before the filename/glob
            declared = step["with"]["strip_components"]
            print(f"{src}: path has {depth} leading dir components, strip_components={declared}", "OK" if depth == declared else "MISMATCH")
EOF
```
Expected: every line ends `OK` — a `MISMATCH` means that file will land in the wrong place on the control plane and `cluster-bootstrap.sh`'s `$SCRIPT_DIR/...` references will fail to find it.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/provision-cluster.yml
git commit -m "ci: add the bootstrap job to provision-cluster.yml

Waits for cloud-init, copies cluster-bootstrap.sh and its manifests to the
control plane, runs it over SSH, then pushes the fresh kubeconfig and ELB DNS
name into KUBECONFIG_DEV/DEV_HOST via the GitHub API so deploy-dev.yml keeps
working without any manual secret edit."
```

---

### Task 5: Provision the required GitHub secrets

**Files:** none — this is operator setup, no code changes. Included as its own task because Task 6's live run cannot succeed without it, and creating the PAT is the one step that genuinely requires the user (nobody else can create a token on their GitHub account).

**Interfaces:** none — this task's "output" is repo configuration state, not a file.

- [ ] **Step 1: Install and authenticate the `gh` CLI locally**

Run: `sudo apt-get install -y gh`
Expected: `gh` installed, `gh --version` prints `gh version 2.45.0` (or similar).

The user creates a fine-grained PAT now (GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token), scoped to this one repository only, with **Secrets: Read and write** and **Variables: Read and write** permissions.

**This step needs the user directly** — hand them this prompt: *"Create the PAT in GitHub's UI now (repo-scoped, Secrets + Variables read/write), then run `gh auth login --with-token` yourself in a terminal and paste it in when prompted — I won't ask you to paste a token to me."*

- [ ] **Step 2: Verify `gh` is authenticated with the right scope**

Run: `gh auth status`
Expected: shows the authenticated account and this repo's token scope.

- [ ] **Step 3: Set the Terraform-related secrets from existing local files**

None of these commands print the secret values — each pipes a file straight into `gh secret set`'s stdin.

```bash
gh secret set TF_CLUSTER_TOKEN --repo MuhammadSawalha/Trading-Agent < ~/.ssh/stock-research-dev-cluster-token
gh secret set TF_SSH_PUBLIC_KEY --repo MuhammadSawalha/Trading-Agent < ~/.ssh/stock-research-dev.pub
gh secret set TF_SSH_PRIVATE_KEY --repo MuhammadSawalha/Trading-Agent < ~/.ssh/stock-research-dev
gh secret set GRAFANA_ADMIN_PASSWORD --repo MuhammadSawalha/Trading-Agent < ~/.ssh/stock-research-dev-grafana-password
```

- [ ] **Step 4: Set the AWS credentials secrets**

Reuses the same IAM user credentials already configured in `~/.aws/credentials` (confirmed working via `aws sts get-caller-identity` earlier this session) — piped straight from the AWS CLI's own config reader, never typed or displayed.

```bash
aws configure get aws_access_key_id | gh secret set TF_AWS_ACCESS_KEY_ID --repo MuhammadSawalha/Trading-Agent
aws configure get aws_secret_access_key | gh secret set TF_AWS_SECRET_ACCESS_KEY --repo MuhammadSawalha/Trading-Agent
```

- [ ] **Step 5: Set the PAT itself as a repo secret**

The token used to `gh auth login` above also becomes `REPO_ADMIN_PAT`, so the *workflow* (not just this local setup) can call the GitHub API:

Run: `gh auth token | gh secret set REPO_ADMIN_PAT --repo MuhammadSawalha/Trading-Agent`
Expected: no error output (successful `gh secret set` runs are silent).

- [ ] **Step 6: Confirm every secret is present**

Run: `gh secret list --repo MuhammadSawalha/Trading-Agent`
Expected: `TF_CLUSTER_TOKEN`, `TF_SSH_PUBLIC_KEY`, `TF_SSH_PRIVATE_KEY`, `GRAFANA_ADMIN_PASSWORD`, `TF_AWS_ACCESS_KEY_ID`, `TF_AWS_SECRET_ACCESS_KEY`, `REPO_ADMIN_PAT` all listed (alongside the pre-existing `AWS_CI_ROLE_ARN`, `KUBECONFIG_DEV`, `FINNHUB_API_KEY`, etc.).

No commit — this task only changes GitHub repo configuration, not files in the repo.

---

### Task 6: End-to-end live validation

**Files:** none.

**Interfaces:** none — this task exercises everything Tasks 1-5 produced, against real AWS infrastructure.

- [ ] **Step 1: Push the branch and trigger the workflow**

```bash
git push -u origin feature/cluster-provision-workflow
gh workflow run "Provision & Bootstrap Cluster" --repo MuhammadSawalha/Trading-Agent --ref feature/cluster-provision-workflow
```
Expected: workflow queued (`gh run list --repo MuhammadSawalha/Trading-Agent --workflow "Provision & Bootstrap Cluster" --limit 1` shows a run `in_progress`).

- [ ] **Step 2: Watch the run**

Run: `gh run watch --repo MuhammadSawalha/Trading-Agent`
Expected: both `provision` and `bootstrap` jobs complete with ✓. Realistic wall-clock: ~15-25 minutes (EC2 boot + k3s + ingress-nginx + ArgoCD + kube-prometheus-stack `--wait`s).

If it fails partway: fix the specific step that failed and re-run `gh workflow run` again — every install step is idempotent by design (Global Constraints), so a re-run from scratch is always safe.

- [ ] **Step 3: Verify the cluster is healthy**

Run:
```bash
# gh secret list never exposes values (by design) -- fetch the kubeconfig directly instead,
# the same way the workflow itself just did, to verify independently rather than trusting
# the workflow's own success report:
scp -i ~/.ssh/stock-research-dev ubuntu@$(cd infra/terraform/envs/dev && terraform output -raw control_plane_public_ip):/etc/rancher/k3s/k3s.yaml /tmp/k3s-verify.yaml
sed -i "s/127.0.0.1/$(cd infra/terraform/envs/dev && terraform output -raw control_plane_public_ip)/" /tmp/k3s-verify.yaml
KUBECONFIG=/tmp/k3s-verify.yaml kubectl get nodes -o wide
KUBECONFIG=/tmp/k3s-verify.yaml kubectl get pods -n ingress-nginx -n argocd -n monitoring
```
Expected: 3 nodes `Ready`; ingress-nginx controller pod `Running`; ArgoCD server/repo-server/application-controller pods `Running`; Prometheus/Grafana/Alertmanager pods `Running`.

- [ ] **Step 4: Verify `deploy-dev.yml` picked up the fresh `KUBECONFIG_DEV`/`DEV_HOST` automatically**

```bash
gh workflow run "Deploy to dev" --repo MuhammadSawalha/Trading-Agent --ref main
gh run watch --repo MuhammadSawalha/Trading-Agent
```
Expected: succeeds without any manual secret edit — this is the actual proof the auto-update step (Task 4) worked. Note the image tag (`github.sha` of the `main` commit that ran) from the run's logs — it's needed for Step 6.

- [ ] **Step 5: Smoke-test the deployed app**

```bash
DEV_HOST=$(gh variable get DEV_HOST --repo MuhammadSawalha/Trading-Agent)
DEV_HOST="$DEV_HOST" ./scripts/smoke_test.sh
```
Expected: `Manager verdict present. Smoke test passed.`

- [ ] **Step 6: Promote the same verified tag to prod and verify the sync**

```bash
gh workflow run "Promote to prod" --repo MuhammadSawalha/Trading-Agent --field image_tag=<sha from Step 4>
gh run watch --repo MuhammadSawalha/Trading-Agent
KUBECONFIG=/tmp/k3s-verify.yaml kubectl get pods,hpa -n prod
```
Expected: prod pods `Running` (2 replicas each per `values-prod.yaml`), HPA objects present with real min/max, confirming Task 1's placeholder fix actually unblocked a real prod deploy.

- [ ] **Step 7: Clean up the local verification kubeconfig**

Run: `rm -f /tmp/k3s-verify.yaml`

No commit — this task is a verification checkpoint. If everything above passes, the branch is ready for the `finishing-a-development-branch` workflow (merge/PR) whenever the user wants that — not assumed here.
