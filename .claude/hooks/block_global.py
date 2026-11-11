# PreToolUse-хук проекта: запрещает писать что-либо в глобальный профиль Claude
# (память, скилы, хуки, settings.json, CLAUDE.md, агенты, команды). Всё о проекте хранится только в его папке.
# Выход 2 + текст в stderr = вызов инструмента заблокирован.
import json
import os
import re
import sys

def _env_roots():
    """Настоящие пути профиля из окружения (без имени пользователя в коде): ~/.claude и папка профилей в %APPDATA%,
    в виде c:/users/<имя>/… и /c/users/<имя>/… (Git Bash)."""
    roots = []
    for var, tail in (("USERPROFILE", "/.claude"), ("HOME", "/.claude"),
                      ("APPDATA", "/multideskclaude-profiles"), ("CLAUDE_CONFIG_DIR", "")):
        v = os.environ.get(var)
        if not v:
            continue
        p = v.replace("\\", "/").lower().rstrip("/") + tail
        roots.append(p)
        if re.match(r"^[a-z]:/", p):
            roots.append("/" + p[0] + p[2:])
    return roots


GLOBAL_ROOTS = _env_roots() + [
    r"~/.claude",
    r"$home/.claude",
    r"${home}/.claude",
    r"%userprofile%/.claude",
    r"$env:userprofile/.claude",
    r"${env:userprofile}/.claude",
    r"multideskclaude-profiles",      # через %appdata%, $env:appdata, ~/appdata/… — по имени папки профиля
    r"$claude_config_dir",
    r"${claude_config_dir}",
    r"%claude_config_dir%",
]
# безобидные перенаправления — не запись в файл: 2>/dev/null, 2>&1, >$null, 2>nul, и стрелки => в коде
HARMLESS_RE = re.compile(r"\d?>\s*(&\d|/dev/null\b|\$null\b|nul\b)|=>", re.I)
# признаки записи в shell-команде (чтение — ls/cat/grep — не блокируем)
WRITE_RE = re.compile(
    r"(>|\btee\b|\brm\b|\bmv\b|\bcp\b|\bmkdir\b|\btouch\b|\bsed\s+-i|\bln\b|\bunlink\b|"
    r"set-content|add-content|out-file|new-item|remove-item|copy-item|move-item|rename-item|"
    r"export-csv|export-clixml|-outfile\b|writeall(text|bytes|lines)|appendall(text|lines)|"
    # алиасы PowerShell 5.1 и утилиты Windows
    r"\b(sc|ac|ni|ri|del|erase|rd|rmdir|copy|move|ren|cpi|mi|robocopy|xcopy|mklink)\b|"
    r"\bcurl\b.*\s-o\b|\bwget\b.*\s-O\b|\btar\b.*\s-C\b|\bunzip\b.*\s-d\b|"
    r"open\([^)]*['\"][wax+]|write_text|write_bytes|json\.dump|shutil\.|"
    r"os\.(remove|rename|replace|makedirs|mkdir|unlink|rmdir))",
    re.I,
)


# всё, что выполняет команды оболочки (Monitor и терминал приложения — тоже)
SHELL_TOOLS = ("Bash", "PowerShell", "Monitor", "mcp__terminal__run_in_terminal")


def norm(s):
    return s.replace("\\", "/").lower()


def hits_global(text):
    t = norm(text)
    return any(r in t for r in GLOBAL_ROOTS)


def path_global(path):
    """Путь файла: как есть и после раскрытия ~, переменных окружения и «..»."""
    full = os.path.normpath(os.path.expandvars(os.path.expanduser(path))) if path else ""
    return hits_global(path) or hits_global(full)


def main():
    sys.stderr.reconfigure(encoding="utf-8")  # иначе Windows пишет в cp1251 и сообщение не читается
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    if tool in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if path_global(path):
            sys.stderr.write(
                "Запрещено правилом проекта: не писать в глобальный профиль Claude (" + path + "). "
                "Заметки, скилы и хуки этого проекта — только в папке проекта (CLAUDE.md, PLAN.md, .claude/).\n")
            return 2
    elif tool in SHELL_TOOLS:
        cmd = " ".join(v for v in inp.values() if isinstance(v, str))
        if hits_global(cmd) and WRITE_RE.search(HARMLESS_RE.sub(" ", cmd)):
            sys.stderr.write(
                "Запрещено правилом проекта: команда пишет в глобальный профиль Claude. "
                "Всё о проекте — только в папке проекта.\n")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
