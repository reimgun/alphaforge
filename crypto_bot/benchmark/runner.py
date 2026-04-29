"""
Hardware Benchmark — misst CPU/RAM/Disk/Netzwerk und generiert Feature-Profil.

Standalone:
    python -m crypto_bot.benchmark

Aus Code:
    from crypto_bot.benchmark import run_benchmark, load_profile
    profile = run_benchmark()
    profile = load_profile()  # gecachtes Ergebnis
"""
from __future__ import annotations

import json
import math
import os
import platform
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROFILE_PATH = Path(__file__).parent.parent.parent / "data_store" / "hardware_profile.json"


def _cpu_score() -> dict:
    """Misst CPU-Performance via Primzahl-Sieb."""
    import threading

    cores = os.cpu_count() or 1
    start = time.perf_counter()
    # Eratosthenes-Sieb bis 500_000
    n = 500_000
    sieve = bytearray([1]) * (n + 1)
    sieve[0] = sieve[1] = 0
    for i in range(2, int(n**0.5) + 1):
        if sieve[i]:
            sieve[i*i::i] = bytearray(len(sieve[i*i::i]))
    elapsed = time.perf_counter() - start
    # Score: Primzahlen pro Sekunde (normiert auf Referenz-Hardware)
    primes = sum(sieve)
    score = round(primes / max(elapsed, 0.001) / 1000, 1)  # k-primes/s
    return {
        "cores": cores,
        "score_kps": score,     # k-primes/s; Referenz-PC ≈ 100–400
        "elapsed_ms": round(elapsed * 1000, 1),
    }


def _ram_info() -> dict:
    """RAM-Größe aus /proc/meminfo oder psutil."""
    total_mb = 0
    available_mb = 0
    try:
        import psutil
        vm = psutil.virtual_memory()
        total_mb = vm.total // (1024 * 1024)
        available_mb = vm.available // (1024 * 1024)
    except ImportError:
        try:
            lines = Path("/proc/meminfo").read_text().splitlines()
            for line in lines:
                if line.startswith("MemTotal:"):
                    total_mb = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    available_mb = int(line.split()[1]) // 1024
        except Exception:
            pass
    return {"total_mb": total_mb, "available_mb": available_mb}


def _disk_iops() -> dict:
    """Misst sequentielle Schreib-/Lese-Geschwindigkeit in MB/s."""
    block = 1024 * 1024  # 1 MB
    blocks = 32          # 32 MB gesamt
    data = os.urandom(block)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bench") as f:
            tmp = f.name
            # Write
            t0 = time.perf_counter()
            for _ in range(blocks):
                f.write(data)
            f.flush()
            os.fsync(f.fileno())
            write_s = time.perf_counter() - t0
            # Read
            f.seek(0)
            t0 = time.perf_counter()
            while f.read(block):
                pass
            read_s = time.perf_counter() - t0
        os.unlink(tmp)
        write_mbs = round(blocks / max(write_s, 0.001), 1)
        read_mbs  = round(blocks / max(read_s,  0.001), 1)
    except Exception:
        write_mbs = read_mbs = 0.0
    return {"write_mbs": write_mbs, "read_mbs": read_mbs}


def _network_latency() -> dict:
    """Misst Latenz zu Binance API (TCP-Connect) und 8.8.8.8."""
    results = {}
    for host, port in [("api.binance.com", 443), ("8.8.8.8", 53)]:
        try:
            t0 = time.perf_counter()
            s = socket.create_connection((host, port), timeout=5)
            s.close()
            ms = round((time.perf_counter() - t0) * 1000, 1)
        except Exception:
            ms = -1
        results[host] = ms
    # Binance-Latenz bevorzugen, Fallback auf DNS
    primary = results.get("api.binance.com", -1)
    fallback = results.get("8.8.8.8", -1)
    latency_ms = primary if primary > 0 else fallback
    return {"latency_ms": latency_ms, "details": results}


def _avx2_support() -> bool:
    """Prüft ob CPU AVX2-Instruktionen unterstützt."""
    try:
        if platform.system() == "Linux":
            flags = Path("/proc/cpuinfo").read_text()
            return "avx2" in flags
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.optional.avx2_0"],
                capture_output=True, text=True
            )
            return result.stdout.strip() == "1"
        if platform.system() == "Windows":
            import cpuinfo  # type: ignore
            return "avx2" in cpuinfo.get_cpu_info().get("flags", [])
    except Exception:
        pass
    return False


def _gpu_present() -> bool:
    """Grobe GPU-Erkennung via nvidia-smi oder rocm-smi."""
    return (
        shutil.which("nvidia-smi") is not None
        or shutil.which("rocm-smi") is not None
    )


def _derive_feature_profile(cpu: dict, ram: dict, disk: dict, net: dict,
                              avx2: bool, gpu: bool) -> dict:
    """Leitet Feature-Flags aus Hardware-Messwerten ab."""
    cores      = cpu.get("cores", 1)
    cpu_score  = cpu.get("score_kps", 0)
    ram_mb     = ram.get("total_mb", 0)
    disk_write = disk.get("write_mbs", 0)
    latency_ms = net.get("latency_ms", 999)

    return {
        # ML aktivieren wenn mind. 2 Kerne + guter CPU-Score
        "FEATURE_ML":            cores >= 2 and cpu_score >= 20,
        # LSTM braucht AVX2 und GPU (oder hohen CPU-Score)
        "FEATURE_LSTM":          avx2 and (gpu or cpu_score >= 200),
        # Mehrere Paare parallel ab 2 GB RAM
        "FEATURE_MULTI_PAIR":    max(1, min(10, ram_mb // 512)),
        # Backtest-Tiefe: 90d / 180d / 365d je nach CPU
        "FEATURE_BACKTEST_DAYS": 365 if cpu_score >= 100 else (180 if cpu_score >= 40 else 90),
        # Postgres nur wenn Disk schnell genug (> 50 MB/s Write)
        "DB_BACKEND":            "postgres" if disk_write >= 50 else "sqlite",
        # Update-Intervall: bei hoher Latenz seltener pollen
        "UPDATE_INTERVAL":       3600 if latency_ms > 200 else (1800 if latency_ms > 50 else 900),
        # Online-Learning ab 4 Kernen
        "FEATURE_ONLINE_LEARNING": cores >= 4,
        # PDF-Reports ab 2 GB und schneller Disk
        "FEATURE_PDF_REPORTS":   ram_mb >= 2048 and disk_write >= 20,
    }


def run_benchmark(save: bool = True, verbose: bool = False) -> dict:
    """
    Führt vollständigen Hardware-Benchmark durch.

    Args:
        save:    Ergebnis in PROFILE_PATH speichern
        verbose: Fortschritt ausgeben

    Returns:
        dict mit hardware-Messwerten + empfohlenen Feature-Flags
    """
    if verbose:
        print("  [1/6] CPU-Score messen...")
    cpu = _cpu_score()

    if verbose:
        print("  [2/6] RAM ermitteln...")
    ram = _ram_info()

    if verbose:
        print("  [3/6] Disk-Geschwindigkeit messen...")
    disk = _disk_iops()

    if verbose:
        print("  [4/6] Netzwerk-Latenz messen...")
    net = _network_latency()

    if verbose:
        print("  [5/6] AVX2 / GPU erkennen...")
    avx2 = _avx2_support()
    gpu  = _gpu_present()

    if verbose:
        print("  [6/6] Feature-Profil berechnen...")
    features = _derive_feature_profile(cpu, ram, disk, net, avx2, gpu)

    profile = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "platform":   platform.system(),
        "machine":    platform.machine(),
        "python":     platform.python_version(),
        "hardware": {
            "cpu":  cpu,
            "ram":  ram,
            "disk": disk,
            "net":  net,
            "avx2": avx2,
            "gpu":  gpu,
        },
        "recommended_features": features,
    }

    if save:
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_PATH.write_text(json.dumps(profile, indent=2))

    return profile


def load_profile() -> dict | None:
    """Lädt gespeichertes Hardware-Profil. None wenn noch keins vorhanden."""
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text())
        except Exception:
            pass
    return None


def profile_age_hours() -> float | None:
    """Alter des gespeicherten Profils in Stunden. None wenn kein Profil."""
    profile = load_profile()
    if not profile:
        return None
    try:
        ts = datetime.fromisoformat(profile["timestamp"])
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    except Exception:
        return None


if __name__ == "__main__":
    print("\n Hardware Benchmark\n" + "─" * 40)
    result = run_benchmark(verbose=True)
    hw = result["hardware"]
    print(f"\n  CPU:     {hw['cpu']['cores']} Kerne | Score {hw['cpu']['score_kps']} k-primes/s")
    print(f"  RAM:     {hw['ram']['total_mb']} MB gesamt | {hw['ram']['available_mb']} MB frei")
    print(f"  Disk:    Write {hw['disk']['write_mbs']} MB/s | Read {hw['disk']['read_mbs']} MB/s")
    print(f"  Netz:    {hw['net']['latency_ms']} ms zu Binance")
    print(f"  AVX2:    {'✓' if hw['avx2'] else '✗'}")
    print(f"  GPU:     {'✓' if hw['gpu'] else '✗'}")
    print("\n  Empfohlene Feature-Flags:")
    for k, v in result["recommended_features"].items():
        print(f"    {k}={v}")
    print(f"\n  Profil gespeichert: {PROFILE_PATH}\n")
