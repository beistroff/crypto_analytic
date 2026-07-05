#!/bin/bash

# Calculate CPU Load
CPU_IDLE=$(top -bn1 | grep "Cpu(s)" | sed 's/%,/ /g' | awk '{print $8}')
CPU_LOAD=$(awk "BEGIN {print 100 - $CPU_IDLE}")
CPU_INT=$(printf "%.0f" "$CPU_LOAD")
if [ "$CPU_INT" -lt 50 ]; then CPU_EMOJI="🟢"; elif [ "$CPU_INT" -lt 80 ]; then CPU_EMOJI="🟡"; else CPU_EMOJI="🔴"; fi

# Calculate Memory Usage
MEM_USED=$(free -m | awk '/Mem:/ {print $3}')
MEM_TOTAL=$(free -m | awk '/Mem:/ {print $2}')
MEM_PCT=$(awk "BEGIN {printf \"%.2f\", $MEM_USED/$MEM_TOTAL*100}")
MEM_INT=${MEM_PCT%.*}
if [ "$MEM_INT" -lt 70 ]; then MEM_EMOJI="🟢"; elif [ "$MEM_INT" -lt 90 ]; then MEM_EMOJI="🟡"; else MEM_EMOJI="🔴"; fi

# Calculate Disk Usage
DISK_INFO=$(df -h / | awk 'NR==2 {print $3 " / " $2 " (" $5 ")"}')
DISK_PCT=$(df / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_PCT" -lt 70 ]; then DISK_EMOJI="🟢"; elif [ "$DISK_PCT" -lt 90 ]; then DISK_EMOJI="🟡"; else DISK_EMOJI="🔴"; fi

# System Uptime
UPTIME=$(uptime -p | sed 's/up //')

echo "🖥️ System Resource Status"
echo ""
echo "• CPU Load: ${CPU_LOAD}% ${CPU_EMOJI}"
echo "• Memory Usage: ${MEM_USED}MB / ${MEM_TOTAL}MB (${MEM_PCT}%) ${MEM_EMOJI}"
echo "• Disk Usage (Root): ${DISK_INFO} ${DISK_EMOJI}"
echo "• System Uptime: up ${UPTIME}"
