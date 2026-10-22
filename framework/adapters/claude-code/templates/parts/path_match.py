# The path match of paths.tests and paths.checks. The hook and K6 get the same text (D62).
# A value with no glob character uses the prefix rule: the path, or a path under that folder.
# A glob starts at the repo root. `*`, `?`, and `[...]` match inside one folder level. A `**`
# level matches any number of levels, also zero. A glob also covers each path under a folder
# that it matches. compile_path raises ValueError for a glob that is not valid.
GLOB_CHARS = "*?["


def _glob_level(level: str, pattern: str) -> str:
    out, i = "", 0
    while i < len(level):
        char = level[i]
        if char == "*":
            out += "[^/]*"
            while i + 1 < len(level) and level[i + 1] == "*":
                i += 1
        elif char == "?":
            out += "[^/]"
        elif char == "[":
            start = i + 1 + (level[i + 1:i + 2] == "!")
            end = level.find("]", start + (level[start:start + 1] == "]"))
            if end == -1:
                raise ValueError(f"'{pattern}' has a '[' with no ']'.")
            body = level[start:end].replace("\\", "\\\\").replace("^", "\\^")
            out += ("[^" if start > i + 1 else "[") + body + "]"
            i = end
        else:
            out += re.escape(char)
        i += 1
    return out


def compile_path(pattern: str):
    """Return the regex of a glob, or None for a value with no glob character."""
    if not any(char in pattern for char in GLOB_CHARS):
        return None
    if pattern.startswith("/"):
        raise ValueError(f"'{pattern}' starts with '/'. Write it relative to the repo root.")
    levels = pattern.rstrip("/").split("/")
    if pattern.endswith("/"):
        levels.append("**")
    out = ""
    for number, level in enumerate(levels):
        last = number == len(levels) - 1
        if level == "**":
            out += ".*" if last else "(?:[^/]+/)*"
        else:
            out += _glob_level(level, pattern) + ("" if last else "/")
    return re.compile(out)


def covers(patterns: list[str], path: str) -> bool:
    """True if a value in patterns covers the repo path (a path with '/' between the levels)."""
    levels = path.split("/")
    for pattern in patterns:
        regex = compile_path(pattern)
        if regex is None:
            folder = pattern.rstrip("/")
            if path == folder or path.startswith(folder + "/"):
                return True
        elif any(regex.fullmatch("/".join(levels[:n])) for n in range(1, len(levels) + 1)):
            return True
    return False
