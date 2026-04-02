param(
    [string]$InstanceId = "i-0ac1cc81aeaeefc43"
)

Write-Host "Uploading scripts and skills to EC2 instance..."

# Read file contents
$marketIntel = Get-Content "e:\ai_tools\crypto_analytic\scripts\market_intelligence.py" -Raw
$sentinelMem = Get-Content "e:\ai_tools\crypto_analytic\scripts\sentinel_memory.py" -Raw
$skillMD = Get-Content "e:\ai_tools\crypto_analytic\skills\market_analyzer.md" -Raw

# Create JSON array of commands
$commands = @(
    "mkdir -p /home/ubuntu/sentinel/{scripts,skills}",
    "cat > /home/ubuntu/sentinel/scripts/market_intelligence.py << 'PYEOF'`n$marketIntel`nPYEOF",
    "cat > /home/ubuntu/sentinel/scripts/sentinel_memory.py << 'PYEOF'`n$sentinelMem`nPYEOF",
    "cat > /home/ubuntu/sentinel/skills/market_analyzer.md << 'MDEOF'`n$skillMD`nMDEOF",
    "chmod +x /home/ubuntu/sentinel/scripts/*.py",
    "chown -R ubuntu:ubuntu /home/ubuntu/sentinel",
    "ls -la /home/ubuntu/sentinel/scripts/"
)

# Convert to JSON
$commandsJson = $commands | ConvertTo-Json -Compress

Write-Host "Sending files to instance $InstanceId..."
aws-vault exec sentinel-deploy -- aws ssm send-command `
  --document-name "AWS-RunShellScript" `
  --parameters commands=$($commands) `
  --targets "Key=instanceids,Values=$InstanceId"

Write-Host "Done! Files should now be on the instance."
Write-Host "Check with: aws-vault exec sentinel-deploy -- aws ssm start-session --target $InstanceId"
