locals {
  user_data_script = templatefile("${path.module}/../../../scripts/bootstrap.sh", {
    market_intelligence = file("${path.module}/../../../scripts/market_intelligence.py")
    sentinel_memory     = file("${path.module}/../../../scripts/sentinel_memory.py")
  })
}
