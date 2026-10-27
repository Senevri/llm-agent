# agent_deb_tools.py
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger("AgentDebTools")

HOME = Path.home()
LOCAL = HOME / ".local"
LOCAL_BIN = LOCAL / "bin"
STAGING_ROOT = HOME / ".cache" / "agent-debs"
LISTS_DIR = HOME / ".cache" / "agent-apt-lists"
APT_TIMEOUT = 120
PKG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _run(cmd, timeout=APT_TIMEOUT, cwd=None):
    """Run argv, return (rc, stdout, stderr). Never raises on non-zero."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace",
            timeout=timeout, cwd=cwd,
        )
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"

def _already_available(pkg: str) -> bool:
    if _dpkg_installed(pkg):
        return True
    # Debian packages often have a binary name matching the package name,
    # or a few well-known aliases.
    aliases = {"python3": ["python3"], "python": ["python3", "python"]}
    names = aliases.get(pkg, [pkg])
    return any(shutil.which(n) for n in names)

def _extract_package(deb: Path, pkg_name: str) -> tuple[list[str], list[str]]:
    """Extract a .deb to ~/.local/opt/<pkg>/ and symlink its bins into ~/.local/bin.
    Returns (new_binaries, errors)."""
    target = LOCAL / "opt" / pkg_name
    target.mkdir(parents=True, exist_ok=True)
    rc, out, err = _run(["dpkg", "-x", str(deb), str(target)], timeout=60)
    if rc != 0:
        return [], [f"extract {deb.name}: {(err or out).strip()[:200]}"]

    binaries = []
    pkg_bin = target / "usr" / "bin"
    if pkg_bin.is_dir():
        for b in pkg_bin.iterdir():
            if not b.is_file():
                continue
            link = LOCAL_BIN / b.name
            try:
                if link.exists() or link.is_symlink():
                    link.unlink()          # replace stale link; record it
                link.symlink_to(b)
                binaries.append(b.name)
            except Exception as e:
                return binaries, [f"symlink {b.name}: {e}"]
    return binaries, []


def _dpkg_installed(pkg: str) -> bool:
    rc, out, _ = _run(["dpkg-query", "-W", "-f=${Status}", pkg], timeout=10)
    return rc == 0 and "install ok installed" in out


def _direct_deps(pkg: str) -> list[str]:
    rc, out, _ = _run(
        ["apt-cache", "depends", "--no-recommends", "--no-suggests",
         "--no-conflicts", "--no-breaks", "--no-replaces", "--no-enhances", pkg],
        timeout=15,
    )
    if rc != 0:
        return []
    deps = []
    for line in out.splitlines():
        s = line.strip().lstrip("|").strip()
        if not s.startswith("Depends:"):
            continue
        name = s.split(":", 1)[1].strip().split("(")[0].strip()
        if name and not name.startswith("<") and not _already_available(name):
            deps.append(name)
    return deps


def _download(pkg: str, dest: Path) -> tuple[int, str]:
    dest.mkdir(parents=True, exist_ok=True)
    rc, out, err = _run(["apt-get", "download", pkg], cwd=str(dest))
    if rc == 0:
        return 0, "ok"
    if "Unable to locate package" in (out + err):
        return rc, f"package not in apt sources: {pkg}"
    return rc, f"download failed ({rc}): {(err or out).strip()[:300]}"


def install_deb_package(package: str, with_deps: bool = True) -> str:
    pkg = (package or "").strip()
    if not PKG_RE.match(pkg):
        return f"Error: invalid package name: {package!r}"
    if _already_available(pkg):                     # dpkg-query OR shutil.which
        return f"{pkg} is already available"
    targets = [pkg]
    if with_deps:
        targets.extend(_direct_deps(pkg))           # _direct_deps uses _already_available
    if len(targets) > 12:
        return f"Error: {pkg} pulls in {len(targets)} packages..."

    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"deb_{pkg}_{uuid.uuid4().hex[:6]}_", dir=STAGING_ROOT))

    LOCAL.mkdir(parents=True, exist_ok=True)
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)

    downloaded = []
    errors = []
    for t in targets:
        rc, msg = _download(t, staging)
        if rc != 0:
            errors.append(f"{t}: {msg}")
        else:
            downloaded.append(t)

    # ---- extract ----
    new_bins: list[tuple[str, str]] = []      # (binary_name, package_name)
    for t in downloaded:
        debs = [d for d in staging.glob("*.deb") if d.name.split("_", 1)[0] == t]
        if not debs:
            errors.append(f"{t}: no .deb found in staging")
            continue
        for deb in debs:
            bins, errs = _extract_package(deb, t)
            new_bins.extend((b, t) for b in bins)
            errors.extend(errs)

    # Best-effort cleanup; keep the dir if extraction failed so the user can inspect.
    if not errors:
        shutil.rmtree(staging, ignore_errors=True)
    else:
        logger.warning(f"kept staging dir for inspection: {staging}")

    lines = [f"package: {pkg}"]
    lines.append(f"targets: {', '.join(targets)}")
    lines.append(f"extracted: {len(extracted)} .deb file(s)")
    if new_bins:
        lines.append("binaries on PATH:")
        for b, owner in new_bins:
            lines.append(f"  {b} (from {owner}) → ~/.local/bin/{b}")
    else:
        lines.append("binaries on PATH: (none — package ships libs/config only)")

    if errors:
        lines.append("errors:")
        for e in errors:
            lines.append(f"  - {e}")
        lines.append(f"staging kept at: {staging}")
    lines.append("notes:")
    lines.append("  - maintainer scripts were NOT run (no postinst/prerm)")
    lines.append("  - shared libraries are in ~/.local/lib, NOT on the linker path;")
    lines.append("    if a binary fails with 'cannot open shared object file', set")
    lines.append("    LD_LIBRARY_PATH=$HOME/.local/lib for that command")
    if not errors and new_bins:
        lines.append(f"  - record in tools.md: {', '.join(b for b, _ in new_bins)}")
    return "\n".join(lines)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Install a Debian package into ~/.local without root.")
    parser.add_argument("package", help="Debian package name, e.g. 'jq' or 'libimage-exiftool-perl'.")
    parser.add_argument("--no-deps", action="store_true", help="Do not fetch direct runtime dependencies.")
    args = parser.parse_args()

    result = install_deb_package(args.package, with_deps=not args.no_deps)
    print(result)