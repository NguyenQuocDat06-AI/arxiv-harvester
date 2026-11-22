"""Compare resolved paths without changing their I/O namespaces."""
from pathlib import PurePath, PureWindowsPath


def _comparison_path(path: PurePath) -> PurePath:
    if not isinstance(path, PureWindowsPath):
        return path
    text = str(path)
    if text[:8].lower() == "\\\\?\\unc\\":
        return PureWindowsPath("\\\\" + text[8:])
    if (text.startswith("\\\\?\\") and len(text) >= 7 and text[4].isalpha()
            and text[5:7] == ":\\"):
        return PureWindowsPath(text[4:])
    return path


def resolved_is_relative_to(path: PurePath, root: PurePath, *, allow_equal: bool = True) -> bool:
    """Check containment after callers resolve symlinks and parent components."""
    child, parent = _comparison_path(path), _comparison_path(root)
    return child.is_relative_to(parent) and (allow_equal or child != parent)
