"""The commands a shell line runs, for rules that must tell a program from text that names it.

`commands(line)` returns the argv of every simple command in command position: after ; && || | & ( ) { } and shell
keywords, past VAR=value assignments and wrappers (sudo, env, timeout N, ...), and recursively inside `bash -c '...'`,
$( ... ) and backquotes. Heredoc bodies are skipped: they are data written to a file or fed to a program's stdin, not
commands this shell runs (a program reading them, such as `python - <<EOF`, is itself a command, and what it does
reaches the kernel's counters). A line shlex can't split (an unclosed quote) gives None.

lean: a POSIX-ish subset (no aliases, functions, eval, arithmetic or brace expansion); upgrade to a real bash parser
(bashlex, or tree-sitter-bash) if a rule ever decides on more than which programs a line starts.
"""
import posixpath
import re
import shlex

SEPARATORS = {";", ";;", "&", "&&", "|", "||", "|&", "(", ")", "{", "}", "!", "if", "then", "else", "elif", "fi",
              "do", "done", "while", "until", "for", "case", "esac", "in"}
REDIRECT = re.compile(r"^\d*(?:>>?|<<?<?|>&|<&|&>>?|>\|)$")
HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELLS = {"sh", "bash", "dash", "zsh", "ksh"}


def strip_heredocs(text):
    """`text` without the bodies of its heredocs (the lines between a `<<WORD` and the line that is WORD)."""
    out, pending = [], []
    for line in text.split("\n"):
        if pending:
            dash, word = pending[0]
            if (line.lstrip("\t") if dash else line) == word:
                pending.pop(0)
            continue
        out.append(line)
        pending = [(m.group(1) == "-", m.group(3)) for m in HEREDOC.finditer(line)]
    return "\n".join(out)


def _tokens(text):
    lex = shlex.shlex(text.replace("\n", " ; "), posix=True, punctuation_chars=";&|()<>")
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def _skip_wrappers(argv, wrappers):
    i = 0
    while i < len(argv):
        w = posixpath.basename(argv[i])
        if ASSIGN.match(argv[i]):
            i += 1
        elif w in wrappers:
            i += 1
            while i < len(argv) and (argv[i].startswith("-") or ASSIGN.match(argv[i])
                                     or (w == "timeout" and re.fullmatch(r"\d+(?:\.\d+)?[smhd]?", argv[i]))):
                i += 1
        else:
            break
    return argv[i:]


def commands(line, wrappers=(), depth=0):
    """The argv of each command `line` runs (program first), or None when the line can't be split."""
    if depth > 4:
        return []
    text = strip_heredocs(line)
    inner = []
    for m in re.finditer(r"\$\(([^()]*)\)|`([^`]*)`", text):   # command substitutions run commands too
        sub = commands(m.group(1) or m.group(2) or "", wrappers, depth + 1)
        inner += sub or []
    try:
        toks = _tokens(text)
    except ValueError:
        return None
    out, cur, skip_next = [], [], False
    for t in toks + [";"]:
        if skip_next:
            skip_next = False
            continue
        if t in SEPARATORS and not cur or t in {";", ";;", "&", "&&", "|", "||", "|&", "(", ")"}:
            if cur:
                out.append(cur)
            cur = []
            continue
        if REDIRECT.match(t):
            skip_next = True
            continue
        cur.append(t.lstrip("`$("))
    result = []
    for argv in out:
        argv = _skip_wrappers([a for a in argv if a], set(wrappers))
        if not argv:
            continue
        result.append(argv)
        prog = posixpath.basename(argv[0])
        if prog in SHELLS and "-c" in argv[1:-1]:
            sub = commands(argv[argv.index("-c") + 1], wrappers, depth + 1)
            result += sub or []
    seen, unique = set(), []
    for argv in result + inner:
        if tuple(argv) not in seen:
            seen.add(tuple(argv))
            unique.append(argv)
    return unique
