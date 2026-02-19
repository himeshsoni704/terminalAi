#!/bin/bash

OUTPUT="rag_docs/system_snapshot.txt"

echo "Generating system snapshot..."

echo "===== SYSTEM INFO =====" > $OUTPUT
uname -a >> $OUTPUT
echo "" >> $OUTPUT

echo "===== OS RELEASE =====" >> $OUTPUT
cat /etc/os-release >> $OUTPUT
echo "" >> $OUTPUT

echo "===== CURRENT USER =====" >> $OUTPUT
whoami >> $OUTPUT
echo "" >> $OUTPUT

echo "===== HOME DIRECTORY STRUCTURE =====" >> $OUTPUT
tree -L 2 -I "venv" ~ >> $OUTPUT
echo "" >> $OUTPUT

echo "===== MOUNTED DRIVES =====" >> $OUTPUT
lsblk -f >> $OUTPUT
echo "" >> $OUTPUT

echo "===== DISK USAGE =====" >> $OUTPUT
df -h >> $OUTPUT
echo "" >> $OUTPUT

echo "===== IMPORTANT PATHS =====" >> $OUTPUT
echo "AI Project: /mnt/ai/ai-agent" >> $OUTPUT
echo "Ollama API: http://localhost:11434" >> $OUTPUT
echo "" >> $OUTPUT

echo "Snapshot saved to $OUTPUT"
