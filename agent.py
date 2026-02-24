import os
import re
import sys
import json
import hashlib
import shutil
import subprocess
import termios
import requests
import chromadb
from sentence_transformers import SentenceTransformer
from rich import print
from rich.panel import Panel
from rich.text import Text
import glob

# ---------------------------
# CONFIG
# ---------------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5-coder:7b"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory", "cache.json")

# ---------------------------
# EMBEDDING MODEL
# ---------------------------
embedder = SentenceTransformer("all-MiniLM-L6-v2")

# ---------------------------
# CHROMA DB (Persistent Memory)
# ---------------------------
chroma_client = chromadb.PersistentClient(path="./memory")
collection = chroma_client.get_or_create_collection("rag_memory")


# ---------------------------
# MEMORY CACHE — skip re-embedding on restart
# ---------------------------
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {"hashes": []}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


def content_hash(text):
    return hashlib.md5(text.encode()).hexdigest()


_cache = load_cache()


# ---------------------------
# ADD DOCUMENT TO MEMORY (with caching)
# ---------------------------
def add_to_memory(text, skip_if_cached=False):
    """Add text to ChromaDB. If skip_if_cached=True, skip if already stored."""
    global _cache
    h = content_hash(text)
    if skip_if_cached and h in _cache["hashes"]:
        return False  # already in memory
    embedding = embedder.encode(text).tolist()
    doc_id = str(len(collection.get()["ids"]) + 1)
    collection.add(documents=[text], embeddings=[embedding], ids=[doc_id])
    _cache["hashes"].append(h)
    save_cache(_cache)
    return True


# ---------------------------
# SEARCH MEMORY
# ---------------------------
def search_memory(query, n=3):
    embedding = embedder.encode(query).tolist()
    results = collection.query(query_embeddings=[embedding], n_results=n)
    return results["documents"][0] if results["documents"] else []


# ---------------------------
# SYSTEM SNAPSHOT (File Structure + Drives)
# ---------------------------
def snapshot_system():
    print("[cyan]Updating system memory snapshot...[/cyan]")

    snapshot_data = []

    # Home directory structure
    home_tree = os.popen("tree -L 2 -I 'venv' ~").read()
    snapshot_data.append("HOME STRUCTURE:\n" + home_tree)

    # Mounted drives
    mounts = os.popen("lsblk -f").read()
    snapshot_data.append("MOUNTED DRIVES:\n" + mounts)

    # Current working directory
    pwd = os.getcwd()
    snapshot_data.append("CURRENT PROJECT LOCATION:\n" + pwd)

    full_snapshot = "\n\n".join(snapshot_data)
    add_to_memory(full_snapshot, skip_if_cached=True)


# ---------------------------
# QUERY OLLAMA
# ---------------------------
def query_model(prompt):
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": MODEL_NAME, "prompt": prompt, "stream": False},
            timeout=120
        )
        return response.json()["response"]
    except requests.exceptions.ConnectionError:
        return "ERROR: Ollama not running (start with: ollama serve)"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------
# LOAD RAG DOCUMENTS (cached — skips if already embedded)
# ---------------------------
def load_rag_documents():
    loaded = 0
    skipped = 0
    for file_path in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag_docs", "*.txt")):
        with open(file_path, "r") as f:
            text = f.read()
            if add_to_memory(text, skip_if_cached=True):
                loaded += 1
            else:
                skipped += 1
    if loaded:
        print(f"[cyan]Loaded {loaded} new RAG doc(s) into memory.[/cyan]")
    if skipped:
        print(f"[dim]{skipped} RAG doc(s) already cached — skipped.[/dim]")


# ---------------------------
# INTENT CLASSIFIER (expanded keywords + LLM fallback)
# ---------------------------
INTENTS = ["CASUAL", "FUN", "TECH_COMMAND", "INSTALL", "FILE_NAVIGATION", "SYSTEM_QUERY"]

KEYWORD_MAP = {
    "FUN": ["matrix", "cow", "cowsay", "lolcat", "fire", "train", "fortune",
            "ascii", "figlet", "nyan", "pipes", "clock", "wizard", "rainbow"],
    "INSTALL": ["install", "uninstall", "remove package", "add package"],
    "TECH_COMMAND": ["create", "make", "write", "script", "timer", "build",
                     "run", "execute", "compile", "move", "copy", "rename",
                     "delete", "remove", "edit", "open", "start", "stop",
                     "restart", "enable", "disable", "mkdir", "touch", "chmod",
                     "tar", "zip", "unzip", "curl", "wget", "grep", "sed",
                     "awk", "cron", "schedule", "permission", "service"],
    "FILE_NAVIGATION": ["where is", "find file", "show folder", "list files",
                        "go to", "open folder", "my files", "my desktop"],
    "SYSTEM_QUERY": ["how much ram", "disk space", "cpu", "uptime", "ip address",
                     "what os", "kernel", "who am i", "memory usage", "temperature"],
}


def classify_intent(user_input):
    lower = user_input.lower()

    # Keyword matching first
    for intent, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            if kw in lower:
                return intent

    # LLM fallback
    result = query_model(
        f'Classify into ONE: CASUAL/FUN/TECH_COMMAND/INSTALL/FILE_NAVIGATION/SYSTEM_QUERY.\nInput: "{user_input}"\nOutput ONE word:'
    ).strip().upper()

    for cat in INTENTS:
        if cat in result:
            return cat
    return "TECH_COMMAND"


# ---------------------------
# COMMAND EXTRACTOR (handles multi-line + multiple commands)
# ---------------------------
def extract_commands(response):
    """Extract ALL commands from response as a list."""
    commands = []

    # Method 1: grab everything between COMMAND: and ASK: (handles multi-line commands)
    if "COMMAND:" in response:
        parts = response.split("COMMAND:")
        for part in parts[1:]:  # skip text before first COMMAND:
            if "ASK:" in part:
                cmd = part.split("ASK:")[0].strip()
            else:
                cmd = part.strip()
            # Collapse internal newlines into single line
            cmd = " ".join(cmd.split())
            if cmd:
                commands.append(cmd)
        if commands:
            return commands

    # Method 2: extract from ```bash ... ``` or ``` ... ``` blocks
    match = re.search(r'```(?:bash|sh)?\n(.+?)\n```', response, re.DOTALL)
    if match:
        block = match.group(1).strip()
        for line in block.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                commands.append(line)
        if commands:
            return commands

    # Method 3: single lines that look like commands
    for line in response.split('\n'):
        line = line.strip()
        if line and not line.startswith(('ASK', '#', '-', '*')) and any(
            line.startswith(p) for p in ['ls ', 'cd ', 'mkdir ', 'rm ', 'cp ', 'mv ', 'sudo ', 'dnf ',
                                          'cat ', 'grep ', 'find ', 'chmod ', 'chown ', 'tar ',
                                          'curl ', 'wget ', 'systemctl ', 'pip ', 'python',
                                          'echo ', 'touch ', 'nano ', 'vim ']
        ):
            commands.append(line)

    return commands if commands else None


# ---------------------------
# CLEAN RESPONSE FOR DISPLAY (strip ASK: lines to avoid double prompt)
# ---------------------------
def clean_response_for_display(response):
    """Remove ASK: lines from LLM output so only our own prompt shows."""
    lines = response.split("\n")
    cleaned = [line for line in lines if not line.strip().upper().startswith("ASK:")]
    return "\n".join(cleaned).strip()


# ---------------------------
# FLUSH STDIN (prevent buffered input from auto-skipping)
# ---------------------------
def flush_stdin():
    """Discard any buffered keystrokes before showing a prompt."""
    try:
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass  # not a TTY or Windows


# ---------------------------
# SELF-CHECK (safety validator)
# ---------------------------
def self_check(command):
    result = query_model(
        f"Safety check on Fedora Linux: `{command}`\n"
        f"Reply ONE word: SAFE/NEEDS_SUDO/DANGEROUS/INVALID. Then reason (max 8 words)."
    ).strip()
    lines = result.split("\n")
    verdict = "SAFE"
    for v in ["SAFE", "NEEDS_SUDO", "DANGEROUS", "INVALID"]:
        if v in lines[0].upper():
            verdict = v
            break
    reason = lines[1].strip() if len(lines) > 1 else ""
    return verdict, reason


# ---------------------------
# RUN COMMANDS (in current terminal)
# ---------------------------
def run_commands(commands):
    """Run all commands sequentially in the current terminal."""
    for i, cmd in enumerate(commands, 1):
        if len(commands) > 1:
            print(f"[dim]▶ Running ({i}/{len(commands)}): {cmd}[/dim]")

        # Auto install if first word (the binary) is missing
        cmd_name = cmd.split()[0]
        if shutil.which(cmd_name) is None:
            print(f"[red]⚠ '{cmd_name}' not found — installing via dnf...[/red]")
            subprocess.run(["sudo", "dnf", "install", "-y", cmd_name])

        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        if result.stdout:
            print(f"[blue]{result.stdout}[/blue]")
        if result.stderr:
            print(f"[red]{result.stderr}[/red]")
        if result.returncode != 0:
            print(f"[red]✗ Command failed (exit {result.returncode})[/red]")
            break

    print("[green]✅ Done[/green]")


# ---------------------------
# MAIN
# ---------------------------
if __name__ == "__main__":
    print(Panel(Text(" Terminal Agent ", style="bold cyan"), subtitle="himesh soni"))

    # Load RAG docs + system snapshot (cached — fast on restarts)
    load_rag_documents()
    snapshot_system()

    print(Panel(Text("✅ Ready — type 'exit' to quit", style="bold green")))

    while True:
        user_input = input("\nYou: ")

        if user_input.lower() in ("exit", "quit", "q"):
            print("[dim]👋[/dim]")
            break
        if not user_input.strip():
            continue

        # Classify intent
        intent = classify_intent(user_input)
        print(f"[dim]» {intent}[/dim]")

        # Retrieve memory
        memory_context = search_memory(user_input)

        # Build prompt based on intent
        if intent == "CASUAL":
            full_prompt = f"You're a friendly Fedora Linux assistant. Chat naturally, be helpful.\nUser: {user_input}"
        else:
            if intent == "FUN":
                persona = "You are a fun Linux wizard who generates entertaining terminal effects."
            else:
                persona = "You are a precise Fedora Linux system assistant."

            full_prompt = f"""{persona}

RULES:
- You MUST use this EXACT format: COMMAND: <cmd>
- Then on next line: ASK: Run? (y/n)
- Do NOT use markdown. No ```bash blocks. No backticks. No code fences.
- Fedora Linux only. Use dnf for package management.
- NEVER use apt, apt-get, or pacman.
- Multiple commands: use separate COMMAND: lines for each.
- No explanations. Just COMMAND: and ASK: lines.

Relevant memory:
{memory_context}

User request:
{user_input}"""

        response = query_model(full_prompt)
        # Display response with ASK: lines stripped (we show our own prompt)
        display_response = clean_response_for_display(response)
        print(f"\n[bold magenta]AI:[/bold magenta] {display_response}")

        # Extract and handle commands
        commands = extract_commands(response)

        if commands:
            print(f"[dim]  → extracted {len(commands)} command(s):[/dim]")
            for i, cmd in enumerate(commands, 1):
                print(f"[cyan]  {i}. {cmd}[/cyan]")

            # Safety check on the full combined command
            full_cmd = " && ".join(commands)
            verdict, reason = self_check(full_cmd)

            if verdict == "DANGEROUS":
                print(f"[bold red]⛔ DANGEROUS: {reason}[/bold red]")
                flush_stdin()
                if input("[red]Are you sure? (yes/no): [/red]").lower() != "yes":
                    print("[yellow]Aborted.[/yellow]")
                    add_to_memory(f"User: {user_input}\nAI: {full_cmd}")
                    continue

            elif verdict == "INVALID":
                print(f"[red]❌ Invalid: {reason}[/red]")
                add_to_memory(f"User: {user_input}\nAI: {full_cmd}")
                continue

            elif verdict == "NEEDS_SUDO":
                print(f"[yellow]⚠ {reason}[/yellow]")

            # Flush any buffered keystrokes, then ask for confirmation
            flush_stdin()
            user_confirm = input("Run? (y/n): ").strip().lower()
            if user_confirm in ('y', 'yes'):
                run_commands(commands)
            else:
                print("[yellow]Skipped.[/yellow]")

        # Store conversation in memory (clean — no status tags)
        add_to_memory(f"User: {user_input}\nAI: {response}")
