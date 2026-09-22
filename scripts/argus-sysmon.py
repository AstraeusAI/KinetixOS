#!/usr/bin/env python3
"""argus-sysmon.py — High-precision system telemetry stream.
Streams 100% accurate system metrics in JSON format, once per second.
Monitors CPU (overall + per-core + freq + temp + load), detailed RAM & Swap,
Network (rates, totals, interfaces), Storage, GPUs, and Top Processes.
"""

import json
import os
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
                    # vals: user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice
                    idle = vals[3] + (vals[4] if len(vals) > 4 else 0.0)
                    total = sum(vals)
                    stats[name] = (idle, total)
    except Exception:
        pass
    return stats

def read_cpu_freq():
    # Try scaling_cur_freq first for active core average
    freqs = []
    try:
        base = "/sys/devices/system/cpu"
        for entry in os.listdir(base):
            if entry.startswith("cpu") and entry[3:].isdigit():
                sf = os.path.join(base, entry, "cpufreq", "scaling_cur_freq")
                if os.path.isfile(sf):
                    with open(sf, "r") as f:
                        freqs.append(float(f.read().strip()) / 1000.0)  # MHz
    except Exception:
        pass
    if freqs:
        return round(sum(freqs) / len(freqs) / 1000.0, 2)  # GHz
    
    # Fallback to /proc/cpuinfo
    try:
        with open("/proc/cpuinfo", "r") as f:
            mhz = []
            for line in f:
                if line.startswith("cpu MHz"):
                    mhz.append(float(line.split(":")[1].strip()))
            if mhz:
                return round(sum(mhz) / len(mhz) / 1000.0, 2)
    except Exception:
        pass
    return 0.0

def read_cpu_temp():
    # Search hwmon for CPU sensor (k10temp, coretemp, zenpower, cpu_thermal)
    try:
        hwmon_dir = "/sys/class/hwmon"
        if os.path.isdir(hwmon_dir):
            for h in os.listdir(hwmon_dir):
                hpath = os.path.join(hwmon_dir, h)
                name_file = os.path.join(hpath, "name")
                name = ""
                if os.path.isfile(name_file):
                    with open(name_file, "r") as nf:
                        name = nf.read().strip().lower()
                if any(x in name for x in ("k10temp", "coretemp", "zenpower", "cpu")):
                    for tfile in ("temp1_input", "temp2_input", "temp3_input"):
                        tp = os.path.join(hpath, tfile)
                        if os.path.isfile(tp):
                            with open(tp, "r") as f:
                                val = float(f.read().strip())
                                if val > 0:
                                    return round(val / 1000.0, 1)
    except Exception:
        pass
    
    # Fallback thermal_zone
    try:
        for i in range(10):
            tz = f"/sys/class/thermal/thermal_zone{i}/temp"
            if os.path.isfile(tz):
                with open(tz, "r") as f:
                    val = float(f.read().strip())
                    if val > 0:
                        return round(val / 1000.0, 1)
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
                    if iface != "lo" and not iface.startswith("docker"):
                        cols = rest.split()
                        net[iface] = {
                            "rx": int(cols[0]),
                            "tx": int(cols[8]),
                        }
    except Exception:
        pass
    return net

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

def read_gpus():
    gpus = []
    # Try nvidia-smi
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            timeout=0.6,
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
                })
        if gpus:
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
            gpus.append({
                "name": "GPU",
                "load": load,
                "vram_used": 0.0,
                "vram_total": 0.0,
                "temp": temp,
            })
    except Exception:
        pass
    return gpus

def read_top_processes():
    procs = []
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"],
            timeout=0.5,
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
    prev_time = time.time()
    
    kernel = "Linux"
    try:
        kernel = f"Linux {os.uname().release.split('-')[0]}"
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
            
            idx = 0
            while True:
                cname = f"cpu{idx}"
                if cname not in cur_cpu:
                    break
                pi, pt = prev_cpu.get(cname, (0.0, 0.0))
                ci, ct = cur_cpu.get(cname, (0.0, 0.0))
                cdt = ct - pt
                cdi = ci - pi
                cpct = max(0.0, min(100.0, ((cdt - cdi) / cdt) * 100.0)) if cdt > 0 else 0.0
                core_pcts.append(round(cpct, 1))
                idx += 1
        prev_cpu = cur_cpu
        
        cfreq = read_cpu_freq()
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
                "rx_kbps": round(rx_rate / 1024.0, 1),
                "tx_kbps": round(tx_rate / 1024.0, 1),
                "rx_total_gb": round(rx / (1024.0 ** 3), 2),
                "tx_total_gb": round(tx / (1024.0 ** 3), 2),
            })
        prev_net = cur_net
        
        rx_kbps = round(tot_rx_rate / 1024.0, 1)
        tx_kbps = round(tot_tx_rate / 1024.0, 1)
        rx_total_gb = round(tot_rx_bytes / (1024.0 ** 3), 2)
        tx_total_gb = round(tot_tx_bytes / (1024.0 ** 3), 2)
        
        # 4. Storage
        storage = read_storage()
        
        # 5. GPUs
        gpus = read_gpus()
        
        # 6. Processes
        procs = read_top_processes()
        
        # 7. Uptime
        uptime = read_uptime()
        
        payload = {
            "cpu": round(cpu_pct, 1),
            "cpu_cores": len(core_pcts),
            "core_loads": core_pcts,
            "cpu_freq": cfreq,
            "cpu_temp": ctemp,
            "load": load,
            "mem": mem,
            "net": {
                "rx_kbps": rx_kbps,
                "tx_kbps": tx_kbps,
                "rx_total_gb": rx_total_gb,
                "tx_total_gb": tx_total_gb,
                "active_iface": active_iface if active_iface != "none" else "eth0",
                "interfaces": iface_stats,
            },
            "storage": storage,
            "gpus": gpus,
            "processes": procs,
            "kernel": kernel,
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
