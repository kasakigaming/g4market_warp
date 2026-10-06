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

ZOOM = 1.15        # phóng to cả giao diện cho dễ đọc
SS = 4             # vẽ hình tròn/icon ở 4x rồi thu nhỏ -> viền mượt, không răng cưa
W, H = 330, 470    # kích thước cửa sổ (đơn vị thiết kế, trước khi nhân ZOOM/DPI)
HEAD, FOOT = 38, 436  # đáy thanh tiêu đề, đỉnh chân trang
CX, CY = 165, 172  # tâm nút nguồn
HINT = "Nếu Steam đang mở, app sẽ tự khởi động lại Steam."


def mix(c1, c2, t):
    """Trộn hai màu hex: t=0 -> c1, t=1 -> c2."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def rgba(color, alpha=255):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) + (alpha,)


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

    Toạ độ viết theo đơn vị thiết kế (330x470) rồi nhân self.k. Đường thẳng được làm tròn
    về pixel nguyên cho nét 1px sắc; hình tròn/icon vẽ bằng Pillow ở SS lần rồi thu nhỏ.
    """

    def __init__(self, root):
        self.root = root
        self.enabled = False
        self.busy = False
        self.busy_text = ""  # chữ trạng thái lúc đang xử lý
        self.conn = None  # (trạng thái, ip) từ steam_status()
        self.hover = self.pressed = None
        self.spin = 0
        self.hwnd = None
        self.sprites = {}
        self.k = root.winfo_fpixels("1i") / 96 * ZOOM

        root.title("Steam DNS")
        root.overrideredirect(True)
        root.configure(bg=BG)
        try:
            ico = sys.executable if getattr(sys, "frozen", False) else \
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "steam_dns.ico")
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

        self.refresh()

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

    def minimize(self):
        ctypes.windll.user32.ShowWindow(self.hwnd, 6)  # SW_MINIMIZE

    def region(self, e):
        x, y = e.x / self.k, e.y / self.k
        if y < HEAD:
            return "close" if x >= 294 else "min" if x >= 262 else "drag"
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
            self.cv.config(cursor="hand2" if region in ("power", "recheck", "min", "close") else "")
            self.render()

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
            {"close": self.root.destroy, "min": self.minimize,
             "power": self.toggle, "recheck": self.refresh}.get(pressed, lambda: None)()

    # ---- công cụ vẽ ----

    def X(self, v):
        """Đơn vị thiết kế -> pixel nguyên."""
        return round(v * self.k)

    def line(self, x1, y1, x2, y2, **kw):
        self.cv.create_line(self.X(x1), self.X(y1), self.X(x2), self.X(y2), **kw)

    def rect(self, x1, y1, x2, y2, **kw):
        self.cv.create_rectangle(self.X(x1), self.X(y1), self.X(x2), self.X(y2), **kw)

    def text(self, x, y, **kw):
        self.cv.create_text(self.X(x), self.X(y), **kw)

    def tracked(self, x, y, text, font, fill, track=1.5, anchor="w"):
        """Chữ giãn khoảng cách (Tk không có letter-spacing nên đặt từng ký tự)."""
        gap = track * self.k
        widths = [font.measure(ch) for ch in text]
        cur = x * self.k - ((sum(widths) + gap * (len(text) - 1)) / 2 if anchor == "center" else 0)
        for ch, w in zip(text, widths):
            self.cv.create_text(round(cur), self.X(y), text=ch, font=font, fill=fill, anchor="w")
            cur += w + gap

    def sprite(self, key, size, paint, cx, cy):
        """Đặt ảnh size x size (đơn vị thiết kế) có tâm tại (cx, cy).

        paint(img, f) vẽ lên ảnh RGBA ở SS lần, f() đổi đơn vị thiết kế -> pixel của ảnh đó.
        Kết quả được cache theo key.
        """
        if key not in self.sprites:
            px = self.X(size)
            img = Image.new("RGBA", (px * SS, px * SS), (0, 0, 0, 0))
            paint(img, lambda v: v * px * SS / size)
            self.sprites[key] = ImageTk.PhotoImage(img.resize((px, px), Image.LANCZOS))
        self.cv.create_image(self.X(cx), self.X(cy), image=self.sprites[key])

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
        size = 11.5
        self.f_hint = font("Segoe UI", size)
        while size > 9 and self.f_hint.measure(HINT) > self.X(W - 44):
            size -= 0.5
            self.f_hint = font("Segoe UI", size)

    # ---- các phần giao diện ----

    def render(self):
        self.cv.delete("all")
        self.draw_frame()
        self.draw_power()
        self.draw_info()

    def draw_frame(self):
        for x in range(22, W, 22):
            self.line(x, HEAD, x, FOOT, fill=GRID)
        for y in range(HEAD + 22, FOOT, 22):
            self.line(0, y, W, y, fill=GRID)

        # thanh tiêu đề
        self.line(0, HEAD, W, HEAD, fill=LINE)
        self.sprite("logo", 20, self.paint_logo, 23, 20)
        self.text(42, 20, text="STEAM", anchor="w", font=self.f_title, fill=TEXT)
        self.cv.create_text(self.X(42) + self.f_title.measure("STEAM"), self.X(20), text="DNS",
                            anchor="w", font=self.f_title, fill=LIME)
        if self.hover == "min":
            self.rect(262, 0, 294, HEAD, fill="#1a202b", outline="")
        if self.hover == "close":
            self.rect(294, 0, W, HEAD, fill="#c42b1c", outline="")
        self.line(273, 20, 283, 20, fill=TEXT if self.hover == "min" else LABEL, width=max(1, round(self.k)))
        xc = TEXT if self.hover == "close" else LABEL
        self.sprite(("close", xc), 12, lambda img, f: self.paint_close(img, f, xc), 312, 20)

        self.tracked(CX, 65, "CHỈ DOMAIN STEAM ĐI QUA GOOGLE DNS", self.f_label, LABEL, 1.3, "center")

        # chân trang
        self.line(0, FOOT, W, FOOT, fill=LINE)
        self.sprite("info", 14, self.paint_info, 21, 453)
        self.text(33, 453, text=HINT, anchor="w", font=self.f_hint, fill="#d3d8e1")
        self.cv.create_rectangle(0, 0, self.X(W) - 1, self.X(H) - 1, outline=LINE)  # viền cửa sổ

    def draw_power(self):
        on = self.enabled and not self.busy
        hov = self.hover == "power"
        spin = self.spin if self.busy else 0
        self.sprite(("power", on, hov, self.busy, spin), 184,
                    lambda img, f: self.paint_power(img, f, on, hov, spin), CX, CY)

        ink = BG if on else "#eef1f6" if hov else "#c3cad8"
        label = "..." if self.busy else "TẮT" if self.enabled else "BẬT"
        self.tracked(CX, CY + 14, label, self.f_power, ink, 1.5, "center")

        if self.busy:
            status, color = self.busy_text, OFF
        else:
            status, color = ("ĐANG BẬT", LIME) if self.enabled else ("ĐANG TẮT", OFF)
        self.tracked(CX, 267, "STEAM STATUS", self.f_label, LABEL, 2.2, "center")
        self.tracked(CX, 291, status, self.f_status, color, 1, "center")

    def draw_info(self):
        self.rect(17, 321, 313, 409, fill=PANEL, outline=LINE)
        self.line(17, 366, 313, 366, fill=LINE)
        self.line(165, 321, 165, 366, fill=LINE)

        state, ip = self.conn or (None, None)
        conn, dot = {"ok": ("OK", LIME), "blocked": ("BỊ CHẶN", RED),
                     "fail": ("KHÔNG PHÂN GIẢI", GRAY)}.get(state, ("...", GRAY))
        self.tracked(27, 334, "KẾT NỐI STEAM", self.f_label, LABEL, 1.1)
        self.sprite(("dot", dot), 7, lambda img, f: ImageDraw.Draw(img).ellipse(
            [f(0.5), f(0.5), f(6.5), f(6.5)], fill=rgba(dot)), 30.5, 351.5)
        self.text(37.5, 351, text=conn, anchor="w", font=self.f_value, fill=TEXT)
        self.tracked(175, 334, "DNS ĐANG DÙNG", self.f_label, LABEL, 1.1)
        self.text(175, 351, text="Google" if self.enabled else "Mặc định", anchor="w",
                  font=self.f_value, fill=TEXT)
        self.tracked(27, 380, "IP STEAM PHÂN GIẢI", self.f_label, LABEL, 1.1)
        self.tracked(27, 396, ip or "—", self.f_ip, TEXT, 0.5)

        hov = self.hover == "recheck"
        fg = LABEL if self.busy else CYAN
        self.rect(209, 375, 301, 402, fill=mix(PANEL, CYAN, 0.14 if hov else 0.04),
                  outline=mix(PANEL, fg, 0.75 if hov else 0.45))
        icon_w, gap = self.X(12), self.X(5)
        cur = self.X(255) - (icon_w + gap + self.f_btn.measure("Kiểm tra lại")) / 2
        self.sprite(("refresh", fg), 12, lambda img, f: self.paint_refresh(img, f, fg),
                    (cur + icon_w / 2) / self.k, 388.5)
        self.cv.create_text(round(cur + icon_w + gap), self.X(388.5), text="Kiểm tra lại", anchor="w",
                            font=self.f_btn, fill=fg)

    # ---- icon vẽ bằng Pillow ----

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
    def paint_power(img, f, on, hov, spin):
        c = 92  # tâm ảnh

        def box(r, cy=c):
            return [f(c - r), f(cy - r), f(c + r), f(cy + r)]

        if on:
            glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).ellipse(box(58), fill=rgba(LIME, 120))
            img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(f(10))))
            ring, dash = rgba(LIME, 215), rgba(LIME, 175)
            face = rgba(mix(LIME, "#ffffff", 0.2) if hov else LIME)
            edge, ink = None, rgba(BG)
        else:
            ring = rgba("#2d3442")
            dash = rgba(LIME, 175) if spin else rgba("#353d4d")  # spin != 0 khi đang xử lý
            face = rgba("#1b2130" if hov else "#141923")
            edge = rgba("#3a4354" if hov else "#2b3343")
            ink = rgba("#eef1f6" if hov else "#c3cad8")

        d = ImageDraw.Draw(img)
        thin = max(1, round(f(1.1)))
        d.ellipse(box(67), outline=ring, width=thin)
        for a in range(0, 360, 8):  # vòng nét đứt, quay khi đang xử lý
            d.arc(box(80), a + spin, a + spin + 4, fill=dash, width=thin)
        d.ellipse(box(55), fill=face, outline=edge, width=thin)

        # biểu tượng nguồn
        stroke, cy = round(f(3)), c - 16
        d.arc(box(12.5, cy), 302, 598, fill=ink, width=stroke)
        d.line([f(c), f(cy - 16), f(c), f(cy - 2)], fill=ink, width=stroke)
        ends = [(c, cy - 16), (c, cy - 2)]
        for ang in (302, 598):  # Pillow vẽ nét cung vào phía trong -> tâm nét ở bán kính 11
            ends.append((c + 11 * math.cos(math.radians(ang)), cy + 11 * math.sin(math.radians(ang))))
        for x, y in ends:  # đầu nét tròn
            d.ellipse([f(x - 1.5), f(y - 1.5), f(x + 1.5), f(y + 1.5)], fill=ink)

    # ---- xử lý ----

    def run_bg(self, work):
        """Chạy work() ở thread phụ để cửa sổ không bị đơ, xong thì cập nhật giao diện."""
        self.busy = True
        self.busy_text = "ĐANG XỬ LÝ"
        self.hover = None
        self.cv.config(cursor="")
        self.animate()

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

    def animate(self):
        if self.busy:
            self.spin = (self.spin + 2) % 8 or 8  # nét đứt lặp mỗi 8° -> chỉ cần 4 khung hình
            self.render()
            self.root.after(40, self.animate)

    def show(self, enabled, conn, error):
        self.busy = False
        self.enabled, self.conn = enabled, conn
        self.render()
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
