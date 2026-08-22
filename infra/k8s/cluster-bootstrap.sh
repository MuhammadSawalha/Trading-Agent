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
  worker_count=$(kubectl get nodes -l '!node-role.kubernetes.io/control-plane' --no-headers 2>/dev/null | wc -l) || worker_count=0
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
