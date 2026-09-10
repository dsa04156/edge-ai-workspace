"""Read-only host inventory, no credentials or environment dump."""
import argparse
import json
from pathlib import Path
import platform
import socket
import time
import bench


def inventory():
    files = {}
    for name in ('/proc/device-tree/model', '/etc/nv_tegra_release', '/etc/os-release'):
        try:
            files[name] = Path(name).read_text().strip('\x00\n')
        except OSError:
            files[name] = None
    return {'timestamp': time.time(), 'hostname': socket.gethostname(),
            'architecture': platform.machine(), 'kernel': platform.release(),
            'files': files, 'power_mode': bench.command(['nvpmodel', '-q']),
            'cuda_toolkit': bench.command(['/usr/local/cuda/bin/nvcc', '--version']),
            'gpu': bench.command(['nvidia-smi']),
            'inference_processes': bench.command(['pgrep', '-af', 'llama-server|ollama']),
            'resources': bench.resources(),
            'disk': bench.command(['df', '-h', '/home/etri'])}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    with args.output.open('x') as f:
        json.dump(inventory(), f, indent=2)
