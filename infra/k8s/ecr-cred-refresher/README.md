# ECR credential refresher

k3s (unlike EKS) has no built-in way for containerd to authenticate to ECR, and there's no
IRSA-equivalent for pods to assume a scoped role -- so pulling images requires an
`imagePullSecret` containing a real ECR login, and `aws ecr get-login-password` tokens expire
after 12 hours. This CronJob re-mints that secret every 6 hours using the node's own IAM role
(`stock-research-<env>-node-role`, granted `ecr:GetAuthorizationToken` + pull actions in
`infra/terraform/modules/iam`), so image pulls keep working indefinitely without any
long-lived credential stored anywhere.

Apply once per namespace after the namespace exists and before the first `helm install`:

```bash
kubectl apply -n dev -f infra/k8s/ecr-cred-refresher/
kubectl apply -n prod -f infra/k8s/ecr-cred-refresher/
```

The Job also runs once immediately via `kubectl create job --from=cronjob/...` the first time,
since the CronJob's own schedule won't fire for up to 6 hours otherwise:

```bash
kubectl create job -n dev ecr-cred-refresher-initial --from=cronjob/ecr-cred-refresher
```

Every Deployment's default ServiceAccount in the namespace needs `imagePullSecrets: [{name:
ecr-cred}]` for this to take effect (already patched once manually for `dev`; re-apply after
any namespace recreation):

```bash
kubectl patch serviceaccount default -n dev -p '{"imagePullSecrets": [{"name": "ecr-cred"}]}'
```
