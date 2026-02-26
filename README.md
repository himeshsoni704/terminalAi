# TerminalAi 

> An AI-powered Linux CLI bot that understands your system and answers questions right from your command line.

---

## Overview

**TerminalAI** is a conversational AI assistant built specifically for the Linux terminal. It uses **Retrieval-Augmented Generation (RAG)** to ground responses in your local documentation and maintains persistent conversation memory across sessions.

This version is optimized for **Fedora systems using a dedicated `/mnt/ai` partition**, enabling large-scale document indexing (**"Big RAG"**) and local LLM storage (**"Big Memory"**) without filling the root drive.

---

##  Features

- **Big RAG (Retrieval-Augmented Generation)** — Optimized for large document collections (PDFs, text, code) stored on a dedicated partition (`/mnt/ai/rag_docs`).
- **Persistent Memory (ChromaDB)** — Retains deep chat history and context across sessions via a dedicated vector database.
- **Ollama Integration** — Runs local models like `qwen2.5-coder:7b` for private, offline, and secure assistance.
- **Linux-Native Design** — Tailored for Fedora/RHEL workflows, but compatible with all major distributions.
- **Partition-Aware Storage** — Specifically engineered to use `/mnt/ai` for scalable AI workloads, keeping your root drive clean.

---

##  Recommended Project Layout (Partition-Aware)

To support massive datasets and heavy LLM weights, we recommend the following structure:

```text
/mnt/ai/
├── ollama_models/    # Local LLM storage (Qwen, Llama, etc.)
├── rag_docs/         # Your "Big RAG" knowledge base (PDFs, docs, code)
├── chroma_db/        # Vector database for RAG indexing
└── memory/           # Session logs & "Big Memory" conversation history
```

> **Note:** Your cloned repository can remain in your home folder (e.g., `~/terminalAi`), while heavy data lives on `/mnt/ai`.

---

## Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/himeshsoni704/terminalAi.git
cd terminalAi
```

### 2. Install Python Dependencies

```bash
# Recommended: use a virtual environment
pip install openai langchain chromadb tiktoken
```

### 3. Configure Ollama for "Big Memory"

By default, Ollama saves models to your root partition. To move them to your dedicated AI partition:

**Edit the Ollama service:**
```bash
sudo systemctl edit ollama.service
```

**Add these environment variables:**
```ini
[Service]
Environment="OLLAMA_MODELS=/mnt/ai/ollama_models"
```

**Reload and restart:**
```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

### 4. Pull Your Local Model

```bash
ollama pull qwen2.5-coder:7b
```

### 5. Set Proper Permissions (Critical on Fedora)

Ensure your user and the Ollama service can access the partition:

```bash
sudo chown -R $USER:ollama /mnt/ai
sudo chmod -R 775 /mnt/ai
```

---

##  Usage

Launch the agent:

```bash
python agent.py
```

**Example Interaction:**

```
You: How do I list running processes?
AI:  You can use `ps aux` to list all running processes.

You: What did I ask earlier?
AI:  You previously asked about listing running processes using `ps aux`.
```

---

##  How It Works

1. **Big RAG Pipeline** — The `rag/` module embeds documents from `/mnt/ai/rag_docs`, stores them in ChromaDB, and retrieves relevant context for every query.
2. **Memory** — The `memory/` module tracks your conversation history so the agent remembers context and preferences across sessions.
3. **Agent** — `agent.py` orchestrates the full flow: **Input → Memory Retrieval → RAG Context → Ollama Inference → Response**.

---

##  Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| **KeyError: 'response'** | Ollama not running or model missing | Run `ollama serve` and verify model exists |
| **Permission Denied** | Incorrect `/mnt/ai` ownership | `sudo chown -R $USER:ollama /mnt/ai` |
| **Slow Responses** | CPU fallback (no GPU) | Ensure GPU drivers are active (`ollama ps`) |
| **Root Drive Full** | Default model path used | Verify `OLLAMA_MODELS` env variable in systemd |

---

## Author

**Himesh Soni** — [@himeshsoni704](https://github.com/himeshsoni704)

---
