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


def computer_info():
    import psutil

    def get_uptime_info():
        if IS_LINUX:
            with open("/proc/uptime", "r") as f:
                uptime_data = f.read().split()
                up_time = float(uptime_data[0])
                return {
                    "up_time": int(up_time),
                    "idle_percent": int(((float(uptime_data[1]) / (os.cpu_count() or 1)) / up_time) * 100),
                }
        else:  # macOS, Windows
            boot_time = psutil.boot_time()
            up_time = datetime.datetime.now() - datetime.datetime.fromtimestamp(boot_time)
            return {
                "up_time": int(up_time.total_seconds()),
            }

    uptime_info = get_uptime_info()

    def get_system_name():
        ignore_text = ["To Be Filled By O.E.M."]
        info_strings = []

        if IS_LINUX:
            paths = [
                "/sys/class/dmi/id/sys_vendor",
                "/sys/class/dmi/id/product_name",
                "/sys/class/dmi/id/board_vendor",
                "/sys/class/dmi/id/board_name",
            ]
            for path in paths:
                with suppress(FileNotFoundError):
                    s = Path(path).read_text().strip()
                    if s and s not in ignore_text:
                        info_strings.extend(s.split())

        elif IS_WINDOWS:
            import winreg

            with suppress(PermissionError):
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System")  # type: ignore
                value_names = [
                    "SystemBiosVersion",
                    "SystemProductName",
                    "BaseBoardManufacturer",
                    "BaseBoardProduct",
                ]
                for val_name in value_names:
                    with suppress(FileNotFoundError):
                        s, _ = winreg.QueryValueEx(key, val_name)  # type: ignore
                        if s and s not in ignore_text:
                            info_strings.extend(s.split())
                winreg.CloseKey(key)  # type: ignore

        elif IS_MAC:
            with suppress(subprocess.CalledProcessError):
                output = subprocess.check_output(["system_profiler", "SPHardwareDataType"]).decode()
                lines = output.splitlines()
                for line in lines:
                    line = line.strip()
                    if line.startswith("Manufacturer:"):
                        s = line.split(":")[-1].strip()
                        if s and s not in ignore_text:
                            info_strings.extend(s.split())
                    elif line.startswith("Model Name:"):
                        s = line.split(":")[-1].strip()
                        if s and s not in ignore_text:
                            info_strings.extend(s.split())
                    elif line.startswith("Board Manufacturer:"):
                        s = line.split(":")[-1].strip()
                        if s and s not in ignore_text:
                            info_strings.extend(s.split())
                    elif line.startswith("Board Product:"):
                        s = line.split(":")[-1].strip()
                        if s and s not in ignore_text:
                            info_strings.extend(s.split())

        unique_info = ordered_set(info_strings)
        result = " ".join(unique_info)
        return result

    def get_bios_date():
        if IS_LINUX:
            bios_date_path = Path("/sys/class/dmi/id/bios_date")
            if bios_date_path.exists():
                return bios_date_path.read_text().strip()
        elif IS_WINDOWS:
            import winreg

            with suppress(FileNotFoundError, PermissionError, OSError):
                registry_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS")  # type: ignore
                bios_date, _ = winreg.QueryValueEx(registry_key, "BIOSDate")  # type: ignore
                winreg.CloseKey(registry_key)  # type: ignore
                return bios_date
        elif IS_MAC:
            with suppress(subprocess.CalledProcessError):
                output = subprocess.check_output(["/usr/sbin/ioreg", "-l"]).decode()
                for line in output.splitlines():
                    if "biosDate" in line:
                        # Extract the date from the line
                        bios_date = line.split('"')[1].strip()
                        return bios_date

    def get_processor():
        if IS_WINDOWS:
            return platform.processor()
        elif IS_MAC:
            os.environ["PATH"] = os.environ["PATH"] + os.pathsep + "/usr/sbin"
            command = "sysctl -n machdep.cpu.brand_string"
            return subprocess.check_output(command).strip()
        elif IS_LINUX:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":")[1].strip()

    def get_scaling_governors():
        if IS_LINUX:
            governors = []
            for root, dirs, files in os.walk("/sys/devices/system/cpu/"):
                for dir_name in dirs:
                    if re.match(r"cpu\d+", dir_name):
                        governor_path = os.path.join(root, dir_name, "cpufreq", "scaling_governor")
                        if os.path.exists(governor_path):
                            with open(governor_path, "r") as f:
                                governors.append(f.read().strip())
            return ", ".join(t[0] for t in Counter(governors).most_common())

        elif IS_WINDOWS:
            with suppress(subprocess.CalledProcessError):
                output = subprocess.check_output(["powercfg", "/getactivescheme"], text=True)
                active_scheme_line = [line for line in output.splitlines() if "Active" in line]
                if active_scheme_line:
                    active_scheme = active_scheme_line[0].split(":")[-1].strip()
                    return active_scheme

        elif IS_MAC:
            with suppress(subprocess.CalledProcessError):
                output = subprocess.check_output(["sysctl", "hw"], text=True)
                cpu_freq_line = [line for line in output.splitlines() if "hw.cpufrequency" in line]
                if cpu_freq_line:
                    cpu_freq = cpu_freq_line[0].split(":")[-1].strip()
                    return cpu_freq

    def get_loadavg():
        if IS_LINUX:
            with open("/proc/loadavg", "r") as f:
                loadavg_data = f.read().split()
                return {
                    "loadavg_1min": float(loadavg_data[0]),
                    "loadavg_5min": float(loadavg_data[1]),
                    "loadavg_15min": float(loadavg_data[2]),
                    "proc_runnable": int(loadavg_data[3].split("/")[0]),
                    "processes": int(loadavg_data[3].split("/")[1]),
                    # 'latest_pid': int(loadavg_data[4])
                }
        elif IS_MAC:
            loadavg = os.getloadavg()
            return {
                "loadavg_1min": loadavg[0],
                "loadavg_5min": loadavg[1],
                "loadavg_15min": loadavg[2],
            }
        return {}

    def get_mem_info():
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

    def get_mounts():
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
            else:
                mapped_device = (
                    os.path.realpath(partition.device)
                    if partition.device.startswith("/dev/mapper/")
                    else partition.device
                )
                device_key = mapped_device.replace("\\", "/").split("/")[-1]  # without /dev/ prefix
                io = disk_io[device_key]

                # TODO: IO is counted multiple times for devices with multiple mount points (btrfs subvols)

                mounts[mountpoint] = {
                    "path": mountpoint,
                    "fstype": partition.fstype,
                    "total": usage.total,
                    "free": usage.free,
                    "device": mapped_device,
                    "device_read": io.read_bytes,
                    "device_write": io.write_bytes,
                    "device_read_ms": io.read_time,
                    "device_write_ms": io.write_time,
                    "device_utilization": int((((io.read_time + io.write_time) / 1000) / uptime_info["up_time"]) * 100),
                }

        return mounts

    def get_disk_info(initial_mounts, final_mounts):
        disk_info = []

        for mountpoint, final_info in final_mounts.items():
            initial_info = initial_mounts[mountpoint]

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

    def get_network_io(initial_net_io, final_net_io):
        sent = final_net_io.bytes_sent - initial_net_io.bytes_sent
        recv = final_net_io.bytes_recv - initial_net_io.bytes_recv

        return {
            f"network_sent_{INTERVAL_STR}": sent,
            f"network_recv_{INTERVAL_STR}": recv,
        }

    _initial_cpu_times = psutil.cpu_times_percent()  # internal tracking

    initial_mounts = get_mounts()
    initial_net_io = psutil.net_io_counters()
    time.sleep(INTERVAL)
    final_mounts = get_mounts()
    final_net_io = psutil.net_io_counters()

    cpu_times = psutil.cpu_times_percent()
    cpu_percent = cpu_times.system + cpu_times.user + cpu_times.irq + cpu_times.softirq + cpu_times.steal

    computer_info = {
        "node": platform.node(),
        "board_name": get_system_name(),
        "bios_date": get_bios_date(),
        "processor": get_processor(),
        "platform": platform.platform(),
        **uptime_info,
        "cpu_utilization": int(cpu_percent),
        "cpu_idle": int(cpu_times.idle),
        "cpu_iowait": int(cpu_times.iowait),
        "cpu_scaling": get_scaling_governors(),
        **get_loadavg(),
        **get_mem_info(),
        **get_network_io(initial_net_io, final_net_io),
        "disks": get_disk_info(initial_mounts, final_mounts),
    }

    print(json.dumps(round_floats(computer_info)))


if __name__ == "__main__":
    computer_info()
