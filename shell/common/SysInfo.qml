pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Live system telemetry singleton, streamed from scripts/argus-sysmon.sh (one line/second)
// Provides 100% accurate CPU, Core equalizers, Memory/Swap breakdown, Network I/O, Dual GPUs,
// Storage, and Top Processes with historical buffers for micro sparklines.
QtObject {
    id: sys

    // ── CPU Metrics ───────────────────────────────────────────────────────
    property real cpu: 0
    property int cpuCores: 0
    property var coreLoads: []
    property real cpuTemp: 0
    property real cpuFreq: 0
    property string cpuModel: ""
    property real load1: 0
    property real load5: 0
    property real load15: 0

    // ── Memory & Swap ────────────────────────────────────────────────────
    property real memPct: 0
    property real memUsed: 0
    property real memTotal: 0
    property real memAvail: 0
    property real memFree: 0
    property real memCached: 0
    property real memBuffers: 0
    property real swapUsed: 0
    property real swapTotal: 0
    property real swapPct: 0

    // ── Network I/O ───────────────────────────────────────────────────────
    property real rx: 0          // KB/s
    property real tx: 0          // KB/s
    property real rxTotalGb: 0   // Cumulative session GB
    property real txTotalGb: 0   // Cumulative session GB
    property string netIface: "eth0"
    property string netIp: ""
    property var netInterfaces: []

    // ── GPU Telemetry ─────────────────────────────────────────────────────
    property real gpu: 0
    property real gpuTemp: 0
    property var gpus: []

    // ── Storage ───────────────────────────────────────────────────────────
    property real disk: 0
    property real diskUsedGb: 0
    property real diskTotalGb: 0
    property real diskFreeGb: 0
    property real diskReadKbps: 0
    property real diskWriteKbps: 0

    // ── Per-core frequency & fan sensors ────────────────────────────────
    // coreFreqs is index-aligned with coreLoads (both walk cpu0, cpu1, ...
    // in order — see argus-sysmon.py's read_cpu_freqs()). fans is empty,
    // not a placeholder zero entry, on hosts with no exposed sensor.
    property var coreFreqs: []
    property var fans: []

    // ── Battery (laptops only) ────────────────────────────────────────────
    // batteryPresent gates the UI entirely — a desktop with no battery gets
    // no stat at all, not a permanent "no battery" placeholder.
    property bool batteryPresent: false
    property int batteryPct: 0
    property bool batteryCharging: false
    property string batteryStatus: ""

    // ── Processes & Host Metadata ─────────────────────────────────────────
    property var topProcs: []
    property string kernel: "Linux"
    property string hostname: ""
    property string uptime: "—"

    property bool ready: false

    // ── Rolling Sparkline Histories ──────────────────────────────────────
    property var cpuHist: []
    property var cpuTempHist: []
    property var cpuFreqHist: []
    property var memHist: []
    property var swapHist: []
    property var gpuHist: []
    property var netHist: []
    property var rxHist: []
    property var txHist: []
    property var diskIoHist: []
    readonly property int histLen: 48

    function push(arr, v) {
        var a = (arr || []).slice();
        a.push(v);
        while (a.length > histLen) a.shift();
        return a;
    }

    property Process monitor: Process {
        command: ["sh", Quickshell.shellDir + "/../scripts/argus-sysmon.sh"]
        running: true
        stdout: SplitParser {
            onRead: function (line) { sys.ingest(line); }
        }
    }

    function ingest(line) {
        var str = String(line).trim();
        if (str === "") return;
        if (str.charAt(0) === "{") {
            try {
                var d = JSON.parse(str);
                applyJson(d);
                return;
            } catch (e) {}
        }
        applyLegacy(str);
    }

    function applyJson(d) {
        if (!d) return;
        cpu = d.cpu !== undefined ? d.cpu : 0;
        cpuCores = d.cpu_cores || 0;
        coreLoads = d.core_loads || [];
        coreFreqs = d.core_freqs || [];
        cpuFreq = d.cpu_freq || 0;
        cpuTemp = d.cpu_temp || 0;
        if (d.cpu_model) cpuModel = d.cpu_model;
        if (d.load && d.load.length >= 3) {
            load1 = d.load[0];
            load5 = d.load[1];
            load15 = d.load[2];
        }

        if (d.mem) {
            memUsed = d.mem.used_gb || 0;
            memTotal = d.mem.total_gb || 0;
            memAvail = d.mem.avail_gb || 0;
            memFree = d.mem.free_gb || 0;
            memCached = d.mem.cached_gb || 0;
            memBuffers = d.mem.buffers_gb || 0;
            memPct = d.mem.pct || 0;
            swapUsed = d.mem.swap_used_gb || 0;
            swapTotal = d.mem.swap_total_gb || 0;
            swapPct = d.mem.swap_pct || 0;
        }

        if (d.net) {
            rx = d.net.rx_kbps || 0;
            tx = d.net.tx_kbps || 0;
            rxTotalGb = d.net.rx_total_gb || 0;
            txTotalGb = d.net.tx_total_gb || 0;
            netIface = d.net.active_iface || "eth0";
            netIp = d.net.active_ip || "";
            netInterfaces = d.net.interfaces || [];
        }

        if (d.storage) {
            disk = d.storage.pct || 0;
            diskUsedGb = d.storage.used_gb || 0;
            diskTotalGb = d.storage.total_gb || 0;
            diskFreeGb = d.storage.free_gb || 0;
            diskReadKbps = d.storage.read_kbps || 0;
            diskWriteKbps = d.storage.write_kbps || 0;
        }

        gpus = d.gpus || [];
        if (gpus.length > 0) {
            if (d.gpu_load !== undefined) {
                gpu = d.gpu_load;
                gpuTemp = d.gpu_temp || 0;
            } else {
                var maxL = 0;
                var maxT = 0;
                for (var gi = 0; gi < gpus.length; gi++) {
                    if ((gpus[gi].load || 0) > maxL) maxL = gpus[gi].load;
                    if ((gpus[gi].temp || 0) > maxT) maxT = gpus[gi].temp;
                }
                gpu = maxL;
                gpuTemp = maxT;
            }
        } else {
            gpu = 0;
            gpuTemp = 0;
        }

        fans = d.fans || [];
        if (d.battery) {
            batteryPresent = !!d.battery.present;
            batteryPct = d.battery.pct || 0;
            batteryCharging = !!d.battery.charging;
            batteryStatus = d.battery.status || "";
        }
        topProcs = d.processes || [];
        if (d.kernel) kernel = d.kernel;
        if (d.hostname) hostname = d.hostname;
        if (d.uptime) uptime = d.uptime;

        cpuHist = push(cpuHist, cpu);
        memHist = push(memHist, memPct);
        gpuHist = push(gpuHist, gpu);
        netHist = push(netHist, rx + tx);
        rxHist = push(rxHist, rx);
        txHist = push(txHist, tx);
        if (cpuTemp > 0) cpuTempHist = push(cpuTempHist, cpuTemp);
        if (cpuFreq > 0) cpuFreqHist = push(cpuFreqHist, cpuFreq);
        swapHist = push(swapHist, swapPct);
        diskIoHist = push(diskIoHist, diskReadKbps + diskWriteKbps);
        ready = true;
    }

    function applyLegacy(line) {
        var p = line.split(/\s+/);
        if (p.length < 9) return;
        cpu = parseFloat(p[0]) || 0;
        memPct = parseFloat(p[1]) || 0;
        memUsed = parseFloat(p[2]) || 0;
        memTotal = parseFloat(p[3]) || 0;
        gpu = parseFloat(p[4]) || 0;
        gpuTemp = parseFloat(p[5]) || 0;
        rx = parseFloat(p[6]) || 0;
        tx = parseFloat(p[7]) || 0;
        disk = parseFloat(p[8]) || 0;

        if (p.length >= 10) cpuTemp = parseFloat(p[9]) || 0;
        if (p.length >= 11) cpuFreq = parseFloat(p[10]) || 0;
        if (p.length >= 12) load1 = parseFloat(p[11]) || 0;
        if (p.length >= 13) load5 = parseFloat(p[12]) || 0;
        if (p.length >= 14) load15 = parseFloat(p[13]) || 0;
        if (p.length >= 15) cpuCores = parseInt(p[14]) || 0;
        if (p.length >= 16 && p[15]) {
            var rawCores = p[15].split(",");
            var parsed = [];
            for (var i = 0; i < rawCores.length; i++) {
                parsed.push(parseFloat(rawCores[i]) || 0);
            }
            coreLoads = parsed;
        }

        cpuHist = push(cpuHist, cpu);
        memHist = push(memHist, memPct);
        gpuHist = push(gpuHist, gpu);
        netHist = push(netHist, rx + tx);
        if (AgentState.sysOpen) {
            if (cpuTemp > 0) cpuTempHist = push(cpuTempHist, cpuTemp);
            if (cpuFreq > 0) cpuFreqHist = push(cpuFreqHist, cpuFreq);
        }
        ready = true;
    }

    function fmtGB(v) { return (Math.round(v * 10) / 10).toFixed(1); }
    function fmtNet(kbps) {
        if (kbps >= 1048576) return (kbps / 1048576).toFixed(2) + " GB/s";
        if (kbps >= 1024) return (kbps / 1024).toFixed(1) + " MB/s";
        return Math.round(kbps) + " KB/s";
    }
    function fmtFreq(ghz) {
        if (ghz <= 0) return "—";
        return (Math.round(ghz * 10) / 10).toFixed(1) + " GHz";
    }
    function fmtTemp(c) {
        if (c <= 0) return "—";
        return Math.round(c) + "°C";
    }
    function fmtPct(p) {
        return Math.round(p) + "%";
    }
}
