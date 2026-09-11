#!/usr/bin/env python3
"""Patch a keadm-generated EdgeCore YAML without requiring a YAML package."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


NODE_NAME_PATTERN = re.compile(
    r"^etri-dev(?P<sequence>[0-9]{4})-(?P<suffix>jetorn|jetagx|raspi5|tedger)$"
)
CLASS_SUFFIX = {
    "jetson": "jetorn",
    "jetagx": "jetagx",
    "raspi": "raspi5",
    "tinker": "tedger",
}
KEY_PATTERN = re.compile(r"^(?P<indent>[ ]*)(?P<key>[A-Za-z][A-Za-z0-9]*):(?P<rest>.*)$")


class ConfigurationError(ValueError):
    """Raised when the requested patch is unsafe or incompatible."""


def validate_inputs(node_name: str, node_class: str, cloudcore_host: str) -> None:
    match = NODE_NAME_PATTERN.fullmatch(node_name)
    if match is None:
        raise ConfigurationError(
            "node name must match etri-devNNNN-jetorn, etri-devNNNN-jetagx, "
            "etri-devNNNN-raspi5, or etri-devNNNN-tedger"
        )
    expected_suffix = CLASS_SUFFIX[node_class]
    if match.group("suffix") != expected_suffix:
        raise ConfigurationError(
            f"node class {node_class} requires hostname suffix {expected_suffix}"
        )
    address = ipaddress.ip_address(cloudcore_host)
    if (
        not isinstance(address, ipaddress.IPv4Address)
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ConfigurationError("LAN CloudCore host must be a private IPv4 address")


def patch_lines(
    lines: list[str], node_name: str, cloudcore_host: str, runtime_socket: str,
    network_interface: str | None = None,
) -> tuple[list[str], list[str]]:
    cluster_dns_path = (
        "modules",
        "edged",
        "tailoredKubeletConfig",
        "clusterDNS",
    )
    tailored_config_path = cluster_dns_path[:-1]
    updates = {
        ("modules", "edgeHub", "httpServer"): f"https://{cloudcore_host}:10002",
        ("modules", "edgeHub", "websocket", "server"): f"{cloudcore_host}:10000",
        ("modules", "edgeStream", "enable"): "true",
        ("modules", "edgeStream", "server"): f"{cloudcore_host}:10004",
        ("modules", "edged", "hostnameOverride"): node_name,
        ("modules", "edged", "remoteImageEndpoint"): runtime_socket,
        ("modules", "edged", "remoteRuntimeEndpoint"): runtime_socket,
        ("modules", "edged", "runtimeType"): "remote",
        (
            "modules",
            "edged",
            "tailoredKubeletConfig",
            "containerRuntimeEndpoint",
        ): runtime_socket,
        (
            "modules",
            "edged",
            "tailoredKubeletConfig",
            "imageServiceEndpoint",
        ): runtime_socket,
        ("modules", "metaManager", "metaServer", "enable"): "true",
    }
    found: set[tuple[str, ...]] = set()
    interface_path = ("modules", "edged", "customInterfaceName")
    if network_interface is not None:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,15}", network_interface):
            raise ConfigurationError("invalid network interface")
        updates[interface_path] = network_interface
    changed: list[str] = []
    stack: list[tuple[int, str]] = []
    output: list[str] = []

    existing_paths: set[tuple[str, ...]] = set()
    scan_stack: list[tuple[int, str]] = []
    for line in lines:
        match = KEY_PATTERN.match(line.rstrip("\n"))
        if match is None:
            continue
        indent = len(match.group("indent"))
        key = match.group("key")
        while scan_stack and scan_stack[-1][0] >= indent:
            scan_stack.pop()
        path = tuple(item[1] for item in scan_stack) + (key,)
        existing_paths.add(path)
        if not match.group("rest").strip():
            scan_stack.append((indent, key))

    for line in lines:
        match = KEY_PATTERN.match(line.rstrip("\n"))
        if match is None:
            output.append(line)
            continue

        indent = len(match.group("indent"))
        key = match.group("key")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = tuple(item[1] for item in stack) + (key,)
        rest = match.group("rest").strip()

        if path in updates:
            found.add(path)
            replacement = f"{' ' * indent}{key}: {updates[path]}\n"
            if replacement != line:
                changed.append(".".join(path))
            output.append(replacement)
        else:
            output.append(line)

        if path == tailored_config_path and cluster_dns_path not in existing_paths:
            output.extend(
                [
                    f"{' ' * (indent + 2)}clusterDNS:\n",
                    f"{' ' * (indent + 2)}- 169.254.96.16\n",
                ]
            )
            found.add(cluster_dns_path)
            changed.append(".".join(cluster_dns_path))

        if path == interface_path[:-1] and network_interface is not None and interface_path not in existing_paths:
            output.append(f"{' ' * (indent + 2)}customInterfaceName: {network_interface}\n")
            found.add(interface_path)
            changed.append(".".join(interface_path))

        stream_enable_path = ("modules", "edgeStream", "enable")
        if path == stream_enable_path[:-1] and stream_enable_path not in existing_paths:
            output.append(f"{' ' * (indent + 2)}enable: true\n")
            found.add(stream_enable_path)
            changed.append(".".join(stream_enable_path))

        if not rest:
            stack.append((indent, key))

    required = {
        ("modules", "edgeHub", "httpServer"),
        ("modules", "edgeHub", "websocket", "server"),
        ("modules", "edgeStream", "enable"),
        ("modules", "edgeStream", "server"),
        ("modules", "edged", "hostnameOverride"),
        ("modules", "metaManager", "metaServer", "enable"),
    }
    legacy_runtime = {
        ("modules", "edged", "remoteImageEndpoint"),
        ("modules", "edged", "remoteRuntimeEndpoint"),
        ("modules", "edged", "runtimeType"),
    }
    tailored_runtime = {
        (
            "modules",
            "edged",
            "tailoredKubeletConfig",
            "containerRuntimeEndpoint",
        ),
        (
            "modules",
            "edged",
            "tailoredKubeletConfig",
            "imageServiceEndpoint",
        ),
    }
    missing = required - found
    if missing:
        names = ", ".join(sorted(".".join(path) for path in missing))
        raise ConfigurationError(f"generated EdgeCore YAML is missing required paths: {names}")
    if not (legacy_runtime <= found or tailored_runtime <= found):
        raise ConfigurationError(
            "generated EdgeCore YAML has neither a complete legacy nor tailored containerd runtime shape"
        )

    return output, sorted(set(changed))


def write_atomic(config: Path, content: str, create_backup: bool) -> Path | None:
    backup = None
    if create_backup:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = config.with_name(f"{config.name}.bak.{stamp}")
        shutil.copy2(config, backup)

    mode = stat.S_IMODE(config.stat().st_mode)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=config.parent, prefix=f".{config.name}.", delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.chmod(temporary, mode)
    os.replace(temporary, config)
    return backup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--node-name", required=True)
    parser.add_argument("--node-class", choices=sorted(CLASS_SUFFIX), required=True)
    parser.add_argument("--cloudcore-host", required=True)
    parser.add_argument(
        "--runtime-socket", default="unix:///run/containerd/containerd.sock"
    )
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument("--validate-inputs-only", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--network-interface", help="explicit node IP interface, e.g. wg0")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        validate_inputs(args.node_name, args.node_class, args.cloudcore_host)
        if args.validate_inputs_only:
            print("edge node inputs are valid")
            return 0
        if args.config is None:
            raise ConfigurationError("--config is required unless --validate-inputs-only is used")
        if not args.config.is_file():
            raise ConfigurationError(f"EdgeCore config not found: {args.config}")
        original = args.config.read_text(encoding="utf-8").splitlines(keepends=True)
        patched, changed = patch_lines(
            original, args.node_name, args.cloudcore_host, args.runtime_socket, args.network_interface
        )
        print(f"validated EdgeCore YAML: {args.config}")
        print(f"changed paths: {', '.join(changed) if changed else 'none'}")
        if args.check or not changed:
            return 0
        backup = write_atomic(args.config, "".join(patched), not args.no_backup)
        if backup is not None:
            print(f"backup: {backup}")
        print("EdgeCore YAML updated")
        return 0
    except (ConfigurationError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
