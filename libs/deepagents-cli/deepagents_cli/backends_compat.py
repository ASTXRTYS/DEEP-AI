"""Compatibility helpers for sandbox-related backend types.

This module normalizes imports against different versions of the
``deepagents`` package where sandbox APIs have moved or been removed.
"""

from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, TypeAlias, runtime_checkable

from deepagents.backends.protocol import (
    BackendFactory,
    BackendProtocol,
    EditResult,
    WriteResult,
)
from deepagents.backends.utils import FileInfo, GrepMatch

# ---------------------------------------------------------------------------
# ExecuteResponse compatibility
# ---------------------------------------------------------------------------
try:  # Prefer upstream implementation when available.
    from deepagents.backends.protocol import ExecuteResponse as ExecuteResponse
except ImportError:

    @dataclass
    class ExecuteResponse:  # pragma: no cover - mirrors upstream dataclass
        """Result of sandbox command execution."""

        output: str
        exit_code: int | None = None
        truncated: bool = False


# ---------------------------------------------------------------------------
# SandboxBackendProtocol compatibility
# ---------------------------------------------------------------------------
try:
    from deepagents.backends.protocol import SandboxBackendProtocol as SandboxBackendProtocol
except ImportError:

    @runtime_checkable
    class SandboxBackendProtocol(BackendProtocol, Protocol):
        """Protocol for sandboxed backends with an execute command."""

        def execute(self, command: str) -> ExecuteResponse:
            ...

        @property
        def id(self) -> str:
            ...


# ---------------------------------------------------------------------------
# BACKEND_TYPES compatibility
# ---------------------------------------------------------------------------
try:
    from deepagents.backends.protocol import BACKEND_TYPES as BACKEND_TYPES
except ImportError:
    BACKEND_TYPES: TypeAlias = BackendProtocol | BackendFactory


# ---------------------------------------------------------------------------
# BaseSandbox compatibility
# ---------------------------------------------------------------------------
try:
    from deepagents.backends.sandbox import BaseSandbox as BaseSandbox
except ImportError:

    class BaseSandbox(SandboxBackendProtocol, ABC):
        """Base sandbox implementation with execute() as abstract method."""

        _GLOB_COMMAND_TEMPLATE = """python3 -c "
import glob
import os
import json
import base64

path = base64.b64decode('{path_b64}').decode('utf-8')
pattern = base64.b64decode('{pattern_b64}').decode('utf-8')

os.chdir(path)
matches = sorted(glob.glob(pattern, recursive=True))
for m in matches:
    stat = os.stat(m)
    result = {{
        'path': m,
        'size': stat.st_size,
        'mtime': stat.st_mtime,
        'is_dir': os.path.isdir(m)
    }}
    print(json.dumps(result))
" 2>/dev/null"""

        _WRITE_COMMAND_TEMPLATE = """python3 -c "
import os
import sys
import base64

file_path = '{file_path}'

if os.path.exists(file_path):
    print(f'Error: File \\'{file_path}\\' already exists', file=sys.stderr)
    sys.exit(1)

parent_dir = os.path.dirname(file_path) or '.'
os.makedirs(parent_dir, exist_ok=True)

content = base64.b64decode('{content_b64}').decode('utf-8')
with open(file_path, 'w') as f:
    f.write(content)
" 2>&1"""

        _EDIT_COMMAND_TEMPLATE = """python3 -c "
import sys
import base64

with open('{file_path}', 'r') as f:
    text = f.read()

old = base64.b64decode('{old_b64}').decode('utf-8')
new = base64.b64decode('{new_b64}').decode('utf-8')

count = text.count(old)

if count == 0:
    sys.exit(1)
elif count > 1 and not {replace_all}:
    sys.exit(2)

if {replace_all}:
    result = text.replace(old, new)
else:
    result = text.replace(old, new, 1)

with open('{file_path}', 'w') as f:
    f.write(result)

print(count)
" 2>&1"""

        _READ_COMMAND_TEMPLATE = """python3 -c "
import os
import sys

file_path = '{file_path}'
offset = {offset}
limit = {limit}

if not os.path.isfile(file_path):
    print('Error: File not found')
    sys.exit(1)

if os.path.getsize(file_path) == 0:
    print('System reminder: File exists but has empty contents')
    sys.exit(0)

with open(file_path, 'r') as f:
    lines = f.readlines()

start_idx = offset
end_idx = offset + limit
selected_lines = lines[start_idx:end_idx]

for idx, line in enumerate(selected_lines, start=start_idx + 1):
    line_num = idx
    line_content = line.rstrip('\\n')
    print(f'{{line_num:6d}}\\t{{line_content}}')
" 2>&1"""

        @abstractmethod
        def execute(self, command: str) -> ExecuteResponse:
            """Execute a command in the sandbox and return ExecuteResponse."""

        @property
        @abstractmethod
        def id(self) -> str:
            """Unique identifier for this backend instance."""

        def ls_info(self, path: str) -> list[FileInfo]:
            cmd = """python3 -c "
import os
import json

path = '{path}'

try:
    with os.scandir(path) as it:
        for entry in it:
            result = {{
                'path': entry.name,
                'is_dir': entry.is_dir(follow_symlinks=False)
            }}
            print(json.dumps(result))
except FileNotFoundError:
    pass
except PermissionError:
    pass
" 2>/dev/null""".format(path=path)

            result = self.execute(cmd)
            file_infos: list[FileInfo] = []
            for line in result.output.strip().split("\n"):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    file_infos.append({"path": data["path"], "is_dir": data["is_dir"]})
                except json.JSONDecodeError:
                    continue
            return file_infos

        def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
            cmd = self._READ_COMMAND_TEMPLATE.format(file_path=file_path, offset=offset, limit=limit)
            result = self.execute(cmd)
            output = result.output.rstrip()
            if result.exit_code != 0 or "Error: File not found" in output:
                return f"Error: File '{file_path}' not found"
            return output

        def write(self, file_path: str, content: str) -> WriteResult:
            content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
            cmd = self._WRITE_COMMAND_TEMPLATE.format(file_path=file_path, content_b64=content_b64)
            result = self.execute(cmd)
            if result.exit_code != 0 or "Error:" in result.output:
                error_msg = result.output.strip() or f"Failed to write file '{file_path}'"
                return WriteResult(error=error_msg)
            return WriteResult(path=file_path, files_update=None)

        def edit(
            self,
            file_path: str,
            old_string: str,
            new_string: str,
            replace_all: bool = False,
        ) -> EditResult:
            old_b64 = base64.b64encode(old_string.encode("utf-8")).decode("ascii")
            new_b64 = base64.b64encode(new_string.encode("utf-8")).decode("ascii")
            cmd = self._EDIT_COMMAND_TEMPLATE.format(
                file_path=file_path,
                old_b64=old_b64,
                new_b64=new_b64,
                replace_all=replace_all,
            )
            result = self.execute(cmd)
            exit_code = result.exit_code
            output = result.output.strip()

            if exit_code == 1:
                return EditResult(error=f"Error: String not found in file: '{old_string}'")
            if exit_code == 2:
                return EditResult(
                    error=(
                        "Error: String '{old}' appears multiple times. "
                        "Use replace_all=True to replace all occurrences."
                    ).format(old=old_string)
                )
            if exit_code != 0:
                return EditResult(error=f"Error: File '{file_path}' not found")

            count = int(output) if output else 0
            return EditResult(path=file_path, files_update=None, occurrences=count)

        def grep_raw(
            self,
            pattern: str,
            path: str | None = None,
            glob: str | None = None,
        ) -> list[GrepMatch] | str:
            search_path = path or "."
            grep_opts = "-rHn"
            glob_pattern = f"--include='{glob}'" if glob else ""
            pattern_escaped = pattern.replace("'", "'\\\\''")
            cmd = (
                f"grep {grep_opts} {glob_pattern} -e '{pattern_escaped}' '{search_path}' "
                "2>/dev/null || true"
            )
            result = self.execute(cmd)
            output = result.output.rstrip()
            if not output:
                return []

            matches: list[GrepMatch] = []
            for line in output.split("\n"):
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    matches.append({"path": parts[0], "line": int(parts[1]), "text": parts[2]})
            return matches

        def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
            pattern_b64 = base64.b64encode(pattern.encode("utf-8")).decode("ascii")
            path_b64 = base64.b64encode(path.encode("utf-8")).decode("ascii")
            cmd = self._GLOB_COMMAND_TEMPLATE.format(path_b64=path_b64, pattern_b64=pattern_b64)
            result = self.execute(cmd)
            output = result.output.strip()
            if not output:
                return []

            file_infos: list[FileInfo] = []
            for line in output.split("\n"):
                try:
                    data = json.loads(line)
                    file_infos.append({"path": data["path"], "is_dir": data["is_dir"]})
                except json.JSONDecodeError:
                    continue
            return file_infos

