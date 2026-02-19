import os
import re
import json
import hashlib
import shutil
import subprocess
import requests
import chromadb
from sentence_transformers import SentenceTransformer
from rich import print
from rich.panel import Panel
from rich.text import Text
import glob

# ═══════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5-coder:7b"
RAG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag")
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory", "cache.json")


# ═══════════════════════════════════════════
# EMBEDDING MODEL + CHROMADB
# ═══════════════════════════════════════════
embedder = SentenceTransformer("all-MiniLM-L6-v2")
chroma_client = chromadb.PersistentClient(path="./memory")
collection = chroma_client.get_or_create_collection("rag_memory")


# ═══════════════════════════════════════════
# MEMORY CACHE — skip re-embedding on restart
# ═══════════════════════════════════════════
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


# ═══════════════════════════════════════════
# MEMORY (ChromaDB Wrapper)
# ═══════════════════════════════════════════
_cache = load_cache()


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


def search_memory(query, n=3):
    embedding = embedder.encode(query).tolist()
    results = collection.query(query_embeddings=[embedding], n_results=n)
    return results["documents"][0] if results["documents"] else []


# ═══════════════════════════════════════════
# SYSTEM SCANNER
# ═══════════════════════════════════════════
def run_shell(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def scan_system():
    print("[cyan]🔍 Scanning system...[/cyan]")
    distro = "unknown"
    if os.path.exists("/etc/os-release"):
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    distro = line.split("=")[1].strip().strip('"')
                    break

    pkg_map = {"fedora": "dnf", "rhel": "dnf", "centos": "dnf",
               "ubuntu": "apt-get", "debian": "apt-get",
               "arch": "pacman", "opensuse": "zypper"}
    pkg_manager = pkg_map.get(distro, "dnf")

    system_info = {
        "os": run_shell("uname -s"),
        "kernel": run_shell("uname -r"),
        "distro": distro,
        "shell": os.environ.get("SHELL", run_shell("echo $SHELL")),
        "package_manager": pkg_manager,
        "home": os.path.expanduser("~"),
        "username": os.environ.get("USER", run_shell("whoami")),
        "hostname": run_shell("hostname"),
        "mounted_drives": run_shell("lsblk -o NAME,MOUNTPOINT -n -l").split("\n"),
        "path": os.environ.get("PATH", "").split(":")
    }

    os.makedirs(RAG_DIR, exist_ok=True)
    with open(os.path.join(RAG_DIR, "system_info.json"), "w") as f:
        json.dump(system_info, f, indent=2)

    print(f"[green]  ✓ {distro} | {pkg_manager} | {system_info['shell']}[/green]")
    return system_info


def scan_file_structure():
    print("[cyan] Scanning dirs...[/cyan]")
    home = os.path.expanduser("~")
    file_structure = {}

    for name in ["Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos", "Projects", ".config", ".local"]:
        path = os.path.join(home, name)
        if os.path.isdir(path):
            file_structure[name] = path

    for mount_root in ["/mnt", "/media"]:
        if os.path.isdir(mount_root):
            for entry in os.listdir(mount_root):
                full = os.path.join(mount_root, entry)
                if os.path.isdir(full):
                    file_structure[f"mount_{entry}"] = full

    home_tree = run_shell(f"ls -1 {home}")
    file_structure["_home_listing"] = home_tree.split("\n") if home_tree else []

    os.makedirs(RAG_DIR, exist_ok=True)
    with open(os.path.join(RAG_DIR, "file_structure.json"), "w") as f:
        json.dump(file_structure, f, indent=2)

    print(f"[green]  ✓ {len(file_structure) - 1} dirs found[/green]")
    return file_structure


# ═══════════════════════════════════════════
# RAG LOADER
# ═══════════════════════════════════════════
def load_json(filename):
    path = os.path.join(RAG_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def load_rag_context(intent, user_input):
    parts = []
    sys_info = load_json("system_info.json")
    if sys_info:
        parts.append(f"OS:{sys_info.get('distro','?')} PKG:{sys_info.get('package_manager','dnf')}")

    if intent == "FUN":
        parts.append(f"FUN_CMDS:{json.dumps(load_json('fun_commands.json'))}")
    elif intent in ("TECH_COMMAND", "INSTALL", "SYSTEM_QUERY"):
        parts.append(f"TECH:{json.dumps(load_json('tech_knowledge.json'))}")
    elif intent == "FILE_NAVIGATION":
        parts.append(f"DIRS:{json.dumps(load_json('file_structure.json'))}")

    mem = search_memory(user_input)
    if mem:
        parts.append(f"MEM:{mem}")

    return "\n".join(parts)


# ═══════════════════════════════════════════
# LOAD RAG DOCS (cached — skips if already embedded)
# ═══════════════════════════════════════════
def load_rag_documents():
    loaded = 0
    skipped = 0
    for fp in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag_docs", "*.txt")):
        with open(fp) as f:
            text = f.read()
            if add_to_memory(text, skip_if_cached=True):
                loaded += 1
            else:
                skipped += 1
    if loaded:
        print(f"[cyan] Loaded {loaded} new doc(s)[/cyan]")
    if skipped:
        print(f"[dim] {skipped} doc(s) already cached[/dim]")


# ═══════════════════════════════════════════
# OLLAMA QUERY
# ═══════════════════════════════════════════
def query_ollama(prompt):
    try:
        resp = requests.post(OLLAMA_URL, json={"model": MODEL_NAME, "prompt": prompt, "stream": False}, timeout=120)
        return resp.json()["response"]
    except requests.exceptions.ConnectionError:
        return "ERROR: Ollama not running (ollama serve)"
    except Exception as e:
        return f"ERROR: {e}"


# ═══════════════════════════════════════════
# INTENT CLASSIFIER
# ═══════════════════════════════════════════
INTENTS = ["CASUAL", "FUN", "TECH_COMMAND", "INSTALL", "FILE_NAVIGATION", "SYSTEM_QUERY"]

KEYWORD_MAP = {
    "FUN": ["matrix", "cow", "cowsay", "lolcat", "fire", "train", "fortune",
            "ascii", "figlet", "nyan", "pipes", "clock", "wizard", "rainbow"],
    "INSTALL": ["install", "uninstall", "remove package", "add package"],
    "FILE_NAVIGATION": ["where is", "find file", "show folder", "list files",
                        "go to", "open folder", "my files", "my desktop"],
    "SYSTEM_QUERY": ["how much ram", "disk space", "cpu", "uptime", "ip address",
                     "what os", "kernel", "who am i"],
}


def classify_intent(user_input):
    lower = user_input.lower()
    for intent, kws in KEYWORD_MAP.items():
        for kw in kws:
            if kw in lower:
                return intent

    # LLM fallback
    result = query_ollama(
        f'Classify into ONE: CASUAL/FUN/TECH_COMMAND/INSTALL/FILE_NAVIGATION/SYSTEM_QUERY.\nInput: "{user_input}"\nOutput ONE word:'
    ).strip().upper()

    for cat in INTENTS:
        if cat in result:
            return cat
    return "TECH_COMMAND"


# ═══════════════════════════════════════════
# SELF-CHECK
# ═══════════════════════════════════════════
def self_check(command, system_info):
    d = system_info.get("distro", "?")
    p = system_info.get("package_manager", "dnf")
    result = query_ollama(
        f"Safety check on {d}: `{command}`\nPkg mgr={p}. "
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


# ═══════════════════════════════════════════
# EXECUTOR
# ═══════════════════════════════════════════
def execute_command(command, system_info):
    prefs = load_json("user_preferences.json")
    pkg = system_info.get("package_manager", "dnf")
    cmd_name = command.split()[0]

    if shutil.which(cmd_name) is None and prefs.get("auto_install_missing", True):
        print(f"[red]⚠ '{cmd_name}' missing → installing via {pkg}[/red]")
        subprocess.run(f"sudo {pkg} install -y {cmd_name}", shell=True)

    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(f"[blue]{result.stdout}[/blue]")
    if result.stderr:
        print(f"[red]{result.stderr}[/red]")
    return result.returncode


# ═══════════════════════════════════════════
# PROMPT BUILDER (compact)
# ═══════════════════════════════════════════
def build_prompt(intent, ctx, user_input):
    si = load_json("system_info.json")
    d = si.get("distro", "fedora")
    p = si.get("package_manager", "dnf")

    if intent == "CASUAL":
        return f"You're a friendly {d} Linux assistant. Chat naturally, no COMMAND: format.\nUser: {user_input}"

    persona = " Fun Linux wizard." if intent == "FUN" else f"Precise {d} sysadmin."

    return f"""{persona}
{ctx}
RULES:
- You MUST use this EXACT format: COMMAND: <cmd>
- Then on next line: ASK: Run? (y/n)
- Do NOT use markdown. No ```bash blocks. No backticks. No code fences.
- {d} only. Use {p}. Never {'apt' if p != 'apt-get' else 'dnf'}.
- No explanations. Just COMMAND: and ASK: lines.
User: {user_input}"""


# ═══════════════════════════════════════════
# COMMAND EXTRACTOR (with markdown fallback)
# ═══════════════════════════════════════════
def extract_command(response):
    """Extract command from response. Tries COMMAND: format first, then markdown blocks."""
    # Try COMMAND: format first
    if "COMMAND:" in response:
        try:
            cmd = response.split("COMMAND:")[1].split("ASK:")[0].strip()
            if cmd:
                return cmd
        except Exception:
            pass

    # Fallback: extract from ```bash ... ``` or ``` ... ``` blocks
    match = re.search(r'```(?:bash|sh)?\n(.+?)\n```', response, re.DOTALL)
    if match:
        cmd = match.group(1).strip()
        if cmd:
            return cmd

    # Last resort: single line that looks like a command (starts with common cmds)
    for line in response.split('\n'):
        line = line.strip()
        if line and not line.startswith(('ASK', '#', '-', '*')) and any(
            line.startswith(p) for p in ['ls ', 'cd ', 'mkdir ', 'rm ', 'cp ', 'mv ', 'sudo ', 'dnf ',
                                          'cat ', 'grep ', 'find ', 'chmod ', 'chown ', 'tar ',
                                          'curl ', 'wget ', 'systemctl ', 'pip ', 'python']
        ):
            return line

    return None


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════
def main():
    print(Panel(Text(" Terminal Agent ", style="bold cyan"), subtitle="himesh soni"))

    system_info = scan_system()
    scan_file_structure()
    load_rag_documents()

    # Cache system summary too
    sys_sum = f"{system_info['distro']} | {system_info['package_manager']} | {system_info['shell']} | {system_info['home']}"
    add_to_memory(sys_sum, skip_if_cached=True)

    prefs = load_json("user_preferences.json")
    print(Panel(Text(" Ready — 'exit' to quit", style="bold green")))

    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ("exit", "quit", "q"):
            print("[dim]👋[/dim]")
            break
        if not user_input.strip():
            continue

        intent = classify_intent(user_input)
        print(f"[dim]» {intent}[/dim]")

        ctx = load_rag_context(intent, user_input)
        prompt = build_prompt(intent, ctx, user_input)
        response = query_ollama(prompt)
        print(f"\n[bold magenta]AI:[/bold magenta] {response}")

        command = extract_command(response)

        if command:
            verdict, reason = self_check(command, system_info)

            if verdict == "DANGEROUS":
                print(f"[bold red] {reason}[/bold red]")
                if input("[red]DANGEROUS. Sure? (yes/no): [/red]").lower() != "yes":
                    print("[yellow]Aborted.[/yellow]")
                    add_to_memory(f"Q:{user_input} A:{response} [ABORTED]")
                    continue

            elif verdict == "INVALID":
                print(f"[red]❌ {reason}[/red]")
                add_to_memory(f"Q:{user_input} A:{response} [INVALID]")
                continue

            elif verdict == "NEEDS_SUDO":
                print(f"[yellow]⚠{reason}[/yellow]")

            if prefs.get("confirm_before_execute", True):
                if input("Run? (y/n): ").lower() != "y":
                    print("[yellow]Skipped.[/yellow]")
                    add_to_memory(f"Q:{user_input} A:{response} [SKIP]")
                    continue

            execute_command(command, system_info)

        add_to_memory(f"Q:{user_input} A:{response}")


if __name__ == "__main__":
    main()
