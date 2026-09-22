#!/bin/sh
# argus-sysmon.sh — streams live system stats, one line per second:
# Consumed by shell/common/SysInfo.qml via a streaming Process.

DIR="$(cd "$(dirname "$0")" && pwd)"
if command -v python3 >/dev/null 2>&1 && [ -f "$DIR/argus-sysmon.py" ]; then
    exec python3 -u "$DIR/argus-sysmon.py" "$@"
fi

cpu_raw() {
    awk '/^cpu/ { print $1, $5+$6, $2+$3+$4+$5+$6+$7+$8+$9 }' /proc/stat
}

net_stat() {
    awk -F'[: ]+' '/:/ && $2 != "lo" { rx += $3; tx += $11 } END { printf "%d %d", rx, tx }' /proc/net/dev
}

gpu_stat() {
    if command -v nvidia-smi >/dev/null 2>&1; then
        nvidia-smi --query-gpu=utilization.gpu,temperature.gpu \
                   --format=csv,noheader,nounits 2>/dev/null | awk -F', *' '
            { u += $1; if ($2 > t) t = $2; n++ }
            END { if (n > 0) printf "%d %d", u / n, t; else printf "0 0" }'
        return
    fi
    for d in /sys/class/drm/card*/device/gpu_busy_percent; do
        [ -f "$d" ] || continue
        printf '%s ' "$(cat "$d")"
        h=$(cat "$(dirname "$d")"/hwmon/hwmon*/temp1_input 2>/dev/null | head -1)
        [ -n "$h" ] && printf '%s' "$((h / 1000))" || printf '0'
        return
    done
    printf '0 0'
}

mem_stat() {
    awk '/MemTotal/{t=$2} /MemAvailable/{a=$2}
         END { u=t-a; printf "%.1f %.1f %.0f", u/1048576, t/1048576, (t>0 ? 100*u/t : 0) }' /proc/meminfo
}

disk_stat() { df -P / 2>/dev/null | awk 'NR==2 { gsub("%","",$5); print $5 }'; }

cpu_temp() {
    for h in /sys/class/hwmon/hwmon*/temp1_input; do
        n=$(cat "$(dirname "$h")/name" 2>/dev/null)
        case "$n" in
            k10temp|coretemp|zenpower|cpu_thermal)
                t=$(cat "$h" 2>/dev/null)
                [ -n "$t" ] && [ "$t" -gt 0 ] && { printf "%d" "$((t / 1000))"; return; }
                ;;
        esac
    done
    for t in /sys/class/thermal/thermal_zone*/temp; do
        [ -f "$t" ] || continue
        v=$(cat "$t" 2>/dev/null)
        [ -n "$v" ] && [ "$v" -gt 0 ] && { printf "%d" "$((v / 1000))"; return; }
    done
    printf '0'
}

cpu_freq() {
    awk '/cpu MHz/{s+=$4; n++} END {if(n>0) printf "%.1f", s/n/1000; else printf "0.0"}' /proc/cpuinfo 2>/dev/null
}

load_stat() {
    awk '{printf "%s %s %s", $1, $2, $3}' /proc/loadavg 2>/dev/null
}

p_raw=$(cpu_raw)
set -- $(net_stat); p_rx=$1; p_tx=$2

while :; do
    sleep 1

    c_raw=$(cpu_raw)
    set -- $(awk -v p="$p_raw" -v c="$c_raw" '
    BEGIN {
        n = split(p, p_lines, "\n")
        for (i = 1; i <= n; i++) {
            split(p_lines[i], f)
            p_idle[f[1]] = f[2]; p_tot[f[1]] = f[3]
        }
        m = split(c, c_lines, "\n")
        core_str = ""
        cpu_pct = 0
        cores = 0
        for (i = 1; i <= m; i++) {
            split(c_lines[i], f)
            k = f[1]
            di = f[2] - p_idle[k]
            dt = f[3] - p_tot[k]
            pct = (dt > 0) ? int((100 * (dt - di)) / dt) : 0
            if (k == "cpu") {
                cpu_pct = pct
            } else {
                cores++
                core_str = (core_str == "" ? "" : core_str ",") pct
            }
        }
        printf "%d %d %s\n", cpu_pct, cores, core_str
    }
    ')
    cpu=$1; cores=$2; core_pcts=$3
    p_raw=$c_raw

    set -- $(net_stat); c_rx=$1; c_tx=$2
    rx=$(( (c_rx - p_rx) / 1024 )); tx=$(( (c_tx - p_tx) / 1024 ))
    [ "$rx" -lt 0 ] && rx=0
    [ "$tx" -lt 0 ] && tx=0
    p_rx=$c_rx; p_tx=$c_tx

    set -- $(mem_stat); mused=$1; mtotal=$2; mpct=$3
    set -- $(gpu_stat); gpu=$1; gtemp=$2
    disk=$(disk_stat)
    ctemp=$(cpu_temp)
    cfreq=$(cpu_freq)
    set -- $(load_stat); l1=$1; l5=$2; l15=$3

    printf '%s %s %s %s %s %s %s %s %s %s %s %s %s %s %s %s\n' \
        "$cpu" "$mpct" "$mused" "$mtotal" "$gpu" "$gtemp" "$rx" "$tx" "$disk" \
        "$ctemp" "$cfreq" "$l1" "$l5" "$l15" "$cores" "$core_pcts"
done
