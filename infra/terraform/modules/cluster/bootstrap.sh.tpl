#!/bin/bash
set -euo pipefail
if [ "${role}" = "control-plane" ]; then
  # k3s only puts IPs/hostnames it knows about at install time into the server cert's SAN
  # list; without --tls-san, kubectl/helm from outside the VPC (CI runners, this box) fail
  # TLS verification against the public IP even though the connection itself succeeds.
  # No Elastic IP here (this shared account is out of EIP quota) -- this instance's
  # auto-assigned public IP is read from its own metadata instead. That means it changes,
  # and the TLS SAN/kubeconfig/CI secret go stale, every time this instance is stopped and
  # started again (e.g. by the account's aws-learning-budget-keeper-function) -- recovering
  # from that requires recreating this instance (`terraform apply -replace=...`), not just
  # starting it, so a fresh cert/IP get baked in together.
  PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
  # Without --token, k3s generates its own random cluster token on every install instead of
  # the one Terraform generated -- workers below authenticate with Terraform's cluster_token,
  # so the server must be told to accept that same token or every worker join fails "not
  # authorized".
  curl -sfL https://get.k3s.io | sh -s - server --write-kubeconfig-mode 644 --tls-san "$PUBLIC_IP" --token "${cluster_token}"
else
  curl -sfL https://get.k3s.io | K3S_URL=https://${control_plane_ip}:6443 K3S_TOKEN=${cluster_token} sh -
fi
