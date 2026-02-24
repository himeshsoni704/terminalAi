# TerminalAi

> An AI-powered Linux CLI bot that understands your system and answers questions right from your command line.

---

## Overview

**TerminalAI** is a conversational AI assistant built for the Linux terminal. It leverages Retrieval-Augmented Generation (RAG) to ground its responses in your local documentation and maintains conversation memory across sessions — giving you a smart, context-aware assistant without ever leaving the terminal.

---

## Features

-  **RAG (Retrieval-Augmented Generation)** — Queries your local documents (`rag_docs/`) to provide accurate, grounded answers
-  **Conversation Memory** — Retains chat history across sessions via the `memory/` module
-  **Linux-Native** — Designed to assist with Linux commands, system administration, and developer workflows
-  **Fast CLI Interface** — Interact directly from your terminal with minimal setup

---

## Project Structure

```
terminalAi/
├── agent.py          # Main entry point — runs the AI agent
├── memory/           # Handles conversation history and session memory
├── rag/              # RAG pipeline: retrieval, embedding, and query logic
├── rag_docs/         # Your local documents used as the AI's knowledge base
└── .gitignore
```

---

## Prerequisites

- Python 3.8+
- pip

---

## Installation

```bash
# Clone the repository
git clone https://github.com/himeshsoni704/terminalAi.git
cd terminalAi

# Install dependencies
pip install -r requirements.txt
```

> If a `requirements.txt` is not present, install the core packages manually:
> ```bash
> pip install openai langchain chromadb tiktoken
> ```

---

## Configuration

1. Create a `.env` file in the root directory:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

2. Add your documentation or knowledge base files to the `rag_docs/` directory. These will be indexed and used by the RAG pipeline to answer your questions.

---

## Usage

```bash
python agent.py
```

Once running, type your question or Linux command query at the prompt and the agent will respond using your local knowledge base and its conversation memory.

**Example interactions:**
```
You: How do I list all running processes?
AI: You can use `ps aux` to list all running processes...

You: What did I ask you earlier?
AI: You asked about listing running processes using `ps aux`...
```

---

## How It Works

1. **RAG Pipeline** — When you ask a question, the `rag/` module searches `rag_docs/` for relevant content using vector similarity search and injects it into the prompt as context.
2. **Memory** — The `memory/` module stores your conversation history so the agent can refer back to earlier exchanges.
3. **Agent** — `agent.py` ties everything together, managing the flow between your input, retrieval, memory, and the LLM response.

---

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

---
## Author

**Himesh Soni** — [@himeshsoni704](https://github.com/himeshsoni704)
