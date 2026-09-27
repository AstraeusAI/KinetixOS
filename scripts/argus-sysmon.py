#!/usr/bin/env python3
"""argus-sysmon.py — High-precision system telemetry stream.
Streams 100% accurate system metrics in JSON format, once per second.
Monitors CPU (overall + per-core + freq + temp + load), detailed RAM & Swap,
Network (rates, totals, interfaces), Storage, GPUs, and Top Processes.
"""

import fcntl
import json
import os
import socket
import struct
import subprocess
import sys
import time

def read_cpu_stat():
    stats = {}
    try:
        with open("/proc/stat", "r") as f:
            for line in f:
                if line.startswith("cpu"):
                    parts = line.split()
                    name = parts[0]
                    vals = [float(x) for x in parts[1:]]
                    if len(vals) < 4:
                        continue
                    # Linux /proc/stat fields:
                    # 0: user, 1: nice, 2: system, 3: idle, 4: iowait, 5: irq, 6: softirq, 7: steal, 8: guest, 9: guest_nice
                    # Note: guest is already counted in user, guest_nice in nice.
                    # Standard total = sum of fields 0..7
                    idle = vals[3] + (vals[4] if len(vals) > 4 else 0.0)
                    total = sum(vals[:8]) if len(vals) >= 8 else sum(vals)
                    stats[name] = (idle, total)
    except Exception:
        pass
    return stats

def read_cpu_freqs():
    """(average_ghz, [per_core_ghz, ...]). The per-core list is index-aligned
    with core_loads (both walk cpu0, cpu1, cpu2... sequentially).
    """
    freqs = []
    try:
        base = "/sys/devices/system/cpu"
        idx = 0
        while True:
            core_dir = os.path.join(base, f"cpu{idx}")
            if not os.path.isdir(core_dir):
                break
            sf = os.path.join(core_dir, "cpufreq", "scaling_cur_freq")
            if not os.path.isfile(sf):
                sf = os.path.join(core_dir, "cpufreq", "cpuinfo_cur_freq")
            if not os.path.isfile(sf):
                break
            with open(sf, "r") as f:
                freqs.append(round(float(f.read().strip()) / 1_000_000.0, 2))  # KHz -> GHz
            idx += 1
    except Exception:
        freqs = []
    if freqs:
        return round(sum(freqs) / len(freqs), 2), freqs

    # Fallback to /proc/cpuinfo (also naturally in processor-index order)
    try:
        with open("/proc/cpuinfo", "r") as f:
            mhz = [float(line.split(":")[1].strip()) for line in f if line.startswith("cpu MHz")]
        if mhz:
            per_core = [round(v / 1000.0, 2) for v in mhz]
            return round(sum(per_core) / len(per_core), 2), per_core
    except Exception:
        pass
    return 0.0, []


def read_fans():
    """[{"label", "rpm"}, ...] from hwmon fan*_input sysfs nodes. Zero-RPM
    entries are dropped: a fan header with nothing plugged in reads as a
    permanent 0, which is noise, not a "stopped fan" alarm (an actual stall
    alarm would need a configured minimum this cockpit doesn't try to
    infer). Returns an empty list — not a placeholder entry — when the host
    exposes no working fan sensor, so the UI can hide the stat entirely
    instead of showing a dead "0 RPM" on every desktop and VM that has none.
    """
    fans = []
    try:
        hwmon_dir = "/sys/class/hwmon"
        for h in sorted(os.listdir(hwmon_dir)):
            hpath = os.path.join(hwmon_dir, h)
            name = ""
            try:
                with open(os.path.join(hpath, "name"), "r") as nf:
                    name = nf.read().strip()
            except Exception:
                pass
            for i in range(1, 5):
                fp = os.path.join(hpath, f"fan{i}_input")
                if not os.path.isfile(fp):
                    continue
                try:
                    with open(fp, "r") as ff:
                        rpm = int(float(ff.read().strip()))
                except Exception:
                    continue
                if rpm > 0:
                    fans.append({"label": f"{name or 'fan'} {i}", "rpm": rpm})
    except Exception:
        pass
    return fans

def read_cpu_temp():
    # Search hwmon for CPU sensor (k10temp, coretemp, zenpower, cpu_thermal)
    try:
        hwmon_dir = "/sys/class/hwmon"
        if os.path.isdir(hwmon_dir):
            for h in sorted(os.listdir(hwmon_dir)):
                hpath = os.path.join(hwmon_dir, h)
                name_file = os.path.join(hpath, "name")
                name = ""
                if os.path.isfile(name_file):
                    try:
                        with open(name_file, "r") as nf:
                            name = nf.read().strip().lower()
                    except Exception:
                        pass
                if any(x in name for x in ("k10temp", "coretemp", "zenpower", "cpu")):
                    label_map = {}
                    try:
                        for f in os.listdir(hpath):
                            if f.startswith("temp") and f.endswith("_label"):
                                prefix = f[:-6]  # tempX
                                with open(os.path.join(hpath, f), "r") as lf:
                                    label_map[prefix] = lf.read().strip().lower()
                    except Exception:
                        pass

                    # Preferred sensor order: Tdie > Package id 0 > Tctl > cpu
                    for preferred in ("tdie", "package id 0", "tctl", "cpu"):
                        for prefix, lbl in label_map.items():
                            if preferred in lbl:
                                inp = os.path.join(hpath, f"{prefix}_input")
                                if os.path.isfile(inp):
                                    try:
                                        with open(inp, "r") as tf:
                                            val = float(tf.read().strip())
                                            if val > 0:
                                                return round(val / 1000.0, 1)
                                    except Exception:
                                        pass

                    # Generic fallback inputs
                    for tfile in ("temp1_input", "temp2_input", "temp3_input"):
                        tp = os.path.join(hpath, tfile)
                        if os.path.isfile(tp):
                            try:
                                with open(tp, "r") as f:
                                    val = float(f.read().strip())
                                    if val > 0:
                                        return round(val / 1000.0, 1)
                            except Exception:
                                pass
    except Exception:
        pass
    
    # Fallback thermal_zone
    try:
        for i in range(10):
            tz = f"/sys/class/thermal/thermal_zone{i}/temp"
            if os.path.isfile(tz):
                try:
                    with open(tz, "r") as f:
                        val = float(f.read().strip())
                        if val > 0:
                            return round(val / 1000.0, 1)
                except Exception:
                    pass
    except Exception:
        pass
    return 0.0

def read_mem_info():
    mem = {}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    mem[parts[0].strip()] = int(parts[1].split()[0])
    except Exception:
        pass
    
    total_kb = mem.get("MemTotal", 0)
    avail_kb = mem.get("MemAvailable", 0)
    free_kb = mem.get("MemFree", 0)
    buffers_kb = mem.get("Buffers", 0)
    cached_kb = mem.get("Cached", 0) + mem.get("SReclaimable", 0)
    used_kb = max(0, total_kb - avail_kb)
    
    swap_total_kb = mem.get("SwapTotal", 0)
    swap_free_kb = mem.get("SwapFree", 0)
    swap_used_kb = max(0, swap_total_kb - swap_free_kb)
    
    return {
        "used_gb": round(used_kb / 1048576.0, 2),
        "total_gb": round(total_kb / 1048576.0, 2),
        "avail_gb": round(avail_kb / 1048576.0, 2),
        "free_gb": round(free_kb / 1048576.0, 2),
        "cached_gb": round(cached_kb / 1048576.0, 2),
        "buffers_gb": round(buffers_kb / 1048576.0, 2),
        "pct": round((used_kb / total_kb * 100.0), 1) if total_kb > 0 else 0.0,
        "swap_used_gb": round(swap_used_kb / 1048576.0, 2),
        "swap_total_gb": round(swap_total_kb / 1048576.0, 2),
        "swap_pct": round((swap_used_kb / swap_total_kb * 100.0), 1) if swap_total_kb > 0 else 0.0,
    }

def read_net_dev():
    net = {}
    try:
        with open("/proc/net/dev", "r") as f:
            for line in f:
                if ":" in line:
                    iface, rest = line.split(":", 1)
                    iface = iface.strip()
                    # Exclude loopback and virtual/container bridge interfaces
                    if iface == "lo" or iface.startswith(("docker", "veth", "br-", "virbr")):
                        continue
                    cols = rest.split()
                    if len(cols) >= 9:
                        net[iface] = {
                            "rx": int(cols[0]),
                            "tx": int(cols[8]),
                        }
    except Exception:
        pass
    return net

def read_iface_ip(ifname):
    """IPv4 address for one interface via SIOCGIFADDR — a raw ioctl instead
    of shelling out to `ip addr` once per interface every second. Empty
    string (not an exception surfacing, not "0.0.0.0") for an interface
    that's down or has no address, which is the normal case for most
    non-primary interfaces, not an error.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = struct.pack("256s", ifname[:15].encode())
            addr = fcntl.ioctl(s.fileno(), 0x8915, packed)  # SIOCGIFADDR
            return socket.inet_ntoa(addr[20:24])
        finally:
            s.close()
    except Exception:
        return ""

def read_battery():
    """{"present", "pct", "charging", "status"} from the first BAT* the host
    exposes under /sys/class/power_supply. present=False (not a fake 0%) on
    any desktop with no battery, so the UI can hide the stat entirely.
    """
    try:
        base = "/sys/class/power_supply"
        for entry in sorted(os.listdir(base)):
            if not entry.startswith("BAT"):
                continue
            path = os.path.join(base, entry)
            try:
                with open(os.path.join(path, "capacity"), "r") as f:
                    pct = int(f.read().strip())
            except Exception:
                continue
            status = "Unknown"
            try:
                with open(os.path.join(path, "status"), "r") as f:
                    status = f.read().strip()
            except Exception:
                pass
            return {"present": True, "pct": pct, "charging": status == "Charging", "status": status}
    except Exception:
        pass
    return {"present": False, "pct": 0, "charging": False, "status": ""}

def read_storage():
    try:
        st = os.statvfs("/")
        total_bytes = st.f_blocks * st.f_frsize
        free_bytes = st.f_bavail * st.f_frsize
        used_bytes = total_bytes - free_bytes
        total_gb = round(total_bytes / (1024.0 ** 3), 1)
        used_gb = round(used_bytes / (1024.0 ** 3), 1)
        free_gb = round(free_bytes / (1024.0 ** 3), 1)
        pct = round(used_bytes / total_bytes * 100.0, 1) if total_bytes > 0 else 0.0
        return {"total_gb": total_gb, "used_gb": used_gb, "free_gb": free_gb, "pct": pct}
    except Exception:
        return {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0, "pct": 0.0}

def read_diskstats():
    """{device: (sectors_read, sectors_written)} for whole block devices
    only. /sys/block lists whole disks but never their own partitions, so
    filtering the /proc/diskstats device names through it is what keeps
    e.g. sda and sda1 from both being summed — that would silently double
    (or worse, N-times) every real byte moved across the disk.
    """
    out = {}
    try:
        try:
            whole = set(os.listdir("/sys/block"))
        except Exception:
            whole = set()
        with open("/proc/diskstats", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 10:
                    continue
                name = parts[2]
                if whole and name not in whole:
                    continue
                if name.startswith(("loop", "ram")):
                    continue
                out[name] = (int(parts[5]), int(parts[9]))
    except Exception:
        pass
    return out

_LAST_GPUS = []

def read_gpus():
    global _LAST_GPUS
    gpus = []
    # Try nvidia-smi
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"],
            timeout=1.2,
            text=True,
            stderr=subprocess.DEVNULL
        )
        for line in out.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                gpus.append({
                    "name": parts[0],
                    "load": float(parts[1]),
                    "vram_used": float(parts[2]),
                    "vram_total": float(parts[3]),
                    "temp": float(parts[4]),
                    "power_draw": float(parts[5]) if len(parts) >= 6 else 0.0,
                })
        if gpus:
            _LAST_GPUS = gpus
            return gpus
    except Exception:
        pass

    # Try DRM AMD/Intel
    try:
        import glob
        for dev in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
            with open(dev, "r") as f:
                load = float(f.read().strip())
            temp = 0.0
            hmon = glob.glob(os.path.dirname(dev) + "/hwmon/hwmon*/temp1_input")
            if hmon:
                with open(hmon[0], "r") as hf:
                    temp = round(float(hf.read().strip()) / 1000.0, 1)
            power = 0.0
            pmon = glob.glob(os.path.dirname(dev) + "/hwmon/hwmon*/power1_average")
            if pmon:
                try:
                    with open(pmon[0], "r") as pf:
                        power = round(float(pf.read().strip()) / 1_000_000.0, 1)  # uW -> W
                except Exception:
                    pass
            gpus.append({
                "name": "GPU",
                "load": load,
                "vram_used": 0.0,
                "vram_total": 0.0,
                "temp": temp,
                "power_draw": power,
            })
    except Exception:
        pass
    if gpus:
        _LAST_GPUS = gpus
        return gpus
    if _LAST_GPUS:
        return _LAST_GPUS
    return gpus

def read_top_processes():
    procs = []
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"],
            timeout=0.8,
            text=True,
            stderr=subprocess.DEVNULL
        )
        lines = out.strip().split("\n")[1:12]
        for line in lines:
            cols = line.split(None, 3)
            if len(cols) == 4:
                pname = cols[1]
                if pname in ("ps", "argus-sysmon.py"):
                    continue
                procs.append({
                    "pid": int(cols[0]),
                    "name": pname,
                    "cpu": float(cols[2]),
                    "mem": float(cols[3]),
                })
                if len(procs) >= 5:
                    break
    except Exception:
        pass
    return procs

def read_uptime():
    try:
        with open("/proc/uptime", "r") as f:
            secs = int(float(f.read().split()[0]))
            days = secs // 86400
            hrs = (secs % 86400) // 3600
            mins = (secs % 3600) // 60
            if days > 0:
                return f"{days}d {hrs}h {mins}m"
            return f"{hrs}h {mins}m"
    except Exception:
        return "—"

def main():
    prev_cpu = read_cpu_stat()
    prev_net = read_net_dev()
    prev_disk = read_diskstats()
    prev_time = time.time()
    
    kernel = "Linux"
    try:
        kernel = f"Linux {os.uname().release.split('-')[0]}"
    except Exception:
        pass

    hostname = "localhost"
    try:
        hostname = socket.gethostname().split(".")[0]
    except Exception:
        pass

    # CPU model doesn't change while this process runs — read it once, not
    # every second like the rest of this loop's live metrics.
    cpu_model = ""
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass

    while True:
        time.sleep(1.0)
        now_time = time.time()
        elapsed = max(0.001, now_time - prev_time)
        prev_time = now_time
        
        # 1. CPU
        cur_cpu = read_cpu_stat()
        cpu_pct = 0.0
        core_pcts = []
        if prev_cpu and cur_cpu:
            p_idle, p_tot = prev_cpu.get("cpu", (0.0, 0.0))
            c_idle, c_tot = cur_cpu.get("cpu", (0.0, 0.0))
            dt = c_tot - p_tot
            di = c_idle - p_idle
            if dt > 0:
                cpu_pct = max(0.0, min(100.0, ((dt - di) / dt) * 100.0))
            
            core_keys = [k for k in cur_cpu if k.startswith("cpu") and k != "cpu"]
            core_keys.sort(key=lambda k: int(k[3:]) if k[3:].isdigit() else 9999)
            for cname in core_keys:
                pi, pt = prev_cpu.get(cname, (0.0, 0.0))
                ci, ct = cur_cpu.get(cname, (0.0, 0.0))
                cdt = ct - pt
                cdi = ci - pi
                cpct = max(0.0, min(100.0, ((cdt - cdi) / cdt) * 100.0)) if cdt > 0 else 0.0
                core_pcts.append(round(cpct, 1))
        prev_cpu = cur_cpu
        
        cfreq, core_freqs = read_cpu_freqs()
        ctemp = read_cpu_temp()
        
        # Loadavg
        try:
            with open("/proc/loadavg", "r") as f:
                lparts = f.read().split()
                load = [float(lparts[0]), float(lparts[1]), float(lparts[2])]
        except Exception:
            load = [0.0, 0.0, 0.0]
            
        # 2. Memory
        mem = read_mem_info()
        
        # 3. Network
        cur_net = read_net_dev()
        tot_rx_rate = 0.0
        tot_tx_rate = 0.0
        tot_rx_bytes = 0
        tot_tx_bytes = 0
        active_iface = "none"
        max_traffic = -1.0
        iface_stats = []
        
        for iface, data in cur_net.items():
            rx = data["rx"]
            tx = data["tx"]
            tot_rx_bytes += rx
            tot_tx_bytes += tx
            
            prx = prev_net.get(iface, {}).get("rx", rx) if prev_net else rx
            ptx = prev_net.get(iface, {}).get("tx", tx) if prev_net else tx
            
            rx_rate = max(0.0, (rx - prx) / elapsed)  # bytes/s
            tx_rate = max(0.0, (tx - ptx) / elapsed)  # bytes/s
            tot_rx_rate += rx_rate
            tot_tx_rate += tx_rate
            
            if (rx_rate + tx_rate) > max_traffic:
                max_traffic = rx_rate + tx_rate
                active_iface = iface
                
            iface_stats.append({
                "name": iface,
                "ip": read_iface_ip(iface),
                "rx_kbps": round(rx_rate / 1024.0, 1),
                "tx_kbps": round(tx_rate / 1024.0, 1),
                "rx_total_gb": round(rx / (1024.0 ** 3), 2),
                "tx_total_gb": round(tx / (1024.0 ** 3), 2),
            })
        prev_net = cur_net
        active_ip = next((i["ip"] for i in iface_stats if i["name"] == active_iface), "")
        
        rx_kbps = round(tot_rx_rate / 1024.0, 1)
        tx_kbps = round(tot_tx_rate / 1024.0, 1)
        rx_total_gb = round(tot_rx_bytes / (1024.0 ** 3), 2)
        tx_total_gb = round(tot_tx_bytes / (1024.0 ** 3), 2)
        
        # 4. Storage (capacity + live read/write throughput)
        storage = read_storage()
        cur_disk = read_diskstats()
        read_bps = 0.0
        write_bps = 0.0
        for name, (sectors_read, sectors_written) in cur_disk.items():
            prev_sr, prev_sw = prev_disk.get(name, (sectors_read, sectors_written))
            read_bps += max(0.0, (sectors_read - prev_sr) * 512 / elapsed)
            write_bps += max(0.0, (sectors_written - prev_sw) * 512 / elapsed)
        prev_disk = cur_disk
        storage["read_kbps"] = round(read_bps / 1024.0, 1)
        storage["write_kbps"] = round(write_bps / 1024.0, 1)

        # 5. GPUs
        gpus = read_gpus()

        # 6. Processes
        procs = read_top_processes()

        # 7. Uptime
        uptime = read_uptime()

        # 8. Fans (best-effort; empty on hosts with no exposed sensor)
        fans = read_fans()

        # 9. Battery (best-effort; present=False on any desktop with none)
        battery = read_battery()

        payload = {
            "cpu": round(cpu_pct, 1),
            "cpu_cores": len(core_pcts),
            "core_loads": core_pcts,
            "core_freqs": core_freqs,
            "cpu_freq": cfreq,
            "cpu_temp": ctemp,
            "cpu_model": cpu_model,
            "load": load,
            "mem": mem,
            "net": {
                "rx_kbps": rx_kbps,
                "tx_kbps": tx_kbps,
                "rx_total_gb": rx_total_gb,
                "tx_total_gb": tx_total_gb,
                "active_iface": active_iface if active_iface != "none" else "eth0",
                "active_ip": active_ip,
                "interfaces": iface_stats,
            },
            "storage": storage,
            "gpus": gpus,
            "gpu_load": max((g.get("load", 0.0) for g in gpus), default=0.0) if gpus else 0.0,
            "gpu_temp": max((g.get("temp", 0.0) for g in gpus), default=0.0) if gpus else 0.0,
            "fans": fans,
            "battery": battery,
            "processes": procs,
            "kernel": kernel,
            "hostname": hostname,
            "uptime": uptime,
        }
        
        # Print JSON line
        print(json.dumps(payload), flush=True)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        try:
            sys.stderr.close()
        except Exception:
            pass
        sys.exit(0)
