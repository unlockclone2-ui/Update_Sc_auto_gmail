import os
import json
import re
import time
import sys
import threading
import subprocess
import psutil
import pyotp
import win32gui, win32process, win32con

import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, scrolledtext, messagebox

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ---------------------------
# Globals (will be set at runtime)
# ---------------------------

VERSION = "25.09.15.2"

# Tự động ghi version ra file version.txt
try:
    with open("version.txt", "w", encoding="utf-8") as f:
        f.write(VERSION)
except Exception as e:
    pass

driver = None
wait = None
main_window = None
emails = []
TOTP_SECRETS = {}
selected_indices = []
videos_per_email = 0
delay_sec = 0
PROFILE_NAME_DEFAULT = "F:/SeleniumProfiles/Scoopz GMAIL 1"
selenium_profile_base = PROFILE_NAME_DEFAULT
video_folder_default = r"F:/VIDEO UP/INSTAGRAM/VIDEO AUTOWEB/Scoopz GMAIL 1"
debug_port_default = 9001
stop_flag = False
CONFIG_FILE = "config.json"

chrome_hidden = False  # trạng thái ẩn/hiện

def hide_show_chrome(driver, hide=True):
    try:
        chrome_driver_pid = driver.service.process.pid
        chrome_pid = None
        for proc in psutil.Process(chrome_driver_pid).children():
            if "chrome.exe" in proc.name().lower():
                chrome_pid = proc.pid
                break
        if chrome_pid is None:
            print("Không tìm thấy PID Chrome thực sự")
            return
    except Exception as e:
        print("Lỗi khi lấy PID Chrome:", e)
        return

    def enum_windows(hwnd, windows):
        tid, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == chrome_pid and win32gui.IsWindow(hwnd):
            windows.append(hwnd)
        return True

    windows = []
    win32gui.EnumWindows(enum_windows, windows)

    for hwnd in windows:
        try:
            title = win32gui.GetWindowText(hwnd)
            if not title.strip():
                continue
            if hide:
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                win32gui.SetForegroundWindow(hwnd)
        except Exception as e:
            print("Lỗi khi ẩn/hiện cửa sổ:", e)

# ---------------------------
# GUI App
# ---------------------------
class GUIApp:
    def __init__(self, root):
        self.root = root
        root.title(f"Scoopz Auto Uploader - Gmail v{VERSION}")
        root.geometry("650x650")

        # top frame: profile, video folder, controls
        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")

        # Profile name + Browse
        ttk.Label(top, text="Thư mục Profile:").grid(row=0, column=0, sticky="w")
        self.profile_var = tk.StringVar(value=PROFILE_NAME_DEFAULT)
        ttk.Entry(top, textvariable=self.profile_var, width=35).grid(row=0, column=1, sticky="w", padx=6)
        tk.Button(top, text="Browse", command=self.browse_profile).grid(row=0, column=2, sticky="w", padx=6)

        # Video folder + Browse
        ttk.Label(top, text="Thư mục Video:").grid(row=1, column=0, sticky="w")
        self.video_folder_var = tk.StringVar(value=video_folder_default)
        ttk.Entry(top, textvariable=self.video_folder_var, width=60).grid(row=1, column=1, sticky="w", padx=6)
        tk.Button(top, text="Browse", command=self.browse_folder).grid(row=1, column=2, sticky="w", padx=6)

        ttk.Label(top, text="Cổng port Chrome:").grid(row=2, column=0, sticky="w")
        self.port_entry = ttk.Entry(top, width=10)
        self.port_entry.insert(0, str(debug_port_default))
        self.port_entry.grid(row=2, column=1, sticky="w", padx=6)

        # Videos per account
        ttk.Label(top, text="Số video/account (0 = tất cả):").grid(row=3, column=0, sticky="w")
        self.videos_entry = ttk.Entry(top, width=10)
        self.videos_entry.insert(0, "0")
        self.videos_entry.grid(row=3, column=1, sticky="w", padx=6)

        # Delay
        ttk.Label(top, text="Delay giữa mỗi upload (giây):").grid(row=4, column=0, sticky="w")
        self.delay_entry = ttk.Entry(top, width=10)
        self.delay_entry.insert(0, "0")
        self.delay_entry.grid(row=4, column=1, sticky="w", padx=6)

        # Buttons: Load Accounts, Start, Stop, Quit, Save Config
        btn_font = ("Consolas", 10, "bold") 
        btn_frame = ttk.Frame(top)
        btn_frame.grid(row=5, column=0, columnspan=3, pady=8, sticky="w")
        self.load_btn = tk.Button(btn_frame, text="Load Accounts", command=self.threaded(self.load_accounts), fg="#000000", bg="#E0E0E0", font=btn_font)
        self.load_btn.grid(row=0, column=0, padx=6)
        self.start_btn = tk.Button(btn_frame, text="Start Upload", command=self.threaded(self.start_upload), fg="#FFFFFF", bg="#28a745", font=btn_font)
        self.start_btn.grid(row=0, column=1, padx=6)
        self.stop_btn = tk.Button(btn_frame, text="Stop Upload", command=self.set_stop_flag, fg="#FFFFFF", bg="#dc3545", font=btn_font)
        self.stop_btn.grid(row=0, column=2, padx=6)
        tk.Button(btn_frame, text="Thoát Chrome", command=self.quit_chrome_only, fg="#FFFFFF", bg="#6c757d", font=btn_font).grid(row=0, column=3, padx=6)
        tk.Button(btn_frame, text="Lưu Config", command=self.save_config, fg="#000000", bg="#E0E0E0", font=btn_font).grid(row=0, column=4, padx=6)
        self.btn_toggle_chrome = tk.Button(btn_frame, text="Ẩn Chrome", command=self.toggle_chrome, fg="#000000", bg="#E0E0E0", font=btn_font, width=12)
        self.btn_toggle_chrome.grid(row=0, column=5, padx=6)

        # middle: accounts checkbox area
        mid = ttk.Frame(root, padding=8)
        mid.pack(fill="both", expand=False)

        # label + select-all on same line (select-all placed near label)
        label_frame = ttk.Frame(mid)
        label_frame.pack(fill="x")
        label_frame.columnconfigure(0, weight=0)
        lbl_title = ttk.Label(label_frame, text="Danh sách tài khoản:                                 ")
        lbl_title.grid(row=0, column=0, sticky="w", padx=(2,4))
        self.select_all_var = tk.BooleanVar(value=True)
        self.updating_select_all = False
        self.select_all_chk = ttk.Checkbutton(label_frame, text="Chọn tất cả", variable=self.select_all_var, command=self.on_select_all)
        self.select_all_chk.grid(row=0, column=1, sticky="w", padx=(8,0))

        # ---- Scrollable frame ----
        scroll_frame = ttk.Frame(mid)
        scroll_frame.pack(fill="x", pady=(6,0))

        # Canvas chiều cao đủ cho 5 email, rộng vừa đủ cột checkbox
        row_height = 26  # chiều cao mỗi hàng (label + checkbox)
        num_visible = 5  # số email hiển thị
        canvas_height = num_visible * row_height
        canvas = tk.Canvas(scroll_frame, width=480, height=canvas_height, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)

        # inner frame chứa checkbox + label
        self.check_frame_inner = ttk.Frame(canvas)

        # cập nhật scrollregion khi frame thay đổi
        self.check_frame_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        # đưa check_frame_inner vào canvas
        canvas.create_window((0,0), window=self.check_frame_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # pack canvas và scrollbar sát nhau
        canvas.pack(side="left", fill="y", expand=False)
        scrollbar.pack(side="left", fill="y", padx=(0,2))  # scrollbar sát checkbox

        # --- Enable scrolling with mouse wheel when cursor is over the canvas ---
        def _on_mousewheel(event):
            if event.delta:
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            else:
                if event.num == 4:
                    canvas.yview_scroll(-1, "units")
                elif event.num == 5:
                    canvas.yview_scroll(1, "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        canvas.bind("<Button-4>", _on_mousewheel)
        canvas.bind("<Button-5>", _on_mousewheel)

        try:
            self.check_frame_inner.columnconfigure(0, weight=0)
            self.check_frame_inner.columnconfigure(1, weight=0)
        except Exception:
            pass

        # column configure inner frame
        try:
            self.check_frame_inner.columnconfigure(0, weight=0)
            self.check_frame_inner.columnconfigure(1, weight=0)
        except Exception:
            pass

        self.check_vars = []
        self.row_frames = []

        # bottom: log area
        bottom = ttk.Frame(root, padding=8)
        bottom.pack(fill="both", expand=True)
        ttk.Label(bottom, text="Log:").pack(anchor="w")
        self.log_box = scrolledtext.ScrolledText(bottom, wrap="none", height=20, font=("Consolas", 10), undo=True)

        x_scroll = tk.Scrollbar(bottom, orient="horizontal", command=self.log_box.xview)
        x_scroll.pack(side="bottom", fill="x")
        self.log_box.configure(xscrollcommand=x_scroll.set)

        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_config("red", foreground="red")
        self.log_box.tag_config("green", foreground="green")
        self.log_box.tag_config("yellow", foreground="orange")
        self.log_box.tag_config("magenta", foreground="purple")
        self.log_box.tag_config("cyan", foreground="cyan")
        self.log_box.tag_config("blue", foreground="blue")
        self.log_box.tag_config("black", foreground="black")
        self.log_box.tag_config("countdown", foreground="orange")

        self.driver_created = False
        self.load_config()

    def update_countdown(self, msg, color="yellow"):
        """Thay thế (hoặc tạo mới) một dòng đếm ngược duy nhất trong log."""
        try:
            self.log_box.configure(state="normal")
            # xóa các vùng hiện có có tag 'countdown' (nếu có)
            ranges = self.log_box.tag_ranges("countdown")
            for i in range(0, len(ranges), 2):
                self.log_box.delete(ranges[i], ranges[i+1])

            # chèn dòng mới rồi gán tag 'countdown' cho dòng vừa chèn
            self.log_box.insert("end", msg + "\n", color)
            try:
                last_line = int(self.log_box.index("end-1c").split(".")[0])
                start = f"{last_line}.0"
                end = f"{last_line}.end"
                self.log_box.tag_add("countdown", start, end)
            except Exception:
                pass

            self.log_box.see("end")
        finally:
            self.log_box.configure(state="disabled")

    def clear_countdown(self):
        """Xóa dòng đếm ngược (nếu tồn tại)."""
        try:
            self.log_box.configure(state="normal")
            ranges = self.log_box.tag_ranges("countdown")
            for i in range(0, len(ranges), 2):
                self.log_box.delete(ranges[i], ranges[i+1])
        finally:
            self.log_box.configure(state="disabled")

    def toggle_chrome(self):
        global chrome_hidden
        if driver is None:
            self.log(f"Không có chrome nào đang hoạt động.", "red")
            return
        chrome_hidden = not chrome_hidden
        hide_show_chrome(driver, hide=chrome_hidden)
        self.btn_toggle_chrome.config(text="Hiện Chrome" if chrome_hidden else "Ẩn Chrome")

    # ---------------------------
    # Config functions
    # ---------------------------
    def save_config(self):
        config = {
            "profile_name": self.profile_var.get().strip(),
            "video_folder": self.video_folder_var.get().strip(),
            "debug_port": self.port_entry.get().strip(),
            "videos_per_account": self.videos_entry.get().strip(),
            "delay_sec": self.delay_entry.get().strip()
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self.log("→ Config đã được lưu.", "green")
        except Exception as e:
            self.log(f"Lỗi lưu config: {e}", "red")

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                self.profile_var.set(config.get("profile_name", PROFILE_NAME_DEFAULT))
                self.video_folder_var.set(config.get("video_folder", video_folder_default))
                self.port_entry.delete(0, tk.END)
                self.port_entry.insert(0, str(config.get("debug_port", debug_port_default)))
                self.videos_entry.delete(0, tk.END)
                self.videos_entry.insert(0, str(config.get("videos_per_account", "0")))
                self.delay_entry.delete(0, tk.END)
                self.delay_entry.insert(0, str(config.get("delay_sec", "0")))
                self.log("→ Config được load từ file.", "blue")
            except Exception as e:
                self.log(f"Lỗi load config: {e}", "red")

    # ---------------------------
    # Thread & Logging
    # ---------------------------
    def threaded(self, fn):
        def wrapper(*args, **kwargs):
            t = threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True)
            t.start()
            return t
        return wrapper

    def log(self, msg, color="black"):
        def _insert():
            self.log_box.configure(state="normal")
            self.log_box.insert(tk.END, msg + "\n", color)
            self.log_box.see(tk.END)
            self.log_box.configure(state="disabled")
        self.root.after(0, _insert)

    # ---------------------------
    # Folder browse
    # ---------------------------
    def browse_folder(self):
        fld = filedialog.askdirectory(initialdir=self.video_folder_var.get() or os.path.expanduser("~"))
        if fld:
            self.video_folder_var.set(fld)

    # ---------------------------
    # Profile browse
    # ---------------------------
    def browse_profile(self):
        folder_path = filedialog.askdirectory(
            title="Select Selenium profile folder",
            initialdir=os.path.expanduser("~")
        )
        if folder_path:
            self.profile_var.set(folder_path)
            self.log(f"Đã chọn profile folder: {folder_path}", "green")

    # ---------------------------
    # Quit & Stop
    # ---------------------------
    def quit_chrome_only(self):
          global driver
          if driver:
               try:
                    chrome_pid = driver.service.process.pid  # pid của chromedriver
                    driver.quit()
                    driver = None
                    self.log("Chrome đã được thoát.", "green")
                    
                    # Kill các tiến trình con của chromedriver nếu còn tồn tại
                    if psutil.pid_exists(chrome_pid):
                         parent = psutil.Process(chrome_pid)
                         for child in parent.children(recursive=True):
                              try:
                                   child.kill()
                              except:
                                   pass
                         try:
                              parent.kill()
                         except:
                              pass
               except Exception as e:
                    self.log(f"Lỗi khi thoát Chrome: {e}", "red")
          else:
               self.log("Không có Chrome nào đang chạy.", "yellow")

    def quit_all(self):
        global driver
        if driver:
            try:
                driver.quit()
                driver = None
                self.log("Chrome đã được thoát.", "green")
            except Exception as e:
                self.log(f"Lỗi khi thoát Chrome: {e}", "red")
        else:
            self.log("Không có Chrome nào đang chạy, GUI sẽ đóng.", "yellow")
        self.root.quit()

    def set_stop_flag(self):
        global stop_flag
        stop_flag = True
        # self.log("→ Stop được kích hoạt, upload sẽ dừng sau video hiện tại...", "red")

    # ---------------------------
    # Select-all checkbox handling
    # ---------------------------
    def on_select_all(self):
        if self.updating_select_all:
            return
        v = self.select_all_var.get()
        self.updating_select_all = True
        for var in self.check_vars:
            var.set(v)
        self.updating_select_all = False

    def _individual_changed(self, *args):
        if self.updating_select_all:
            return
        if not self.check_vars:
            return
        all_on = all(var.get() for var in self.check_vars)
        self.updating_select_all = True
        self.select_all_var.set(all_on)
        self.updating_select_all = False

    # -------------------------
    # Load accounts: create driver, open page, click Google continue, gather email list
    # -------------------------
    def load_accounts(self):
        global driver, wait, main_window, emails, TOTP_SECRETS

        profile_name = self.profile_var.get().strip()
        if not profile_name:
            messagebox.showerror("Lỗi", "Vui lòng nhập Profile name")
            return

        self.log(f"→ Khởi tạo Chrome với profile: {profile_name}", "blue")
        selenium_profile = os.path.join(selenium_profile_base, profile_name)
        debug_port = debug_port_default
        try:
            debug_port = int(self.port_entry.get().strip())
        except Exception:
            self.log(f"Port không hợp lệ, dùng mặc định {debug_port_default}", "yellow")

        options = webdriver.ChromeOptions()
        options.add_argument(f"--user-data-dir={selenium_profile}")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--window-size=400,400")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(f"--remote-debugging-port={debug_port}")
        options.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("--log-level=3")

        chromedriver_path = ChromeDriverManager().install()

        driver = webdriver.Chrome(
            executable_path=chromedriver_path, 
            chrome_options=options,
            service_args=['--silent'],  # ẩn log chromedriver
            service_log_path='NUL'      # ẩn log trên Windows
        )

        time.sleep(1)

        def enum_windows_callback(hwnd, result):
            if win32gui.IsWindowVisible(hwnd):
               title = win32gui.GetWindowText(hwnd)
               if "chromedriver" in title.lower():
                   result.append(hwnd)
         
        windows = []
        win32gui.EnumWindows(enum_windows_callback, windows)

        if windows:
            win32gui.ShowWindow(windows[0], win32con.SW_MINIMIZE)

        self.log(f"chromedriver: {chromedriver_path}", "blue")

        wait = WebDriverWait(driver, 30)

        try:
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })
        except Exception:
            pass

        self.log("→ Mở trang upload...", "blue")
        driver.get("https://scoopzapp.com/me/upload")
        time.sleep(2)

        # click Continue with Google if present
        try:
            google_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(),'Continue with Google')]")))
            google_btn.click()
            # self.log("Đã bấm 'Continue with Google' (hãy chọn tài khoản popup nếu cần).", "green")
            time.sleep(5)
            focus_google_popup(debug_port, self)
        except Exception as e:
            self.log(f"Không tìm thấy nút 'Continue with Google': {e}", "red")

        # debug: list window handles
        handles = driver.window_handles
        # self.log(f"Window handles: {handles}", "blue")

        # switch to popup window that contains account list (if any)
        main_window = driver.current_window_handle
        popup_handle = None
        time.sleep(1)
        for handle in driver.window_handles:
            if handle != main_window:
                popup_handle = handle
                try:
                    driver.switch_to.window(handle)
                    # self.log("Đã switch sang cửa sổ popup.", "blue")
                except Exception:
                    pass
                break
        time.sleep(1)

        if not popup_handle:
                self.log("Không tìm thấy popup Google sau 5 giây.", "red")

        # get accounts from popup (try several selectors)
        emails_local = []
        try:
            emails_js = """
                let results = [];
                document.querySelectorAll('div.VV3oRb[data-identifier]').forEach(el => {
                    results.push(el.getAttribute('data-identifier'));
                });
                return results;
            """
            emails_local = driver.execute_script(emails_js)
            if not emails_local:
                emails_local = driver.execute_script("""
                    let results = [];
                    document.querySelectorAll('div[data-identifier]').forEach(el => {
                        results.push(el.getAttribute('data-identifier'));
                    });
                    return results;
                """)
            # fallback: try common element for account email text
            if not emails_local:
                emails_local = driver.execute_script("""
                    let results = [];
                    document.querySelectorAll('div[jsname]').forEach(el=>{
                        try{
                            if(el.innerText && el.innerText.includes('@')) results.push(el.innerText.trim());
                        }catch(e){}
                    });
                    return results;
                """)
        except Exception as e:
            self.log(f"Lỗi khi chạy JS lấy danh sách tài khoản: {e}", "red")
            emails_local = []

        # If still empty, try to extract from main page DOM (no popup case)
        if not emails_local:
            try:
                driver.switch_to.window(main_window)
                self.log("Không thấy popup, thử lấy email từ trang chính...", "yellow")
                # Try several selectors that might contain the signed-in email
                possible = set()
                try:
                    el = driver.find_element(By.CSS_SELECTOR, "a[href*='SignOutOptions']")
                    href = el.get_attribute("href")
                    if "Email=" in href:
                        possible.add(href.split("Email=")[-1].split("&")[0])
                except Exception:
                    pass
                try:
                    el2 = driver.find_element(By.CSS_SELECTOR, "div[aria-label*='Account']")
                    txt = el2.get_attribute("aria-label") or el2.text or ""
                    if "@" in txt:
                        possible.add(re.search(r"[\w\.-]+@[\w\.-]+", txt).group(0))
                except Exception:
                    pass
                # also try for elements containing email-like text
                try:
                    all_text = driver.find_elements(By.XPATH, "//*[contains(text(),'@')]")
                    for t in all_text[:10]:
                        txt = t.text.strip()
                        if "@" in txt:
                            m = re.search(r"[\w\.-]+@[\w\.-]+", txt)
                            if m:
                                possible.add(m.group(0))
                except Exception:
                    pass

                emails_local = list(possible)
                if emails_local:
                    self.log(f"Lấy được email từ trang chính: {emails_local}", "green")
            except Exception as e:
                self.log(f"Lỗi khi thử lấy email từ trang chính: {e}", "red")

        emails = emails_local or []

        # populate GUI checkboxes
        # clear previous check rows
        # destroy any existing children in the check_frame_inner to fully clear previous grid
        try:
            for child in self.check_frame_inner.winfo_children():
                child.destroy()
        except Exception:
            pass
        self.row_frames.clear()
        # clear vars (but keep select_all_var)
        self.check_vars.clear()

        if emails:
            cleaned = []
            for em in emails:
                # nếu chuỗi chứa dấu '|' giả sử định dạng "Tên | email" -> lấy phần sau cùng
                if "|" in em:
                    em = em.split("|")[-1].strip()
                else:
                    # nếu string có nội dung nhiều dòng (ví dụ popup text), lấy email bằng regex
                    m = re.search(r"[\w\.-]+@[\w\.-]+", em)
                    if m:
                        em = m.group(0)
                    else:
                        # nếu vẫn không có dạng email, giữ nguyên (fallback)
                        em = em.strip()

                cleaned.append(em)

            # loại bỏ trùng lặp nhưng vẫn giữ thứ tự
            unique_emails = list(dict.fromkeys(cleaned))

            # cập nhật global emails để đảm bảo mapping index chính xác
            emails = unique_emails
            globals()['emails'] = emails

            # ensure select_all_var default remains (keep current state),
            # and set each new checkbox initial value to that state
            default_state = self.select_all_var.get()

            # use grid for rows so checkbox column is aligned
            try:
                # keep both columns non-expanding so checkbox won't be pushed to far right
                self.check_frame_inner.columnconfigure(0, weight=0)
                self.check_frame_inner.columnconfigure(1, weight=0)
            except Exception:
                pass

            for i, em in enumerate(unique_emails, 1):
                row_index = i - 1
                lbl = ttk.Label(self.check_frame_inner, text=f"[{i}] {em}", anchor="w")
                lbl.grid(row=row_index, column=0, sticky="w", padx=(2,8), pady=2)

                var = tk.BooleanVar(value=default_state)
                chk = ttk.Checkbutton(self.check_frame_inner, variable=var)
                # place checkbox just to the right of the label with comfortable spacing
                chk.grid(row=row_index, column=1, sticky="w", padx=(8,4), pady=2)

                # trace changes so top checkbox updates
                try:
                    var.trace_add("write", self._individual_changed)
                except AttributeError:
                    var.trace("w", self._individual_changed)

                self.check_vars.append(var)
                self.row_frames.append((lbl, chk))

            # update top checkbox state based on individual checkboxes
            self._individual_changed()

            self.log(f"Tìm thấy {len(unique_emails)} tài khoản Google.", "green")
        else:
            self.log("Không tìm thấy tài khoản trong popup Google.", "red")

        # load TOTP secrets from profile folder if exists
        twofa_file = os.path.join(selenium_profile, "2fa.txt")
        TOTP_SECRETS.clear()
        if os.path.exists(twofa_file):
            try:
                with open(twofa_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or "|" not in line: continue
                        email, secret = line.split("|", 1)
                        TOTP_SECRETS[email.strip()] = secret.replace(" ", "")
                self.log(f"Đã load 2FA key ({len(TOTP_SECRETS)}).", "blue")
            except Exception as e:
                self.log(f"Lỗi đọc 2fa.txt: {e}", "red")

        self.driver_created = True

    def set_stop_flag(self):
        global stop_flag
        stop_flag = True
        # self.log("→ Stop được kích hoạt, upload sẽ dừng sau video hiện tại...", "red")

    # -------------------------
    # Start upload (reads GUI values, then calls run_upload)
    # -------------------------
    def start_upload(self):
        global selected_indices, videos_per_email, delay_sec, driver, wait, main_window, emails, stop_flag

        if not self.driver_created:
            messagebox.showwarning("Chưa load", "Bạn chưa bấm 'Load Accounts' để mở Chrome và lấy danh sách tài khoản.\nBấm Load Accounts trước.")
            return

        # gather selected accounts from check_vars
        if not self.check_vars:
            # fallback: if no checkboxes, select all indices
            selected_indices = list(range(1, len(emails) + 1))
            self.log("Không có checkbox, sẽ upload cho tất cả.", "yellow")
        else:
            selected_indices = [i+1 for i, var in enumerate(self.check_vars) if var.get()]
            if not selected_indices:
                self.log("Không có account được chọn — sẽ không làm gì.", "red")
                return

        # parse videos_per_email and delay
        try:
            videos_per_email = int(self.videos_entry.get().strip())
        except:
            videos_per_email = 0
        try:
            delay_sec = int(self.delay_entry.get().strip())
        except:
            delay_sec = 0

        # set video folder
        vid_folder = self.video_folder_var.get().strip()
        if not os.path.isdir(vid_folder):
            messagebox.showerror("Lỗi", f"Thư mục video không hợp lệ:\n{vid_folder}")
            return

        # reset stop flag before starting
        stop_flag = False

        self.log(f"Bắt đầu upload: {videos_per_email} video/account, delay {delay_sec}s, accounts {selected_indices}", "magenta")

        # run upload in same thread (we're already threaded wrapper), call run_upload()
        try:
            run_upload(gui=self)
        except Exception as e:
            self.log(f"Lỗi run_upload: {e}", "red")

# ---------------------------
# Helper functions converted from original code, using gui.log instead of print
# ---------------------------
def get_pid_from_port(port):
    for conn in psutil.net_connections(kind="tcp"):
        if conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
            return conn.pid
    return None

def find_hwnds_by_pid(pid):
    hwnds = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == pid:
                hwnds.append((hwnd, win32gui.GetWindowText(hwnd)))
    win32gui.EnumWindows(callback, None)
    return hwnds

def focus_google_popup(debug_port, gui):
    chrome_pid = get_pid_from_port(debug_port)
    if not chrome_pid:
        gui.log(f"Không tìm thấy Chrome chạy port {debug_port}", "red")
        return
    hwnds = find_hwnds_by_pid(chrome_pid)
    # dò các child process nếu chưa tìm thấy
    if not hwnds:
        for child in psutil.Process(chrome_pid).children(recursive=True):
            hwnds.extend(find_hwnds_by_pid(child.pid))
    for hwnd, title in hwnds:
        if "Đăng nhập - Tài khoản Google - Google Chrome" in title or "Choose an account" in title:
            try:
                win32gui.ShowWindow(hwnd, 5)  # SW_SHOW
                win32gui.SetForegroundWindow(hwnd)
                # gui.log(f"Đã focus popup Google: {title}", "blue")
                time.sleep(0.5)
            except:
                pass

def find_and_close_dialogs(chrome_hwnd):
    closed = []
    def callback(hwnd, _):
        try:
            if win32gui.GetClassName(hwnd) == "#32770":
                owner = win32gui.GetWindow(hwnd, win32con.GW_OWNER)
                if owner == chrome_hwnd:
                    title = win32gui.GetWindowText(hwnd)
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    closed.append((hwnd, title))
        except Exception:
            pass
        return True
    win32gui.EnumWindows(callback, None)
    return closed

def handle_chrome_window(debug_port: int, gui: GUIApp):
    chrome_pid = get_pid_from_port(debug_port)
    if not chrome_pid:
        gui.log(f"Không tìm thấy Chrome chạy port {debug_port}", "red")
        return
    hwnds = find_hwnds_by_pid(chrome_pid)
    if not hwnds:
        for child in psutil.Process(chrome_pid).children(recursive=True):
            hwnds.extend(find_hwnds_by_pid(child.pid))
    if hwnds:
        for hwnd, title in hwnds:
            if "Upload - Scoopz" in title:
                dialogs = find_and_close_dialogs(hwnd)

# 2FA handler adapted to GUI
def handle_2fa_gui(driver_local, email, gui: GUIApp, email_index_display=""):
    try:
        gui.log(f"→ Kiểm tra 2FA cho [{email_index_display}] {email}", "blue")
        # Chỉ tìm input[type='tel'] trong 15 giây
        otp_input = WebDriverWait(driver_local, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='tel']"))
        )
        if email in TOTP_SECRETS:
            totp = pyotp.TOTP(TOTP_SECRETS[email])
            code = totp.now()
            gui.log(f"Nhập mã 2FA cho [{email_index_display}] {email}: {code}", "yellow")
            otp_input.clear()
            otp_input.send_keys(code)
            otp_input.send_keys(u'\ue007')  # Enter
            time.sleep(5)  # đợi xử lý xong
        else:
            gui.log(f"Không có secret key TOTP cho {email}, yêu cầu nhập thủ công.", "red")
            code = simpledialog.askstring("Nhập mã 2FA", f"Nhập mã 2FA cho {email} (Google Authenticator):")
            if code:
                otp_input.clear()
                otp_input.send_keys(code)
                otp_input.send_keys(u'\ue007')
                time.sleep(5)
            else:
                gui.log("Không có mã 2FA được nhập.", "red")
    except Exception:
        gui.log(f"→ Không cần nhập 2FA hoặc lỗi popup 2FA cho [{email_index_display}] {email}", "green")
        pass

# countdown util (logs into gui)
def countdown_gui(prefix_message, seconds, gui: GUIApp, suffix_message=""):
    for remaining in range(seconds, 0, -1):
        # Dùng update_countdown thay vì log
        gui.update_countdown(f"{prefix_message} {remaining} giây {suffix_message}", "countdown")
        time.sleep(1)
    # Xóa dòng đếm ngược khi xong
    gui.clear_countdown()

# upload videos for a given account (adapted from original)
def upload_videos_for_email_gui(selected_email, email_index, driver_local, wait_local, gui: GUIApp, videos_per_email_local, delay_sec_local, debug_port_local, video_folder_path):
    global stop_flag
    gui.log(f"\n==== Bắt đầu upload video cho tài khoản: [{email_index}] {selected_email} ====\n", "magenta")
    time.sleep(1)
    uploaded_count = 0

    try:
        # try to open Upload area
        try:
            menu_btn = wait_local.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button > img[src='/static/web-app/menu.svg']")))
            driver_local.execute_script("arguments[0].click();", menu_btn)
            time.sleep(1)
        except: pass

        try:
            upload_btn = wait_local.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@href,'/me/upload') and .//span[text()='Upload']]")))
            upload_btn.click()
            wait_local.until(EC.presence_of_element_located((By.XPATH, "//div[contains(text(),'Select video')]")))
        except:
            driver_local.get("https://scoopzapp.com/me/upload")
            wait_local.until(EC.presence_of_element_located((By.XPATH, "//div[contains(text(),'Select video')]")))
    except Exception as e:
        gui.log(f"Lỗi khi vào trang upload: {e}", "red")
        return False

    # video folder
    video_folder = video_folder_path
    try:
        video_files = [os.path.join(video_folder, f) for f in os.listdir(video_folder)
                   if f.lower().endswith((".mp4",".mov",".mkv"))]
    except Exception as e:
        gui.log(f"Lỗi đọc thư mục video: {e}", "red")
        return False

    if not video_files:
        gui.log(f"Không còn video nào trong thư mục {video_folder}. Dừng tool!", "red")
        return False

    def natural_sort_key(s):
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
    video_files = sorted(video_files, key=lambda x: natural_sort_key(os.path.basename(x)))

    if videos_per_email_local != 0:
        video_files = video_files[:videos_per_email_local]

    total_videos = len(video_files)

    for idx, video_path in enumerate(video_files, 1):
        # check global stop flag before starting next video
        if stop_flag:
            #gui.log("Stop được kích hoạt → dừng upload cho account hiện tại.", "red")
            return False

        gui.log(f"[{email_index}] {selected_email} Upload video: {os.path.basename(video_path)}", "cyan")
        try:
            select_btn = wait_local.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(text(),'Select video')]")))
            select_btn.click()
            file_input = driver_local.find_element(By.CSS_SELECTOR, "input[type='file'][name='file']")
            driver_local.execute_script("arguments[0].style.display = 'block';", file_input)
        except Exception as e:
            gui.log(f"Lỗi khi bấm Select video: {e}", "red")
            return False

        for attempt in range(3):
            try:
                handle_chrome_window(debug_port_local, gui)
            except Exception:
                pass
            time.sleep(0.1)

        try:
            file_input.send_keys(video_path)
        except Exception as e:
            gui.log(f"Lỗi gửi file path vào input: {e}", "red")
            return False

        # đợi upload xong
        progress_css = "div[data-state][data-value]"
        try:
            while True:
                # allow stopping while waiting for upload
                if stop_flag:
                    #gui.log("Stop được kích hoạt trong quá trình upload → dừng.", "red")
                    return False
                try:
                    progress = driver_local.find_element(By.CSS_SELECTOR, progress_css)
                    value = int(progress.get_attribute("data-value"))
                    if value >= 100:
                        break
                    time.sleep(1)
                except:
                    # nếu không tìm thấy, chỉ sleep rồi thử lại
                    time.sleep(1)

        except Exception as e:
            gui.log(f"Lỗi khi đợi tiến trình upload: {e}", "red")

        # ==== Nhập tiêu đề video ====
        video_title = os.path.splitext(os.path.basename(video_path))[0]
        try:
            title_box = wait_local.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div.tiptap.ProseMirror[contenteditable='true']")))
            title_box.click()
            title_box.clear()
            title_box.send_keys(video_title)
        except Exception:
            gui.log("Không thể nhập tiêu đề", "red")

        time.sleep(1)

        # ====== Bấm Post ======
        success_post = False
        for attempt in range(3):
            try:
                post_btn = WebDriverWait(driver_local, 3).until(
                    EC.visibility_of_element_located((By.XPATH, "//div[contains(text(),'Post')]"))
                )
                time.sleep(0.3)
                driver_local.execute_script("arguments[0].click();", post_btn)
                time.sleep(1)

                continue_btn = WebDriverWait(driver_local, 2).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[contains(text(),'Continue upload')]"))
                )
                driver_local.execute_script("arguments[0].click();", continue_btn)
                time.sleep(1)
                success_post = True
                break
            except Exception:
                gui.log(f"[{selected_email}] Lỗi bấm Post/Continue (lần {attempt+1}/3)", "red")
                time.sleep(2)

        if not success_post:
            gui.log(f"[{selected_email}] Không thể bấm Post/Continue sau 3 lần → logout và chuyển sang tài khoản khác.", "red")
            time.sleep(2)
            return False

        # Xóa file sau khi up
        try:
            os.remove(video_path)
            uploaded_count += 1
            gui.log(f"Đã xoá file: {os.path.basename(video_path)}", "green")
            remaining_videos = len([f for f in os.listdir(video_folder) if f.lower().endswith((".mp4",".mov",".mkv"))])
            gui.log(f"Tổng upload: {uploaded_count}/{total_videos} | Video còn trong thư mục: {remaining_videos}\n", "green")
        except Exception as e:
            gui.log(f"Xoá file thất bại: {e}", "red")
            os._exit(1)

        if delay_sec_local > 0:
            countdown_gui("Chờ", delay_sec_local, gui, "trước khi upload tiếp")

    gui.log(f"==== Hoàn thành upload cho tài khoản: [{email_index}] {selected_email} ({uploaded_count}/{total_videos}) ====\n", "green")
    return True

# run_upload uses globals and GUI
def run_upload(gui: GUIApp):
    global driver, wait, main_window, emails, selected_indices, videos_per_email, delay_sec
    success_accounts = []
    failed_accounts = []

    # verify driver & emails
    if not driver:
        gui.log("Driver chưa được khởi tạo. Bấm Load Accounts trước.", "red")
        return

    if not emails:
        gui.log("Danh sách emails rỗng. Load Accounts lại.", "red")
        return

    video_folder = gui.video_folder_var.get().strip()
    debug_port = debug_port_default

    for i, idx in enumerate(selected_indices):
        try:
            selected_email = emails[idx-1]
        except Exception:
            gui.log(f"Lỗi: index {idx} vượt phạm vi danh sách emails.", "red")
            continue
        email_index = idx

        # click the email element in popup window
        try:
            # ensure we're on popup window that lists accounts
            try:
                # switch sang popup window (không phải main)
                popup_handle = None
                for handle in driver.window_handles:
                    if handle != main_window:
                        popup_handle = handle
                        driver.switch_to.window(handle)
                        break
                time.sleep(0.3)

                if popup_handle is None:
                    gui.log(f"Không tìm thấy popup Google cho email {selected_email}", "red")
                    failed_accounts.append(selected_email)
                    continue

                # tìm tất cả div chứa data-identifier hoặc text có email
                candidates = driver.find_elements(By.XPATH, "//div[@data-identifier or text()]")
                target_element = None
                for el in candidates:
                    try:
                        attr_email = el.get_attribute("data-identifier")
                        el_text = el.text.strip()
                        if selected_email == attr_email or selected_email == el_text:
                            target_element = el
                            break
                    except:
                        continue

                if target_element:
                    driver.execute_script("arguments[0].scrollIntoView(true);", target_element)
                    target_element.click()
                    gui.log(f"Đăng nhập tài khoản: [{email_index}] {selected_email}", "yellow")
                    time.sleep(2)
                else:
                    gui.log(f"Không tìm thấy element tương ứng với email {selected_email}", "red")
                    failed_accounts.append(selected_email)
                    continue

            except Exception as e:
                gui.log(f"Lỗi khi chọn email {selected_email}: {e}", "red")
                failed_accounts.append(selected_email)
                continue

        except Exception as e_outer:
            gui.log(f"Lỗi tổng thể khi chọn email {selected_email}: {e_outer}", "red")
            failed_accounts.append(selected_email)
            continue

        # handle 2FA if necessary (đặt trong try/except riêng)
        try:
            handle_2fa_gui(driver, selected_email, gui, email_index)
        except Exception as e:
            gui.log(f"Lỗi xử lý 2FA cho {selected_email}: {e}", "red")

        # switch back to main window (upload page)
        try:
            driver.switch_to.window(main_window)
        except:
            pass

        # call uploader
        res = upload_videos_for_email_gui(
            selected_email=selected_email,
            email_index=email_index,
            driver_local=driver,
            wait_local=wait,
            gui=gui,
            videos_per_email_local=videos_per_email,
            delay_sec_local=delay_sec,
            debug_port_local=debug_port,
            video_folder_path=video_folder
        )
        if res:
            success_accounts.append(f"[{email_index}] {selected_email}")
        else:
            failed_accounts.append(f"[{email_index}] {selected_email}")

        if stop_flag:
            gui.log("Stop upload → dừng tất cả sau video hiện tại.", "red")
            break

        # if not last account, logout and get popup again
        if i != len(selected_indices) - 1:
            try:
                # logout flow
                try:
                    menu_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button > img[src='/static/web-app/menu.svg']")))
                    driver.execute_script("arguments[0].click();", menu_btn)
                    time.sleep(2)
                except: pass

                try:
                    settings_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[@href='/me/settings']")))
                    driver.execute_script("arguments[0].click();", settings_btn)
                    time.sleep(2)
                except:
                    pass

                try:
                    logout_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//li/button[text()='Log out']")))
                    driver.execute_script("arguments[0].click();", logout_btn)
                    time.sleep(3)
                except:
                    pass

                # back to upload url and click continue google to get popup again
                driver.get("https://scoopzapp.com/me/upload")
                time.sleep(2)
                try:
                    google_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(),'Continue with Google')]")))
                    google_btn.click()
                except:
                    pass
                time.sleep(2)

                # find popup handle and switch
                for handle in driver.window_handles:
                    if handle != main_window:
                        driver.switch_to.window(handle)
                        break
                time.sleep(2)

            except Exception as e:
                gui.log(f"Lỗi logout/chuyển tài khoản: {e}", "red")
                continue

    gui.log(f"\n==== Upload xong {len(selected_indices)} tài khoản ====", "magenta")
    gui.log(f"Thành công ({len(success_accounts)}): {success_accounts}", "green")
    gui.log(f"Thất bại ({len(failed_accounts)}): {failed_accounts}", "red")

# ---------------------------
# Start GUI
# ---------------------------
if __name__ == "__main__":
    root = tk.Tk()
    gui = GUIApp(root)
    root.protocol("WM_DELETE_WINDOW", gui.quit_all)
    root.mainloop()



