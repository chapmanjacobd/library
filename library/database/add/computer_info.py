import datetime, json, os, os.path, platform, re, subprocess, sys, time
from collections import Counter
from contextlib import suppress
from pathlib import Path

INTERVAL = 5
INTERVAL_STR = "5s"

IS_LINUX = sys.platform == "linux"
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt" or sys.platform in ("win32", "cygwin", "msys")


def ordered_set(items):
    seen = set()
    for item in items:
        if item not in seen:
            yield item
            seen.add(item)


def round_floats(o, significance=2):
    if isinstance(o, float):
        return round(o, significance)
    if isinstance(o, dict):
        return {k: round_floats(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [round_floats(x) for x in o]
    return o


def _get_uptime_info(psutil):
    if IS_LINUX:
        with open("/proc/uptime", "r") as f:
            uptime_data = f.read().split()
            up_time = float(uptime_data[0])
            return {
                "up_time": int(up_time),
                "idle_percent": int(((float(uptime_data[1]) / (os.cpu_count() or 1)) / up_time) * 100),
            }

    boot_time = psutil.boot_time()
    up_time = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.datetime.fromtimestamp(
        boot_time, tz=datetime.timezone.utc
    )
    return {"up_time": int(up_time.total_seconds())}


def _linux_system_name():
    info_strings = []
    for path in (
        "/sys/class/dmi/id/sys_vendor",
        "/sys/class/dmi/id/product_name",
        "/sys/class/dmi/id/board_vendor",
        "/sys/class/dmi/id/board_name",
    ):
        with suppress(FileNotFoundError):
            value = Path(path).read_text().strip()
            if value and value != "To Be Filled By O.E.M.":
                info_strings.extend(value.split())
    return info_strings


def _windows_system_name():
    import winreg

    info_strings = []
    with suppress(PermissionError):
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System")  # type: ignore
        for value_name in ("SystemBiosVersion", "SystemProductName", "BaseBoardManufacturer", "BaseBoardProduct"):
            with suppress(FileNotFoundError):
                value, _ = winreg.QueryValueEx(key, value_name)  # type: ignore
                if value and value != "To Be Filled By O.E.M.":
                    info_strings.extend(value.split())
        winreg.CloseKey(key)  # type: ignore
    return info_strings


def _mac_system_name():
    info_strings = []
    with suppress(subprocess.CalledProcessError):
        output = subprocess.check_output(["system_profiler", "SPHardwareDataType"]).decode()
        prefixes = ("Manufacturer:", "Model Name:", "Board Manufacturer:", "Board Product:")
        for raw_line in output.splitlines():
            clean_line = raw_line.strip()
            if clean_line.startswith(prefixes):
                value = clean_line.split(":")[-1].strip()
                if value and value != "To Be Filled By O.E.M.":
                    info_strings.extend(value.split())
    return info_strings


def _get_system_name():
    if IS_LINUX:
        values = _linux_system_name()
    elif IS_WINDOWS:
        values = _windows_system_name()
    elif IS_MAC:
        values = _mac_system_name()
    else:
        values = []
    return " ".join(ordered_set(values))


def _get_bios_date():
    if IS_LINUX:
        bios_date_path = Path("/sys/class/dmi/id/bios_date")
        return bios_date_path.read_text().strip() if bios_date_path.exists() else None
    if IS_WINDOWS:
        import winreg

        with suppress(FileNotFoundError, PermissionError, OSError):
            registry_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS")  # type: ignore
            bios_date, _ = winreg.QueryValueEx(registry_key, "BIOSDate")  # type: ignore
            winreg.CloseKey(registry_key)  # type: ignore
            return bios_date
    if IS_MAC:
        with suppress(subprocess.CalledProcessError):
            output = subprocess.check_output(["/usr/sbin/ioreg", "-l"]).decode()
            for raw_line in output.splitlines():
                if "biosDate" in raw_line:
                    return raw_line.split('"')[1].strip()
    return None


def _get_processor():
    if IS_WINDOWS:
        return platform.processor()
    if IS_MAC:
        os.environ["PATH"] = os.environ["PATH"] + os.pathsep + "/usr/sbin"
        return subprocess.check_output("sysctl -n machdep.cpu.brand_string").strip()
    if IS_LINUX:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if "model name" in line:
                    return line.split(":")[1].strip()
    return None


def _get_scaling_governors():
    if IS_LINUX:
        governors = []
        for root, dirs, _files in os.walk("/sys/devices/system/cpu/"):
            for dir_name in dirs:
                if re.match(r"cpu\d+", dir_name):
                    governor_path = os.path.join(root, dir_name, "cpufreq", "scaling_governor")
                    if os.path.exists(governor_path):
                        with open(governor_path, "r") as f:
                            governors.append(f.read().strip())
        return ", ".join(t[0] for t in Counter(governors).most_common())
    if IS_WINDOWS:
        with suppress(subprocess.CalledProcessError):
            output = subprocess.check_output(["powercfg", "/getactivescheme"], text=True)
            active_scheme_line = [line for line in output.splitlines() if "Active" in line]
            return active_scheme_line[0].split(":")[-1].strip() if active_scheme_line else None
    if IS_MAC:
        with suppress(subprocess.CalledProcessError):
            output = subprocess.check_output(["sysctl", "hw"], text=True)
            cpu_freq_line = [line for line in output.splitlines() if "hw.cpufrequency" in line]
            return cpu_freq_line[0].split(":")[-1].strip() if cpu_freq_line else None
    return None


def _get_loadavg():
    if IS_LINUX:
        with open("/proc/loadavg", "r") as f:
            loadavg_data = f.read().split()
            return {
                "loadavg_1min": float(loadavg_data[0]),
                "loadavg_5min": float(loadavg_data[1]),
                "loadavg_15min": float(loadavg_data[2]),
                "proc_runnable": int(loadavg_data[3].split("/")[0]),
                "processes": int(loadavg_data[3].split("/")[1]),
            }
    if IS_MAC:
        loadavg = os.getloadavg()
        return {
            "loadavg_1min": loadavg[0],
            "loadavg_5min": loadavg[1],
            "loadavg_15min": loadavg[2],
        }
    return {}


def _get_mem_info(psutil):
    virtual_memory = psutil.virtual_memory()
    swap_memory = psutil.swap_memory()
    return {
        "mem": virtual_memory.total,
        "mem_free": virtual_memory.available,
        "mem_utilization": virtual_memory.percent,
        "system_swapped": swap_memory.sout,
        "swap": swap_memory.total,
        "swap_free": swap_memory.free,
        "swap_utilization": swap_memory.percent,
    }


def _get_mounts(psutil, uptime_info):
    disk_io = psutil.disk_io_counters(perdisk=True)
    mounts = {}
    for partition in psutil.disk_partitions():
        mountpoint = partition.mountpoint
        if mountpoint in [os.sep, "/var", "/etc", "/usr"] or mountpoint.startswith(("/boot", "/sysroot")):
            continue
        if mountpoint in ("/", "/home", "/var/home"):
            mountpoint = os.path.expanduser("~")
        try:
            usage = psutil.disk_usage(mountpoint)
        except PermissionError:  # CD-ROM, etc
            print(f"PermissionError: Skipping {mountpoint}", file=sys.stderr)
            continue

        mapped_device = (
            os.path.realpath(partition.device) if partition.device.startswith("/dev/mapper/") else partition.device
        )
        device_key = mapped_device.replace("\\", "/").split("/")[-1]
        io = disk_io.get(device_key)
        mounts[mountpoint] = {
            "path": mountpoint,
            "fstype": partition.fstype,
            "total": usage.total,
            "free": usage.free,
            "device": mapped_device,
            "device_read": getattr(io, "read_bytes", 0),
            "device_write": getattr(io, "write_bytes", 0),
            "device_read_ms": getattr(io, "read_time", 0),
            "device_write_ms": getattr(io, "write_time", 0),
            "device_utilization": int(
                (((getattr(io, "read_time", 0) + getattr(io, "write_time", 0)) / 1000) / uptime_info["up_time"]) * 100
            ),
        }
    return mounts


def _get_disk_info(initial_mounts, final_mounts):
    disk_info = []
    for mountpoint, final_info in final_mounts.items():
        initial_info = initial_mounts.get(mountpoint)
        if initial_info is None:
            print(f"Mountpoint {mountpoint} not found in initial mounts; skipping", file=sys.stderr)
            continue
        device_read = (final_info.pop("device_read_ms") - initial_info.pop("device_read_ms")) / 1000
        device_write = (final_info.pop("device_write_ms") - initial_info.pop("device_write_ms")) / 1000
        disk_info.append(
            {
                **final_info,
                f"freed_{INTERVAL_STR}": final_info["free"] - initial_info["free"],
                f"device_read_{INTERVAL_STR}": final_info["device_read"] - initial_info["device_read"],
                f"device_write_{INTERVAL_STR}": final_info["device_write"] - initial_info["device_write"],
                "device_read_utilization": (device_read / INTERVAL) * 100,
                "device_write_utilization": (device_write / INTERVAL) * 100,
            }
        )
    return disk_info


def _get_network_io(initial_net_io, final_net_io):
    return {
        f"network_sent_{INTERVAL_STR}": final_net_io.bytes_sent - initial_net_io.bytes_sent,
        f"network_recv_{INTERVAL_STR}": final_net_io.bytes_recv - initial_net_io.bytes_recv,
    }


def computer_info():
    import psutil

    uptime_info = _get_uptime_info(psutil)
    _initial_cpu_times = psutil.cpu_times_percent()  # internal tracking
    initial_mounts = _get_mounts(psutil, uptime_info)
    initial_net_io = psutil.net_io_counters()
    time.sleep(INTERVAL)
    final_mounts = _get_mounts(psutil, uptime_info)
    final_net_io = psutil.net_io_counters()

    cpu_times = psutil.cpu_times_percent()
    cpu_percent = cpu_times.system + cpu_times.user + cpu_times.irq + cpu_times.softirq + cpu_times.steal
    info = {
        "node": platform.node(),
        "board_name": _get_system_name(),
        "bios_date": _get_bios_date(),
        "processor": _get_processor(),
        "platform": platform.platform(),
        **uptime_info,
        "cpu_utilization": int(cpu_percent),
        "cpu_idle": int(cpu_times.idle),
        "cpu_iowait": int(cpu_times.iowait),
        "cpu_scaling": _get_scaling_governors(),
        **_get_loadavg(),
        **_get_mem_info(psutil),
        **_get_network_io(initial_net_io, final_net_io),
        "disks": _get_disk_info(initial_mounts, final_mounts),
    }
    print(json.dumps(round_floats(info)))


if __name__ == "__main__":
    computer_info()
