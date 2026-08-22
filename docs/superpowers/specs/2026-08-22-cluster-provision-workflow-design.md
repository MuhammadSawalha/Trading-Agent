# Cluster Provision & Bootstrap Workflow — Design

## Motivation

The dev cluster (`infra/terraform/envs/dev`) currently comes up through a long sequence of manual commands: `terraform apply` with two hand-typed `-var` flags, `scp` the kubeconfig off the control plane, `helm install` ingress-nginx/ArgoCD/kube-prometheus-stack one at a time from `docs/plan.md` Tasks 49/52/54, then hand-editing the `KUBECONFIG_DEV` secret and `DEV_HOST` variable so `deploy-dev.yml` can find the new cluster. Tonight's incident (the dev ELB returning `503` because both EC2 instances were stopped by this shared AWS account's `aws-learning-budget-keeper-function`) walked through that whole sequence by hand.

Two separate failure modes both land on the same fix today:
1. **Instances stopped** (budget-keeper, twice daily) — recoverable by `terraform apply -replace` on just the instance resources. The ELB itself is untouched, so `DEV_HOST` doesn't change, but the control plane gets a new public IP and TLS cert, so `KUBECONFIG_DEV` goes stale.
2. **Full `terraform destroy`** — everything is gone, including the ELB, so both `KUBECONFIG_DEV` and `DEV_HOST` need to change, and every cluster add-on (ingress-nginx, ArgoCD, monitoring) needs reinstalling from scratch.

This design automates both into a single `workflow_dispatch` run, modeled on a sibling project's (`PolyAI`) `cluster.yaml`, adapted for this repo's k3s (not kubeadm) cluster and Classic ELB (not ALB) setup.

## Goals

- One GitHub Actions workflow, triggered manually, that gets the dev cluster from "stopped or destroyed" to "fully bootstrapped and ready for `deploy-dev.yml`" with no manual commands.
- Handles both failure modes above without the operator needing to know which one applies.
- Leaves `KUBECONFIG_DEV` and `DEV_HOST` correct afterward automatically, so `deploy-dev.yml` needs no manual secret edits.
- Every install step idempotent (`helm upgrade --install`, `kubectl apply`), so re-running the whole workflow after a partial failure is always safe.

## Non-Goals

- **`envs/prod`.** Confirmed via `terraform state list` that it has never been applied — the real "prod" is the `prod` namespace on this same dev cluster, managed by ArgoCD (`infra/k8s/argocd/applications/*-prod.yaml`). This workflow only ever touches `envs/dev`.
- **Broadening the existing `AWS_CI_ROLE_ARN` OIDC role.** It has ECR-only permissions (`infra/terraform/envs/shared/main.tf`). Granting it EC2/VPC/IAM-creation permissions would mean widening a CI role's reach on a shared multi-student AWS account — out of scope here. This workflow uses separate, narrowly-held static AWS credentials instead (matching what PolyAI's own `cluster.yaml` does).
- **A `deploy-prod.yml`.** Doesn't exist by design (Task 52) — prod deploys go through `promote-prod.yml` + ArgoCD sync, unchanged by this work.
- **Fixing the underlying no-Elastic-IP problem.** Still blocked on this shared account's EIP quota (documented in `bootstrap.sh.tpl`). This workflow makes recovering from IP churn fast, not the churn itself go away.

## Architecture

Two jobs in one new workflow, `.github/workflows/provision-cluster.yml`, `workflow_dispatch`-only (no inputs — single env, single region):

```
provision job                              bootstrap job (needs: provision)
──────────────                             ─────────────────────────────────
1. checkout, configure AWS (static keys)   1. wait for cloud-init (SSH retry loop)
2. detect stopped instances -> -replace    2. scp cluster-bootstrap.sh +
   targets                                    argocd/applications/*.yaml +
3. terraform apply (envs/dev)                 monitoring/prometheus/* +
4. output control_plane_ip, elb_dns_name      monitoring/grafana/dashboards/*
                                            3. ssh: run cluster-bootstrap.sh
                                               (ingress-nginx, ArgoCD + apply
                                               Applications, kube-prometheus-
                                               stack + ServiceMonitors/rules)
                                            4. scp kubeconfig back, fix IP,
                                               base64 it
                                            5. GitHub API (via PAT): update
                                               KUBECONFIG_DEV secret,
                                               DEV_HOST variable
                                            6. print IP/DNS/ArgoCD password
                                               to job summary
```

### `provision` job detail

- `aws-actions/configure-aws-credentials` with static `TF_AWS_ACCESS_KEY_ID`/`TF_AWS_SECRET_ACCESS_KEY` secrets (not the ECR-only OIDC role — see Non-Goals).
- **Stopped-instance detection**, the step that actually closes the loop on tonight's root cause: `aws ec2 describe-instances --filters "Name=tag:Name,Values=stock-research-dev-control-plane" "Name=instance-state-name,Values=stopped,stopping"` (and the same for each `stock-research-dev-worker-*`), building a `-replace=module.cluster.aws_instance.X` argument for each match. If nothing is stopped (fresh account / already running), no `-replace` args are added and `apply` is a normal no-op-or-create.
- `terraform apply -auto-approve $REPLACE_ARGS -var="cluster_token=$TF_CLUSTER_TOKEN" -var="ssh_public_key=$TF_SSH_PUBLIC_KEY"`, working directory `infra/terraform/envs/dev`.
- Concurrency group keyed on the workflow name, to guard against two runs racing the same Terraform state (mirrors PolyAI's `concurrency:` block).
- Outputs: `control_plane_public_ip`, `elb_dns_name` (both `terraform output -raw`).

### `bootstrap` job detail

- SSH readiness: bounded retry loop (`cloud-init status --wait` over SSH, ~60 attempts / 10s apart) — same pattern as PolyAI's, needed because `terraform apply` returns once the instance is `running`, not once k3s has actually finished installing.
- SCP targets (new file `infra/k8s/cluster-bootstrap.sh`, plus existing files this repo already has — nothing new to write for these): `infra/k8s/argocd/applications/*.yaml`, `monitoring/prometheus/values.yaml`, `monitoring/prometheus/servicemonitors.yaml`, `monitoring/prometheus/rules/alerts.yaml`.
- `cluster-bootstrap.sh` runs over SSH with `GRAFANA_ADMIN_PASSWORD` exported. It:
  1. Waits for both worker `Node` objects to register (k3s workers join automatically at boot via `K3S_URL`/`K3S_TOKEN`, but this guards against installing add-ons before they're up).
  2. Installs ingress-nginx as a `NodePort` service pinned to port `30080` — matching `infra/terraform/modules/cluster/main.tf`'s `aws_elb.ingress` listener, and matching `docs/plan.md` Task 49 exactly.
  3. Installs ArgoCD (`kubectl create namespace argocd` + upstream `install.yaml`, `rollout status` wait), then `kubectl apply -f` the 6 `*-prod.yaml` Applications already committed under `infra/k8s/argocd/applications/`.
  4. Installs `kube-prometheus-stack` via Helm into `monitoring`, `-f monitoring/prometheus/values.yaml --set grafana.adminPassword="$GRAFANA_ADMIN_PASSWORD"`, then `kubectl apply -f` the ServiceMonitors and alert rules.
  5. No Calico, no metrics-server, no EBS CSI driver install steps — k3s bundles all three by default, unlike PolyAI's kubeadm cluster. (See the "why k3s" discussion from the design conversation — this is the concrete payoff: a shorter, faster bootstrap script.)
- Kubeconfig retrieval: `scp` `/etc/rancher/k3s/k3s.yaml` off the control plane, `sed` the embedded `127.0.0.1` to the real public IP (k3s's default kubeconfig points at localhost, since it's written to be used from the node itself), `base64 -w0` it.
- Secret/variable auto-update: authenticate to the GitHub API with `REPO_ADMIN_PAT` (a fine-grained PAT, `secrets: write` + `variables: write` on this repo only — created manually by the user, cannot be provisioned by this workflow itself), then `gh secret set KUBECONFIG_DEV` and `gh variable set DEV_HOST`.
- Job summary (`$GITHUB_STEP_SUMMARY`): control-plane IP, ELB DNS name, and the ArgoCD initial-admin password (`kubectl -n argocd get secret argocd-initial-admin-secret ...`), so the operator doesn't have to dig through logs before a demo.

## New GitHub secrets required

| Secret | Purpose | Source |
|---|---|---|
| `TF_AWS_ACCESS_KEY_ID` / `TF_AWS_SECRET_ACCESS_KEY` | Terraform apply against `envs/dev` (EC2/VPC/IAM/ELB) | User's existing IAM user credentials |
| `TF_CLUSTER_TOKEN` | k3s worker join token (`cluster_token` tfvar) | `~/.ssh/stock-research-dev-cluster-token` (existing) |
| `TF_SSH_PUBLIC_KEY` | EC2 key pair (`ssh_public_key` tfvar) | `~/.ssh/stock-research-dev.pub` (existing) |
| `TF_SSH_PRIVATE_KEY` | SSH/SCP into the control plane from the bootstrap job | `~/.ssh/stock-research-dev` (existing) |
| `GRAFANA_ADMIN_PASSWORD` | kube-prometheus-stack Grafana admin login | `~/.ssh/stock-research-dev-grafana-password` (existing) |
| `REPO_ADMIN_PAT` | Update `KUBECONFIG_DEV`/`DEV_HOST` via GitHub API | New fine-grained PAT, user-created |

`KUBECONFIG_DEV` and `DEV_HOST` themselves are not new — they already exist for `deploy-dev.yml`; this workflow just becomes another writer of them, replacing the manual edit step.

## Error handling

- Every wait loop (cloud-init, worker-node registration) is bounded with an explicit count and a failing exit + diagnostic message on timeout — no silent indefinite hangs.
- Every install step is idempotent by construction (`helm upgrade --install`, `kubectl apply`, `kubectl create namespace || true`-style guards where the resource might already exist) — a failed run can always be re-triggered via `workflow_dispatch` without manual cleanup first.
- `terraform apply`'s own plan/apply failure surfaces directly as a failed job — no swallowing.
- The stopped-instance detection step is read-only (`describe-instances`) and only ever adds `-replace` targets; it cannot itself make an unwanted change.

## Testing

- `terraform validate` and `terraform plan` run locally (already part of the `provision` job too) before this is ever pushed, to catch config/syntax errors without spending a CI run.
- No mocked dry-run of the full workflow is practical (it provisions real, billable AWS resources) — the first real `workflow_dispatch` run tonight is the functional test, and it doubles as getting the dev cluster back up for tomorrow's presentation.
- Post-run verification: `kubectl get nodes` (3 `Ready`), `kubectl get pods -n dev -n prod -n monitoring -n argocd -n ingress-nginx`, `scripts/smoke_test.sh` against the new `DEV_HOST`.
