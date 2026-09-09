import sys
import time
import struct
import threading
import subprocess
import socket
import platform
import os
import glob
import json
import re
import io
import math
from datetime import datetime, timedelta, timezone

import usb.core
import usb.util
import psutil
import numpy as np
import serial
from serial.tools.list_ports import comports
from PIL import Image, ImageDraw, ImageFont

STATS_LOCK = threading.Lock()

# Tenta importar pystray apenas se houver um ambiente gráfico, para evitar erro no serviço systemd
pystray = None
if os.environ.get("DISPLAY"):
    try:
        import pystray
        from pystray import MenuItem as item
    except Exception:
        pystray = None
else:
    pystray = None

# Configurações de Path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.expanduser("~/.config/big-screen-monitor/settings.json")

def get_settings():
    default_settings = {
        "model": "auto",
        "size": "3.5",
        "orientation": "horizontal",
        "brightness": 70,
        "theme": "dark",
        "network_iface": "auto"
    }
    
    config_path = CONFIG_FILE
    
    # Se rodar como root, tenta encontrar o arquivo de config do usuário
    if os.getuid() == 0 and not os.path.exists(config_path):
        # Tenta pegar do ambiente se o sudo/pkexec passou
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user:
            user_config = os.path.expanduser(f"~{sudo_user}/.config/big-screen-monitor/settings.json")
            if os.path.exists(user_config):
                config_path = user_config
        else:
            # Fallback: procura o primeiro usuário em /home que tenha a config
            for user_home in glob.glob("/home/*"):
                test_path = os.path.join(user_home, ".config/big-screen-monitor/settings.json")
                if os.path.exists(test_path):
                    config_path = test_path
                    break

    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                default_settings.update(json.load(f))
        except Exception:
            pass
    return default_settings

def get_theme_colors(theme_name):
    themes = {
        "dark": {
            "bg": (18, 18, 25), "panel_bg": (30, 30, 40), "text_main": (255, 255, 255),
            "text_muted": (180, 180, 200), "text_label": (200, 200, 220), "time": (77, 217, 255),
            "good": (77, 217, 112), "warn": (249, 217, 35), "crit": (255, 85, 85),
            "vram": (215, 120, 255), "swap": (77, 150, 255), "disk": (200, 200, 200),
            "temp_line": (249, 100, 35), "bar_bg": (40, 40, 50), "border": (60, 60, 80),
            "icon_color": (255, 255, 255)
        },
        "light": {
            "bg": (231, 239, 248), "panel_bg": (250, 252, 255), "text_main": (24, 35, 52),
            "text_muted": (83, 101, 124), "text_label": (42, 91, 138), "time": (0, 105, 192),
            "good": (24, 148, 91), "warn": (190, 119, 0), "crit": (198, 56, 79),
            "vram": (105, 76, 180), "swap": (25, 111, 190), "disk": (102, 119, 137),
            "temp_line": (214, 98, 28), "bar_bg": (215, 226, 238), "border": (184, 202, 222),
            "icon_color": (42, 82, 117)
        },
        "neon": {
            "bg": (10, 5, 20), "panel_bg": (20, 10, 40), "text_main": (255, 255, 255),
            "text_muted": (255, 105, 180), "text_label": (0, 255, 255), "time": (255, 0, 255),
            "good": (57, 255, 20), "warn": (255, 255, 0), "crit": (255, 49, 49),
            "vram": (157, 0, 255), "swap": (0, 255, 255), "disk": (200, 200, 200),
            "temp_line": (255, 165, 0), "bar_bg": (40, 20, 60), "border": (80, 40, 120),
            "icon_color": (255, 255, 255)
        },
        "cyberpunk": {
            "bg": (2, 2, 4), "panel_bg": (10, 10, 15), "text_main": (253, 237, 5),
            "text_muted": (153, 143, 3), "text_label": (255, 99, 146), "time": (0, 240, 255),
            "good": (22, 198, 12), "warn": (253, 237, 5), "crit": (255, 25, 76),
            "vram": (138, 43, 226), "swap": (0, 240, 255), "disk": (200, 200, 200),
            "temp_line": (255, 140, 0), "bar_bg": (20, 20, 30), "border": (253, 237, 5),
            "icon_color": (255, 255, 255)
        },
        "gkrellm": {
            "bg": (0, 0, 0), "panel_bg": (0, 0, 0), "text_main": (170, 255, 170),
            "text_muted": (85, 170, 85), "text_label": (85, 170, 85), "time": (170, 255, 170),
            "good": (170, 255, 170), "warn": (170, 255, 170), "crit": (170, 255, 170),
            "vram": (170, 255, 170), "swap": (170, 255, 170), "disk": (170, 255, 170),
            "temp_line": (170, 255, 170), "bar_bg": (0, 0, 0), "border": (85, 170, 85),
            "icon_color": (170, 255, 170)
        },
        "planet": {
            "bg": (3, 7, 18), "panel_bg": (7, 17, 36), "text_main": (229, 245, 255),
            "text_muted": (103, 157, 190), "text_label": (121, 211, 255), "time": (188, 239, 255),
            "good": (67, 231, 190), "warn": (255, 190, 84), "crit": (255, 91, 112),
            "vram": (169, 123, 255), "swap": (61, 157, 255), "disk": (120, 210, 235),
            "temp_line": (255, 129, 75), "bar_bg": (12, 38, 64), "border": (29, 107, 151),
            "icon_color": (125, 220, 255)
        },
        "old_computer": {
            "bg": (192, 192, 192), "panel_bg": (192, 192, 192), "text_main": (64, 64, 64),
            "text_muted": (64, 64, 64), "text_label": (0, 0, 128), "time": (0, 0, 128),
            "good": (0, 205, 0), "warn": (128, 128, 0), "crit": (180, 0, 0),
            "vram": (0, 0, 180), "swap": (0, 0, 128), "disk": (64, 64, 64),
            "temp_line": (0, 160, 0), "bar_bg": (0, 32, 0), "border": (0, 0, 128),
            "icon_color": (0, 0, 128)
        }
    }
    # Fallback default para temas customizados ou incompletos
    theme = themes.get(theme_name, themes["dark"])
    if "icon_color" not in theme:
        theme["icon_color"] = (255, 255, 255) if theme_name != "light" else (40, 40, 45)
    return theme

# ================= BACKGROUND MONITOR =================
SYSTEM_STATS = {
    "cpu_percent": 0.0,
    "cpu_temp": "?°C",
    "ram_used_mb": 0,
    "ram_total_mb": 0,
    "ram_percent": 0.0,
    "swap_used_mb": 0,
    "swap_total_mb": 0,
    "swap_percent": 0.0,
    "disk_percent": 0.0,
    "disk_text": "0/0 GB",
    "net_rx_mbps": 0.0,
    "net_tx_mbps": 0.0,
    "gpus": [],
    "cpu_cores_history": [],
    "cpu_cores_percent": [],
    "active_gpu_idx": 0,
    "procs": [],
    "hostname": socket.gethostname(),
    "kernel": platform.release(),
    "kernel_offset": 0,
    "kernel_dir": 1,
    "gpu_marquee_offset": 0,
    "gpu_marquee_dir": 1,
    "power_profile": "",
    "cpu_user": 0.0,
    "cpu_system": 0.0,
}

# Historico para linha CPU Temp, CPU Uso e RAM Uso
CPU_TEMP_HISTORY = [0] * 30
CPU_USAGE_HISTORY = [0] * 30
CPU_USER_HISTORY = [0] * 30
CPU_SYSTEM_HISTORY = [0] * 30
RAM_USAGE_HISTORY = [0] * 30
GPU_USAGE_HISTORY = [0] * 30
GPU_MEM_HISTORY = [0] * 30
DISK_IO_HISTORY = [0] * 30
NET_RX_HISTORY = [0] * 30
NET_TX_HISTORY = [0] * 30

# Cache Global de Icones SVG 
ICON_CACHE = {}

_LOGO_CACHE = {}

def load_distro_logo(logo_name, size):
    """Load distro logo from /usr/share/pixmaps/, supporting PNG and SVG."""
    cache_key = f"{logo_name}_{size}"
    if cache_key in _LOGO_CACHE:
        return _LOGO_CACHE[cache_key]

    base = f"/usr/share/pixmaps/{logo_name}"
    for ext in (".png", ".svg"):
        path = base + ext
        if not os.path.exists(path):
            continue
        try:
            if ext == ".svg":
                p = subprocess.run(
                    ["rsvg-convert", "-w", str(size), "-h", str(size), path],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
                if p.returncode == 0:
                    logo = Image.open(io.BytesIO(p.stdout)).convert("RGBA")
                    _LOGO_CACHE[cache_key] = logo
                    return logo
            else:
                logo = Image.open(path).convert("RGBA")
                try:
                    resamp = Image.Resampling.LANCZOS
                except AttributeError:
                    resamp = 1
                logo.thumbnail((size, size), resamp)
                _LOGO_CACHE[cache_key] = logo
                return logo
        except Exception:
            continue
    return None

def get_svg_icon(name, size, color=None):
    cache_key = f"{name}_{size}_{color}"
    if cache_key in ICON_CACHE:
        return ICON_CACHE[cache_key]
        
    path = os.path.join(BASE_DIR, "img", name)
    if os.path.exists(path):
        try:
            if color:
                with open(path, 'r') as f:
                    svg_data = f.read()
                
                # Converte tupla (R, G, B) para Hex
                c_hex = '#{:02x}{:02x}{:02x}'.format(*color) if isinstance(color, tuple) else color
                
                # Substituição robusta usando Regex: 
                # Pega #ffffff, #FFFFFF, #fff, #FFF e variações em stroke ou fill
                svg_data = re.sub(r'(stroke|fill)="#[fF]{3,6}"', r'\1="{}"'.format(c_hex), svg_data)
                # Caso não tenha aspas ou use aspas simples
                svg_data = re.sub(r'#[fF]{3,6}', c_hex, svg_data)
                
                p = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size)], 
                                   input=svg_data.encode('utf-8'),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
            else:
                p = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), path], 
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
            
            if p.returncode == 0:
                img = Image.open(io.BytesIO(p.stdout)).convert("RGBA")
                ICON_CACHE[cache_key] = img
                return img
        except Exception:
            pass
    return None

def find_gpus():
    gpus = []
    # Vasculha todas as placas DRM em /sys/class/drm/
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]")):
        if not os.path.exists(os.path.join(card, "device")):
            continue
            
        gpu_info = {
            "path": card,
            "name": "GPU Desconhecida",
            "percent": 0.0,
            "mem_used_mb": 0,
            "mem_total_mb": 0,
            "enc_percent": 0.0,
            "temp": "?°C",
            "usage_history": [0] * 30,
            "mem_history": [0] * 30
        }
        
        uevent_path = os.path.join(card, "device", "uevent")
        pci_slot = ""
        if os.path.exists(uevent_path):
            try:
                with open(uevent_path, "r") as f:
                    for line in f:
                        if line.startswith("PCI_SLOT_NAME="):
                            pci_slot = line.split("=")[1].strip()
                            break
            except Exception:
                pass
                
        if pci_slot:
            try:
                # Pega o nome dinâmico via lspci
                cmd = f"lspci -s {pci_slot} | sed -n 's/.*\\[\\(.*\\)\\].*/\\1/p'"
                out = subprocess.check_output(cmd, shell=True, text=True).strip()
                if out:
                    gpu_info["name"] = out.split("\n")[0][:20]
            except Exception:
                pass

        if gpu_info["name"] == "GPU Desconhecida" and os.path.exists(uevent_path):
            try:
                with open(uevent_path, "r") as f:
                    content = f.read()
                    if "1002:7590" in content:
                        gpu_info["name"] = "RX 580"[:20]
                    elif "1002" in content:
                        gpu_info["name"] = "AMD Radeon"[:20]
                    elif "8086" in content:
                        gpu_info["name"] = "Intel"[:20]
                    elif "10de" in content:
                        gpu_info["name"] = "NVIDIA"[:20]
            except Exception:
                pass
        
        # Garante que só será listada se for uma GPU real (removendo placa dummie sem nome)
        if gpu_info["name"] != "GPU Desconhecida":
            gpus.append(gpu_info)
            
    if not gpus:
        gpus.append({
            "path": None,
            "name": "GPU",
            "percent": 0.0,
            "mem_used_mb": 0,
            "mem_total_mb": 0,
            "enc_percent": 0.0,
            "temp": "?°C",
            "usage_history": [0] * 30,
            "mem_history": [0] * 30
        })
        
    return gpus

def monitor_thread():
    last_net = psutil.net_io_counters()
    last_disk = psutil.disk_io_counters()
    last_time = time.time()
    
    SYSTEM_STATS["gpus"] = find_gpus()
    gpu_switch_counter = 0
    
    while True:
        try:
            SYSTEM_STATS["cpu_percent"] = psutil.cpu_percent(interval=None)
            cpu_times = psutil.cpu_times_percent(interval=None)
            cpu_user = cpu_times.user
            cpu_system = cpu_times.system
            with STATS_LOCK:
                SYSTEM_STATS["cpu_user"] = cpu_user
                SYSTEM_STATS["cpu_system"] = cpu_system
                CPU_USER_HISTORY.append(cpu_user)
                CPU_USER_HISTORY.pop(0)
                CPU_SYSTEM_HISTORY.append(cpu_system)
                CPU_SYSTEM_HISTORY.pop(0)
                CPU_USAGE_HISTORY.append(SYSTEM_STATS["cpu_percent"])
                CPU_USAGE_HISTORY.pop(0)
            
            cpu_cores = psutil.cpu_percent(interval=None, percpu=True)
            with STATS_LOCK:
                SYSTEM_STATS["cpu_cores_percent"] = cpu_cores
                if not SYSTEM_STATS["cpu_cores_history"]:
                    SYSTEM_STATS["cpu_cores_history"] = [[] for _ in cpu_cores]
                for i, c in enumerate(cpu_cores):
                    if i < len(SYSTEM_STATS["cpu_cores_history"]):
                        SYSTEM_STATS["cpu_cores_history"][i].append(c)
                        if len(SYSTEM_STATS["cpu_cores_history"][i]) > 40:
                            SYSTEM_STATS["cpu_cores_history"][i].pop(0)
            
            mem = psutil.virtual_memory()
            SYSTEM_STATS["ram_percent"] = mem.percent
            with STATS_LOCK:
                RAM_USAGE_HISTORY.append(mem.percent)
            RAM_USAGE_HISTORY.pop(0)
            
            SYSTEM_STATS["ram_used_mb"] = mem.used // 1048576
            SYSTEM_STATS["ram_total_mb"] = mem.total // 1048576
            
            try:
                swap = psutil.swap_memory()
                SYSTEM_STATS["swap_percent"] = swap.percent
                SYSTEM_STATS["swap_used_mb"] = swap.used // 1048576
                SYSTEM_STATS["swap_total_mb"] = swap.total // 1048576
            except Exception:
                pass
                
            try:
                disk = psutil.disk_usage('/')
                SYSTEM_STATS["disk_percent"] = disk.percent
                SYSTEM_STATS["disk_text"] = f"{disk.used//(1024**3)} / {disk.total//(1024**3)} GB"
            except Exception:
                pass
                
            net = psutil.net_io_counters()
            now = time.time()
            dt = now - last_time
            if dt > 0:
                rx_mbps = ((net.bytes_recv - last_net.bytes_recv) * 8) / (dt * 1e6)
                tx_mbps = ((net.bytes_sent - last_net.bytes_sent) * 8) / (dt * 1e6)
                SYSTEM_STATS["net_rx_mbps"] = rx_mbps
                SYSTEM_STATS["net_tx_mbps"] = tx_mbps
                with STATS_LOCK:
                    NET_RX_HISTORY.append(rx_mbps)
                    NET_RX_HISTORY.pop(0)
                    NET_TX_HISTORY.append(tx_mbps)
                    NET_TX_HISTORY.pop(0)
            last_net = net
            
            disk_io = psutil.disk_io_counters()
            if dt > 0:
                read_kb = (disk_io.read_bytes - last_disk.read_bytes) / (dt * 1024)
                write_kb = (disk_io.write_bytes - last_disk.write_bytes) / (dt * 1024)
                total_io = read_kb + write_kb
                SYSTEM_STATS["disk_io_kbs"] = total_io
                with STATS_LOCK:
                    DISK_IO_HISTORY.append(total_io)
                    DISK_IO_HISTORY.pop(0)
            last_disk = disk_io
            
            try:
                SYSTEM_STATS["load_avg"] = os.getloadavg()
            except:
                SYSTEM_STATS["load_avg"] = (0.0, 0.0, 0.0)

            last_time = now

            try:
                procs = sorted([p.info for p in psutil.process_iter(['name', 'cpu_percent', 'memory_percent']) if p.info['cpu_percent'] is not None], 
                       key=lambda x: x['cpu_percent'], reverse=True)[:10]
                SYSTEM_STATS["procs"] = procs
            except Exception:
                pass
            
            try:
                cpu_t_val = 0
                if hasattr(psutil, "sensors_temperatures"):
                    temps = psutil.sensors_temperatures()
                    for name, entries in temps.items():
                        if "coretemp" in name or "k10temp" in name or "zenpower" in name:
                            for entry in entries:
                                if "Tctl" in entry.label or "Package id 0" in entry.label or "Tdie" in entry.label or "Core 0" in entry.label or not entry.label:
                                    cpu_t_val = entry.current
                                    break
                            if cpu_t_val > 0: break
                    if cpu_t_val == 0:
                        for entries in temps.values():
                            if entries:
                                cpu_t_val = entries[0].current
                                break
                    if cpu_t_val > 0:
                        with STATS_LOCK:
                            SYSTEM_STATS["cpu_temp"] = f"{cpu_t_val:.0f}°C"
                            CPU_TEMP_HISTORY.append(cpu_t_val)
                            CPU_TEMP_HISTORY.pop(0)
            except Exception:
                pass

            if len(SYSTEM_STATS["gpus"]) > 1:
                gpu_switch_counter += 1
                if gpu_switch_counter >= 3:
                    SYSTEM_STATS["active_gpu_idx"] = (SYSTEM_STATS["active_gpu_idx"] + 1) % len(SYSTEM_STATS["gpus"])
                    gpu_switch_counter = 0

            # GPU Status
            for i, gpu in enumerate(SYSTEM_STATS["gpus"]):
                if not gpu["path"]: continue
                card_dev = os.path.join(gpu["path"], "device")
                try:
                    if os.path.exists(os.path.join(card_dev, "gpu_busy_percent")):
                        with open(os.path.join(card_dev, "gpu_busy_percent")) as f:
                            gpu["percent"] = float(f.read().strip())
                            
                    if os.path.exists(os.path.join(card_dev, "mem_info_vram_used")):
                        with open(os.path.join(card_dev, "mem_info_vram_used")) as f:
                            gpu["mem_used_mb"] = int(f.read().strip()) // 1048576
                        with open(os.path.join(card_dev, "mem_info_vram_total")) as f:
                            gpu["mem_total_mb"] = int(f.read().strip()) // 1048576
                            
                    # Update individual GPU history
                    with STATS_LOCK:
                        gpu["usage_history"].append(gpu["percent"])
                        gpu["usage_history"].pop(0)
                        m_p = (gpu["mem_used_mb"] / gpu["mem_total_mb"] * 100) if gpu.get("mem_total_mb", 0) > 0 else 0
                        gpu["mem_history"].append(m_p)
                        gpu["mem_history"].pop(0)

                    if i == SYSTEM_STATS.get("active_gpu_idx", 0):
                        with STATS_LOCK:
                            GPU_USAGE_HISTORY.append(gpu["percent"])
                            GPU_USAGE_HISTORY.pop(0)
                            mem_p = (gpu["mem_used_mb"] / gpu["mem_total_mb"] * 100) if gpu.get("mem_total_mb", 0) > 0 else 0
                            GPU_MEM_HISTORY.append(mem_p)
                            GPU_MEM_HISTORY.pop(0)
                            
                    if os.path.exists(os.path.join(card_dev, "vcn_busy_percent")):
                        with open(os.path.join(card_dev, "vcn_busy_percent")) as f:
                            val = f.read().strip()
                            gpu["enc_percent"] = float(val) if val.isdigit() else 0.0
                            
                    hwmon_path = glob.glob(os.path.join(card_dev, "hwmon", "hwmon*"))
                    if hwmon_path:
                        temp1_input = os.path.join(hwmon_path[0], "temp1_input")
                        if os.path.exists(temp1_input):
                            with open(temp1_input) as f:
                                gpu["temp"] = f"{int(f.read().strip()) // 1000}°C"
                            
                    # Tenta pegar sensores avançados (edge, junction, ppt) se for AMD
                    for sensor_file in ["temp1_input", "temp2_input", "temp3_input", "power1_average"]:
                        path = os.path.join(hwmon_path[0], sensor_file)
                        if os.path.exists(path):
                            with open(path) as f:
                                val = int(f.read().strip())
                                if "temp" in sensor_file:
                                    label = "edge" if "1" in sensor_file else ("junc" if "2" in sensor_file else "mem")
                                    gpu[label] = f"{val//1000}°C"
                                else:
                                    gpu["ppt"] = f"{val/1000000:.1f}W"
                except Exception:
                    pass
            
            # Perfil de Energia
            try:
                prof_path = "/sys/firmware/acpi/platform_profile"
                if os.path.exists(prof_path):
                    with open(prof_path) as f:
                        SYSTEM_STATS["power_profile"] = f.read().strip()
                else:
                    # Fallback power-profiles-ctl
                    p = subprocess.check_output("powerprofilesctl get 2>/dev/null", shell=True, text=True).strip()
                    if p: SYSTEM_STATS["power_profile"] = p
            except: pass

        except Exception:
            pass
            
        # Marquee offset kernel e GPU
        try:
            # Kernel
            k = SYSTEM_STATS.get('kernel', '')
            k_len = len(k)
            limit_k = 20 # Perfect fit for the column width
            if k_len > limit_k:
                off = SYSTEM_STATS.get('kernel_offset', 0)
                d_dir = SYSTEM_STATS.get('kernel_dir', 1)
                off += d_dir
                if off >= (k_len - limit_k):
                    off = k_len - limit_k
                    d_dir = -1
                elif off <= 0:
                    off = 0
                    d_dir = 1
                SYSTEM_STATS['kernel_offset'] = off
                SYSTEM_STATS['kernel_dir'] = d_dir
            else:
                SYSTEM_STATS['kernel_offset'] = 0
            
            # GPU (Sync all GPUs based on the longest name)
            max_gn_len = 0
            for g in SYSTEM_STATS.get("gpus", []):
                max_gn_len = max(max_gn_len, len(g.get("name", "")))
            
            limit_g = 20
            if max_gn_len > limit_g:
                off_g = SYSTEM_STATS.get('gpu_marquee_offset', 0)
                d_dir_g = SYSTEM_STATS.get('gpu_marquee_dir', 1)
                off_g += d_dir_g
                if off_g >= (max_gn_len - limit_g):
                    off_g = max_gn_len - limit_g
                    d_dir_g = -1
                elif off_g <= 0:
                    off_g = 0
                    d_dir_g = 1
                SYSTEM_STATS['gpu_marquee_offset'] = off_g
                SYSTEM_STATS['gpu_marquee_dir'] = d_dir_g
            else:
                SYSTEM_STATS['gpu_marquee_offset'] = 0
        except Exception:
            pass
        
        time.sleep(0.4)

threading.Thread(target=monitor_thread, daemon=True).start()

# ================= COMUNICAÇÃO DISPLAY =================

class AX206_DPF:
    def __init__(self, vid=0x1908, pid=0x0102):
        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            sys.exit(1)
        
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except Exception:
            pass
            
        try:
            self.dev.set_configuration()
            # Pequeno delay para estabilização após handshake USB
            time.sleep(0.1)
        except Exception:
            pass
            
        self.ep_out = 0x01
        self.ep_in = 0x81
        
        # Tenta detectar a resolução com retentativas
        self.width, self.height = 0, 0
        for _ in range(3):
            self.width, self.height = self.get_dimensions()
            if self.width > 0 and self.height > 0:
                break
            time.sleep(0.2)

        if self.width == 0 or self.height == 0:
            # Fallback seguro para o modelo mais comum
            self.width = 800
            self.height = 480
        else:
            pass

    def scsi_wrap(self, cmd, dir_out=True, data=None):
        block_len = len(data) if data else 0
        cmd_padded = cmd.ljust(16, b'\x00')
        cbw_flags = 0x00 if dir_out else 0x80
        cbw = struct.pack("<4sIIBBb16s", b"USBC", 0xdeadbeef, block_len, cbw_flags, 0x00, len(cmd), cmd_padded)
                          
        try:
            self.dev.write(self.ep_out, cbw, timeout=1000)
        except Exception:
            return -1

        resp_data = None
        if block_len > 0:
            if dir_out:
                try:
                    self.dev.write(self.ep_out, data, timeout=3000)
                except Exception:
                    return -1
            else:
                try:
                    resp_data = self.dev.read(self.ep_in, block_len, timeout=4000)
                except Exception:
                    return -1

        try:
            csw = self.dev.read(self.ep_in, 13, timeout=5000)
            if len(csw) == 13 and csw[:4] == b"USBS":
                return resp_data if not dir_out else csw[12]
            else:
                return resp_data if not dir_out else 0
        except Exception:
            return resp_data if not dir_out else 0

    def get_dimensions(self):
        cmd = bytearray([0xcd, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        res = self.scsi_wrap(cmd, dir_out=False, data=bytearray(5))
        if res != -1 and res is not None and len(res) == 5:
            w = res[0] | (res[1] << 8)
            h = res[2] | (res[3] << 8)
            return w, h
        return 0, 0

    def set_backlight(self, b):
        # Mapeia o valor de 10-100 (vindo do novo slider) para o hardware 1-7
        # Se b <= 7, assumimos que é uma versão antiga das configs e forçamos o mapeamento
        if b <= 7:
            # Legado: se for 0, vira 1 (mínimo ligado)
            hardware_b = max(1, int(b))
        else:
            # Novo: mapeia 10-100 para 1-7
            # 10% -> 1 (mínimo), 100% -> 7 (máximo)
            hardware_b = int(1 + (b - 10) * (7 - 1) / (100 - 10))
            # Garante limites
            hardware_b = max(1, min(7, hardware_b))
            
        cmd = bytearray([0xcd, 0, 0, 0, 0, 6, 0x01, 0x01, 0x00, hardware_b, 0x00, 0, 0, 0, 0, 0])
        self.scsi_wrap(cmd, dir_out=True, data=None)

    def draw(self, image, settings=None):
        # Handle orientation/rotation
        if settings and settings.get("orientation") == "vertical":
            # Rotate 90 degrees if vertical is desired on a landscape hardware
            # We assume internal rendering was done in (h, w) format
            image = image.rotate(90, expand=True)
            
        width, height = image.size
        # Fast RGB565 conversion - avoids DeprecationWarning
        img_bytes = image.convert("RGB").tobytes()
        
        rgb565 = bytearray(width * height * 2)
        for i in range(width * height):
            r = img_bytes[i*3]
            g = img_bytes[i*3+1]
            b = img_bytes[i*3+2]
            val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            rgb565[i*2] = (val >> 8) & 0xFF
            rgb565[i*2+1] = val & 0xFF

        self._draw_rgb565(rgb565, width, height)

    def _draw_rgb565(self, rgb565, width, height):
        x1 = width - 1
        y1 = height - 1
        cmd = bytearray([
            0xcd, 0x00, 0x00, 0x00, 0x00, 0x06, 0x12, 
            0x00, 0x00, 0x00, 0x00,
            x1 & 0xFF, (x1 >> 8) & 0xFF,
            y1 & 0xFF, (y1 >> 8) & 0xFF,
            0x00
        ])
        
        self.scsi_wrap(cmd, dir_out=True, data=rgb565)


class TuringSmartScreen:
    """Driver for QinHeng Electronics UsbMonitor (VID 0x1a86, PID 0x5722).

    Uses USB-CDC serial protocol (ttyACM) as documented by the
    turing-smart-screen-python project (GPL-3.0, by @mathoudebine).
    """

    # Protocol command codes
    CMD_RESET = 101
    CMD_CLEAR = 102
    CMD_SCREEN_OFF = 108
    CMD_SCREEN_ON = 109
    CMD_SET_BRIGHTNESS = 110
    CMD_SET_ORIENTATION = 121
    CMD_DISPLAY_BITMAP = 197
    CMD_HELLO = 69

    @staticmethod
    def find_com_port():
        """Auto-detect the serial port for the Turing Smart Screen."""
        for port in comports():
            if getattr(port, "serial_number", None) == "USB35INCHIPSV2":
                return port.device
            if getattr(port, "vid", None) == 0x1A86 and getattr(port, "pid", None) == 0x5722:
                return port.device
        return None

    def __init__(self, com_port=None):
        if com_port is None:
            com_port = self.find_com_port()
        if com_port is None:
            raise RuntimeError("Turing Smart Screen not found on any serial port")

        self.com_port = com_port
        self.lcd_serial = serial.Serial(self.com_port, 115200, timeout=1, rtscts=True)

        # Default 3.5" dimensions (portrait native)
        self.native_width = 320
        self.native_height = 480
        self._detect_model()

        # Expose width/height in landscape (matches AX206_DPF convention)
        self.width = self.native_height  # 480
        self.height = self.native_width  # 320

        # Set landscape orientation once at init (avoids per-frame overhead)
        self._orientation_set = False
        # Previous frame for dirty-rectangle optimization
        self._prev_frame = None

    def _detect_model(self):
        """Send HELLO command to identify display model and resolution."""
        hello = bytes([self.CMD_HELLO] * 6)
        self.lcd_serial.write(hello)
        resp = self.lcd_serial.read(6)
        self.lcd_serial.reset_input_buffer()

        if resp == bytes([0x01] * 6):
            self.native_width, self.native_height = 320, 480
        elif resp == bytes([0x02] * 6):
            self.native_width, self.native_height = 480, 800
        elif resp == bytes([0x03] * 6):
            self.native_width, self.native_height = 600, 1024
        else:
            # Turing 3.5" original does not respond to HELLO
            self.native_width, self.native_height = 320, 480

    def _send_command(self, cmd, x=0, y=0, ex=0, ey=0):
        buf = bytearray(6)
        buf[0] = (x >> 2)
        buf[1] = (((x & 3) << 6) + (y >> 4))
        buf[2] = (((y & 15) << 4) + (ex >> 6))
        buf[3] = (((ex & 63) << 2) + (ey >> 8))
        buf[4] = (ey & 255)
        buf[5] = cmd
        self.lcd_serial.write(bytes(buf))

    def _set_orientation_cmd(self, orientation_code, width, height):
        """Send the 16-byte orientation command."""
        buf = bytearray(16)
        buf[0] = 0
        buf[1] = 0
        buf[2] = 0
        buf[3] = 0
        buf[4] = 0
        buf[5] = self.CMD_SET_ORIENTATION
        buf[6] = orientation_code + 100
        buf[7] = (width >> 8)
        buf[8] = (width & 255)
        buf[9] = (height >> 8)
        buf[10] = (height & 255)
        self.lcd_serial.write(bytes(buf))

    def set_backlight(self, b):
        """Set brightness. Maps 10-100% range to 0-255 (0=brightest)."""
        if b <= 0:
            level_abs = 255
        elif b >= 100:
            level_abs = 0
        else:
            level_abs = int(255 - ((b / 100) * 255))
        self._send_command(self.CMD_SET_BRIGHTNESS, level_abs, 0, 0, 0)

    def draw(self, image, settings=None):
        """Draw a PIL Image with tile-based dirty detection.

        Divides the screen into small tiles (48x20 pixels).  Only tiles whose
        pixels actually changed are sent.  Dirty tiles within the same row are
        merged into wider rectangles to reduce USB command overhead, then the
        row groups are sent in shuffled order so the visual update is spread
        across the whole screen instead of scanning top-to-bottom.
        """
        if settings and settings.get("orientation") == "vertical":
            image = image.rotate(90, expand=True)

        img_w, img_h = image.size

        # Set orientation only once
        if not self._orientation_set:
            self._set_orientation_cmd(2, img_w, img_h)
            self._orientation_set = True

        # Convert image to RGB565 little-endian using numpy
        rgb565le = self._image_to_rgb565(image)

        if self._prev_frame is not None and len(self._prev_frame) == len(rgb565le):
            # Tile-based dirty detection
            tile_w, tile_h = 48, 20
            cols = img_w // tile_w   # 10 for 480px
            rows = img_h // tile_h   # 16 for 320px

            curr = np.frombuffer(rgb565le, dtype="<u2").reshape(img_h, img_w)
            prev = np.frombuffer(self._prev_frame, dtype="<u2").reshape(img_h, img_w)

            # Reshape into tile grid: (rows, cols, tile_h, tile_w)
            curr_tiles = curr[:rows * tile_h, :cols * tile_w].reshape(
                rows, tile_h, cols, tile_w).transpose(0, 2, 1, 3)
            prev_tiles = prev[:rows * tile_h, :cols * tile_w].reshape(
                rows, tile_h, cols, tile_w).transpose(0, 2, 1, 3)

            # Vectorized comparison: which tiles changed?
            tile_changed = (curr_tiles != prev_tiles).any(axis=(2, 3))

            if not tile_changed.any():
                return False  # Nothing changed

            # Merge horizontally adjacent dirty tiles into wider rectangles
            # to reduce the number of USB transactions
            rects = []  # list of (y0, x0, x1_excl, row_idx) — merged rects
            for ty in range(rows):
                tx = 0
                while tx < cols:
                    if not tile_changed[ty, tx]:
                        tx += 1
                        continue
                    # Start of a run of dirty tiles in this row
                    tx_start = tx
                    while tx < cols and tile_changed[ty, tx]:
                        tx += 1
                    # Merged rectangle: full tile_h height, tx_start..tx columns
                    y0 = ty * tile_h
                    x0 = tx_start * tile_w
                    x1 = tx * tile_w  # exclusive
                    rects.append((y0, x0, x1, ty))

            # Shuffle rectangles so the visual update is distributed across
            # the whole screen rather than sweeping top-to-bottom
            import random
            random.shuffle(rects)

            for y0, x0, x1, ty in rects:
                rect_data = curr[y0:y0 + tile_h, x0:x1].tobytes()
                self._send_command(self.CMD_DISPLAY_BITMAP,
                                   x0, y0, x1 - 1, y0 + tile_h - 1)
                self.lcd_serial.write(rect_data)

            self._prev_frame = rgb565le
            return True
        else:
            # First frame or size changed: send everything
            self._send_command(self.CMD_DISPLAY_BITMAP, 0, 0, img_w - 1, img_h - 1)
            chunk_size = img_w * 8
            for i in range(0, len(rgb565le), chunk_size):
                self.lcd_serial.write(rgb565le[i:i + chunk_size])

            self._prev_frame = rgb565le
            return True

    def _draw_rgb565(self, rgb565, width, height):
        """Send pre-converted RGB565 data. Converts from big-endian to little-endian."""
        self._set_orientation_cmd(2, width, height)

        x1, y1 = width - 1, height - 1
        self._send_command(self.CMD_DISPLAY_BITMAP, 0, 0, x1, y1)

        # The existing code produces big-endian RGB565; we need little-endian
        data = bytearray(rgb565)
        for i in range(0, len(data), 2):
            data[i], data[i + 1] = data[i + 1], data[i]

        chunk_size = width * 8
        for i in range(0, len(data), chunk_size):
            self.lcd_serial.write(bytes(data[i:i + chunk_size]))

    @staticmethod
    def _image_to_rgb565(image):
        """Convert PIL Image to RGB565 little-endian bytes using numpy."""
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")
        rgb = np.asarray(image).reshape((image.size[1] * image.size[0], -1))
        r = rgb[:, 0].astype(np.uint16) >> 3
        g = rgb[:, 1].astype(np.uint16) >> 2
        b = rgb[:, 2].astype(np.uint16) >> 3
        rgb565 = (r << 11) | (g << 5) | b
        return rgb565.astype("<u2").tobytes()

    def close(self):
        if self.lcd_serial and self.lcd_serial.is_open:
            self.lcd_serial.close()


def detect_display(settings):
    """Factory: detect and instantiate the appropriate display driver."""
    model = settings.get("model", "auto")

    if model == "turing":
        return TuringSmartScreen()
    elif model == "ax206":
        return AX206_DPF()

    # Auto-detection: try Turing first (serial), then AX206 (USB)
    turing_port = TuringSmartScreen.find_com_port()
    if turing_port:
        return TuringSmartScreen(com_port=turing_port)

    ax206_dev = usb.core.find(idVendor=0x1908, idProduct=0x0102)
    if ax206_dev:
        return AX206_DPF()

    raise RuntimeError("No supported display found")


# ================= RENDERIZACAO DA TELA =================

def get_os_release():
    info = {"PRETTY_NAME": "Linux", "LOGO": ""}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    info[k] = v.strip('"')
    except Exception:
        pass
    return info

def get_text_width(d, text, font):
    try:
        return int(d.textlength(text, font=font))
    except AttributeError:
        try:
            return int(d.textbbox((0, 0), text, font=font)[2])
        except AttributeError:
            return int(font.getsize(text)[0])


def fit_text_to_width(d, value, max_width, font):
    """Trim a label with an ellipsis so adjacent metrics never collide."""
    value = str(value)
    if max_width <= 0:
        return ""
    if get_text_width(d, value, font) <= max_width:
        return value
    ellipsis = "…"
    while value and get_text_width(d, value + ellipsis, font) > max_width:
        value = value[:-1]
    return (value + ellipsis) if value else ellipsis



def render_dashboard_gkrellm(width, height, settings):
    # Tela inteira (800x480)
    bg_color = (0, 0, 0)
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    
    try:
        font_mono = ImageFont.truetype("/usr/share/fonts/Adwaita/AdwaitaMono-Regular.ttf", 20)
        font_mono_lg = ImageFont.truetype("/usr/share/fonts/Adwaita/AdwaitaMono-Bold.ttf", 26)
        font_mono_sm = ImageFont.truetype("/usr/share/fonts/Adwaita/AdwaitaMono-Regular.ttf", 16)
    except:
        font_mono = font_mono_lg = font_mono_sm = ImageFont.load_default()

    gk_theme = settings.get("gk_theme_color", "urlicht")
    
    if gk_theme == "urlicht":
        font_main  = (220, 220, 230)
        font_blue  = (80, 130, 255)
        font_dim   = (120, 120, 130)
        line_top   = (80, 80, 90)
        line_bot   = (30, 30, 40)
        bar_fill   = (80, 130, 255)
    elif gk_theme == "cyber_red":
        font_main  = (255, 180, 180)  
        font_blue  = (255, 50, 50)   
        font_dim   = (150, 100, 100) 
        line_top   = (120, 50, 50)    
        line_bot   = (50, 20, 20)    
        bar_fill   = (255, 50, 50)
    else: # classic
        font_main  = (170, 255, 170)
        font_blue  = (85, 170, 85)
        font_dim   = (85, 170, 85)
        line_top   = (85, 170, 85)
        line_bot   = (40, 80, 40)
        bar_fill   = (170, 255, 170)

    is_vertical = settings.get("orientation", "horizontal") == "vertical" or height > width
    num_cols = 2 if is_vertical else 4
    col_w = width // num_cols
    
    # Dividers
    for i in range(1, num_cols):
        d.line((col_w*i, 0, col_w*i, height), fill=line_bot, width=2)
        d.line((col_w*i-2, 0, col_w*i-2, height), fill=line_top, width=2)

    def draw_sep(x, y, w, title="", is_net=False):
        d.line((x, y, x+w, y), fill=line_top, width=2)
        d.line((x, y+2, x+w, y+2), fill=line_bot, width=2)
        if title:
            d.rectangle((x, y+4, x+w, y+26), fill=(line_bot[0]//2, line_bot[1]//2, line_bot[2]//2))
            tw = get_text_width(d, title, font_mono)
            d.text((x + (w-tw)//2, y + 2), title, fill=font_main, font=font_mono)
            
            if is_net:
                sec = int(time.time() * 2)
                # Blink LED for RX and TX
                rx_color = font_blue if sec % 2 == 0 else (40, 40, 50)
                tx_color = font_blue if (sec+1) % 2 == 0 else (40, 40, 50)
                # Draw right aligned LEDs
                d.rectangle((x+w-25, y+10, x+w-15, y+18), fill=rx_color, outline=line_top)
                d.rectangle((x+w-12, y+10, x+w-2, y+18), fill=tx_color, outline=line_top)

            d.line((x, y+28, x+w, y+28), fill=line_top, width=2)
            d.line((x, y+30, x+w, y+30), fill=line_bot, width=2)
            return y + 32
        return y + 6
        
    def format_bytes(b):
        if b < 1024: return f"{b}"
        elif b < 1024*1024: return f"{b/1024:.1f}K"
        else: return f"{b/(1024*1024):.1f}M"

    pad = 8
    graph_h = 45

    def draw_graph(x, y, w, h, data, max_val=100, style="line", color=font_blue, fill_color=(10,30,80), current_val=0, data2=None, color2=(255,100,100)):
        # Background gradient effect
        for i in range(h):
            ratio = i / h
            bg_c = (int(0 * ratio), int(0 * ratio), int(40 * (1-ratio)))
            d.line((x, y+i, x+w, y+i), fill=bg_c)
        
        d.line((x, y, x+w, y), fill=line_bot) # top border
        
        if data:
            actual_max = max(max_val, max(data) if data else 1)
            if data2:
                actual_max = max(actual_max, max(data2) if data2 else 1)
            step = w / max(1, len(data)-1)
            pts = []
            pts2 = []
            for i, val in enumerate(data):
                px = x + int(i*step)
                py = y + h - int((val / actual_max) * h)
                pts.append((px, py))
                if py < y + h:
                    if style == "line" or style == "mixed":
                        if style == "mixed":
                            d.line((px, py, px, y+h), fill=(color[0]//3, color[1]//3, color[2]//3))
                        d.line((px, py, px, py+1), fill=color) # The bright top line 
                    elif style == "bar":
                        d.rectangle((px, py, px+2, y+h), fill=(color[0]//2, color[1]//2, color[2]//2))
                        d.rectangle((px, py, px+2, py+1), fill=(min(255, color[0]+80), min(255, color[1]+80), min(255, color[2]+80)))
                if data2 and i < len(data2):
                    val2 = data2[i]
                    py2 = y + h - int((val2 / actual_max) * h)
                    pts2.append((px, py2))
            
            if len(pts) > 1 and style in ["bar", "mixed"]:
                d.line(pts, fill=(min(255, color[0]+50), min(255, color[1]+50), min(255, color[2]+50)), width=1)
            if pts2 and len(pts2) > 1 and style in ["line", "mixed"]:
                d.line(pts2, fill=color2, width=1)

        # Bottom tick horizontal bar
        d.line((x, y+h, x+w, y+h), fill=line_top) # bottom border
        d.rectangle((x, y+h+1, x+w, y+h+4), fill=(20, 20, 25))
        
        tick_w = int(w * (current_val / actual_max if 'actual_max' in locals() and actual_max > 0 else 0))
        tick_w = min(max(tick_w, 0), w)
        d.rectangle((x, y+h+1, x+tick_w, y+h+4), fill=color)

        return y + h + 6

    # Dynamic placement algorithm
    col = 0
    cx = 0; cy = 2; cw = col_w
    def request_space(h_req):
        nonlocal cy, col, cx
        if cy + h_req > height:
            col += 1
            cy = 0
            cx = col * cw
        if col >= num_cols:
            return False
        return True

    def draw_temp_row(label, val_str, default_val=40, custom_cy=None):
        nonlocal cy
        used_cy = custom_cy if custom_cy else cy
        try:
            val = float(str(val_str).replace('°C', ''))
        except:
            val = default_val
        ratio = max(0.0, min(1.0, (val - 30) / 60.0)) # 30 to 90
        r_c = int(font_blue[0] * (1-ratio) + 255*ratio)
        g_c = int(font_blue[1] * (1-ratio) + 50*ratio)
        b_c = int(font_blue[2] * (1-ratio) + 50*ratio)
        t_color = (r_c, g_c, b_c)
        
        d.text((cx+pad, used_cy), label, fill=font_blue, font=font_mono_sm)
        vw = get_text_width(d, f"{val:.1f}°C", font_mono_sm)
        d.text((cx+cw-vw-pad, used_cy), f"{val:.1f}°C", fill=t_color, font=font_mono_sm)
        
        b_y = used_cy + 18
        bar_len = int((cw-pad*2) * ratio)
        for i in range(bar_len):
            r_i = i/(cw-pad*2)
            cur_c = (int(font_blue[0] * (1-r_i) + 255*r_i), int(font_blue[1] * (1-r_i) + 50*r_i), int(font_blue[2] * (1-r_i) + 50*r_i))
            d.line((cx+pad+i, b_y, cx+pad+i, b_y+2), fill=cur_c)
            
        if custom_cy is None:
            cy += 25

    # Logo / Host
    if settings.get('gk_show_host', True):
        if request_space(80):
            os_info = get_os_release()
            logo_name = os_info.get("LOGO", "")
            hn = SYSTEM_STATS.get('hostname', 'URSPECHT')
            krn = SYSTEM_STATS.get('kernel', 'Linux')
            tw = get_text_width(d, hn, font_mono_lg)
            kw = get_text_width(d, krn, font_mono_sm)
            
            logo = load_distro_logo(logo_name, 45)
            if logo:
                img.paste(logo, (cx + (cw - logo.width)//2, cy), mask=logo)
                cy += logo.height + 5
                
            d.text((cx + (cw - tw)//2, cy), hn, fill=font_dim, font=font_mono_lg)
            cy += 30
            
            # Scroll Kernel
            k_text = krn
            limit_k = 20
            if len(krn) > limit_k:
                off_k = SYSTEM_STATS.get('kernel_offset', 0)
                k_text = krn[off_k : off_k + limit_k]
            
            kw = get_text_width(d, k_text, font_mono_sm)
            kx = cx + (cw - kw)//2 if len(krn) <= limit_k else cx + pad
            d.text((kx, cy), k_text, fill=font_main, font=font_mono_sm)
            cy += 20

    now = datetime.now()

    # DATE
    if settings.get('gk_show_date', True):
        if request_space(25):
            ds1 = now.strftime("%a ")
            ds2 = now.strftime("%d")
            ds3 = now.strftime(" %b")
            d.text((cx + pad + 20, cy), ds1, fill=font_main, font=font_mono)
            w1 = get_text_width(d, ds1, font_mono)
            d.text((cx + pad + 20 + w1, cy), ds2, fill=font_blue, font=font_mono)
            w2 = get_text_width(d, ds2, font_mono)
            d.text((cx + pad + 20 + w1 + w2, cy), ds3, fill=font_main, font=font_mono)
            cy += 25

    # TIME
    if settings.get('gk_show_time', True):
        if request_space(35):
            ts1 = now.strftime("%H:%M")
            ts2 = now.strftime(" %S")
            d.text((cx + pad + 20, cy), ts1, fill=font_main, font=font_mono_lg)
            w1 = get_text_width(d, ts1, font_mono_lg)
            d.text((cx + pad + 20 + w1, cy+4), ts2, fill=font_blue, font=font_mono)
            cy += 35

    # UPTIME
    if settings.get('gk_show_uptime', True):
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
            uptime_str = str(timedelta(seconds=int(uptime_seconds)))
        except:
            uptime_str = "0:00:00"
        if request_space(25):
            up_str = f"up: {uptime_str}"
            tw = get_text_width(d, up_str, font_mono_sm)
            d.text((cx + (cw - tw)//2, cy), up_str, fill=font_main, font=font_mono_sm)
            cy += 25

    # CPU MONITOR (ADVANCED DUAL-LAYER)
    if settings.get('gk_show_cpu', True):
        # space for title + graph + text
        if request_space(110):
            cy = draw_sep(cx, cy, cw, "CPU")
            
            # CPU STATS
            cpu_p = SYSTEM_STATS.get('cpu_percent', 0)
            cpu_u = SYSTEM_STATS.get('cpu_user', 0)
            cpu_s = SYSTEM_STATS.get('cpu_system', 0)
            cpu_t = SYSTEM_STATS.get('cpu_temp', '0°C')
            
            # Colors for CPUS - System (Darker/Reddish) and User (Lighter/Greenish)
            c_user = (100, 255, 100) if gk_theme != "classic" else (170, 255, 170)
            c_sys  = (255, 100, 100) if gk_theme != "classic" else (255, 80, 80)
            
            # --- Draw the specialized CPU Graph ---
            # Moves Right to Left (History is append-only, so we show it directly or reversed)
            # data is [0...30], current is at index 29 (right)
            gx, gy, gw, gh = cx + pad, cy, cw - pad*2, graph_h
            
            # Background with grid lines every 20%
            for i in range(gh):
                ratio = i / gh
                bg_c = (int(0 * ratio), int(0 * ratio), int(40 * (1-ratio)))
                d.line((gx, gy+i, gx+gw, gy+i), fill=bg_c)
            
            # Grid lines
            for perc in [20, 40, 60, 80]:
                grid_y = gy + gh - int((perc / 100) * gh)
                d.line((gx, grid_y, gx+gw, grid_y), fill=(50, 50, 60), width=1)
                
            # Border
            d.rectangle((gx, gy, gx+gw, gy+gh), outline=line_bot)
            
            # Draw layers (User + System = Total)
            # We draw them as stacked areas
            # System is "top" relative to user, but visual order: User on bottom, System added on top
            step = gw / max(1, len(CPU_USER_HISTORY)-1)
            
            pts_user = []
            pts_system = []
            
            for i in range(len(CPU_USER_HISTORY)):
                px = gx + i * step
                u_val = CPU_USER_HISTORY[i]
                s_val = CPU_SYSTEM_HISTORY[i]
                
                # User Layer (Bottom)
                uy = gy + gh - int((u_val / 100) * gh)
                pts_user.append((px, uy))
                
                # System Layer (Stacked on top of User)
                sy = gy + gh - int(((u_val + s_val) / 100) * gh)
                pts_system.append((px, sy))
                
                # Fill vertical bars for area effect
                if uy < gy + gh:
                    d.line((px, uy, px, gy+gh), fill=(c_user[0]//3, c_user[1]//3, c_user[2]//3))
                if sy < uy:
                    d.line((px, sy, px, uy), fill=(c_sys[0]//3, c_sys[1]//3, c_sys[2]//3))
            
            # Draw top lines for the layers
            if len(pts_user) > 1:
                d.line(pts_user, fill=c_user, width=1)
                d.line(pts_system, fill=c_sys, width=1)
            
            cy += gh + 5
            
            # Numerical Values: u% s% Temp
            # Text align: Left-center-right/distributed
            txt_u = f"u: {cpu_u:.1f}%"
            txt_s = f"s: {cpu_s:.1f}%"
            
            d.text((cx + pad, cy), txt_u, fill=font_main, font=font_mono_sm)
            
            sw = get_text_width(d, txt_s, font_mono_sm)
            d.text((cx + (cw - sw)//2, cy), txt_s, fill=font_dim, font=font_mono_sm)
            
            tw = get_text_width(d, cpu_t, font_mono_sm)
            d.text((cx + cw - tw - pad, cy), cpu_t, fill=font_blue, font=font_mono_sm)
            
            cy += 20
            cy += 5

    # GPU (Iterate all detected GPUs)
    if settings.get('gk_show_gpu', True):
        for i, gpu in enumerate(SYSTEM_STATS.get("gpus", [])):
            if request_space(120):
                cy = draw_sep(cx, cy, cw, f"GPU {i}")
                gn = gpu.get("name", "GPU")
                limit_g = 20
                msg_gpu = gn
                if len(gn) > limit_g:
                    off_g = SYSTEM_STATS.get('gpu_marquee_offset', 0)
                    current_off = min(off_g, len(gn) - limit_g)
                    msg_gpu = gn[current_off : current_off + limit_g]
                
                gw_text = get_text_width(d, msg_gpu, font_mono_sm)
                gx_text = cx + (cw - gw_text)//2 if len(gn) <= limit_g else cx + pad
                d.text((gx_text, cy), msg_gpu, fill=font_main, font=font_mono_sm)
                cy += 20
                
                gpu_temp = gpu.get("temp", "43°C")
                gpu_perc = gpu.get("percent", 0)
                mem_tot = gpu.get("mem_total_mb", 1)
                mem_used = gpu.get("mem_used_mb", 0)
                gpu_mem_p = (mem_used / mem_tot * 100) if mem_tot > 0 else 0
                
                # Use individual history per GPU
                cy = draw_graph(cx+pad, cy, cw-pad*2, graph_h, list(gpu["usage_history"]), 100, "mixed", color=font_blue, current_val=gpu_perc, data2=list(gpu["mem_history"]), color2=(255,150,50))
                
                draw_temp_row("Temp", gpu_temp)
                
                # Align values text
                txt_vals = f"GPU {gpu_perc:.0f}% MEM {gpu_mem_p:.0f}%"
                vw_vals = get_text_width(d, txt_vals, font_mono_sm)
                d.text((cx + (cw-vw_vals)//2, cy), txt_vals, fill=font_main, font=font_mono_sm)
                cy += 20
                cy += 5

    # INDIVIDUAL CORES
    if settings.get('gk_show_cores', True):
        cores = SYSTEM_STATS.get('cpu_cores_percent', [])
        history = SYSTEM_STATS.get('cpu_cores_history', [])
        for i, val in enumerate(cores):
            if request_space(18):
                d.text((cx+pad, cy), f"CPU{i}", fill=font_main, font=font_mono_sm)
                pct_str = f"{val:.0f}%"
                vw = get_text_width(d, pct_str, font_mono_sm)
                d.text((cx+pad+90-vw, cy), pct_str, fill=font_main, font=font_mono_sm)
                fill_w = int((cw - pad*3 - 95) * (val/100.0))
                fill_w = max(0, fill_w)
                d.rectangle((cx+pad+95, cy+4, cx+pad+95+fill_w, cy+14), fill=font_blue)
                cy += 18

    # PROCESSES & LOAD
    if settings.get('gk_show_proc', True):
        if request_space(95):
            procs = sum(1 for p in SYSTEM_STATS.get('procs', []))
            if procs == 0: procs = 133
            load1, load5, load15 = SYSTEM_STATS.get('load_avg', (0,0,0))
            cy = draw_sep(cx, cy, cw, "Proc")
            d.text((cx+pad, cy), f"{procs} procs", fill=font_main, font=font_mono_sm)
            load_txt = f"{load1:.2f} {load5:.2f}"
            lw = get_text_width(d, load_txt, font_mono_sm)
            d.text((cx+cw-pad-lw, cy), load_txt, fill=font_dim, font=font_mono_sm)
            cy += 20
            cy = draw_graph(cx+pad, cy, cw-pad*2, graph_h, [min(100, x*1.2) for x in list(CPU_USAGE_HISTORY)[::-1]], 100, "mixed", color=font_blue, current_val=min(100, len(SYSTEM_STATS.get('procs', []))))
            cy += 5

    if settings.get('gk_show_temp', True):
        draw_temp_row("CPU", SYSTEM_STATS.get('cpu_temp', '16.0°C'))
    
    if settings.get('gk_show_temp', True):
        draw_temp_row("chipset", "45.0°C")

    # ETH0
    if settings.get('gk_show_eth0', True):
        if request_space(95):
            cy = draw_sep(cx, cy, cw, "eth0", is_net=True)
            rx_mbps = SYSTEM_STATS.get('net_rx_mbps', 0)
            tx_mbps = SYSTEM_STATS.get('net_tx_mbps', 0)
            txt_rx = f"RX: {rx_mbps:.1f}M"
            txt_tx = f"TX: {tx_mbps:.1f}M"
            d.text((cx+pad, cy), txt_rx, fill=font_main, font=font_mono_sm)
            vw = get_text_width(d, txt_tx, font_mono_sm)
            d.text((cx+cw-vw-pad, cy), txt_tx, fill=font_main, font=font_mono_sm)
            cy += 20
            
            c2_tx = (255, 120, 100) # Laranja/Vermelho para TX
            cy = draw_graph(cx+pad, cy, cw-pad*2, graph_h, list(NET_RX_HISTORY), 10, "mixed", color=font_blue, current_val=rx_mbps, data2=list(NET_TX_HISTORY), color2=c2_tx) 
            cy += 5

    # RAM
    if settings.get('gk_show_mem', True):
        if request_space(45):
            cy = draw_sep(cx, cy, cw, "Mem")
            mem_p = SYSTEM_STATS.get('ram_percent', 0)
            mem_tot = format_bytes(SYSTEM_STATS.get('ram_total_mb', 0)*1024*1024)
            d.text((cx+pad, cy), f"{mem_p:.0f}%", fill=font_main, font=font_mono_sm)
            vw = get_text_width(d, mem_tot, font_mono_sm)
            d.text((cx+cw-vw-pad, cy), mem_tot, fill=font_dim, font=font_mono_sm)
            cy += 20
            d.rectangle((cx+pad, cy, cx+cw-pad, cy+18), fill=(20, 20, 25))
            fw = int((cw-pad*2) * (mem_p/100.0))
            d.rectangle((cx+pad, cy, cx+pad+fw, cy+18), fill=bar_fill) 
            cy += 25

    # SWAP
    if settings.get('gk_show_swap', True):
        if request_space(45):
            cy = draw_sep(cx, cy, cw, "Swap")
            swap_p = SYSTEM_STATS.get('swap_percent', 0)
            sw_tot = format_bytes(SYSTEM_STATS.get('swap_total_mb', 0)*1024*1024)
            d.text((cx+pad, cy), f"{swap_p:.0f}%", fill=font_main, font=font_mono_sm)
            vw = get_text_width(d, sw_tot, font_mono_sm)
            d.text((cx+cw-vw-pad, cy), sw_tot, fill=font_dim, font=font_mono_sm)
            cy += 20
            d.rectangle((cx+pad, cy, cx+cw-pad, cy+18), fill=(20, 20, 25))
            sw = int((cw-pad*2) * (swap_p/100.0))
            d.rectangle((cx+pad, cy, cx+pad+sw, cy+18), fill=bar_fill)
            cy += 25

    # DISKS (NVME, etc)
    if settings.get('gk_show_disk', True):
        disks = []
        try:
            for part in psutil.disk_partitions(all=False):
                if 'loop' not in part.device:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append((part.device.split('/')[-1], usage.percent))
        except:
            disks = [("hda", SYSTEM_STATS.get('disk_percent', 0))]

        for name, percent in disks:
            if request_space(45):
                cy = draw_sep(cx, cy, cw, name)
                d.text((cx+pad, cy), f"{percent}%", fill=font_main, font=font_mono_sm)
                d.rectangle((cx+pad+45, cy+2, cx+cw-pad, cy+16), fill=(20, 20, 25))
                dw = int((cw-pad*2 - 45) * (percent/100.0))
                d.rectangle((cx+pad+45, cy+2, cx+pad+45+dw, cy+16), fill=bar_fill)
                cy += 25

    # DOCKER
    if settings.get('gk_show_docker', False):
        if request_space(35):
            try:
                dk = len(subprocess.check_output(['docker', 'ps', '-q']).splitlines())
            except:
                dk = 0
            cy = draw_sep(cx, cy, cw, "docker")
            d.text((cx+pad, cy), f"{dk} containers", fill=font_main, font=font_mono_sm)
            cy += 25
            
    # DEVICES
    if settings.get('gk_show_devices', True):
        if request_space(110):
            cy = draw_sep(cx, cy, cw)
            items = [("cdrom", "/dev/sr0"), ("keydrive", "/dev/sdb1"), ("cardread", "/dev/mmcblk0"), ("fwdrive", "/dev/sdc1")]
            
            # Tenta detectar montagens reais
            partitions = psutil.disk_partitions(all=True)
            mounted_devs = [p.device for p in partitions]
            
            for it, dev in items:
                cy += 5
                is_active = any(dev in m for m in mounted_devs) or os.path.exists(dev)
                d.rectangle((cx+pad, cy+8, cx+pad+4, cy+12), fill=(0,255,0) if is_active else (50, 50, 50))
                d.text((cx+pad+10, cy), it, fill=font_main, font=font_mono_sm)
                by = cy + 4
                d.rectangle((cx+cw-30, by, cx+cw-10, by+10), fill=line_top, outline=line_bot)
                if is_active:
                    d.rectangle((cx+cw-20, by+2, cx+cw-12, by+8), fill=(100, 255, 100))
                else:
                    d.rectangle((cx+cw-20, by+2, cx+cw-12, by+8), fill=(40, 45, 50))
                cy += 25

    # MEDIA
    if settings.get('gk_show_media', True):
        if request_space(130):
            vol = "4/4"
            play_st = "( )"
            track = "Idle"
            try:
                # Tentativa de pegar info media real dbus do KDE/GNOME
                pmt = subprocess.check_output("playerctl status 2>/dev/null", shell=True, text=True).strip()
                if "Playing" in pmt:
                    play_st = "(>)"
                    tr = subprocess.check_output("playerctl metadata title 2>/dev/null", shell=True, text=True).strip()
                    track = tr[:12] if tr else "Track 1"
                elif "Paused" in pmt:
                    play_st = "(II)"
                
                v = subprocess.check_output("amixer sget Master 2>/dev/null | grep 'Right:' | awk -F'[][]' '{ print $2 }'", shell=True, text=True).strip()
                if v: vol = v
            except: pass
                
            cy += 10
            d.text((cx + cw//2 - 25, cy+10), play_st, fill=font_blue, font=font_mono_lg)
            d.text((cx + cw//2 + 15, cy + 14), vol, fill=font_main, font=font_mono)
            cy += 45
            d.text((cx+pad, cy), "Pcm", fill=font_main, font=font_mono_sm)
            d.line((cx+40, cy+10, cx+cw-30, cy+10), fill=line_top, width=2)
            if play_st == "(>)":
                d.ellipse((cx+cw-25, cy+4, cx+cw-10, cy+19), fill=(0,255,0))
            else:
                d.ellipse((cx+cw-25, cy+4, cx+cw-10, cy+19), fill=font_blue)
            cy += 25
            d.text((cx+pad, cy), "CD", fill=font_main, font=font_mono_sm)
            d.line((cx+40, cy+10, cx+cw-30, cy+10), fill=line_top, width=2)
            d.ellipse((cx+40, cy+4, cx+55, cy+19), fill=font_blue)
            cy += 20
            tw = get_text_width(d, track, font_mono)
            d.text((cx + (cw-tw)//2, cy), track, fill=font_dim, font=font_mono)
            cy += 25

    # PPP
    if settings.get('gk_show_ppp', False):
        ppps = ["ppp0", "ppp1", "ppp2"]
        for p in ppps:
            if request_space(80):
                cy = draw_sep(cx, cy, cw, p, is_net=True)
                d.text((cx+pad, cy), "0", fill=font_main, font=font_mono_sm)
                cy += 20
                cy = draw_graph(cx+pad, cy, cw-pad*2, 30, [max(0, x-5) for x in list(CPU_USAGE_HISTORY)], 100, "mixed", color=font_blue, current_val=0)

    # VLAN
    if settings.get('gk_show_vlan', False):
        if request_space(45):
            cy = draw_sep(cx, cy, cw, "vlan1", is_net=True)
            d.text((cx+pad, cy), "0", fill=font_main, font=font_mono_sm)
            cy += 25

    # SYS (TENSÕES)
    if settings.get('gk_show_sys', True):
        sensors_sys = []
        try:
            temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
            fans = psutil.sensors_fans() if hasattr(psutil, "sensors_fans") else {}
            # get some random actual sys values for hardware feeling
            for name, entries in temps.items():
                if "nvme" in name or "acpi" in name or "k10temp" in name:
                    for e in entries[:2]:
                        lbl = e.label if e.label else name
                        sensors_sys.append((lbl[:6], f"{e.current}°C"))
            for name, entries in fans.items():
                for e in entries[:2]:
                    lbl = e.label if e.label else name
                    sensors_sys.append((lbl[:6], f"{e.current}R"))
        except: pass
        
        if not sensors_sys: # Fallback dummy
            sensors_sys = [
                ("Vcore", "1.79V"),
                ("+3.3V", "3.29V"),
                ("+5V", "5.00V"),
                ("Fan0", "3770")
            ]
        
        sensors_sys = sensors_sys[:6] # Limite para não explodir layout
        if request_space(35 + len(sensors_sys)*20):
            cy = draw_sep(cx, cy, cw, "sys")
            
            # Adiciona sensores avançados solicitados se existirem na GPU ativa
            gpu = SYSTEM_STATS["gpus"][0] if SYSTEM_STATS["gpus"] else {}
            for label in ["ppt", "edge", "junc", "mem", "vddgfx", "vddnb", "power"]:
                if label in gpu:
                    sensors_sys.append((label, gpu[label]))
            
            for k, v in sensors_sys[:10]: # Aumentado limite
                d.text((cx+pad, cy), k, fill=font_main, font=font_mono_sm)
                tw = get_text_width(d, v, font_mono_sm)
                d.text((cx+cw-tw-pad, cy), v, fill=font_main, font=font_mono_sm)
                cy += 20
            cy += 10

    # HDA (I/O)
    if settings.get('gk_show_hda', True):
        if request_space(100):
            disk_u = SYSTEM_STATS.get('disk_percent', 0)
            io_kb = SYSTEM_STATS.get('disk_io_kbs', 0)
            io_str = f"{io_kb/1024:.1f}M" if io_kb > 1024 else f"{io_kb:.1f}K"
            
            cy = draw_sep(cx, cy, cw, "hda")
            cy = draw_graph(cx+pad, cy, cw-pad*2, graph_h, list(DISK_IO_HISTORY), 500, "mixed", color=font_blue, current_val=min(500, io_kb))
            d.text((cx+pad, cy), f"{disk_u}%", fill=font_main, font=font_mono_sm)
            vw = get_text_width(d, io_str, font_mono_sm)
            d.text((cx+cw-vw-pad, cy), io_str, fill=font_dim, font=font_mono_sm)
            cy += 20
            cy += 5

    # INET0
    if settings.get('gk_show_inet', False):
        if request_space(80):
            cy = draw_sep(cx, cy, cw, "inet0", is_net=True)
            d.text((cx+pad, cy), "0", fill=font_main, font=font_mono_sm)
            cy += 20
            cy = draw_graph(cx+pad, cy, cw-pad*2, 30, [max(0, x-5) for x in list(CPU_USAGE_HISTORY)], 100, "mixed", color=font_blue, current_val=0)

    # BATTERY
    if settings.get('gk_show_battery', False):
        if request_space(50):
            try:
                bat = psutil.sensors_battery()
                b_pct = bat.percent if bat else 100
                plt = "AC" if bat and bat.power_plugged else "BAT"
                prof = SYSTEM_STATS.get("power_profile", "")
                bat_str = f"{b_pct}% {plt}"
                if prof: bat_str += f" [{prof}]"
            except:
                bat_str = "100% AC"
            cy = draw_sep(cx, cy, cw, "bat0")
            d.text((cx+pad, cy), bat_str, fill=font_main, font=font_mono_sm)
            cy += 25
    
    # Preenchimentos
    d.line((0, height-2, width, height-2), fill=line_bot, width=2)
    return img


def _planet_cpu_model():
    """Return a short CPU model name for the compact Planet panel."""
    cached = getattr(_planet_cpu_model, "cached", None)
    if cached:
        return cached

    model = platform.processor() or "CPU"
    try:
        with open("/proc/cpuinfo", "r") as cpuinfo:
            for line in cpuinfo:
                if line.lower().startswith("model name") and ":" in line:
                    model = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass

    model = re.sub(r"\s+", " ", model).strip()
    if len(model) > 25:
        model = model[:24].rstrip() + "…"
    _planet_cpu_model.cached = model or "CPU"
    return _planet_cpu_model.cached


def _planet_temperature(value):
    """Convert a sensor value such as '62°C' into a float or None."""
    try:
        return float(re.sub(r"[^0-9.+-]", "", str(value)))
    except (TypeError, ValueError):
        return None


def _planet_julian_day(when):
    """Convert an aware UTC datetime to a Julian day."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp() / 86400.0 + 2440587.5


def _planet_normalize_longitude(longitude):
    return ((longitude + 180.0) % 360.0) - 180.0


def _planet_sidereal_degrees(julian_day):
    """Greenwich apparent sidereal time, adequate for a display globe."""
    centuries = (julian_day - 2451545.0) / 36525.0
    sidereal = (280.46061837
                + 360.98564736629 * (julian_day - 2451545.0)
                + 0.000387933 * centuries * centuries
                - centuries * centuries * centuries / 38710000.0)
    return sidereal % 360.0


def _planet_sun_position(when):
    """Return the Sun's subsolar latitude/longitude in degrees.

    The longitude is the geographic point where the Sun is overhead. The
    low-order solar model is more than sufficient for a 3.5-inch telemetry
    display and keeps the feature fully offline.
    """
    jd = _planet_julian_day(when)
    days = jd - 2451545.0
    mean_longitude = math.radians((280.460 + 0.9856474 * days) % 360.0)
    mean_anomaly = math.radians((357.528 + 0.9856003 * days) % 360.0)
    ecliptic_longitude = (mean_longitude
                          + math.radians(1.915) * math.sin(mean_anomaly)
                          + math.radians(0.020) * math.sin(2.0 * mean_anomaly))
    obliquity = math.radians(23.439 - 0.0000004 * days)
    right_ascension = math.degrees(math.atan2(
        math.cos(obliquity) * math.sin(ecliptic_longitude),
        math.cos(ecliptic_longitude))) % 360.0
    declination = math.degrees(math.asin(
        math.sin(obliquity) * math.sin(ecliptic_longitude)))
    longitude = _planet_normalize_longitude(
        right_ascension - _planet_sidereal_degrees(jd))
    return declination, longitude


def _planet_moon_position(when):
    """Return the Moon's approximate sublunar latitude/longitude in degrees."""
    jd = _planet_julian_day(when)
    days = jd - 2451543.5
    ascending_node = math.radians((125.1228 - 0.0529538083 * days) % 360.0)
    inclination = math.radians(5.1454)
    argument = math.radians((318.0634 + 0.1643573223 * days) % 360.0)
    eccentricity = 0.054900
    mean_anomaly = math.radians((115.3654 + 13.0649929509 * days) % 360.0)

    eccentric_anomaly = math.degrees(mean_anomaly) + math.degrees(eccentricity) * math.sin(mean_anomaly) \
        * (1.0 + eccentricity * math.cos(mean_anomaly))
    eccentric_anomaly = math.radians(eccentric_anomaly)
    xv = 60.2666 * (math.cos(eccentric_anomaly) - eccentricity)
    yv = 60.2666 * math.sqrt(1.0 - eccentricity * eccentricity) * math.sin(eccentric_anomaly)
    true_anomaly = math.atan2(yv, xv)
    distance = math.hypot(xv, yv)
    longitude = true_anomaly + argument

    x_ecliptic = distance * (math.cos(ascending_node) * math.cos(longitude)
                             - math.sin(ascending_node) * math.sin(longitude) * math.cos(inclination))
    y_ecliptic = distance * (math.sin(ascending_node) * math.cos(longitude)
                             + math.cos(ascending_node) * math.sin(longitude) * math.cos(inclination))
    z_ecliptic = distance * math.sin(longitude) * math.sin(inclination)

    obliquity = math.radians(23.4393)
    x_equatorial = x_ecliptic
    y_equatorial = y_ecliptic * math.cos(obliquity) - z_ecliptic * math.sin(obliquity)
    z_equatorial = y_ecliptic * math.sin(obliquity) + z_ecliptic * math.cos(obliquity)
    right_ascension = math.degrees(math.atan2(y_equatorial, x_equatorial)) % 360.0
    declination = math.degrees(math.atan2(
        z_equatorial, math.hypot(x_equatorial, y_equatorial)))
    sublunar_longitude = _planet_normalize_longitude(
        right_ascension - _planet_sidereal_degrees(jd))
    return declination, sublunar_longitude


def _planet_path(position_function, when, hours_before=12, hours_after=12, step_minutes=60):
    path = []
    for minutes in range(-hours_before * 60, hours_after * 60 + 1, step_minutes):
        point_time = when + timedelta(minutes=minutes)
        path.append(position_function(point_time))
    return path


def _planet_texture():
    """Load the detailed equirectangular Earth texture once."""
    cached = getattr(_planet_texture, "cached", False)
    if cached is not False:
        return cached
    path = os.path.join(BASE_DIR, "img", "planet-earth-texture.png")
    try:
        _planet_texture.cached = np.asarray(Image.open(path).convert("RGB"))
    except Exception:
        _planet_texture.cached = None
    return _planet_texture.cached


def _planet_globe(radius, phase, sun_position, moon_position, sun_path, moon_path):
    """Build the detailed Earth with clock-based illumination and tracks."""
    radius = max(12, int(radius))
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    nx = xx / radius
    ny = yy / radius
    distance = nx * nx + ny * ny
    inside = distance <= 1.0
    nz = np.sqrt(np.clip(1.0 - distance, 0.0, 1.0))

    sun_latitude, sun_longitude = sun_position
    sun_lon_screen = math.radians(sun_longitude) + phase
    sun_lat_screen = math.radians(sun_latitude)
    sun_vector_x = math.cos(sun_lat_screen) * math.sin(sun_lon_screen)
    sun_vector_y = math.sin(sun_lat_screen)
    sun_vector_z = math.cos(sun_lat_screen) * math.cos(sun_lon_screen)
    # The terminator is driven by the actual subsolar point, not an animation.
    light = np.clip((nx * sun_vector_x) - (ny * sun_vector_y) + (nz * sun_vector_z), -1.0, 1.0)
    day = np.clip(0.18 + (light * 0.82), 0.045, 1.0)
    texture = _planet_texture()
    if texture is not None:
        texture_height, texture_width = texture.shape[:2]
        screen_longitude = np.arctan2(nx, nz)
        world_longitude = screen_longitude - phase
        latitude = np.arcsin(np.clip(-ny, -1.0, 1.0))
        texture_x = ((world_longitude + math.pi) / (2.0 * math.pi) * texture_width).astype(int) % texture_width
        texture_y = ((math.pi / 2.0 - latitude) / math.pi * (texture_height - 1)).astype(int)
        pixels = texture[texture_y, texture_x].astype(np.float32)
        shade = np.where(light >= 0.0, 0.25 + 0.75 * light, 0.035 + 0.13 * (light + 1.0))
        city_lights = np.maximum(0.0, pixels[..., 0] - pixels[..., 2] * 0.72) / 255.0
        pixels = pixels * shade[..., None]
        pixels += city_lights[..., None] * np.clip(-light[..., None], 0.0, 1.0) * np.array([155.0, 91.0, 24.0])
        rim = np.clip((1.0 - nz) * 1.8, 0.0, 1.0)
        pixels += rim[..., None] * np.array([4.0, 32.0, 72.0])
        pixels = np.clip(pixels, 0, 255).astype(np.uint8)
    else:
        noise = (np.sin(xx * 0.23) + np.sin(yy * 0.17)) * 2.0
        red = np.clip((8 + 16 * day + noise), 0, 255)
        green = np.clip((31 + 72 * day + noise), 0, 255)
        blue = np.clip((82 + 125 * day + noise), 0, 255)
        pixels = np.dstack((red, green, blue)).astype(np.uint8)
    pixels[~inside] = 0
    globe = Image.fromarray(pixels, "RGB")
    draw = ImageDraw.Draw(globe, "RGBA")
    center = radius

    def project(longitude, latitude):
        lon = math.radians(longitude) + phase
        lat = math.radians(latitude)
        visible = math.cos(lat) * math.cos(lon) > -0.08
        x = center + radius * math.cos(lat) * math.sin(lon)
        y = center - radius * math.sin(lat)
        return x, y, visible

    # Keep the generated texture clean: the detailed coastlines and terrain
    # remain visible, while the astronomy tracks are the only overlays.
    cities = [(-74, 10), (-58, -15), (-3, 6), (31, 30), (37,  -1),
              (77, 28), (116, 40), (139, 36), (151, -33)]
    for longitude, latitude in cities:
        x, y, visible = project(longitude, latitude)
        lon = math.radians(longitude) + phase
        lat = math.radians(latitude)
        city_light = math.cos(lat) * math.cos(lon) * 0.30 - math.sin(lat) * 0.20
        if visible and city_light < 0.02:
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(255, 208, 103, 190))

    def draw_path(path, color):
        segment = []
        path_width = max(1, radius // 55)
        for latitude, longitude in path:
            x, y, visible = project(longitude, latitude)
            if visible:
                segment.append((x, y))
            elif len(segment) > 1:
                draw.line(segment, fill=color, width=path_width)
                segment = []
        if len(segment) > 1:
            draw.line(segment, fill=color, width=path_width)

    # The two tracks show where the bodies have been and where they are going
    # over the surrounding 24 hours. The current markers are drawn brighter.
    draw_path(sun_path, (255, 181, 72, 145))
    draw_path(moon_path, (226, 237, 255, 110))

    moon_latitude, moon_longitude = moon_position
    sun_x, sun_y, sun_visible = project(sun_longitude, sun_latitude)
    if sun_visible:
        marker_radius = max(3, radius // 22)
        draw.ellipse((sun_x - marker_radius - 2, sun_y - marker_radius - 2,
                      sun_x + marker_radius + 2, sun_y + marker_radius + 2),
                     outline=(255, 224, 129, 180), width=1)
        draw.ellipse((sun_x - marker_radius, sun_y - marker_radius,
                      sun_x + marker_radius, sun_y + marker_radius),
                     fill=(255, 170, 48, 255), outline=(255, 245, 170, 255))
        draw.line((sun_x - marker_radius - 4, sun_y, sun_x + marker_radius + 4, sun_y),
                  fill=(255, 205, 87, 230), width=1)
        draw.line((sun_x, sun_y - marker_radius - 4, sun_x, sun_y + marker_radius + 4),
                  fill=(255, 205, 87, 230), width=1)

    moon_x, moon_y, moon_visible = project(moon_longitude, moon_latitude)
    if moon_visible:
        marker_radius = max(3, radius // 27)
        draw.ellipse((moon_x - marker_radius, moon_y - marker_radius,
                      moon_x + marker_radius, moon_y + marker_radius),
                     fill=(214, 228, 238, 230), outline=(255, 255, 255, 240))
        draw.ellipse((moon_x - 1, moon_y - 2, moon_x + 1, moon_y), fill=(145, 170, 188, 220))

    return globe


def _planet_moon_icon(radius, phase_angle):
    """Return a small Moon sprite whose lit side follows the Sun angle."""
    radius = max(3, int(radius))
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    nx = xx / radius
    ny = yy / radius
    distance = nx * nx + ny * ny
    inside = distance <= 1.0
    nz = np.sqrt(np.clip(1.0 - distance, 0.0, 1.0))
    light = np.clip(
        nx * math.sin(phase_angle) + nz * math.cos(phase_angle), -1.0, 1.0)
    shade = np.clip(0.12 + 0.88 * light, 0.055, 1.0)
    crater_noise = (np.sin(xx * 1.7) + np.sin(yy * 1.35)) * 4.0
    gray = np.clip(42.0 + shade * 166.0 + crater_noise, 0.0, 255.0)
    pixels = np.dstack((gray * 0.88, gray, gray * 1.04)).clip(0, 255).astype(np.uint8)
    pixels[~inside] = 0
    sprite = Image.fromarray(pixels, "RGB")
    mask = Image.fromarray((inside.astype(np.uint8) * 255), "L")
    return sprite, mask


def render_dashboard_planet_portrait(width, height, settings):
    """Render Planet as one vertical column for portrait displays."""
    scale = max(0.75, min(width / 320.0, height / 480.0))
    colors = get_theme_colors("planet")
    img = Image.new("RGB", (width, height), colors["bg"])
    d = ImageDraw.Draw(img)
    font_dir = os.path.join(BASE_DIR, "fonts")

    def make_font(filename, size):
        try:
            return ImageFont.truetype(os.path.join(font_dir, filename), max(7, int(size)))
        except Exception:
            return ImageFont.load_default()

    font_title = make_font("DejaVuSans-Bold.ttf", 12 * scale)
    font_time = make_font("DejaVuSans-Bold.ttf", 23 * scale)
    font_medium = make_font("DejaVuSans-Bold.ttf", 10.2 * scale)
    font_small = make_font("DejaVuSans.ttf", 8.5 * scale)
    font_mono = make_font("DejaVuSans.ttf", 8.6 * scale)
    font_mono_bold = make_font("DejaVuSans-Bold.ttf", 8.6 * scale)
    line_width = max(1, int(scale))
    panel_radius = max(3, int(6 * scale))
    margin = max(5, int(6 * scale))
    inner_x = margin + max(5, int(7 * scale))
    inner_w = width - inner_x * 2

    def panel(x, y, w, h, fill=colors["panel_bg"]):
        d.rounded_rectangle((x, y, x + w, y + h), radius=panel_radius,
                            fill=fill, outline=colors["border"], width=line_width)

    def text(x, y, value, font=font_small, fill=colors["text_main"]):
        d.text((int(x), int(y)), str(value), font=font, fill=fill)

    def clipped(value, limit):
        value = str(value)
        return value if len(value) <= limit else value[:max(1, limit - 1)] + "…"

    now_local = datetime.now()
    now_utc = datetime.now(timezone.utc)
    astronomy_utc = now_utc.replace(second=0, microsecond=0)
    julian_day = _planet_julian_day(astronomy_utc)
    sun_position = _planet_sun_position(astronomy_utc)
    moon_position = _planet_moon_position(astronomy_utc)
    sun_path = _planet_path(_planet_sun_position, astronomy_utc)
    moon_path = _planet_path(_planet_moon_position, astronomy_utc, step_minutes=120)
    earth_phase = math.radians(_planet_sidereal_degrees(julian_day))
    moon_elongation = math.radians(
        _planet_normalize_longitude(moon_position[1] - sun_position[1]))
    moon_illumination = (1.0 - math.cos(moon_elongation)) / 2.0
    moon_light_phase = math.radians(
        _planet_normalize_longitude(moon_position[1] - sun_position[1] + 180.0))

    # One uninterrupted portrait canvas: header, astronomical view and then
    # the complete hardware stack.
    panel(margin, margin, width - margin * 2, height - margin * 2, (2, 8, 22))
    text(inner_x, int(10 * scale), "PLANET", font_title, colors["text_label"])
    text(inner_x, int(27 * scale), "SYSTEM ORBIT // PORTRAIT", font_mono, colors["text_muted"])
    text(inner_x, int(39 * scale), now_local.strftime("%H:%M:%S"), font_time, colors["time"])
    text(inner_x, int(65 * scale), now_local.strftime("%a, %Y-%m-%d"), font_small, colors["text_main"])
    text(inner_x, int(77 * scale), "SUNNY / WIND 3 / 22°C", font_mono, colors["text_muted"])

    # Keep the astronomical readout beside the clock/date, leaving the
    # entire area above the globe visually clear for the orbital view.
    astro_x = inner_x + int(inner_w * 0.49)
    astro_y = int(25 * scale)
    astro_w = width - margin - astro_x
    astro_h = max(51, int(51 * scale))
    panel(astro_x, astro_y, astro_w, astro_h, (5, 14, 31))
    astro_text_w = max(10, astro_w - max(8, int(10 * scale)))
    text(astro_x + max(4, int(5 * scale)), astro_y + max(2, int(3 * scale)),
         fit_text_to_width(d, f"SUN {sun_position[0]:+.1f}° {sun_position[1]:+.1f}°",
                           astro_text_w, font_mono_bold),
         font_mono_bold, (255, 190, 84))
    text(astro_x + max(4, int(5 * scale)), astro_y + max(14, int(16 * scale)),
         fit_text_to_width(d, f"MOON {moon_position[0]:+.1f}° {moon_position[1]:+.1f}°",
                           astro_text_w, font_mono_bold),
         font_mono_bold, colors["text_main"])
    text(astro_x + max(4, int(5 * scale)), astro_y + max(27, int(29 * scale)),
         fit_text_to_width(d, f"MOON LIGHT {moon_illumination * 100:.0f}% · UTC",
                           astro_text_w, font_mono),
         font_mono, colors["text_muted"])

    planet_radius = max(32, int(min(width * 0.156, height * 0.105)))
    planet_cx = width // 2
    planet_cy = int(162 * scale)
    orbit_rx = planet_radius + max(8, int(10 * scale))
    orbit_ry = planet_radius + max(7, int(9 * scale))
    orbit_box = (planet_cx - orbit_rx, planet_cy - orbit_ry,
                 planet_cx + orbit_rx, planet_cy + orbit_ry)
    d.arc(orbit_box, 0, 360, fill=(31, 86, 126), width=line_width)
    moon_orbit_angle = math.radians(moon_position[1]) + earth_phase
    moon_orbit_x = planet_cx + orbit_rx * math.cos(moon_orbit_angle)
    moon_orbit_y = planet_cy + orbit_ry * math.sin(moon_orbit_angle)
    d.arc(orbit_box, math.degrees(moon_orbit_angle) - 22,
          math.degrees(moon_orbit_angle) + 22,
          fill=(179, 218, 238), width=max(1, line_width + 1))
    d.ellipse((planet_cx - planet_radius - 4, planet_cy - planet_radius - 4,
               planet_cx + planet_radius + 4, planet_cy + planet_radius + 4),
              outline=(31, 120, 174), width=line_width)
    globe = _planet_globe(planet_radius, earth_phase, sun_position, moon_position,
                          sun_path, moon_path)
    mask = Image.new("L", globe.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, globe.width - 1, globe.height - 1), fill=255)
    img.paste(globe, (planet_cx - planet_radius, planet_cy - planet_radius), mask)
    d = ImageDraw.Draw(img)
    d.ellipse((planet_cx - planet_radius, planet_cy - planet_radius,
               planet_cx + planet_radius, planet_cy + planet_radius),
              outline=(124, 222, 255), width=line_width)
    moon_radius = max(3, int(5 * scale))
    moon_sprite, moon_mask = _planet_moon_icon(moon_radius, moon_light_phase)
    img.paste(moon_sprite,
              (int(moon_orbit_x - moon_radius), int(moon_orbit_y - moon_radius)),
              moon_mask)
    d = ImageDraw.Draw(img)
    d.ellipse((moon_orbit_x - moon_radius - 1, moon_orbit_y - moon_radius - 1,
               moon_orbit_x + moon_radius + 1, moon_orbit_y + moon_radius + 1),
              outline=(235, 247, 255), width=line_width)
    moon_label_x = min(width - margin - get_text_width(d, "MOON", font_mono),
                       moon_orbit_x + moon_radius + 3)
    text(moon_label_x, moon_orbit_y - max(4, int(4 * scale)), "MOON",
         font_mono, (226, 237, 255))
    text(inner_x, int(226 * scale),
         "TERMINATOR LIVE  ·  MOON ORBIT",
         font_mono, (255, 190, 84))

    hardware_y = int(237 * scale)
    text(inner_x, hardware_y, "HARDWARE TELEMETRY", font_medium, colors["text_label"])
    gpu_list = SYSTEM_STATS.get("gpus", [])
    gpu_idx = min(SYSTEM_STATS.get("active_gpu_idx", 0), max(0, len(gpu_list) - 1))
    active_gpu = gpu_list[gpu_idx] if gpu_list else {}
    cpu_freq = None
    try:
        cpu_freq = psutil.cpu_freq().current
    except Exception:
        pass
    cpu_freq_text = f"{cpu_freq:.0f}M" if cpu_freq else "--"
    cpu_name = clipped(_planet_cpu_model(), 16)
    gpu_name = clipped(active_gpu.get("name", "GPU"), 16)
    gpu_usage = float(active_gpu.get("percent", 0.0) or 0.0)
    gpu_mem = float(active_gpu.get("mem_used_mb", 0) or 0)
    gpu_mem_total = float(active_gpu.get("mem_total_mb", 0) or 0)
    gpu_mem_percent = (gpu_mem / gpu_mem_total * 100.0) if gpu_mem_total else 0.0
    card_y = int(247 * scale)
    card_h = max(23, int(23 * scale))

    def draw_hardware_row(y, label, model, temperature, load, accent):
        panel(inner_x, y, inner_w, card_h, (5, 14, 31))
        numeric = _planet_temperature(temperature)
        temp_text = f"{numeric:.0f}°" if numeric is not None else "--"
        temp_w = get_text_width(d, temp_text, font_mono_bold)
        temp_color = colors["crit"] if (numeric is not None and numeric >= 85) else (
            colors["warn"] if (numeric is not None and numeric >= 60) else colors["good"])
        label_x = inner_x + max(4, int(6 * scale))
        temp_x = inner_x + inner_w - temp_w - max(4, int(6 * scale))
        load_text = f"{load:.0f}%"
        load_w = get_text_width(d, load_text, font_mono_bold)
        load_x = temp_x - load_w - max(8, int(10 * scale))
        model_x = label_x + max(25, int(28 * scale))
        model_w = max(20, load_x - model_x - max(8, int(9 * scale)))
        text(label_x, y + max(2, int(2 * scale)), label, font_mono_bold, colors["text_label"])
        text(model_x, y + max(2, int(2 * scale)),
             fit_text_to_width(d, model, model_w, font_mono),
             font_mono, colors["text_main"])
        text(load_x, y + max(2, int(2 * scale)), load_text, font_mono_bold, colors["text_muted"])
        text(temp_x, y + max(2, int(2 * scale)), temp_text, font_mono_bold, temp_color)
        track_y = y + card_h - max(2, int(3 * scale))
        d.line((inner_x + 4, track_y, inner_x + inner_w - 4, track_y), fill=colors["bar_bg"], width=line_width)
        fill_w = int((inner_w - 8) * max(0.0, min(100.0, load)) / 100.0)
        if fill_w:
            d.line((inner_x + 4, track_y, inner_x + 4 + fill_w, track_y), fill=accent,
                   width=max(2, line_width + 1))

    draw_hardware_row(card_y, "CPU", cpu_name, SYSTEM_STATS.get("cpu_temp"),
                      SYSTEM_STATS.get("cpu_percent", 0), colors["good"])
    draw_hardware_row(card_y + card_h + max(3, int(3 * scale)), "GPU", gpu_name,
                      active_gpu.get("temp"), gpu_usage, colors["warn"])

    # Wider portrait panels (for example 480x800) have more vertical room.
    # Give that room to the telemetry graphs instead of leaving an empty
    # strip below the RAM card.
    extra_height = max(0, height - margin - int(474 * scale))
    metric_gap = max(3, int(3 * scale)) + extra_height // 24
    metric_y = int(301 * scale)
    metric_h = max(23, int(23 * scale)) + extra_height // 8
    metric_w = inner_w

    def draw_metric(x, y, label, value, percent, history, color):
        panel(x, y, metric_w, metric_h, (5, 14, 31))
        text(x + 4, y + 1, label, font_mono, colors["text_muted"])
        value_w = get_text_width(d, value, font_mono_bold)
        text(x + metric_w - value_w - 4, y + 1, value, font_mono_bold, colors["text_main"])
        graph_y = y + metric_h - max(3, int(4 * scale))
        d.line((x + 4, graph_y, x + metric_w - 4, graph_y), fill=colors["bar_bg"], width=line_width)
        if history and len(history) > 1:
            maximum = max(1.0, max(abs(float(item)) for item in history))
            points = []
            for index, item in enumerate(history):
                px = x + 4 + (metric_w - 8) * index / (len(history) - 1)
                py = graph_y - min(1.0, abs(float(item)) / maximum) * max(3, int(8 * scale))
                points.append((px, py))
            d.line(points, fill=color, width=line_width)
        fill_w = int((metric_w - 8) * max(0.0, min(100.0, percent)) / 100.0)
        if fill_w:
            d.line((x + 4, graph_y, x + 4 + fill_w, graph_y), fill=color,
                   width=max(2, line_width + 1))

    metric_specs = [
        ("CPU", f"{SYSTEM_STATS.get('cpu_percent', 0):.0f}%", SYSTEM_STATS.get("cpu_percent", 0), CPU_USAGE_HISTORY, colors["good"]),
        ("FREQ", cpu_freq_text, min(100.0, (cpu_freq or 0) / 40.0), [], colors["text_label"]),
        ("GPU", f"{gpu_usage:.0f}%", gpu_usage, GPU_USAGE_HISTORY, colors["warn"]),
        ("CLOCK", "--", 0, [], colors["vram"]),
        ("VRAM", f"{gpu_mem:.0f}M" if gpu_mem else "--", gpu_mem_percent, GPU_MEM_HISTORY, colors["vram"]),
    ]
    for index, (label, value, percent, history, color) in enumerate(metric_specs):
        draw_metric(inner_x, metric_y + index * (metric_h + metric_gap),
                    label, value, percent, history, color)

    metric_end = metric_y + len(metric_specs) * metric_h + (len(metric_specs) - 1) * metric_gap
    network_y = metric_end + max(3, int(4 * scale))
    network_h = max(20, int(20 * scale)) + extra_height // 16
    net_up = max(0.0, SYSTEM_STATS.get("net_tx_mbps", 0.0) * 125.0)
    net_down = max(0.0, SYSTEM_STATS.get("net_rx_mbps", 0.0) * 125.0)
    network_specs = [
        ("VOL", "28%", 28, colors["good"]),
        ("U", f"{net_up:.0f}K", min(100.0, net_up / 10.0), colors["text_label"]),
        ("D", f"{net_down:.0f}K", min(100.0, net_down / 10.0), colors["swap"]),
    ]
    network_gap = max(2, int(3 * scale))
    network_w = (inner_w - network_gap * 2) // 3
    for index, (label, value, percent, color) in enumerate(network_specs):
        x = inner_x + index * (network_w + network_gap)
        panel(x, network_y, network_w, network_h, (5, 14, 31))
        text(x + 3, network_y + 1, label, font_mono_bold, colors["text_label"])
        value_w = get_text_width(d, value, font_mono_bold)
        text(x + network_w - value_w - 3, network_y + 1, value, font_mono_bold, colors["text_main"])
        line_y = network_y + network_h - max(3, int(4 * scale))
        d.line((x + 3, line_y, x + network_w - 3, line_y), fill=colors["bar_bg"], width=line_width)
        fill_w = int((network_w - 6) * percent / 100.0)
        if fill_w:
            d.line((x + 3, line_y, x + 3 + fill_w, line_y), fill=color,
                   width=max(2, line_width + 1))

    ram_y = network_y + network_h + max(3, int(4 * scale))
    ram_h = max(18, height - margin - ram_y)
    panel(inner_x, ram_y, inner_w, ram_h, (5, 14, 31))
    text(inner_x + 5, ram_y + max(2, int(2 * scale)), "RAM", font_mono_bold, colors["text_label"])
    ram_values = (f"{SYSTEM_STATS.get('ram_total_mb', 0) / 1024:.1f}G / "
                  f"{SYSTEM_STATS.get('ram_used_mb', 0) / 1024:.1f}G")
    ram_value_w = get_text_width(d, ram_values, font_mono)
    text(inner_x + inner_w - ram_value_w - max(34, int(40 * scale)),
         ram_y + max(2, int(2 * scale)), ram_values, font_mono, colors["text_main"])
    ram_donut_cx = inner_x + inner_w - max(14, int(17 * scale))
    ram_donut_cy = ram_y + ram_h // 2
    ram_donut_r = max(6, int(7 * scale))
    d.ellipse((ram_donut_cx - ram_donut_r, ram_donut_cy - ram_donut_r,
               ram_donut_cx + ram_donut_r, ram_donut_cy + ram_donut_r),
              outline=colors["bar_bg"], width=max(2, int(3 * scale)))
    d.arc((ram_donut_cx - ram_donut_r, ram_donut_cy - ram_donut_r,
           ram_donut_cx + ram_donut_r, ram_donut_cy + ram_donut_r),
          -90, -90 + int(360 * SYSTEM_STATS.get("ram_percent", 0) / 100),
          fill=colors["good"], width=max(2, int(3 * scale)))
    ram_graph_y = ram_y + ram_h - max(4, int(5 * scale))
    ram_graph_x2 = ram_donut_cx - ram_donut_r - max(4, int(5 * scale))
    d.line((inner_x + 5, ram_graph_y, ram_graph_x2, ram_graph_y),
           fill=colors["bar_bg"], width=line_width)
    ram_fill_w = int((ram_graph_x2 - inner_x - 5) *
                     max(0.0, min(100.0, SYSTEM_STATS.get("ram_percent", 0))) / 100.0)
    if ram_fill_w:
        d.line((inner_x + 5, ram_graph_y, inner_x + 5 + ram_fill_w, ram_graph_y),
               fill=colors["good"], width=max(2, line_width + 1))
    ram_usage_text = f"{SYSTEM_STATS.get('ram_percent', 0):.0f}%"
    ram_usage_w = get_text_width(d, ram_usage_text, font_mono)
    text(ram_donut_cx - ram_usage_w / 2, ram_donut_cy - max(3, int(3 * scale)),
         ram_usage_text, font_mono, colors["text_main"])
    return img


def render_dashboard_planet(width, height, settings):
    """Render the Planet interface: orbital Earth plus compact telemetry."""
    if settings.get("orientation") == "vertical" or height > width:
        # The main loop already swaps dimensions for portrait mode. This
        # fallback also handles direct callers that still pass landscape
        # dimensions together with orientation="vertical".
        portrait_width, portrait_height = ((width, height) if height >= width
                                            else (height, width))
        return render_dashboard_planet_portrait(portrait_width, portrait_height, settings)

    scale = max(0.58, min(width / 800.0, height / 480.0))
    colors = get_theme_colors("planet")
    img = Image.new("RGB", (width, height), colors["bg"])
    d = ImageDraw.Draw(img)
    font_dir = os.path.join(BASE_DIR, "fonts")

    def make_font(filename, size):
        try:
            return ImageFont.truetype(os.path.join(font_dir, filename), max(7, int(size)))
        except Exception:
            return ImageFont.load_default()

    font_title = make_font("DejaVuSans-Bold.ttf", 14 * scale)
    font_time = make_font("DejaVuSans-Bold.ttf", 29 * scale)
    font_medium = make_font("DejaVuSans-Bold.ttf", 14 * scale)
    font_small = make_font("DejaVuSans.ttf", 11 * scale)
    font_mono = make_font("DejaVuSans.ttf", 10 * scale)
    font_mono_bold = make_font("DejaVuSans-Bold.ttf", 10 * scale)

    line_width = max(1, int(scale))
    pad = max(5, int(8 * scale))
    radius = max(3, int(7 * scale))

    orbital_x = 7
    right_x = int(width * 0.56)
    right_w = width - right_x - 7
    orbital_w = right_x - orbital_x - 6
    left_x = orbital_x + pad
    # The former information and planet columns now share one uninterrupted
    # orbital canvas, allowing the globe to use almost all of its width.
    center_x = orbital_x
    center_w = orbital_w

    now_local = datetime.now()
    now_utc = datetime.now(timezone.utc)
    astronomy_utc = now_utc.replace(second=0, microsecond=0)
    julian_day = _planet_julian_day(astronomy_utc)
    sun_position = _planet_sun_position(astronomy_utc)
    moon_position = _planet_moon_position(astronomy_utc)
    sun_path = _planet_path(_planet_sun_position, astronomy_utc)
    moon_path = _planet_path(_planet_moon_position, astronomy_utc, step_minutes=120)
    # Earth rotation is tied to Greenwich sidereal time. It advances because
    # the clock advances, never because the renderer runs an animation timer.
    earth_phase = math.radians(_planet_sidereal_degrees(julian_day))
    moon_elongation = math.radians(
        _planet_normalize_longitude(moon_position[1] - sun_position[1]))
    moon_illumination = (1.0 - math.cos(moon_elongation)) / 2.0
    # The icon helper expects zero to mean a fully sun-facing Moon.
    moon_light_phase = math.radians(
        _planet_normalize_longitude(moon_position[1] - sun_position[1] + 180.0))

    def panel(x, y, w, h, fill=colors["panel_bg"]):
        d.rounded_rectangle((x, y, x + w, y + h), radius=radius,
                            fill=fill, outline=colors["border"], width=line_width)

    def text(x, y, value, font=font_small, fill=colors["text_main"]):
        d.text((int(x), int(y)), str(value), font=font, fill=fill)

    def clipped(value, limit):
        value = str(value)
        return value if len(value) <= limit else value[:max(1, limit - 1)] + "…"

    def draw_line_bar(x, y, w, label, value, percent, history, color):
        bar_h = max(20, int(34 * scale))
        panel(x, y, w, bar_h, (5, 14, 31))
        text(x + 5, y + 3, label, font_mono_bold, colors["text_label"])
        value_w = get_text_width(d, value, font_mono_bold)
        text(x + w - value_w - 5, y + 3, value, font_mono_bold, colors["text_main"])
        graph_y = y + bar_h - max(5, int(8 * scale))
        if history and len(history) > 1:
            max_value = max(1.0, max(abs(float(item)) for item in history))
            points = []
            for i, item in enumerate(history):
                px = x + 4 + ((w - 8) * i / (len(history) - 1))
                py = graph_y - min(1.0, abs(float(item)) / max_value) * max(3, int(7 * scale))
                points.append((px, py))
            d.line(points, fill=color, width=line_width)
        d.line((x + 5, graph_y, x + w - 5, graph_y), fill=colors["bar_bg"], width=line_width)
        fill_w = int((w - 10) * max(0.0, min(100.0, percent)) / 100.0)
        if fill_w:
            d.line((x + 5, graph_y, x + 5 + fill_w, graph_y), fill=color, width=max(2, line_width + 1))

    def metric_bar(x, y, w, label, value, percent, history, color):
        bar_h = max(30, int(58 * scale))
        panel(x, y, w, bar_h, (5, 14, 31))
        text(x + 5, y + 3, label, font_mono, colors["text_muted"])
        value_w = get_text_width(d, value, font_mono_bold)
        text(x + w - value_w - 5, y + 3, value, font_mono_bold, colors["text_main"])
        graph_top = y + int(bar_h * 0.53)
        graph_bottom = y + bar_h - 4
        d.line((x + 5, graph_bottom, x + w - 5, graph_bottom), fill=colors["bar_bg"], width=line_width)
        if history and len(history) > 1:
            maximum = max(1.0, max(abs(float(item)) for item in history))
            points = []
            for i, item in enumerate(history):
                px = x + 5 + ((w - 10) * i / (len(history) - 1))
                py = graph_bottom - (min(1.0, abs(float(item)) / maximum) * (graph_bottom - graph_top))
                points.append((px, py))
            d.line(points, fill=color, width=line_width)
        fill_w = int((w - 10) * max(0.0, min(100.0, percent)) / 100.0)
        if fill_w:
            d.line((x + 5, graph_bottom, x + 5 + fill_w, graph_bottom), fill=color, width=max(2, line_width + 1))

    def draw_temperature_gauge(x, y, w, h, label, value):
        panel(x, y, w, h, (5, 14, 31))
        numeric = _planet_temperature(value)
        ratio = max(0.0, min(1.0, (numeric or 0.0) / 100.0))
        track_x = x + w // 2 - max(2, int(3 * scale))
        track_top = y + int(h * 0.25)
        track_bottom = y + h - int(h * 0.15)
        d.rounded_rectangle((track_x - 2, track_top, track_x + max(4, int(6 * scale)), track_bottom),
                            radius=3, fill=colors["bar_bg"])
        fill_top = track_bottom - int((track_bottom - track_top) * ratio)
        if numeric is not None:
            temp_color = colors["crit"] if numeric >= 85 else (colors["warn"] if numeric >= 60 else colors["good"])
            d.rounded_rectangle((track_x - 2, fill_top, track_x + max(4, int(6 * scale)), track_bottom),
                                radius=3, fill=temp_color)
        value_text = f"{numeric:.0f}°" if numeric is not None else "--"
        value_w = get_text_width(d, value_text, font_medium)
        text(x + (w - value_w) // 2, y + 4, value_text, font_medium, colors["text_main"])
        label_w = get_text_width(d, label, font_mono)
        text(x + (w - label_w) // 2, y + h - int(13 * scale), label, font_mono, colors["text_muted"])

    # ORBITAL PANEL: information and the enlarged planet share one canvas.
    panel(orbital_x, 7, orbital_w, height - 14, (2, 8, 22))
    text(left_x, 11, "PLANET", font_title, colors["text_label"])
    text(left_x, 31, "SYSTEM ORBIT", font_mono, colors["text_muted"])
    time_y = max(30, int(50 * scale))
    date_y = max(52, int(87 * scale))
    weather_y = max(66, int(105 * scale))
    text(left_x, time_y, now_local.strftime("%H:%M:%S"), font_time, colors["time"])
    text(left_x, date_y, now_local.strftime("%a, %Y-%m-%d"), font_small, colors["text_main"])
    text(left_x, weather_y, "SUNNY / WIND 3 / 22°C", font_mono, colors["text_muted"])

    solar_x = orbital_x + int(orbital_w * 0.56)
    text(solar_x, 11, "SOLAR TRACK", font_medium, colors["text_label"])
    text(solar_x, 32, f"SUN  {sun_position[0]:+.1f}°  {sun_position[1]:+.1f}°", font_mono, (255, 190, 84))
    text(solar_x, 49, f"MOON {moon_position[0]:+.1f}°  {moon_position[1]:+.1f}°", font_mono, colors["text_main"])
    text(solar_x, 66, f"MOON LIGHT  {moon_illumination * 100:.0f}%", font_mono, colors["text_main"])

    # CENTER: stars, orbital rings and the clock-oriented Earth.
    star_top = max(int(weather_y + 14), int(80 * scale))
    star_bottom = int(height * 0.83)
    for index in range(42):
        sx = center_x + 8 + ((index * 47 + 19) % max(1, center_w - 16))
        sy = star_top + ((index * 31 + 11) % max(1, star_bottom - star_top))
        star_color = (42 + (index % 3) * 20, 91 + (index % 4) * 18, 132 + (index % 5) * 18)
        d.point((sx, sy), fill=star_color)

    planet_radius = int(min(center_w * 0.40, height * 0.30))
    planet_cx = center_x + center_w // 2
    planet_cy = int(height * 0.56)
    orbit_rx = planet_radius + max(12, int(16 * scale))
    orbit_ry = planet_radius + max(9, int(11 * scale))
    orbit_box = (planet_cx - orbit_rx, planet_cy - orbit_ry,
                 planet_cx + orbit_rx, planet_cy + orbit_ry)
    d.arc(orbit_box, 0, 360, fill=(31, 86, 126), width=line_width)
    moon_orbit_angle = math.radians(moon_position[1]) + earth_phase
    moon_orbit_x = planet_cx + orbit_rx * math.cos(moon_orbit_angle)
    moon_orbit_y = planet_cy + orbit_ry * math.sin(moon_orbit_angle)
    d.arc(orbit_box,
          math.degrees(moon_orbit_angle) - 22,
          math.degrees(moon_orbit_angle) + 22,
          fill=(179, 218, 238), width=max(1, line_width + 1))
    d.ellipse((planet_cx - planet_radius - 5, planet_cy - planet_radius - 5,
               planet_cx + planet_radius + 5, planet_cy + planet_radius + 5),
              outline=(31, 120, 174), width=line_width)
    d.arc((planet_cx - planet_radius - 15, planet_cy - planet_radius // 2,
           planet_cx + planet_radius + 15, planet_cy + planet_radius // 2), 185, 355,
          fill=(66, 185, 241), width=line_width)
    globe = _planet_globe(planet_radius, earth_phase, sun_position, moon_position, sun_path, moon_path)
    # Hide the square corners of the procedural globe with a circular mask.
    mask = Image.new("L", globe.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, globe.width - 1, globe.height - 1), fill=255)
    img.paste(globe, (planet_cx - planet_radius, planet_cy - planet_radius), mask)
    d.ellipse((planet_cx - planet_radius, planet_cy - planet_radius,
               planet_cx + planet_radius, planet_cy + planet_radius),
              outline=(124, 222, 255), width=line_width)
    moon_radius = max(4, int(6 * scale))
    moon_sprite, moon_mask = _planet_moon_icon(moon_radius, moon_light_phase)
    img.paste(moon_sprite,
              (int(moon_orbit_x - moon_radius), int(moon_orbit_y - moon_radius)),
              moon_mask)
    d = ImageDraw.Draw(img)
    d.ellipse((moon_orbit_x - moon_radius - 1, moon_orbit_y - moon_radius - 1,
               moon_orbit_x + moon_radius + 1, moon_orbit_y + moon_radius + 1),
              outline=(235, 247, 255), width=line_width)
    moon_label = "MOON"
    moon_label_w = get_text_width(d, moon_label, font_mono)
    moon_label_x = moon_orbit_x + moon_radius + 3
    if moon_label_x + moon_label_w > center_x + center_w - pad:
        moon_label_x = moon_orbit_x - moon_radius - moon_label_w - 3
    text(moon_label_x, moon_orbit_y - 5, moon_label, font_mono, (226, 237, 255))
    orbital_footer_y = height - max(30, int(34 * scale))
    text(left_x, orbital_footer_y, f"SUN  {now_utc.strftime('%H:%M:%S')} UTC", font_mono_bold, (255, 190, 84))
    text(left_x, orbital_footer_y + max(13, int(16 * scale)),
         "TERMINATOR // LIVE  ·  MOON ORBIT", font_mono, colors["text_muted"])

    # RIGHT: telemetry is a dense, two-column dashboard so RAM, network and
    # all performance graphs use the full hardware panel.
    panel(right_x, 7, right_w, height - 14)
    gpu_list = SYSTEM_STATS.get("gpus", [])
    gpu_idx = min(SYSTEM_STATS.get("active_gpu_idx", 0), max(0, len(gpu_list) - 1))
    active_gpu = gpu_list[gpu_idx] if gpu_list else {}
    cpu_freq = None
    try:
        cpu_freq = psutil.cpu_freq().current
    except Exception:
        pass
    cpu_freq_text = f"{cpu_freq:.0f}M" if cpu_freq else "--"
    gpu_name = clipped(active_gpu.get("name", "GPU"), 20)
    cpu_name = clipped(_planet_cpu_model(), 20)
    gpu_usage = float(active_gpu.get("percent", 0.0) or 0.0)
    gpu_mem = float(active_gpu.get("mem_used_mb", 0) or 0)
    gpu_mem_total = float(active_gpu.get("mem_total_mb", 0) or 0)
    gpu_mem_percent = (gpu_mem / gpu_mem_total * 100.0) if gpu_mem_total else 0.0

    text(right_x + pad, 14, "HARDWARE TELEMETRY", font_title, colors["text_label"])
    hardware_x = right_x + pad
    hardware_w = right_w - pad * 2
    card_gap = max(4, int(6 * scale))
    card_w = max(45, (hardware_w - card_gap) // 2)
    card_h = max(44, int(70 * scale))
    cpu_card_y = max(30, int(41 * scale))
    gpu_card_x = hardware_x + card_w + card_gap

    def draw_hardware_card(x, y, label, model, temperature, load, accent):
        panel(x, y, card_w, card_h, (5, 14, 31))
        text(x + 7, y + 5, label, font_medium, colors["text_label"])
        numeric = _planet_temperature(temperature)
        temp_text = f"{numeric:.0f}°" if numeric is not None else "--"
        temp_w = get_text_width(d, temp_text, font_medium)
        temp_color = colors["crit"] if (numeric is not None and numeric >= 85) else (
            colors["warn"] if (numeric is not None and numeric >= 60) else colors["good"])
        text(x + card_w - temp_w - 7, y + 5, temp_text, font_medium, temp_color)
        model_limit = 20 if width >= 600 else 13
        text(x + 7, y + max(23, int(27 * scale)), clipped(model, model_limit),
             font_mono_bold, colors["text_main"])
        text(x + 7, y + card_h - max(17, int(20 * scale)),
             f"LOAD {load:.0f}%  ·  V  --  ·  P  --", font_mono, colors["text_muted"])
        track_y = y + card_h - max(5, int(7 * scale))
        d.line((x + 7, track_y, x + card_w - 7, track_y), fill=colors["bar_bg"], width=line_width)
        fill_w = int((card_w - 14) * max(0.0, min(100.0, load)) / 100.0)
        if fill_w:
            d.line((x + 7, track_y, x + 7 + fill_w, track_y), fill=accent,
                   width=max(2, line_width + 1))

    draw_hardware_card(hardware_x, cpu_card_y, "CPU", cpu_name,
                       SYSTEM_STATS.get("cpu_temp"), SYSTEM_STATS.get("cpu_percent", 0), colors["good"])
    draw_hardware_card(gpu_card_x, cpu_card_y, "GPU", gpu_name,
                       active_gpu.get("temp"), gpu_usage, colors["warn"])

    metric_gap = max(3, int(6 * scale))
    metric_cols = 2
    metric_w = max(30, (hardware_w - metric_gap) // metric_cols)
    metric_y = cpu_card_y + card_h + max(6, int(8 * scale))
    metric_h = max(34, int(66 * scale))
    metric_specs = [
        ("CPU USAGE", f"{SYSTEM_STATS.get('cpu_percent', 0):.0f}%", SYSTEM_STATS.get("cpu_percent", 0), CPU_USAGE_HISTORY, colors["good"]),
        ("CPU FREQ", cpu_freq_text, min(100.0, (cpu_freq or 0) / 40.0), [], colors["text_label"]),
        ("GPU USAGE", f"{gpu_usage:.0f}%", gpu_usage, GPU_USAGE_HISTORY, colors["warn"]),
        ("GPU CLOCK", "--", 0, [], colors["vram"]),
        ("MEM USED", f"{gpu_mem:.0f}M" if gpu_mem else "--", gpu_mem_percent, GPU_MEM_HISTORY, colors["vram"]),
        ("RAM USAGE", f"{SYSTEM_STATS.get('ram_percent', 0):.0f}%",
         SYSTEM_STATS.get("ram_percent", 0), RAM_USAGE_HISTORY, colors["good"]),
    ]
    for index, (label, value, percent, history, color) in enumerate(metric_specs):
        metric_column = index % metric_cols
        metric_row = index // metric_cols
        metric_bar(hardware_x + metric_column * (metric_w + metric_gap),
                   metric_y + metric_row * (metric_h + metric_gap), metric_w,
                   label, value, percent, history, color)

    metric_rows = (len(metric_specs) + metric_cols - 1) // metric_cols
    network_y = metric_y + metric_rows * (metric_h + metric_gap) + max(4, int(6 * scale))
    net_up = max(0.0, SYSTEM_STATS.get("net_tx_mbps", 0.0) * 125.0)
    net_down = max(0.0, SYSTEM_STATS.get("net_rx_mbps", 0.0) * 125.0)
    network_value = (lambda value: f"{value:.0f}K" if width < 600 else f"{value:.0f} KB/s")
    network_specs = [
        ("VOLUME", "28%", 28, [], colors["good"]),
        ("NET/U", network_value(net_up), min(100.0, net_up / 10.0), NET_TX_HISTORY, colors["text_label"]),
        ("NET/D", network_value(net_down), min(100.0, net_down / 10.0), NET_RX_HISTORY, colors["swap"]),
    ]
    network_gap = max(3, int(5 * scale))
    network_w = (hardware_w - network_gap * 2) // 3
    for index, (label, value, percent, history, color) in enumerate(network_specs):
        draw_line_bar(hardware_x + index * (network_w + network_gap), network_y,
                      network_w, label, value, percent, history, color)

    # RAM is intentionally the last full-width card in Hardware Telemetry.
    network_h = max(20, int(34 * scale))
    ram_y = network_y + network_h + max(4, int(6 * scale))
    ram_h = max(43, int(64 * scale))
    panel(hardware_x, ram_y, hardware_w, ram_h, (5, 14, 31))
    text(hardware_x + 7, ram_y + 5, "RAM", font_medium, colors["text_label"])
    text(hardware_x + 7, ram_y + max(21, int(24 * scale)),
         f"{SYSTEM_STATS.get('ram_total_mb', 0) / 1024:.1f} GB TOTAL",
         font_mono, colors["text_main"])
    text(hardware_x + 7, ram_y + max(31, int(43 * scale)),
         f"{SYSTEM_STATS.get('ram_used_mb', 0) / 1024:.1f} G USED",
         font_mono_bold, colors["good"])
    ram_donut_cx = hardware_x + hardware_w - max(25, int(31 * scale))
    ram_donut_cy = ram_y + ram_h // 2
    ram_donut_r = max(10, int(20 * scale))
    d.ellipse((ram_donut_cx - ram_donut_r, ram_donut_cy - ram_donut_r,
               ram_donut_cx + ram_donut_r, ram_donut_cy + ram_donut_r),
              outline=colors["bar_bg"], width=max(3, int(5 * scale)))
    d.arc((ram_donut_cx - ram_donut_r, ram_donut_cy - ram_donut_r,
           ram_donut_cx + ram_donut_r, ram_donut_cy + ram_donut_r),
          -90, -90 + int(360 * SYSTEM_STATS.get("ram_percent", 0) / 100),
          fill=colors["good"], width=max(3, int(5 * scale)))
    ram_usage_text = f"{SYSTEM_STATS.get('ram_percent', 0):.0f}%"
    ram_usage_w = get_text_width(d, ram_usage_text, font_mono_bold)
    text(ram_donut_cx - ram_usage_w / 2, ram_donut_cy - 4 * scale,
         ram_usage_text, font_mono_bold, colors["text_main"])

    return img


def render_dashboard_old_computer(width, height, settings):
    """Render a functional mid-2000s desktop-monitor window.

    The layout intentionally uses the visual language of a classic gray
    system window: navy title bars, beveled borders, bitmap-like labels and
    black diagnostic plots with green traces. All values and traces come from
    the same live statistics used by the other themes.
    """
    if settings.get("orientation") == "vertical" and width > height:
        width, height = height, width

    portrait = height > width
    if portrait:
        scale = max(0.72, min(width / 320.0, height / 480.0))
    else:
        scale = max(0.55, min(width / 1024.0, height / 480.0))

    colors = get_theme_colors("old_computer")
    os_info = get_os_release()
    distro_name = os_info.get("NAME") or os_info.get("PRETTY_NAME") or "Linux"
    gray = colors["bg"]
    white = (255, 255, 255)
    light_gray = (224, 224, 224)
    mid_gray = (128, 128, 128)
    dark_gray = (64, 64, 64)
    navy = colors["text_label"]
    black = (0, 0, 0)
    graph_green = colors["good"]
    graph_grid = (0, 90, 0)

    img = Image.new("RGB", (width, height), gray)
    d = ImageDraw.Draw(img)
    font_dir = os.path.join(BASE_DIR, "fonts")

    def make_font(filename, size):
        try:
            return ImageFont.truetype(os.path.join(font_dir, filename), max(7, int(size)))
        except Exception:
            return ImageFont.load_default()

    if portrait:
        title_font = make_font("DejaVuSans-Bold.ttf", 18 * scale)
        percent_font = make_font("DejaVuSans-Bold.ttf", 24 * scale)
        model_font = make_font("DejaVuSans-Bold.ttf", 10 * scale)
        small_bold = make_font("DejaVuSans-Bold.ttf", 8.5 * scale)
        small_font = make_font("DejaVuSans.ttf", 8 * scale)
        header_font = make_font("DejaVuSans-Bold.ttf", 16 * scale)
        time_font = make_font("DejaVuSans-Bold.ttf", 21 * scale)
        titlebar_font = make_font("DejaVuSans-Bold.ttf", 10 * scale)
    else:
        title_font = make_font("DejaVuSans-Bold.ttf", 42 * scale)
        percent_font = make_font("DejaVuSans-Bold.ttf", 46 * scale)
        model_font = make_font("DejaVuSans-Bold.ttf", 19 * scale)
        small_bold = make_font("DejaVuSans-Bold.ttf", 15 * scale)
        small_font = make_font("DejaVuSans.ttf", 13 * scale)
        header_font = make_font("DejaVuSans-Bold.ttf", 27 * scale)
        time_font = make_font("DejaVuSans-Bold.ttf", 28 * scale)
        titlebar_font = make_font("DejaVuSans-Bold.ttf", 13 * scale)

    def text(x, y, value, font, fill=dark_gray):
        d.text((int(x), int(y)), str(value), font=font, fill=fill)

    def classic_frame(x, y, w, h, fill=gray):
        """Draw the raised gray bevel used by classic desktop windows."""
        x, y, w, h = int(x), int(y), int(w), int(h)
        d.rectangle((x, y, x + w, y + h), fill=fill, outline=dark_gray, width=1)
        if w > 3 and h > 3:
            d.line((x + 1, y + 1, x + w - 1, y + 1), fill=white, width=1)
            d.line((x + 1, y + 1, x + 1, y + h - 1), fill=white, width=1)
            d.line((x + w - 1, y + 2, x + w - 1, y + h - 1), fill=mid_gray, width=1)
            d.line((x + 2, y + h - 1, x + w - 1, y + h - 1), fill=mid_gray, width=1)

    def graph_frame(x, y, w, h, history, current, line_color=graph_green):
        """Draw a black monitor plot with live history and green grid lines."""
        classic_frame(x, y, w, h, black)
        left, top = x + 10, y + 8
        right, bottom = x + w - 10, y + h - 8
        if right <= left or bottom <= top:
            return
        for fraction in (0.25, 0.50, 0.75):
            gy = int(top + (bottom - top) * fraction)
            d.line((left, gy, right, gy), fill=graph_grid, width=1)

        values = [float(item) for item in list(history or [])[-30:]]
        if values:
            values.append(float(current or 0.0))
        else:
            values = [float(current or 0.0)]
        values = values[-31:]
        points = []
        for index, value in enumerate(values):
            normalized = max(0.0, min(100.0, value)) / 100.0
            px = left + (right - left) * index / max(1, len(values) - 1)
            py = bottom - normalized * (bottom - top)
            points.append((int(px), int(py)))
        if len(points) == 1:
            points = [(left, points[0][1]), (right, points[0][1])]
        d.line(points, fill=line_color, width=max(1, int(scale)))
        last_x, last_y = points[-1]
        marker = max(1, int(scale))
        d.rectangle((last_x - marker, last_y - marker, last_x + marker, last_y + marker),
                    fill=line_color)

    def draw_icon(kind, x, y, size):
        """Small pixel-style hardware icons matching the reference image."""
        size = max(12, int(size))
        x, y = int(x), int(y)
        shadow = (128, 128, 0)
        chip = (224, 224, 224)
        blue = (0, 0, 128)
        if kind == "cpu":
            for offset in range(4, size - 3, max(5, size // 5)):
                d.line((x + offset, y, x + offset, y - 5), fill=shadow, width=2)
                d.line((x + offset, y + size, x + offset, y + size + 5), fill=shadow, width=2)
                d.line((x, y + offset, x - 5, y + offset), fill=shadow, width=2)
                d.line((x + size, y + offset, x + size + 5, y + offset), fill=shadow, width=2)
            d.rectangle((x, y, x + size, y + size), fill=shadow, outline=black, width=1)
            d.rectangle((x + 4, y + 4, x + size - 4, y + size - 4), fill=chip, outline=dark_gray)
            d.rectangle((x + 9, y + 9, x + size - 9, y + size - 9), fill=blue, outline=black)
            d.rectangle((x + 12, y + 12, x + size - 12, y + size - 12), fill=(32, 32, 80))
        elif kind == "ram":
            d.rectangle((x, y + size // 4, x + size + 8, y + size * 3 // 4), fill=shadow, outline=black)
            d.rectangle((x + 4, y + size // 4 + 3, x + size + 4, y + size * 3 // 4 - 3), fill=chip)
            for index in range(3):
                bx = x + 8 + index * max(5, size // 4)
                d.rectangle((bx, y + size // 4 + 5, bx + max(3, size // 7),
                             y + size * 3 // 4 - 5), fill=blue)
            d.line((x + 5, y + size * 3 // 4 + 3, x + size + 3, y + size * 3 // 4 + 3),
                   fill=shadow, width=2)
        elif kind == "gpu":
            d.rectangle((x, y + 3, x + size + 8, y + size - 2), fill=chip, outline=black)
            cx, cy = x + (size + 8) // 2, y + size // 2
            d.ellipse((cx - size // 3, cy - size // 3, cx + size // 3, cy + size // 3), fill=black)
            d.ellipse((cx - size // 8, cy - size // 8, cx + size // 8, cy + size // 8), fill=white)
            d.line((x + 4, y + size, x + size + 5, y + size), fill=shadow, width=2)
        else:  # VRAM
            for index in range(3):
                yy = y + index * max(5, size // 4)
                d.rectangle((x + 5, yy + 3, x + size, yy + max(7, size // 4)), fill=blue, outline=black)
            d.rectangle((x + 2, y + size - 2, x + size + 2, y + size + 3), fill=shadow, outline=black)

    def series_stats(history, current):
        values = [float(item) for item in list(history or []) if item is not None]
        if current is not None:
            values.append(float(current))
        values = values or [0.0]
        return sum(values) / len(values), max(values)

    def safe_temperature(value):
        numeric = _planet_temperature(value)
        return f"{numeric:.0f}C" if numeric is not None else "--C"

    def format_uptime():
        try:
            elapsed = max(0, int(time.time() - psutil.boot_time()))
            days, remainder = divmod(elapsed, 86400)
            hours, minutes = divmod(remainder, 3600)
            minutes //= 60
            return f"{days}d {hours:02d}:{minutes:02d}" if days else f"{hours:02d}:{minutes:02d}"
        except Exception:
            return "--:--"

    gpu_list = SYSTEM_STATS.get("gpus", [])
    gpu_index = min(SYSTEM_STATS.get("active_gpu_idx", 0), max(0, len(gpu_list) - 1))
    gpu = gpu_list[gpu_index] if gpu_list else {}
    cpu_usage = float(SYSTEM_STATS.get("cpu_percent", 0.0) or 0.0)
    ram_usage = float(SYSTEM_STATS.get("ram_percent", 0.0) or 0.0)
    gpu_usage = float(gpu.get("percent", 0.0) or 0.0)
    gpu_mem = float(gpu.get("mem_used_mb", 0.0) or 0.0)
    gpu_mem_total = float(gpu.get("mem_total_mb", 0.0) or 0.0)
    gpu_mem_percent = (gpu_mem / gpu_mem_total * 100.0) if gpu_mem_total else 0.0
    cpu_freq = None
    try:
        cpu_freq = psutil.cpu_freq().current
    except Exception:
        pass
    cpu_freq_text = f"{cpu_freq:.0f}MHz" if cpu_freq else "--MHz"
    cpu_model = _planet_cpu_model()
    gpu_model = str(gpu.get("name", "GPU"))
    ram_total_gb = SYSTEM_STATS.get("ram_total_mb", 0) / 1024.0
    ram_used_gb = SYSTEM_STATS.get("ram_used_mb", 0) / 1024.0
    vram_total_gb = gpu_mem_total / 1024.0
    vram_used_gb = gpu_mem / 1024.0
    cpu_avg, cpu_peak = series_stats(CPU_USAGE_HISTORY, cpu_usage)
    ram_avg, ram_peak = series_stats(RAM_USAGE_HISTORY, ram_usage)
    gpu_avg, gpu_peak = series_stats(GPU_USAGE_HISTORY, gpu_usage)
    vram_avg, vram_peak = series_stats(GPU_MEM_HISTORY, gpu_mem_percent)

    # Window chrome and header.
    titlebar_h = max(18, int(height * (0.045 if portrait else 0.052)))
    d.rectangle((0, 0, width - 1, titlebar_h), fill=navy)
    titlebar_left = max(4, int(5 * scale))
    button_size = max(11, titlebar_h - 7)
    button_y = max(3, (titlebar_h - button_size) // 2)
    button_x = width - max(4, int(5 * scale)) - button_size
    first_button_x = button_x
    titlebar_name = fit_text_to_width(d, distro_name, max(24, first_button_x - titlebar_left - 6), titlebar_font)
    text(titlebar_left, max(2, int(3 * scale)), titlebar_name, titlebar_font, white)
    for symbol in ("X", "□", "—"):
        classic_frame(button_x, button_y, button_size, button_size, light_gray)
        symbol_w = get_text_width(d, symbol, titlebar_font)
        text(button_x + (button_size - symbol_w) // 2, button_y - 1, symbol, titlebar_font, black)
        button_x -= button_size + max(2, int(3 * scale))

    if portrait:
        content_pad = max(7, int(9 * scale))
        header_h = max(48, int(54 * scale))
        header_x = content_pad
        header_y = titlebar_h + max(5, int(5 * scale))
        header_title_y = header_y + 2
        header_subtitle_y = header_y + max(20, int(22 * scale))
        time_y = header_y + max(1, int(1 * scale))
        status_h = max(22, int(24 * scale))
    else:
        content_pad = max(12, int(width * 0.02))
        header_h = max(58, int(height * 0.17))
        header_x = max(content_pad * 3, int(width * 0.07))
        header_y = titlebar_h + max(10, int(height * 0.035))
        header_title_y = header_y
        header_subtitle_y = header_y + max(22, int(24 * scale))
        time_y = header_y + max(1, int(1 * scale))
        status_h = max(24, int(height * 0.06))

    now = datetime.now()
    time_value = now.strftime("%H:%M")
    time_w = get_text_width(d, time_value, time_font)
    header_name_width = max(20, width - header_x - content_pad - time_w - max(8, int(10 * scale)))
    text(header_x, header_title_y, fit_text_to_width(d, distro_name, header_name_width, header_font), header_font, navy)
    subtitle = (f"KERNEL {SYSTEM_STATS.get('kernel', '--')}  |  "
                f"HOST {SYSTEM_STATS.get('hostname', '--')}  |  UPTIME {format_uptime()}")
    text(header_x, header_subtitle_y,
         fit_text_to_width(d, subtitle, max(20, width - header_x - content_pad), small_bold),
         small_bold, dark_gray)
    text(width - content_pad - time_w, time_y, time_value, time_font, navy)
    if not portrait:
        date_value = now.strftime("%Y-%m-%d")
        date_w = get_text_width(d, date_value, small_font)
        text(width - content_pad - date_w, time_y + max(29, int(31 * scale)), date_value, small_font, dark_gray)

    separator_y = titlebar_h + header_h
    d.line((content_pad, separator_y, width - content_pad, separator_y), fill=navy, width=max(1, int(scale)))

    graph_data = [
        ("CPU", cpu_usage, cpu_model, CPU_USAGE_HISTORY, f"CLOCK {cpu_freq_text}  |  AVG {cpu_avg:.0f}%  PEAK {cpu_peak:.0f}%", "cpu"),
        ("RAM", ram_usage, f"{ram_total_gb:.1f}GB DDR  MEMORY", RAM_USAGE_HISTORY,
         f"{ram_used_gb:.1f}/{ram_total_gb:.1f}GB  |  AVG {ram_avg:.0f}%  PEAK {ram_peak:.0f}%", "ram"),
        ("GPU", gpu_usage, gpu_model, GPU_USAGE_HISTORY,
         f"CLOCK --MHz  |  TEMP {safe_temperature(gpu.get('temp'))}  |  AVG {gpu_avg:.0f}%  PEAK {gpu_peak:.0f}%", "gpu"),
        ("VRAM", gpu_mem_percent, gpu_model,
         GPU_MEM_HISTORY,
         f"{vram_used_gb:.1f}/{vram_total_gb:.1f}GB  |  AVG {vram_avg:.0f}%  PEAK {vram_peak:.0f}%", "vram"),
    ]

    def draw_card(x, y, w, h, label, percent, model, history, footer, icon_kind):
        classic_frame(x, y, w, h, gray)
        if portrait:
            icon_size = max(18, min(27, int(h * 0.27)))
            head_h = max(32, int(h * 0.39))
            footer_h = max(13, int(15 * scale))
        else:
            icon_size = max(25, min(43, int(h * 0.25)))
            head_h = max(56, int(h * 0.43))
            footer_h = max(17, int(18 * scale))
        icon_x = x + max(8, int(12 * scale))
        icon_y = y + max(7, int(13 * scale))
        draw_icon(icon_kind, icon_x, icon_y, icon_size)
        title_x = icon_x + icon_size + max(8, int(12 * scale))
        text(title_x, y + max(4, int(7 * scale)), label, title_font, navy)
        percent_text = f"{percent:.0f}%"
        percent_w = get_text_width(d, percent_text, percent_font)
        text(x + w - percent_w - max(9, int(12 * scale)), y + max(4, int(6 * scale)), percent_text, percent_font, navy)
        graph_y = y + head_h
        graph_h = max(18, h - head_h - footer_h - max(5, int(7 * scale)))
        model_text = fit_text_to_width(d, str(model).upper(), w - max(20, int(24 * scale)), model_font)
        model_box = d.textbbox((0, 0), model_text, font=model_font)
        model_h = max(7, model_box[3] - model_box[1])
        model_y = graph_y - model_h - max(2, int(4 * scale))
        text(title_x, model_y, model_text, model_font, dark_gray)
        graph_frame(x + max(8, int(12 * scale)), graph_y,
                    w - max(16, int(24 * scale)), graph_h, history, percent)
        footer_text = fit_text_to_width(d, footer, w - max(18, int(24 * scale)), small_bold)
        text(x + max(10, int(13 * scale)), y + h - footer_h + max(1, int(1 * scale)), footer_text, small_bold, dark_gray)

    status_y = height - status_h
    card_top = separator_y + max(5, int(6 * scale))
    card_bottom = status_y - max(5, int(6 * scale))
    if portrait:
        card_gap = max(3, int(4 * scale))
        card_w = width - content_pad * 2
        card_h = max(45, (card_bottom - card_top - card_gap * 3) // 4)
        for index, card in enumerate(graph_data):
            draw_card(content_pad, card_top + index * (card_h + card_gap), card_w, card_h, *card)
    else:
        card_gap = max(5, int(8 * scale))
        card_w = max(60, (width - content_pad * 2 - card_gap) // 2)
        card_h = max(70, (card_bottom - card_top - card_gap) // 2)
        for index, card in enumerate(graph_data):
            col, row = index % 2, index // 2
            draw_card(content_pad + col * (card_w + card_gap),
                      card_top + row * (card_h + card_gap), card_w, card_h, *card)

    try:
        process_count = len(psutil.pids())
    except Exception:
        process_count = len(SYSTEM_STATS.get("procs", []))
    sensor_ok = _planet_temperature(SYSTEM_STATS.get("cpu_temp")) is not None
    sensor_status = "OK" if sensor_ok else "CHECK"
    status = (f"GRAPH  |  POLL 1.0S  |  HISTORY 60S  |  SENSORS {sensor_status}  |  "
              f"PROCESSES {process_count}  |  O: OVERLAY")
    d.rectangle((content_pad, status_y, width - content_pad, height - 1), fill=gray)
    d.line((content_pad, status_y, width - content_pad, status_y), fill=white, width=1)
    d.line((content_pad, height - 1, width - content_pad, height - 1), fill=mid_gray, width=1)
    text(content_pad + max(4, int(8 * scale)), status_y + max(3, int(4 * scale)),
         fit_text_to_width(d, status, width - content_pad * 2 - max(8, int(16 * scale)), small_bold),
         small_bold, navy)
    return img


def render_dashboard(width, height, settings):
    if settings.get("theme") == "old_computer":
        return render_dashboard_old_computer(width, height, settings)
    if settings.get("theme") == "planet":
        return render_dashboard_planet(width, height, settings)
    if settings.get("theme") == "gkrellm":
        return render_dashboard_gkrellm(width, height, settings)
    if settings.get("orientation") == "vertical":
        return render_dashboard_portrait(width, height, settings)
    return render_dashboard_landscape(width, height, settings)

def render_dashboard_portrait(width, height, settings):
    theme_colors = get_theme_colors(settings.get("theme", "dark"))
    bg_color = theme_colors["bg"]
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    
    # === FONTS ===
    try:
        font_dir = os.path.join(BASE_DIR, "fonts")
        font_time = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.04)) 
        font_lg = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.032))  
        font_md = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.024))  
        font_sm = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.022))       
        font_icon = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.015))     
    except Exception:
        font_time = font_md = font_sm = ImageFont.load_default()

    os_info = get_os_release()
    pretty_name = os_info.get("PRETTY_NAME", "Linux")
    logo_name = os_info.get("LOGO", "")
    
    # === 1. HEADER PORTRAIT ===
    header_h = int(height * 0.12)
    d.rounded_rectangle((10, 10, width-10, header_h), radius=10, fill=theme_colors["panel_bg"])
    
    # Logo
    logo_offset = 20
    logo = load_distro_logo(logo_name, header_h - 30)
    if logo:
        img.paste(logo, (20, 15), mask=logo)
        logo_offset = logo.width + 30

    # Simple clock in header
    now = datetime.now().strftime("%H:%M")
    time_w = get_text_width(d, now, font_time)
    d.text((width - time_w - 20, 20), now, fill=theme_colors["time"], font=font_time)
    
    # OS Name (font reduced) + Host + Kernel (Split lines)
    d.text((logo_offset, 18), pretty_name[:20], fill=theme_colors["text_main"], font=font_md)
    d.text((logo_offset, 36), f"{SYSTEM_STATS['hostname']}", fill=theme_colors["text_muted"], font=font_sm)
    d.text((logo_offset, 50), f"{SYSTEM_STATS['kernel']}", fill=theme_colors["text_muted"], font=font_sm)

    # Rede RX / TX below clock
    net_rx_icon = get_svg_icon("rx-symbolic.svg", int(height*0.022), theme_colors["icon_color"])
    net_tx_icon = get_svg_icon("tx-symbolic.svg", int(height*0.022), theme_colors["icon_color"])
    net_rx_t = f"{SYSTEM_STATS['net_rx_mbps']:.1f}"
    net_tx_t = f"{SYSTEM_STATS['net_tx_mbps']:.1f}"
    
    rx_w = get_text_width(d, net_rx_t, font_sm)
    tx_w = get_text_width(d, net_tx_t, font_sm)
    icon_sz = int(height*0.022)
    
    # Position TX first (rightmost)
    tx_x = width - tx_w - 20
    d.text((tx_x, 43), net_tx_t, fill=theme_colors["good"], font=font_sm)
    if net_tx_icon:
        img.paste(net_tx_icon, (tx_x - icon_sz - 4, 45), net_tx_icon)
        
    # Position RX to the left of TX
    rx_x = tx_x - icon_sz - 15 - rx_w
    d.text((rx_x, 43), net_rx_t, fill=theme_colors["good"], font=font_sm)
    if net_rx_icon:
        img.paste(net_rx_icon, (rx_x - icon_sz - 4, 45), net_rx_icon)

    # === PROGRESS BAR HELPER ===
    def draw_bar(x, y, w, h, percent, label, text_val, color, icon_name=""):
        icon_offset = 0
        if icon_name:
            icon_img = get_svg_icon(icon_name, int(height*0.025), theme_colors["icon_color"])
            if icon_img:
                img.paste(icon_img, (x, y-2), icon_img)
                icon_offset = icon_img.width + 8

        val_w = get_text_width(d, text_val, font=font_md)
        value_x = x + w - val_w
        label_width = max(10, value_x - (x + icon_offset) - 8)
        label = fit_text_to_width(d, label, label_width, font_md)
        d.text((x + icon_offset, y), label, fill=theme_colors["text_label"], font=font_md)
        d.text((value_x, y), text_val, fill=theme_colors["text_main"], font=font_md)
        try:
            text_bottom = max(d.textbbox((0, 0), label, font=font_md)[3],
                              d.textbbox((0, 0), text_val, font=font_md)[3])
        except AttributeError:
            text_bottom = 14
        by = y + max(int(height * 0.035), text_bottom + 5)
        d.rounded_rectangle((x, by, x + w, by + h), radius=h//2, fill=theme_colors["bar_bg"])
        fill_w = int(w * (percent / 100))
        if fill_w > 0:
            fill_w = max(fill_w, h)
            d.rounded_rectangle((x, by, x + fill_w, by + h), radius=h//2, fill=color)

    # === VERTICAL STACK ===
    curr_y = header_h + 20
    row_w = width - 40
    row_h = int(height * 0.015)
    spacing = int(height * 0.08)

    # CPU section (Manual draw to match landscape style with colored temp)
    cpu_w = int(row_w * 0.55)
    cpu_temp = SYSTEM_STATS['cpu_temp']
    current_temp = CPU_TEMP_HISTORY[-1] if CPU_TEMP_HISTORY else 40
    temp_color = theme_colors["crit"] if current_temp > 85 else (theme_colors["warn"] if current_temp >= 50 else theme_colors["good"])
    
    # Icon
    icon_img = get_svg_icon("cpu-symbolic.svg", int(height*0.025), theme_colors["icon_color"])
    icon_w = 0
    if icon_img:
        img.paste(icon_img, (20, curr_y-2), icon_img)
        icon_w = icon_img.width + 8

    # Label "CPU " + "Temp"
    d.text((20 + icon_w, curr_y), "CPU ", fill=theme_colors["text_label"], font=font_md)
    off_cpu = get_text_width(d, "CPU ", font_md)
    d.text((20 + icon_w + off_cpu, curr_y), f"{cpu_temp}", fill=temp_color, font=font_md)

    # Value %
    val_txt = f"{SYSTEM_STATS['cpu_percent']:.0f}%"
    val_w = get_text_width(d, val_txt, font_md)
    d.text((20 + cpu_w - val_w, curr_y), val_txt, fill=theme_colors["text_main"], font=font_md)

    # Bar
    by = curr_y + int(height * 0.035)
    d.rounded_rectangle((20, by, 20 + cpu_w, by + row_h), radius=row_h//2, fill=theme_colors["bar_bg"])
    fill_w = int(cpu_w * (SYSTEM_STATS["cpu_percent"] / 100))
    if fill_w > 0:
        fill_w = max(fill_w, row_h)
        d.rounded_rectangle((20, by, 20 + fill_w, by + row_h), radius=row_h//2, fill=theme_colors["warn"])
             
    # Graph on the right of CPU
    gx = 20 + cpu_w + 10
    gw = width - gx - 20
    gh = int(height * 0.05)
    d.rectangle((gx, curr_y, gx + gw, curr_y + gh), fill=theme_colors["panel_bg"], outline=theme_colors["border"])
    if len(CPU_USAGE_HISTORY) > 1:
        max_t = max(80, max(CPU_TEMP_HISTORY))
        min_t = 30
        step = gw / (len(CPU_USAGE_HISTORY) - 1)
        pts_cpu = []
        pts_ram = []
        pts_temp = []
        for i in range(len(CPU_USAGE_HISTORY)):
            px = gx + i*step
            pts_cpu.append((px, curr_y + gh - (CPU_USAGE_HISTORY[i]/100*gh)))
            pts_ram.append((px, curr_y + gh - (RAM_USAGE_HISTORY[i]/100*gh)))
            tv = max(min_t, min(CPU_TEMP_HISTORY[i], max_t))
            pts_temp.append((px, curr_y + gh - (((tv - min_t) / max(1, max_t - min_t)) * gh)))
        d.line(pts_temp, fill=theme_colors["temp_line"], width=2)
        d.line(pts_cpu, fill=theme_colors["warn"], width=2)
        d.line(pts_ram, fill=theme_colors["good"], width=2)

    curr_y += spacing
    
    # RAM
    draw_bar(20, curr_y, row_w, row_h, SYSTEM_STATS["ram_percent"], 
             "RAM", f"{SYSTEM_STATS['ram_used_mb']}MB", theme_colors["good"], "ram-symbolic.svg")
    curr_y += spacing
    
    # SWAP
    draw_bar(20, curr_y, row_w, row_h, SYSTEM_STATS["swap_percent"], 
             "SWAP", f"{SYSTEM_STATS['swap_used_mb']}MB", theme_colors["swap"], "swap-symbolic.svg")
    curr_y += spacing
    
    # DISK
    draw_bar(20, curr_y, row_w, row_h, SYSTEM_STATS["disk_percent"], 
             "DISK", f"{SYSTEM_STATS['disk_percent']:.0f}%", theme_colors["disk"], "disk-symbolic.svg")
    curr_y += spacing
    
    # GPU Box
    gpu_box_h = int(height * 0.16)
    d.rounded_rectangle((10, curr_y, width-10, curr_y + gpu_box_h), radius=10, fill=theme_colors["panel_bg"])
    
    active_gpu = SYSTEM_STATS["gpus"][SYSTEM_STATS["active_gpu_idx"]] if SYSTEM_STATS["gpus"] else {}
    gpu_badge = f" [GPU {SYSTEM_STATS['active_gpu_idx']+1}/{len(SYSTEM_STATS['gpus'])}]" if len(SYSTEM_STATS['gpus']) > 1 else ""
    gpu_title = f"{active_gpu.get('name', 'GPU')[:17]}{gpu_badge}"
    
    # GPU Icon + Title (Landscape style)
    gpu_icon = get_svg_icon("gpu-symbolic.svg", int(height*0.025), theme_colors["icon_color"])
    icon_off = 20
    if gpu_icon:
        img.paste(gpu_icon, (20, curr_y + 8), gpu_icon)
        icon_off = 20 + gpu_icon.width + 8
        
    # Dynamic Temp Color
    gpu_t = active_gpu.get("temp", "?°C")
    try:
        gpu_t_val = int(gpu_t.replace("°C", ""))
    except Exception:
        gpu_t_val = 40
    
    gpu_c = theme_colors["crit"] if gpu_t_val > 85 else (theme_colors["warn"] if gpu_t_val >= 50 else theme_colors["good"])
    
    t_w = get_text_width(d, gpu_t, font_md)
    gpu_title_width = max(20, (width - 25) - icon_off - t_w - 8)
    gpu_title = fit_text_to_width(d, gpu_title, gpu_title_width, font_md)
    d.text((icon_off, curr_y + 8), gpu_title, fill=theme_colors["text_label"], font=font_md)
    d.text((width - t_w - 20, curr_y + 8), gpu_t, fill=gpu_c, font=font_md)
    
    # GPU Load Bar inside GPU Box
    draw_bar(20, curr_y + int(height * 0.045), row_w, row_h, active_gpu.get("percent", 0), 
             "CORE", f"{active_gpu.get('percent', 0):.0f}%", theme_colors["crit"])
    
    current_gpu_mem_p = (active_gpu.get("mem_used_mb", 0) / max(1, active_gpu.get("mem_total_mb", 1))) * 100
    draw_bar(20, curr_y + int(height * 0.1), row_w, row_h, current_gpu_mem_p, 
             "VRAM", f"{active_gpu.get('mem_used_mb', 0)}MB", theme_colors["vram"])
             
    curr_y += gpu_box_h + 15
    
    # TOP PROCESSES (Same style as landscape)
    proc_icon = get_svg_icon("process-symbolic.svg", int(height*0.03), theme_colors["icon_color"])
    if proc_icon:
        img.paste(proc_icon, (20, curr_y-2), proc_icon)
        d.text((20 + proc_icon.width + 8, curr_y), "TOP 10 PROCESSOS | CPU | MEM", fill=theme_colors["text_muted"], font=font_md)
    else:
        d.text((20, curr_y), "TOP 10 PROCESSOS | CPU | MEM", fill=theme_colors["text_muted"], font=font_md)
        
    d.line((20, curr_y + 25, width - 20, curr_y + 25), fill=theme_colors["border"], width=1)
    curr_y += 35
    
    proc_step = int(height * 0.03)
    for i, p in enumerate(SYSTEM_STATS["procs"][:10]):
        py = curr_y + (i * proc_step)
        if py + proc_step > height - 5: break
        
        # Color logic from landscape
        color = theme_colors["crit"] if i < 2 else (theme_colors["warn"] if i < 5 else (theme_colors["text_label"] if i < 8 else theme_colors["good"]))
        
        d.text((20, py), f"{i+1}. {p['name'][:10]}", fill=color, font=font_sm)
        # Align CPU and MEM to the right
        cpu_txt = f"{p['cpu_percent']:.1f}%"
        cpu_w = get_text_width(d, cpu_txt, font_sm)
        d.text((width - 95 - cpu_w, py), cpu_txt, fill=color, font=font_sm)
        
        mem_txt = f"{p.get('memory_percent') or 0:.0f}%"
        mem_w = get_text_width(d, mem_txt, font_sm)
        d.text((width - 25 - mem_w, py), mem_txt, fill=theme_colors["text_muted"] if i >= 2 else color, font=font_sm)

    return img

def render_dashboard_landscape(width, height, settings):
    theme_colors = get_theme_colors(settings.get("theme", "dark"))
    bg_color = theme_colors["bg"]
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    
    # === FONTS ===
    try:
        font_dir = os.path.join(BASE_DIR, "fonts")
        font_time = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.07)) 
        font_lg = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.050))  
        font_md = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.038))  
        font_sm = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.035))       
        font_proc = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.028))
        font_icon = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.022))     
    except Exception:
        font_time = font_md = font_sm = font_proc = ImageFont.load_default()

    os_info = get_os_release()
    pretty_name = os_info.get("PRETTY_NAME", "Linux OS")
    logo_name = os_info.get("LOGO", "")
    
    # === 1. HEADER BANNER ===
    header_h = int(height * 0.18)
    try:
        d.rounded_rectangle((10, 10, width-10, header_h), radius=10, fill=theme_colors["panel_bg"])
    except AttributeError:
        d.rectangle((10, 10, width-10, header_h), fill=theme_colors["panel_bg"])
    
    # Logo
    logo = load_distro_logo(logo_name, header_h - 20)
    logo_right = 20
    if logo:
        img.paste(logo, (20, 15), mask=logo)
        logo_right = 20 + logo.width + 8

    # Info OS + Hostname + Kernel (posicionar logo do logo)
    d.text((logo_right, 14), f"{pretty_name}", fill=theme_colors["text_main"], font=font_lg)
    _subtitle = f"{SYSTEM_STATS['hostname']} | {SYSTEM_STATS['kernel']}"
    if len(_subtitle) > 44:
        _subtitle = _subtitle[:44]
    d.text((logo_right, 36), _subtitle, fill=theme_colors["text_muted"], font=font_sm)

    # Relógio MENOR
    now = datetime.now().strftime("%H:%M")
    time_w = get_text_width(d, now, font_time)
    d.text((width - time_w - 20, 15), now, fill=theme_colors["time"], font=font_time)
    
    # Rede RX / TX
    net_rx_icon = get_svg_icon("rx-symbolic.svg", int(height*0.04), theme_colors["icon_color"])
    net_tx_icon = get_svg_icon("tx-symbolic.svg", int(height*0.04), theme_colors["icon_color"])
    
    net_str = f"  {SYSTEM_STATS['net_rx_mbps']:.1f} Mbps      {SYSTEM_STATS['net_tx_mbps']:.1f} Mbps"
    net_w = get_text_width(d, net_str, font_sm)
    d.text((width - net_w - 20, 36), net_str, fill=theme_colors["good"], font=font_sm)
    
    if net_rx_icon:
        img.paste(net_rx_icon, (int(width - net_w - 30), 36), net_rx_icon)
    if net_tx_icon:
        middle_offset = get_text_width(d, f"  {SYSTEM_STATS['net_rx_mbps']:.1f} Mbps    ", font_sm)
        img.paste(net_tx_icon, (int(width - net_w - 30 + middle_offset), 36), net_tx_icon)

    # === FUNCAO PROGRESS BAR ===
    def draw_bar(x, y, w, h, percent, label, text_val, color, icon_name=""):
        icon_offset = 0
        if icon_name:
            icon_img = get_svg_icon(icon_name, int(height*0.045), theme_colors["icon_color"])
            if icon_img:
                img.paste(icon_img, (x, y-2), icon_img)
                icon_offset = icon_img.width + 10

        val_w = get_text_width(d, text_val, font=font_md)
        value_x = x + w - val_w
        label_width = max(10, value_x - (x + icon_offset) - 8)
        label = fit_text_to_width(d, label, label_width, font_md)
        d.text((x + icon_offset, y), label, fill=theme_colors["text_label"], font=font_md)
        d.text((value_x, y), text_val, fill=theme_colors["text_main"], font=font_md)

        # Reserve the real font height before drawing the graph/bar. This
        # avoids the label appearing on top of the metric visualization.
        try:
            text_bottom = max(d.textbbox((0, 0), label, font=font_md)[3],
                              d.textbbox((0, 0), text_val, font=font_md)[3])
        except AttributeError:
            text_bottom = 14
        by = y + max(20, text_bottom + 5, int(height * 0.055))
        try:
            d.rounded_rectangle((x, by, x + w, by + h), radius=h//2, fill=theme_colors["bar_bg"])
            fill_w = int(w * (percent / 100))
            if fill_w > 0:
                fill_w = max(fill_w, h)  # minimum width = bar height for rounded shape
                d.rounded_rectangle((x, by, x + fill_w, by + h), radius=h//2, fill=color)
        except AttributeError:
            d.rectangle((x, by, x + w, by + h), fill=theme_colors["bar_bg"])
            fill_w = int(w * (percent / 100))
            if fill_w > 0:
                fill_w = max(fill_w, h)
                d.rectangle((x, by, x + fill_w, by + h), fill=color)

    # === 2. LEFT COLUMN (HARDWARE) ===
    col1_x, col1_w = 20, int(width * 0.45)
    bar_y = header_h + 15
    col1_spacing = int(height * 0.12)

    #  ----- CPU (Split: Barra esq | Gráfico Temp dir) -----
    cpu_label = f"CPU ({SYSTEM_STATS['cpu_temp']})"
    icon_img = get_svg_icon("cpu-symbolic.svg", int(height*0.05), theme_colors["icon_color"])
    icon_w = 0
    if icon_img:
        img.paste(icon_img, (col1_x, bar_y-2), icon_img)
        icon_w = icon_img.width + 8
    
    current_temp = CPU_TEMP_HISTORY[-1] if CPU_TEMP_HISTORY else 40
    if current_temp > 85:
        temp_color = theme_colors["crit"] # Vermelho (Sobrecarga)
    elif current_temp >= 50:
        temp_color = theme_colors["warn"] # Amarelo (Carga)
    else:
        temp_color = theme_colors["good"] # Verde (Normal 30-50°C)

    d.text((col1_x + icon_w, bar_y), "CPU ", fill=theme_colors["text_label"], font=font_md)
    offset_cpu = get_text_width(d, "CPU ", font=font_md)
    d.text((col1_x + icon_w + offset_cpu, bar_y), f"{SYSTEM_STATS['cpu_temp']}", fill=temp_color, font=font_md)
    offset_cpu += get_text_width(d, f"{SYSTEM_STATS['cpu_temp']}", font=font_md)
    d.text((col1_x + icon_w + offset_cpu, bar_y), " ", fill=theme_colors["text_label"], font=font_md)
    
    val_w = get_text_width(d, f"{SYSTEM_STATS['cpu_percent']:.1f}%", font=font_md)
    # Metade da tela na barra:
    half_w = int(col1_w * 0.6)
    d.text((col1_x + half_w - val_w, bar_y), f"{SYSTEM_STATS['cpu_percent']:.1f}%", fill=theme_colors["text_main"], font=font_md)
    
    h_bar = int(height * 0.025)
    # Keep the combined graph below the CPU label line as well.
    try:
        cpu_text_bottom = max(d.textbbox((0, 0), "CPU ", font=font_md)[3],
                              d.textbbox((0, 0), f"{SYSTEM_STATS['cpu_temp']}", font=font_md)[3],
                              d.textbbox((0, 0), f"{SYSTEM_STATS['cpu_percent']:.1f}%", font=font_md)[3])
    except AttributeError:
        cpu_text_bottom = 14
    by = bar_y + max(20, cpu_text_bottom + 5, int(height * 0.055))
    try:
        d.rounded_rectangle((col1_x, by, col1_x + half_w, by + h_bar), radius=h_bar//2, fill=theme_colors["bar_bg"])
        fcpu = int(half_w * (SYSTEM_STATS["cpu_percent"] / 100))
        if fcpu > 0:
            fcpu = max(fcpu, h_bar)  # minimum width = bar height for rounded shape
            d.rounded_rectangle((col1_x, by, col1_x + fcpu, by + h_bar), radius=h_bar//2, fill=theme_colors["warn"])
    except AttributeError:
        pass
        
    # Gráfico Temperatura, CPU e MEM na direita
    gx = col1_x + half_w + 15
    # Limites
    max_t = max(80, max(CPU_TEMP_HISTORY))
    min_t = 30
    gw = (col1_x + col1_w) - gx
    gh = (by + h_bar + 5) - bar_y
    step = gw / max(1, len(CPU_TEMP_HISTORY) - 1)
    
    # Bg do Grafico
    d.rectangle((gx, bar_y, gx + gw, bar_y + gh), fill=theme_colors["panel_bg"], outline=theme_colors["border"])
    
    pts_temp = []
    pts_cpu = []
    pts_ram = []
    for i in range(len(CPU_TEMP_HISTORY)):
        px = gx + (i * step)
        
        # Temp (Laranja)
        tv = max(min_t, min(CPU_TEMP_HISTORY[i], max_t))
        py_temp = bar_y + gh - (((tv - min_t) / max(1, max_t - min_t)) * gh)
        pts_temp.append((px, py_temp))
        
        # CPU (Amarelo)
        vcpu = max(0, min(CPU_USAGE_HISTORY[i], 100))
        py_cpu = bar_y + gh - ((vcpu / 100) * gh)
        pts_cpu.append((px, py_cpu))
        
        # RAM (Verde)
        vram = max(0, min(RAM_USAGE_HISTORY[i], 100))
        py_ram = bar_y + gh - ((vram / 100) * gh)
        pts_ram.append((px, py_ram))

    if len(pts_temp) > 1:
        d.line(pts_temp, fill=theme_colors["temp_line"], width=2)
        d.line(pts_cpu, fill=theme_colors["warn"], width=2)
        d.line(pts_ram, fill=theme_colors["good"], width=2)
        
    # ------ RAM ------
    bar_y += col1_spacing
    draw_bar(col1_x, bar_y, col1_w, h_bar, SYSTEM_STATS["ram_percent"], 
             "RAM", f"{SYSTEM_STATS['ram_used_mb']} / {SYSTEM_STATS['ram_total_mb']} MB", theme_colors["good"], icon_name="ram-symbolic.svg") 
             
    # ------ SWAP ------
    bar_y += col1_spacing
    draw_bar(col1_x, bar_y, col1_w, h_bar, SYSTEM_STATS["swap_percent"], 
             "SWAP", f"{SYSTEM_STATS['swap_used_mb']} / {SYSTEM_STATS['swap_total_mb']} MB", theme_colors["swap"], icon_name="swap-symbolic.svg") 
             
    # ------ DISK ------
    bar_y += col1_spacing
    draw_bar(col1_x, bar_y, col1_w, h_bar, SYSTEM_STATS["disk_percent"], 
             "DISK /", SYSTEM_STATS["disk_text"], theme_colors["disk"], icon_name="disk-symbolic.svg")

    # === NVTOP GPU SECTION === #
    bar_y += col1_spacing + 5
    box_h = height - bar_y - 10
    
    # Caixa background GPU
    try:
        d.rounded_rectangle((10, bar_y-5, col1_x + col1_w + 10, height - 10), radius=10, fill=theme_colors["panel_bg"])
    except AttributeError:
        d.rectangle((10, bar_y-5, col1_x + col1_w + 10, height - 10), fill=theme_colors["panel_bg"])
        
    active_gpu = SYSTEM_STATS["gpus"][SYSTEM_STATS["active_gpu_idx"]] if SYSTEM_STATS["gpus"] else {}
    gpu_badge = f" [GPU {SYSTEM_STATS['active_gpu_idx']+1}/{len(SYSTEM_STATS['gpus'])}]" if len(SYSTEM_STATS['gpus']) > 1 else ""
    gpu_title = f"{active_gpu.get('name', 'N/A')[:15]}{gpu_badge}"
    
    # Titulo e Temp GPU 
    gpu_icon = get_svg_icon("gpu-symbolic.svg", int(height*0.05), theme_colors["icon_color"])
    icon_gpu_w = 0
    if gpu_icon:
        img.paste(gpu_icon, (col1_x, bar_y+2), gpu_icon)
        icon_gpu_w = gpu_icon.width + 5
    
    gpu_t = active_gpu.get("temp", "?°C")
    try:
        gpu_t_val = int(gpu_t.replace("°C", ""))
    except Exception:
        gpu_t_val = 40
        
    if gpu_t_val > 85:
        gpu_c = theme_colors["crit"]
    elif gpu_t_val >= 50:
        gpu_c = theme_colors["warn"]
    else:
        gpu_c = theme_colors["good"]
        
    gpu_t_w = get_text_width(d, f"{gpu_t}", font=font_md)
    gpu_title_width = max(20, (col1_x + col1_w - 5) - (col1_x + icon_gpu_w) - gpu_t_w - 8)
    gpu_title = fit_text_to_width(d, gpu_title, gpu_title_width, font_md)
    d.text((col1_x + icon_gpu_w, bar_y+3), gpu_title, fill=theme_colors["text_label"], font=font_md)
    d.text((col1_x + col1_w - gpu_t_w, bar_y+3), f"{gpu_t}", fill=gpu_c, font=font_md)
    
    # Barras lado a lado ou em sequencia (espaco vertical)
    gpu_spacing = max(18, int(height * 0.065))
    bar_y += gpu_spacing
    h_gpu = int(height * 0.02)
    # Processamento Core GPU
    draw_bar(col1_x, bar_y-7, col1_w, h_gpu, active_gpu.get("percent", 0), 
             "CORE", f"{active_gpu.get('percent', 0):.1f}%", theme_colors["crit"]) 
    
    bar_y += gpu_spacing
    # VRAM
    gpu_mem_p = (active_gpu.get("mem_used_mb", 0) / max(1, active_gpu.get("mem_total_mb", 1))) * 100
    draw_bar(col1_x, bar_y-4, col1_w, h_gpu, gpu_mem_p, 
             "VRAM", f"{active_gpu.get('mem_used_mb', 0)}/{active_gpu.get('mem_total_mb', 0)} MB", theme_colors["vram"]) 
             
    bar_y += gpu_spacing
    # Encode / Decode
    enc = active_gpu.get("enc_percent", 0.0)
    enc_icon = get_svg_icon("encdec-symbolic.svg", int(height*0.04), theme_colors["icon_color"])
    if enc_icon:
        img.paste(enc_icon, (col1_x, bar_y+2), enc_icon)
        d.text((col1_x + enc_icon.width + 5, bar_y+2), f"ENC / DEC: {enc:.1f}%", fill=theme_colors["text_muted"], font=font_sm)
    else:
        d.text((col1_x, bar_y-5), f"ENC / DEC: {enc:.1f}%", fill=theme_colors["text_muted"], font=font_sm)


# === 3. RIGHT COLUMN (PROCESSES TOP 10) ===
    col2_x = int(width * 0.5) + 5
    col2_w = width - col2_x - 10
    
    try:
        d.rounded_rectangle((col2_x, header_h + 10, width - 10, height - 10), radius=15, fill=theme_colors["panel_bg"])
    except AttributeError:
        d.rectangle((col2_x, header_h + 10, width - 10, height - 10), fill=theme_colors["panel_bg"])
        
    proc_icon = get_svg_icon("process-symbolic.svg", int(height*0.045), theme_colors["icon_color"])
    if proc_icon:
        img.paste(proc_icon, (col2_x + 15, header_h + 18), proc_icon)
        d.text((col2_x + 15 + proc_icon.width + 8, header_h + 20), "TOP 10 PROCESSOS | CPU | MEM", fill=theme_colors["text_muted"], font=font_sm)
    else:
        d.text((col2_x + 15, header_h + 20), "TOP 10 PROCESSOS | CPU | MEM", fill=theme_colors["text_muted"], font=font_sm)
    d.line((col2_x + 15, header_h + 50, width - 25, header_h + 50), fill=theme_colors["border"], width=2)
    
    py = header_h + 60
    # Processos: vamos mostrar exatamente 10 
    proc_limit = 10
    available_h = height - py - 20
    step_y = available_h // max(1, proc_limit)
    
    for i, p in enumerate(SYSTEM_STATS["procs"][:proc_limit]):
        # trinca string conforme espaço
        p_name = p['name'][:12] if width > 500 else p['name'][:8]
        p_cpu = f"{p['cpu_percent']:.1f}%"
        p_mem = f"{p.get('memory_percent') or 0:.1f}%"
        
        # Coloracao Top
        color = theme_colors["crit"] if i < 2 else (theme_colors["warn"] if i < 5 else (theme_colors["text_label"] if i < 8 else theme_colors["good"]))
        
        # Numeração
        d.text((col2_x + 15, py), f"{i+1}.", fill=theme_colors["text_muted"], font=font_proc)
        # Nome
        d.text((col2_x + 40, py), p_name, fill=color, font=font_proc)
        
        # CPU alinhado à direita (penúltima coluna)
        cpu_w = get_text_width(d, p_cpu, font=font_proc)
        d.text((width - 85 - cpu_w, py), f"{p_cpu}", fill=color, font=font_proc)
        
        # MEM alinhado à direita (última coluna)
        mem_w = get_text_width(d, p_mem, font=font_proc)
        d.text((width - 25 - mem_w, py), f"{p_mem}", fill=color, font=font_proc)
        
        py += step_y

    return img


def animate_intro(lcd, settings):
    """Show a quick intro logo splash, optimised for slow serial displays."""
    is_vertical = settings.get("orientation") == "vertical"
    if is_vertical:
        width, height = lcd.height, lcd.width
    else:
        width, height = lcd.width, lcd.height
    theme_colors = get_theme_colors(settings.get("theme", "dark"))
    bg_color = theme_colors["bg"]

    possible_paths = [
        os.path.abspath(os.path.join(BASE_DIR, "..", "icons", "hicolor", "scalable", "apps", "big-screen-monitor-display.svg")),
        "/usr/share/icons/hicolor/scalable/apps/big-screen-monitor-display.svg"
    ]

    logo_path = None
    for p in possible_paths:
        if os.path.exists(p):
            logo_path = p
            break

    if not logo_path:
        return

    max_h = int(height * 0.3) if is_vertical else int(height * 0.5)
    try:
        p = subprocess.run(["rsvg-convert", "-h", str(max_h), logo_path],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        if p.returncode != 0:
            return
        base_logo = Image.open(io.BytesIO(p.stdout)).convert("RGBA")
    except Exception:
        return

    # Single splash frame: logo centred on background
    img = Image.new('RGB', (width, height), color=bg_color)
    lw, lh = base_logo.size
    x = (width - lw) // 2
    y = (height - lh) // 2
    img.paste(base_logo, (x, y), base_logo)

    # Use the efficient draw() path (numpy RGB565, tile-based)
    lcd.draw(img, settings)

    # Hold for a moment, then clear with background
    time.sleep(0.5)
    bg_img = Image.new('RGB', (width, height), color=bg_color)
    lcd.draw(bg_img, settings)

def run_tray_icon():
    if pystray is None or os.getuid() == 0 or not os.environ.get("DISPLAY"):
        return

    try:
        def open_config(icon, item):
            subprocess.Popen(["python3", os.path.join(BASE_DIR, "config_gui.py")])

        def exit_app(icon, item):
            icon.stop()
            os._exit(0)

        # Busca o ícone
        possible_paths = [
            "/usr/share/icons/hicolor/scalable/apps/big-screen-monitor-display.svg",
            os.path.abspath(os.path.join(BASE_DIR, "..", "icons", "hicolor", "scalable", "apps", "big-screen-monitor-display.svg")),
            os.path.join(BASE_DIR, "img", "gpu-symbolic.svg") # Extremo fallback
        ]
        
        icon_path = next((p for p in possible_paths if os.path.exists(p)), None)
        
        if icon_path:
            p = subprocess.run(["rsvg-convert", "-w", "64", "-h", "64", icon_path], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p.returncode == 0:
                icon_img = Image.open(io.BytesIO(p.stdout))
            else:
                icon_img = Image.new('RGB', (64, 64), color=(0, 120, 215))
        else:
            icon_img = Image.new('RGB', (64, 64), color=(0, 120, 215))

        menu = pystray.Menu(item('Configurações', open_config), item('Sair', exit_app))
        icon = pystray.Icon("BigScreenMonitor", icon_img, "Big Screen Monitor", menu)
        icon.run_detached()
    except Exception:
        pass


def main():
    print("\n" + "="*50)
    print("🚀 Big Screen Monitor Display - Iniciando...")
    print("="*50)
    
    print("🔄 Carregando configurações...")
    settings = get_settings()
    
    print("\n📝 Resumo das Configurações Aplicadas:")
    print(f"   • Modelo do Display: {settings.get('model', 'auto')}")
    print(f"   • Tamanho: {settings.get('size', '3.5')}\"")
    print(f"   • Orientação: {settings.get('orientation', 'horizontal')}")
    print(f"   • Nível de Brilho: {settings.get('brightness', 70)}%")
    print(f"   • Tema de Interface: {settings.get('theme', 'dark')}")
    print(f"   • Conexão de Rede: {settings.get('network_iface', 'auto')}")
    
    print("\n⚡ Conectando ao hardware do Display...")
    try:
        lcd = detect_display(settings)
        driver_name = type(lcd).__name__
        print(f"✅ Sucesso: Display detectado via {driver_name} ({lcd.width}x{lcd.height})")
    except Exception as e:
        print(f"❌ Falha crítica: Não foi possível acessar o display USB.")
        print(f"   Dica: Verifique se o cabo está conectado ou se tem permissões udev.")
        sys.exit(1)
    
    print("🌟 Preparando animação de entrada e ícone de sistema...")
    lcd.set_backlight(settings.get("brightness", 70))
    
    animate_intro(lcd, settings)
    run_tray_icon()
    
    print("\n" + "="*50)
    print("✅ MONITORAMENTO ATIVO COM SUCESSO!")
    print("   O painel está renderizando agora no display secundário.")
    print("   Pressione [Ctrl+C] para encerrar este processo.")
    print("="*50 + "\n")
    
    try:
        last_check = 0
        while True:
            # Check for settings update every 5 seconds without blocking
            now = time.time()
            if now - last_check > 5:
                # reload settings dynamically
                new_settings = get_settings()
                if new_settings.get("brightness") != settings.get("brightness"):
                    lcd.set_backlight(new_settings.get("brightness", 7))
                
                # Dispara a intro se a orientação mudar dinamicamente
                if new_settings.get("orientation") != settings.get("orientation"):
                    animate_intro(lcd, new_settings)
                    lcd._prev_frame = None  # Force full redraw after orientation change
                    
                settings = new_settings
                last_check = now
            
            # Use swapped dimensions if vertical
            if settings.get("orientation") == "vertical":
                render_w, render_height = lcd.height, lcd.width
            else:
                render_w, render_height = lcd.width, lcd.height
                
            img = render_dashboard(render_w, render_height, settings)
            updated = lcd.draw(img, settings)
            # Adaptive sleep: short if data was sent (serial is the bottleneck),
            # longer if nothing changed (avoid busy-looping render+compare)
            if updated:
                time.sleep(0.01)
            else:
                time.sleep(0.25)
    except KeyboardInterrupt:
        lcd.set_backlight(0)

if __name__ == '__main__':
    main()
