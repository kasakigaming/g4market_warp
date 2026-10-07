"""Steam DNS - bật/tắt bypass chặn Steam bằng NRPT (Name Resolution Policy Table).

Chỉ các domain của Steam được hỏi qua Google DNS; DNS của Wi-Fi giữ nguyên,
các trang khác vẫn đi DNS router. Cần quyền admin (tự hỏi UAC khi mở).
"""
import ctypes
import math
import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import winreg

from PIL import Image, ImageDraw, ImageFilter, ImageTk

RULE_NAME = "SteamDNS"
RESOLVERS = ["8.8.8.8", "8.8.4.4"]
DOMAINS = [
    "steampowered.com", "steamcommunity.com", "steamstatic.com", "steamserver.net", "steamcontent.com",
    "steamusercontent.com", "s.team", "steam-chat.com", "steamgames.com", "valvesoftware.com",
    "steamdeck.com", "akamaihd.net",
]
# NRPT: "x.com" khớp đúng tên miền, ".x.com" khớp mọi subdomain -> thêm cả hai.
NAMESPACES = [ns for d in DOMAINS for ns in (d, "." + d)]
BLOCKED_IPS = {"127.0.0.1", "::1", "0.0.0.0", "::"}

# Giao diện tối, nhấn màu xanh chanh.
BG = "#0a0d13"
GRID = "#11151e"
PANEL = "#0e121a"
LINE = "#242b38"
TEXT = "#f2f5f9"
LABEL = "#9aa4b8"
OFF = "#a3aec6"
LIME = "#c6f432"
CYAN = "#62d4ee"
YELLOW = "#f5b73b"
RED = "#ff5d5d"
GRAY = "#6b7385"
BRAND = "#99ee2d"  # xanh G4Market
CARD = "#10151e"   # nền thẻ popup

ZOOM = 1.15        # phóng to cả giao diện cho dễ đọc
SS = 3             # vẽ hình tròn/icon ở 3x rồi thu nhỏ -> viền mượt, không răng cưa
W, H = 330, 524    # kích thước cửa sổ (đơn vị thiết kế, trước khi nhân ZOOM/DPI)
HEAD, FOOT = 38, 490  # đáy thanh tiêu đề, đỉnh chân trang
CX, CY = 165, 172  # tâm nút nguồn
HINT = "Nếu Steam đang mở, app sẽ tự khởi động lại Steam."
G4_URL = "https://g4market.com/"
SETTINGS_KEY = r"Software\SteamDNS"  # HKCU, lưu "không hiện lại popup"
FPS_MS = 16       # ~60 khung hình/giây khi có chuyển động


def mix(c1, c2, t):
    """Trộn hai màu hex: t=0 -> c1, t=1 -> c2."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def rgba(color, alpha=255):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) + (alpha,)


def q(v, steps):
    """Làm tròn 0..1 về `steps` mức để cache ảnh theo mức chuyển tiếp."""
    return round(max(0.0, min(1.0, v)) * steps) / steps


def ease(t):
    """easeOutCubic."""
    return 1 - (1 - t) ** 3


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def welcome_hidden():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as k:
            return bool(winreg.QueryValueEx(k, "HideWelcome")[0])
    except OSError:
        return False


def hide_welcome():
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as k:
        winreg.SetValueEx(k, "HideWelcome", 0, winreg.REG_DWORD, 1)


def open_url(url):
    # Mở qua explorer để trình duyệt chạy quyền thường, không kế thừa quyền admin của app.
    subprocess.Popen(["explorer.exe", url], stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def ps_list(items):
    return ",".join(f"'{i}'" for i in items)


def run_ps(script):
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        stdin=subprocess.DEVNULL,  # exe --windowed không có stdin hợp lệ
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"PowerShell exit {result.returncode}")
    return result.stdout.strip()


REMOVE_RULE = (
    f"Get-DnsClientNrptRule | Where-Object DisplayName -eq '{RULE_NAME}' | "
    "ForEach-Object { Remove-DnsClientNrptRule -Name $_.Name -Force }"
)


def is_enabled():
    out = run_ps(f"[bool](Get-DnsClientNrptRule | Where-Object DisplayName -eq '{RULE_NAME}')")
    return out == "True"


def enable():
    run_ps(
        f"$ErrorActionPreference='Stop'; {REMOVE_RULE}; "
        f"Add-DnsClientNrptRule -Namespace {ps_list(NAMESPACES)} -NameServers {ps_list(RESOLVERS)} "
        f"-DisplayName '{RULE_NAME}' -Comment 'Bypass Steam DNS block' | Out-Null; Clear-DnsClientCache"
    )


def disable():
    run_ps(f"$ErrorActionPreference='Stop'; {REMOVE_RULE}; Clear-DnsClientCache")


def steam_status():
    """Trả về (trạng thái, ip): trạng thái là "ok", "blocked" hoặc "fail"."""
    run_ps("Clear-DnsClientCache")
    try:
        ips = [ai[4][0] for ai in socket.getaddrinfo("api.steampowered.com", 443, proto=socket.IPPROTO_TCP)]
    except OSError:
        return "fail", None
    if not ips:
        return "fail", None
    if any(ip in BLOCKED_IPS for ip in ips):
        return "blocked", next(ip for ip in ips if ip in BLOCKED_IPS)
    return "ok", ips[0]


def steam_exe():
    """Đường dẫn steam.exe lấy từ registry, None nếu không tìm thấy."""
    for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamExe"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(hive, key) as k:
                path = winreg.QueryValueEx(k, value)[0]
        except OSError:
            continue
        if value == "InstallPath":
            path = os.path.join(path, "steam.exe")
        path = os.path.normpath(path)
        if os.path.isfile(path):
            return path
    return None


def steam_running():
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout
    return "steam.exe" in out.lower()


def restart_steam():
    """Thoát hẳn Steam rồi mở lại để Steam dùng DNS mới."""
    exe = steam_exe()
    if not exe:
        return
    no_window = {"stdin": subprocess.DEVNULL, "creationflags": subprocess.CREATE_NO_WINDOW}
    subprocess.Popen([exe, "-shutdown"], **no_window)
    deadline = time.monotonic() + 30
    while steam_running() and time.monotonic() < deadline:
        time.sleep(1)
    if steam_running():  # không chịu thoát (treo) -> buộc tắt
        subprocess.run(["taskkill", "/F", "/T", "/IM", "steam.exe"], capture_output=True, **no_window)
        time.sleep(2)
    # Mở qua explorer để Steam chạy quyền thường, không kế thừa quyền admin của app.
    subprocess.Popen(["explorer.exe", exe], **no_window)


class App:
    """Cửa sổ không viền vẽ trên một Canvas.

    Toạ độ viết theo đơn vị thiết kế (W x H) rồi nhân self.k. Đường thẳng được làm tròn
    về pixel nguyên cho nét 1px sắc; hình tròn/icon vẽ bằng Pillow ở SS lần rồi thu nhỏ.

    Chuyển động: mỗi trạng thái (bật/tắt, rê chuột, đang xử lý, popup...) là một giá trị 0..1
    trong self.anim, trượt dần về self.target theo hàm mũ; khi còn giá trị chưa tới đích thì
    vẽ lại ~60 lần/giây, tới đích hết thì dừng.
    """

    TAU = {"on": 0.09, "busy": 0.12, "pop": 0.085, "chk": 0.05}  # hằng thời gian (giây), mặc định 0.06
    HOVERABLE = ("power", "recheck", "min", "close", "g4", "w_ok", "w_site", "w_check")

    def __init__(self, root):
        self.root = root
        self.enabled = False
        self.busy = False
        self.busy_text = ""  # chữ trạng thái lúc đang xử lý
        self.conn = None  # (trạng thái, ip) từ steam_status()
        self.hover = self.pressed = None
        self.welcome = False  # popup chào mừng đang mở
        self.dont_show = False  # ô "không hiện lại"
        self.hwnd = None
        self.sprites, self.bases = {}, {}
        self.tag = "dyn"
        self.static_done = False
        self.anim, self.target = {}, {}
        self.spin = 0.0
        self.ticking = False
        self.last_tick = 0.0
        self.k = root.winfo_fpixels("1i") / 96 * ZOOM
        try:
            self.logo = Image.open(resource("assets", "g4market_logo.png")).convert("RGBA")
        except OSError:
            self.logo = None

        root.title("Steam DNS")
        root.overrideredirect(True)
        root.configure(bg=BG)
        root.attributes("-alpha", 0.0)
        try:
            ico = sys.executable if getattr(sys, "frozen", False) else resource("steam_dns.ico")
            root.iconbitmap(default=ico)
        except tk.TclError:
            pass

        self.cv = tk.Canvas(root, width=self.X(W), height=self.X(H), bg=BG, highlightthickness=0, bd=0)
        self.cv.pack()
        self.make_fonts()
        x = (root.winfo_screenwidth() - self.X(W)) // 2
        y = (root.winfo_screenheight() - self.X(H)) // 2
        root.geometry(f"+{x}+{y}")
        root.after(10, self.show_in_taskbar)

        self.cv.bind("<Motion>", lambda e: self.set_hover(self.region(e)))
        self.cv.bind("<Leave>", lambda e: self.set_hover(None))
        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        root.bind("<Return>", lambda e: self.welcome and self.close_welcome())
        root.bind("<Escape>", lambda e: self.welcome and self.close_welcome())

        if not welcome_hidden():
            root.after(260, self.open_welcome)
        self.refresh()
        root.after(400, self.prewarm)

    def prewarm(self):
        """Dựng trước các ảnh nút nguồn (ở mọi mức sáng) vào lúc rảnh, rải qua nhiều nhịp
        để lần bấm bật/tắt đầu tiên không phải dựng ảnh -> không khựng."""
        jobs = []
        for i in range(7):
            o = i / 6
            jobs.append(lambda o=o: self.sprite(("rings", o, 0.0, 0), 184,
                        lambda img, f: self.paint_rings(img, f, o, 0.0, 0), -99, -99))
            for h in (0.0, 1.0):
                jobs.append(lambda o=o, h=h: self.sprite(("face", o, h), 184,
                            lambda img, f: self.paint_face(img, f, o, h), -99, -99))

        def run():
            for _ in range(3):  # 3 ảnh mỗi nhịp
                if jobs:
                    jobs.pop()()
            if jobs:
                self.root.after(FPS_MS, run)
            else:
                self.cv.delete("dyn")  # xoá các ảnh vẽ tạm ngoài màn hình

        run()

    # ---- cửa sổ ----

    def show_in_taskbar(self):
        """overrideredirect làm cửa sổ mất khỏi taskbar -> bật lại WS_EX_APPWINDOW."""
        user32 = ctypes.windll.user32
        self.hwnd = int(self.root.wm_frame(), 16)
        ex = user32.GetWindowLongW(self.hwnd, -20)  # GWL_EXSTYLE
        user32.SetWindowLongW(self.hwnd, -20, (ex & ~0x80) | 0x40000)  # bỏ TOOLWINDOW, thêm APPWINDOW
        style = user32.GetWindowLongW(self.hwnd, -16)  # GWL_STYLE
        user32.SetWindowLongW(self.hwnd, -16, style | 0x20000)  # WS_MINIMIZEBOX: bấm taskbar để thu/mở
        self.root.withdraw()
        self.root.after(10, self.root.deiconify)
        self.root.after(20, self.fade_window, 0.0, 1.0, 180)

    def fade_window(self, start, end, ms, done=None):
        """Làm mờ/hiện cả cửa sổ (thuộc tính -alpha của Windows)."""
        t0 = time.perf_counter()

        def step():
            t = min(1.0, (time.perf_counter() - t0) * 1000 / ms)
            self.root.attributes("-alpha", start + (end - start) * ease(t))
            if t < 1:
                self.root.after(FPS_MS, step)
            elif done:
                done()

        step()

    def minimize(self):
        def done():
            ctypes.windll.user32.ShowWindow(self.hwnd, 6)  # SW_MINIMIZE
            self.root.attributes("-alpha", 1.0)

        self.fade_window(1.0, 0.0, 130, done)

    def close(self):
        self.fade_window(1.0, 0.0, 150, self.root.destroy)

    def region(self, e):
        x, y = e.x / self.k, e.y / self.k
        if y < HEAD:
            return "close" if x >= 294 else "min" if x >= 262 else "drag"
        if self.welcome:
            if 52 <= x <= 280 and 318 <= y <= 336:
                return "w_check"
            if 41 <= x <= 160 and 354 <= y <= 386:
                return "w_site"
            if 170 <= x <= 289 and 354 <= y <= 386:
                return "w_ok"
            return None
        if 17 <= x <= 313 and 421 <= y <= 465:
            return "g4"
        if self.busy:
            return None
        if (x - CX) ** 2 + (y - CY) ** 2 <= 58 ** 2:
            return "power"
        if 209 <= x <= 301 and 375 <= y <= 402:
            return "recheck"
        return None

    def set_hover(self, region):
        if region != self.hover:
            self.hover = region
            self.cv.config(cursor="hand2" if region in self.HOVERABLE else "")
            self.kick()

    def on_press(self, e):
        self.pressed = self.region(e)
        if self.pressed == "drag":
            self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def on_drag(self, e):
        if self.pressed == "drag":
            self.root.geometry(f"+{e.x_root - self.drag[0]}+{e.y_root - self.drag[1]}")

    def on_release(self, e):
        pressed, self.pressed = self.pressed, None
        if pressed != "drag" and pressed == self.region(e):
            {"close": self.close, "min": self.minimize, "power": self.toggle, "recheck": self.refresh,
             "g4": lambda: open_url(G4_URL), "w_site": lambda: open_url(G4_URL),
             "w_ok": self.close_welcome, "w_check": self.flip_dont_show}.get(pressed, lambda: None)()

    # ---- popup chào mừng ----

    def open_welcome(self):
        self.welcome = True
        self.set_hover(None)
        self.kick()

    def close_welcome(self):
        if self.dont_show:
            try:
                hide_welcome()
            except OSError:
                pass
        self.welcome = False
        self.kick()

    def flip_dont_show(self):
        self.dont_show = not self.dont_show
        self.kick()

    # ---- chuyển động ----

    def targets(self):
        t = {"on": float(self.enabled and not self.busy), "busy": float(self.busy),
             "pop": float(self.welcome), "chk": float(self.dont_show)}
        for name in self.HOVERABLE:
            t["h_" + name] = float(self.hover == name)
        return t

    def a(self, name):
        return self.anim.get(name, 0.0)

    def kick(self):
        """Có trạng thái đổi -> chạy vòng vẽ lại nếu chưa chạy."""
        if not self.ticking:
            self.ticking = True
            self.last_tick = time.perf_counter()
            self.tick()

    def tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self.last_tick)
        self.last_tick = now
        moving = False
        for name, goal in self.targets().items():
            v = self.anim.setdefault(name, goal if name.startswith("h_") else 0.0)
            if v != goal:
                v += (goal - v) * (1 - math.exp(-dt / self.TAU.get(name, 0.06)))
                if abs(goal - v) < 0.004:
                    v = goal
                self.anim[name] = v
                moving = True
        if self.a("busy") > 0.001:
            self.spin = (self.spin + dt * 110) % 360  # 110°/giây
            moving = True
        self.render()
        if moving:
            self.root.after(FPS_MS, self.tick)
        else:
            self.ticking = False

    # ---- công cụ vẽ ----

    def X(self, v):
        """Đơn vị thiết kế -> pixel nguyên."""
        return round(v * self.k)

    def line(self, x1, y1, x2, y2, **kw):
        self.cv.create_line(self.X(x1), self.X(y1), self.X(x2), self.X(y2), tags=self.tag, **kw)

    def rect(self, x1, y1, x2, y2, **kw):
        self.cv.create_rectangle(self.X(x1), self.X(y1), self.X(x2), self.X(y2), tags=self.tag, **kw)

    def text(self, x, y, **kw):
        self.cv.create_text(self.X(x), self.X(y), tags=self.tag, **kw)

    def tracked(self, x, y, text, font, fill, track=1.5, anchor="w"):
        """Chữ giãn khoảng cách (Tk không có letter-spacing nên đặt từng ký tự)."""
        gap = track * self.k
        widths = [font.measure(ch) for ch in text]
        cur = x * self.k - ((sum(widths) + gap * (len(text) - 1)) / 2 if anchor == "center" else 0)
        for ch, w in zip(text, widths):
            self.cv.create_text(round(cur), self.X(y), text=ch, font=font, fill=fill, anchor="w",
                                tags=self.tag)
            cur += w + gap

    def sprite(self, key, size, paint, cx, cy, alpha=1.0, anchor="center"):
        """Đặt ảnh size x size hoặc (rộng, cao) (đơn vị thiết kế) tại (cx, cy).

        paint(img, f) vẽ lên ảnh RGBA ở SS lần, f() đổi đơn vị thiết kế -> pixel của ảnh đó.
        Ảnh gốc cache theo key; alpha (đã làm tròn bằng q()) cache riêng để mờ dần không phải vẽ lại.
        """
        if alpha <= 0.001:
            return
        if key not in self.bases:
            w, h = size if isinstance(size, tuple) else (size, size)
            pw, ph = self.X(w), self.X(h)
            img = Image.new("RGBA", (pw * SS, ph * SS), (0, 0, 0, 0))
            paint(img, lambda v: v * pw * SS / w)
            self.bases[key] = img.resize((pw, ph), Image.LANCZOS)
        self.place(key, self.bases[key], cx, cy, alpha, anchor)

    def place(self, key, base, cx, cy, alpha=1.0, anchor="center"):
        sk = (key, alpha)
        if sk not in self.sprites:
            img = base
            if alpha < 1:
                img = base.copy()
                img.putalpha(base.getchannel("A").point(lambda v: round(v * alpha)))
            self.sprites[sk] = ImageTk.PhotoImage(img)
        self.cv.create_image(self.X(cx), self.X(cy), image=self.sprites[sk], anchor=anchor, tags=self.tag)

    def wordmark(self, height, x, y, alpha=1.0, anchor="center"):
        """Logo chữ G4Market (ảnh của g4market.com); thiếu file thì viết bằng font."""
        if self.logo is None:
            font = self.f_brand_big if height > 15 else self.f_brand
            w1, w2 = font.measure("G4"), font.measure("Market")
            left = self.X(x) - ((w1 + w2) / 2 if anchor == "center" else 0)
            self.cv.create_text(round(left), self.X(y), text="G4", anchor="w", font=font,
                                fill=mix(CARD, TEXT, alpha), tags=self.tag)
            self.cv.create_text(round(left + w1), self.X(y), text="Market", anchor="w", font=font,
                                fill=mix(CARD, BRAND, alpha), tags=self.tag)
            return
        key = ("wordmark", height)
        if key not in self.bases:
            ph = self.X(height)
            self.bases[key] = self.logo.resize((round(self.logo.width * ph / self.logo.height), ph),
                                               Image.LANCZOS)
        self.place(key, self.bases[key], x, y, alpha, anchor)

    def make_fonts(self):
        fams = set(tkfont.families())
        head = "Bahnschrift" if "Bahnschrift" in fams else "Segoe UI"
        mono = next((f for f in ("Cascadia Mono SemiBold", "Consolas") if f in fams), "Courier New")

        def font(family, size, weight="normal"):
            return tkfont.Font(family=family, size=-self.X(size), weight=weight)

        self.f_title = font(head, 15, "bold")
        self.f_label = font(mono, 9.5)
        self.f_power = font(head, 12, "bold")
        self.f_status = font(head, 26, "bold")
        self.f_value = font("Segoe UI", 13.5, "bold")
        self.f_ip = font(head, 15, "bold")
        self.f_btn = font("Segoe UI", 11.5, "bold")
        self.f_small = font("Segoe UI", 11)
        self.f_body = font("Segoe UI", 13.5)
        self.f_brand = font(head, 14, "bold")
        self.f_brand_big = font(head, 17, "bold")
        size = 11.5
        self.f_hint = font("Segoe UI", size)
        while size > 9 and self.f_hint.measure(HINT) > self.X(W - 44):
            size -= 0.5
            self.f_hint = font("Segoe UI", size)

    # ---- các phần giao diện ----

    def render(self):
        if not self.static_done:
            self.tag = "static"  # lưới, nhãn cố định, viền bảng, chân trang: tạo 1 lần
            self.draw_static()
            self.tag = "dyn"
            self.static_done = True
        self.cv.delete("dyn")  # mỗi khung chỉ vẽ lại phần thay đổi, nằm trên nền tĩnh
        self.draw_power()
        self.draw_info()
        self.draw_banner()
        self.draw_welcome()
        self.draw_titlebar()

    def draw_static(self):
        for x in range(22, W, 22):
            self.line(x, HEAD, x, FOOT, fill=GRID)
        for y in range(HEAD + 22, FOOT, 22):
            self.line(0, y, W, y, fill=GRID)
        self.tracked(CX, 65, "CHỈ DOMAIN STEAM ĐI QUA GOOGLE DNS", self.f_label, LABEL, 1.3, "center")
        # khung bảng + nhãn cố định
        self.rect(17, 321, 313, 409, fill=PANEL, outline=LINE)
        self.line(17, 366, 313, 366, fill=LINE)
        self.line(165, 321, 165, 366, fill=LINE)
        self.tracked(27, 334, "KẾT NỐI STEAM", self.f_label, LABEL, 1.1)
        self.tracked(175, 334, "DNS ĐANG DÙNG", self.f_label, LABEL, 1.1)
        self.tracked(27, 380, "IP STEAM PHÂN GIẢI", self.f_label, LABEL, 1.1)
        self.tracked(CX, 267, "STEAM STATUS", self.f_label, LABEL, 2.2, "center")
        # chân trang
        self.line(0, FOOT, W, FOOT, fill=LINE)
        self.sprite("info", 14, self.paint_info, 21, FOOT + 17)
        self.text(33, FOOT + 17, text=HINT, anchor="w", font=self.f_hint, fill="#d3d8e1")

    def draw_titlebar(self):
        """Vẽ sau cùng để nằm trên lớp tối của popup (vẫn kéo / đóng được)."""
        self.rect(0, 0, W, HEAD, fill=BG, outline="")
        self.line(0, HEAD, W, HEAD, fill=LINE)
        self.sprite("logo", 20, self.paint_logo, 23, 20)
        self.text(42, 20, text="STEAM", anchor="w", font=self.f_title, fill=TEXT)
        self.cv.create_text(self.X(42) + self.f_title.measure("STEAM"), self.X(20), text="DNS",
                            anchor="w", font=self.f_title, fill=LIME, tags=self.tag)
        hm, hc = self.a("h_min"), self.a("h_close")
        if hm > 0.01:
            self.rect(262, 0, 294, HEAD, fill=mix(BG, "#1a202b", hm), outline="")
        if hc > 0.01:
            self.rect(294, 0, W, HEAD, fill=mix(BG, "#c42b1c", hc), outline="")
        self.line(273, 20, 283, 20, fill=mix(LABEL, TEXT, hm), width=max(1, round(self.k)))
        xc = mix(LABEL, TEXT, q(hc, 6))
        self.sprite(("close", xc), 12, lambda img, f: self.paint_close(img, f, xc), 312, 20)
        self.cv.create_rectangle(0, 0, self.X(W) - 1, self.X(H) - 1, outline=LINE, tags=self.tag)  # viền

    def draw_power(self):
        on, busy, hov = self.a("on"), self.a("busy"), self.a("h_power")
        # ít mức màu (6/4) -> ít ảnh phải dựng lại khi chuyển, hiệu ứng chỉ ~6 khung nên vẫn mượt
        qo, qb, qh = q(on, 6), q(busy, 6), q(hov, 4)
        frame = int(self.spin) % 8 if busy > 0.001 else 0  # chỉ quay khi đang xử lý

        self.sprite("glow", 184, self.paint_glow, CX, CY, alpha=qo)
        self.sprite(("rings", qo, qb, frame), 184,
                    lambda img, f: self.paint_rings(img, f, qo, qb, frame), CX, CY)
        self.sprite(("face", qo, qh), 184, lambda img, f: self.paint_face(img, f, qo, qh), CX, CY)

        ink = mix(mix("#c3cad8", "#eef1f6", hov), BG, on)
        label = "..." if self.busy else "TẮT" if self.enabled else "BẬT"
        self.tracked(CX, CY + 14, label, self.f_power, ink, 1.5, "center")

        status = self.busy_text if self.busy else "ĐANG BẬT" if self.enabled else "ĐANG TẮT"
        color = mix(mix(OFF, LIME, on), OFF, busy)
        self.tracked(CX, 291, status, self.f_status, color, 1, "center")

    def draw_info(self):
        state, ip = self.conn or (None, None)
        conn, dot = {"ok": ("OK", LIME), "blocked": ("BỊ CHẶN", RED),
                     "fail": ("KHÔNG PHÂN GIẢI", GRAY)}.get(state, ("...", GRAY))
        self.sprite(("dot", dot), 7, lambda img, f: ImageDraw.Draw(img).ellipse(
            [f(0.5), f(0.5), f(6.5), f(6.5)], fill=rgba(dot)), 30.5, 351.5)
        self.text(37.5, 351, text=conn, anchor="w", font=self.f_value, fill=TEXT)
        self.text(175, 351, text="Google" if self.enabled else "Mặc định", anchor="w",
                  font=self.f_value, fill=TEXT)
        self.tracked(27, 396, ip or "—", self.f_ip, TEXT, 0.5)

        hov = self.a("h_recheck")
        fg = mix(CYAN, LABEL, q(self.a("busy"), 6))
        self.rect(209, 375, 301, 402, fill=mix(PANEL, CYAN, 0.04 + 0.1 * hov),
                  outline=mix(PANEL, fg, 0.45 + 0.3 * hov))
        icon_w, gap = self.X(12), self.X(5)
        cur = self.X(255) - (icon_w + gap + self.f_btn.measure("Kiểm tra lại")) / 2
        self.sprite(("refresh", fg), 12, lambda img, f: self.paint_refresh(img, f, fg),
                    (cur + icon_w / 2) / self.k, 388.5)
        self.cv.create_text(round(cur + icon_w + gap), self.X(388.5), text="Kiểm tra lại", anchor="w",
                            font=self.f_btn, fill=fg, tags=self.tag)

    def draw_banner(self):
        hov = self.a("h_g4")
        qh = q(hov, 6)
        self.sprite(("banner", qh), (296, 44), lambda img, f: self.paint_banner(img, f, qh), 165, 443)
        self.sprite("g4icon", 26, lambda img, f: self.paint_g4icon(img, f, 26), 43, 443)
        self.wordmark(14, 62, 435, anchor="w")
        self.text(62, 452.5, text="Chợ game bản quyền", anchor="w", font=self.f_small, fill=LABEL)
        fg = mix(TEXT, BRAND, qh)
        nudge = 1.5 * hov  # mũi tên nhích lên-phải khi rê chuột
        self.text(278 - nudge, 443, text="Ghé shop", anchor="e", font=self.f_btn, fill=fg)
        self.sprite(("arrow", fg), 12, lambda img, f: self.paint_arrow(img, f, fg), 292 + nudge, 443 - nudge)

    def draw_welcome(self):
        p = self.a("pop")
        if p <= 0.001:
            return
        e = ease(p)
        qa = q(p, 12)
        # lớp tối đậm lên nhanh và tắt chậm (>= độ rõ của thẻ) để nền không lộ qua khi chữ popup còn hiện
        qdim = q(min(1.0, e * 2.6), 12)
        dy = (1 - e) * 16  # thẻ trượt lên khi hiện

        def fade(color):
            return mix(CARD, color, e)

        self.sprite("dim", (W, H - HEAD), lambda img, f: ImageDraw.Draw(img).rectangle(
            [0, 0, img.width, img.height], fill=(4, 6, 10, 232)), W / 2, (H + HEAD) / 2, alpha=qdim)
        self.sprite("card", (272, 290), self.paint_card, 165, 254 + dy, alpha=qa)
        self.sprite("g4icon_big", 44, lambda img, f: self.paint_g4icon(img, f, 44), 165, 147 + dy, alpha=qa)
        self.wordmark(17, 165, 186 + dy, alpha=qa)
        self.tracked(165, 214 + dy, "SẢN PHẨM MIỄN PHÍ", self.f_label, fade(BRAND), 2.2, "center")
        self.cv.create_text(self.X(165), self.X(256 + dy), width=self.X(226), justify="center",
                            text="Đây là sản phẩm miễn phí dành cho cộng đồng của g4market.com.",
                            font=self.f_body, fill=fade(TEXT), tags=self.tag)
        self.cv.create_text(self.X(165), self.X(296 + dy), width=self.X(236), justify="center",
                            text="Nếu bạn phải mua lại từ bất kỳ ai, chắc chắn đó là lừa đảo!",
                            font=self.f_small, fill=fade(YELLOW), tags=self.tag)

        hc, chk = self.a("h_w_check"), self.a("chk")
        qc, qhc = q(chk, 8), q(hc, 4)
        self.sprite(("check", qc, qhc), 16, lambda img, f: self.paint_check(img, f, qc, qhc), 62, 327 + dy,
                    alpha=qa)
        self.text(76, 327 + dy, text="Không hiện lại thông báo này", anchor="w", font=self.f_small,
                  fill=fade(mix(LABEL, TEXT, max(hc, chk))))

        hs = self.a("h_w_site")
        self.rect(41, 354 + dy, 160, 386 + dy, fill=fade(mix(CARD, BRAND, 0.12 * hs)),
                  outline=fade(mix(CARD, BRAND, 0.5 + 0.3 * hs)))
        self.text(94, 370 + dy, text="g4market.com", font=self.f_btn, fill=fade(BRAND))
        self.sprite(("arrow", BRAND), 12, lambda img, f: self.paint_arrow(img, f, BRAND),
                    143 + 1.5 * hs, 370 + dy - 1.5 * hs, alpha=qa)
        ho = self.a("h_w_ok")
        self.rect(170, 354 + dy, 289, 386 + dy, fill=fade(mix(BRAND, "#ffffff", 0.2 * ho)), outline="")
        self.text(229.5, 370 + dy, text="Đã hiểu", font=self.f_btn, fill=mix(CARD, BG, e))

    # ---- hình vẽ bằng Pillow ----

    @staticmethod
    def paint_logo(img, f):
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([f(1), f(1), f(19), f(19)], radius=f(4), fill=rgba(LIME))
        bolt = [(11.5, 3.5), (5.5, 11), (9.6, 11), (8.5, 16.5), (14.5, 9), (10.4, 9)]
        pts = [(f(x), f(y)) for x, y in bolt]
        d.line(pts + pts[:2], fill=rgba(BG), width=round(f(1.7)), joint="curve")

    @staticmethod
    def paint_close(img, f, color):
        d = ImageDraw.Draw(img)
        w = round(f(1.3))
        d.line([f(2), f(2), f(10), f(10)], fill=rgba(color), width=w)
        d.line([f(10), f(2), f(2), f(10)], fill=rgba(color), width=w)

    @staticmethod
    def paint_info(img, f):
        d = ImageDraw.Draw(img)
        d.ellipse([f(1), f(1), f(13), f(13)], outline=rgba(YELLOW), width=round(f(1.3)))
        d.ellipse([f(6.25), f(3.6), f(7.75), f(5.1)], fill=rgba(YELLOW))
        d.rounded_rectangle([f(6.3), f(6.2), f(7.7), f(10.6)], radius=f(0.6), fill=rgba(YELLOW))

    @staticmethod
    def paint_refresh(img, f, color):
        d = ImageDraw.Draw(img)
        d.arc([f(1), f(1), f(11), f(11)], 335, 245, fill=rgba(color), width=round(f(1.6)))
        # mũi tên ở cuối cung (245°), chĩa theo chiều kim đồng hồ
        a = math.radians(245)
        nx, ny, tx, ty = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
        px, py = 6 + 4.2 * nx, 6 + 4.2 * ny
        d.polygon([(f(px + 3 * tx), f(py + 3 * ty)),
                   (f(px + 2.6 * nx - 0.6 * tx), f(py + 2.6 * ny - 0.6 * ty)),
                   (f(px - 2.6 * nx - 0.6 * tx), f(py - 2.6 * ny - 0.6 * ty))], fill=rgba(color))

    @staticmethod
    def paint_arrow(img, f, color):
        d = ImageDraw.Draw(img)
        w = round(f(1.6))
        d.line([f(2.5), f(9.5), f(9.5), f(2.5)], fill=rgba(color), width=w)
        d.line([f(4), f(2.5), f(9.5), f(2.5), f(9.5), f(8)], fill=rgba(color), width=w, joint="curve")

    # Nút nguồn chia 3 lớp (quầng sáng / các vòng / mặt nút) để mỗi lớp chỉ phụ thuộc ít trạng thái.

    @staticmethod
    def paint_glow(img, f):
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([f(34), f(34), f(150), f(150)], fill=rgba(LIME, 120))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(f(10))))

    @staticmethod
    def paint_rings(img, f, on, busy, spin):
        d = ImageDraw.Draw(img)
        thin = max(1, round(f(1.1)))
        ring = mix("#2d3442", mix(BG, LIME, 0.85), on)
        dash = mix("#353d4d", mix(BG, LIME, 0.7), max(on, busy))
        d.ellipse([f(25), f(25), f(159), f(159)], outline=rgba(ring), width=thin)
        for a in range(0, 360, 8):  # vòng nét đứt, quay khi đang xử lý
            d.arc([f(12), f(12), f(172), f(172)], a + spin, a + spin + 4, fill=rgba(dash), width=thin)

    @staticmethod
    def paint_face(img, f, on, hov):
        c = 92
        d = ImageDraw.Draw(img)
        thin = max(1, round(f(1.1)))
        face = mix(mix("#141923", "#1b2130", hov), mix(LIME, mix(LIME, "#ffffff", 0.2), hov), on)
        edge = mix(mix("#2b3343", "#3a4354", hov), face, on)
        ink = mix(mix("#c3cad8", "#eef1f6", hov), BG, on)
        d.ellipse([f(c - 55), f(c - 55), f(c + 55), f(c + 55)], fill=rgba(face), outline=rgba(edge), width=thin)

        # biểu tượng nguồn
        stroke, cy = round(f(3)), c - 16
        d.arc([f(c - 12.5), f(cy - 12.5), f(c + 12.5), f(cy + 12.5)], 302, 598, fill=rgba(ink), width=stroke)
        d.line([f(c), f(cy - 16), f(c), f(cy - 2)], fill=rgba(ink), width=stroke)
        ends = [(c, cy - 16), (c, cy - 2)]
        for ang in (302, 598):  # Pillow vẽ nét cung vào phía trong -> tâm nét ở bán kính 11
            ends.append((c + 11 * math.cos(math.radians(ang)), cy + 11 * math.sin(math.radians(ang))))
        for x, y in ends:  # đầu nét tròn
            d.ellipse([f(x - 1.5), f(y - 1.5), f(x + 1.5), f(y + 1.5)], fill=rgba(ink))

    @staticmethod
    def paint_banner(img, f, hov):
        w, h = 296, 44
        grad = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        steps = 60
        for i in range(steps):  # ánh xanh G4 nhạt dần từ trái sang phải
            t = i / steps
            col = mix(mix(PANEL, BRAND, 0.11 + 0.05 * hov), PANEL, t)
            gd.rectangle([f(w * t), 0, f(w * (t + 1 / steps)) + 1, f(h)], fill=rgba(col))
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([f(0.5), f(0.5), f(w - 0.5), f(h - 0.5)], radius=f(8), fill=255)
        img.paste(grad, (0, 0), mask)
        ImageDraw.Draw(img).rounded_rectangle([f(0.5), f(0.5), f(w - 0.5), f(h - 0.5)], radius=f(8),
                                              outline=rgba(mix(PANEL, BRAND, 0.35 + 0.35 * hov)),
                                              width=round(f(1)))

    @staticmethod
    def paint_g4icon(img, f, size):
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([f(0.5), f(0.5), f(size - 0.5), f(size - 0.5)], radius=f(size * 0.23),
                            fill=(0, 0, 0, 255), outline=rgba("#2a3242"), width=max(1, round(f(1))))
        c, r = size / 2, size * 0.29
        d.polygon([(f(c), f(c - r)), (f(c + r), f(c)), (f(c), f(c + r)), (f(c - r), f(c))], fill=rgba(BRAND))

    @staticmethod
    def paint_card(img, f):
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([f(0.5), f(0.5), f(271.5), f(289.5)], radius=f(14), fill=rgba(CARD),
                            outline=rgba("#2a3242"), width=round(f(1)))
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([f(56), f(-60), f(216), f(60)], fill=rgba(BRAND, 38))
        glow = glow.filter(ImageFilter.GaussianBlur(f(24)))
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([f(1), f(1), f(271), f(289)], radius=f(14), fill=255)
        img.paste(Image.alpha_composite(img.copy(), glow), (0, 0), mask)
        ImageDraw.Draw(img).line([f(96), f(1), f(176), f(1)], fill=rgba(BRAND, 200), width=round(f(1.5)))

    @staticmethod
    def paint_check(img, f, on, hov):
        d = ImageDraw.Draw(img)
        box = mix("#141923", BRAND, on)
        edge = mix(mix("#3a4354", "#56607a", hov), BRAND, on)
        d.rounded_rectangle([f(1), f(1), f(15), f(15)], radius=f(3.5), fill=rgba(box), outline=rgba(edge),
                            width=round(f(1.2)))
        if on > 0:
            d.line([f(4.5), f(8.2), f(7), f(10.8), f(11.8), f(5.4)], fill=rgba(mix(box, BG, on)),
                   width=round(f(1.9)), joint="curve")

    # ---- xử lý ----

    def run_bg(self, work):
        """Chạy work() ở thread phụ để cửa sổ không bị đơ, xong thì cập nhật giao diện."""
        self.busy = True
        self.busy_text = "ĐANG XỬ LÝ"
        self.set_hover(None)
        self.kick()

        def worker():
            error = None
            try:
                work()
                enabled = is_enabled()
                conn = steam_status()
            except Exception as e:  # noqa: BLE001 - hiện lỗi cho người dùng
                error, enabled, conn = e, self.enabled, self.conn
            self.root.after(0, self.show, enabled, conn, error)

        threading.Thread(target=worker, daemon=True).start()

    def show(self, enabled, conn, error):
        self.busy = False
        self.enabled, self.conn = enabled, conn
        self.kick()
        if error:
            from tkinter import messagebox
            messagebox.showerror("Steam DNS", f"Không đổi được:\n{error}", parent=self.root)

    def refresh(self):
        self.run_bg(lambda: None)

    def toggle(self):
        change = disable if self.enabled else enable

        def work():
            change()
            if steam_running():
                self.root.after(0, setattr, self, "busy_text", "ĐANG MỞ LẠI STEAM")
                restart_steam()

        self.run_bg(work)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def main():
    if not is_admin():
        # Bản exe (PyInstaller) đã có manifest đòi admin; nhánh này chủ yếu cho bản .pyw.
        if getattr(sys, "frozen", False):
            exe, args = sys.executable, None
        else:
            exe, args = sys.executable.replace("python.exe", "pythonw.exe"), f'"{__file__}"'
        # ShellExecute trả về <= 32 nếu lỗi / người dùng bấm No ở UAC -> thoát luôn.
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # chữ nét trên màn hình scale > 100%
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
