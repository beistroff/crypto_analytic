# CryptoSentinel Terraform - Separate Deployments

This directory contains independent Terraform configurations for each component of the CryptoSentinel infrastructure.

## Directory Structure

```
env/
├── dynamodb/     # DynamoDB state table
├── iam/          # IAM roles and policies
└── ec2/          # EC2 instance
```

## Deployment Order

Deploy in this order due to dependencies:

### 1. Deploy DynamoDB
```bash
cd env/dynamodb
terraform init
terraform plan
terraform apply
terraform output table_arn          # Save this for IAM step
```

### 2. Deploy IAM
```bash
cd ../iam
terraform init
# Edit terraform.tfvars and set dynamodb_table_arn from previous output
terraform plan
terraform apply
terraform output instance_profile_name  # Save this for EC2 step
```

### 3. Deploy EC2
```bash
cd ../ec2
terraform init
# Edit terraform.tfvars and set iam_instance_profile_name from previous output
terraform plan
terraform apply
```

## Each Configuration is Independent

- **Separate state files** per component
- **No module dependencies** within Terraform
- **Manual coordination** via outputs/inputs
- **Individual lifecycle management**

## Free Tier Setup

All configurations default to free tier eligible resources:
- **EC2:** t2.micro (750 hrs/month)
- **DynamoDB:** PAY_PER_REQUEST (25 GB included)
- **Data Transfer:** First 100 GB/month free

## Managing Each Component

### Update only DynamoDB
```bash
cd env/dynamodb
terraform apply
```

### Update only IAM
```bash
cd ../iam
terraform apply
```

### Destroy individual components
```bash
cd env/ec2
terraform destroy

cd ../iam
terraform destroy

cd ../dynamodb
terraform destroy
```

## Remote State (Optional)

To use S3 backend for each component, uncomment the backend block in each `terraform.tf` file.

## Troubleshooting

If you forgot an output value:
```bash
cd env/dynamodb
terraform output table_arn

cd ../iam
terraform output instance_profile_name
```

Then update the dependent terraform.tfvars files with those values.
