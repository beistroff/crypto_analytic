# CryptoSentinel Terraform

Independent configurations, one per component, each with its own state in S3.

```
env/
├── bootstrap/    # S3 bucket for Terraform state (local state, run once)
├── dynamodb/     # sentinel-real and sentinel-sim tables
├── iam/          # EC2 role, instance profile, least-privilege policy
└── ec2/          # the agent instance (outbound-only security group)
```

Requires Terraform >= 1.10 (S3 native state locking, no DynamoDB lock table).
Credentials are used through `aws-vault exec <profile> -- ...` in the examples.

## Deployment order

### 0. State bucket (once)
```bash
cd env/bootstrap
terraform init
terraform apply
```
Creates the bucket named in the `backend "s3"` blocks of the other envs (versioning,
encryption, public access blocked, TLS-only). Its own small state stays local in
`env/bootstrap/`; keep that file.

### 1. DynamoDB, 2. IAM, 3. EC2
```bash
cd env/dynamodb   # then env/iam, then env/ec2
terraform init
terraform plan
terraform apply
```
- `iam` builds the DynamoDB ARNs from the table names, so nothing is copied by hand.
- `ec2` needs `iam_instance_profile_name` in `terraform.tfvars` (default profile: `SentinelProfile`).
- `terraform.tfvars` is gitignored.

## Cost notes
- DynamoDB uses provisioned capacity (2 RCU/WCU per table and index), inside the always-free tier.
  Continuous backups (PITR) are off to keep the cost at $0; the tables are not backed up (the trade journal is re-entered by hand if lost).
- The instance type decides the architecture, and the AMI (Ubuntu 24.04) follows it, so
  switching to another free-tier type is a one-line change in `terraform.tfvars`.

## First bring-up of the instance
`openclaw/bootstrap.sh` runs once as user data. Connect with Session Manager (no SSH, no inbound ports):
```bash
aws-vault exec <profile> -- aws ssm start-session --target <instance-id>
```
Then follow `openclaw/README.md`: `openclaw onboard`, pin the installed version in
`ec2/terraform.tfvars` (`openclaw_version = "..."`), deploy the sentinel package.

## Checks (same as CI)
```bash
terraform fmt -recursive -check
cd env/<name> && terraform init -backend=false && terraform validate
```

## Destroy
`sentinel-real` has deletion protection on; disable it deliberately before destroying.
The state bucket has `prevent_destroy`.
