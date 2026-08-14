#!/bin/bash
set -euo pipefail
if [ "${role}" = "control-plane" ]; then
  curl -sfL https://get.k3s.io | sh -s - server --write-kubeconfig-mode 644
else
  curl -sfL https://get.k3s.io | K3S_URL=https://${control_plane_ip}:6443 K3S_TOKEN=${cluster_token} sh -
fi
