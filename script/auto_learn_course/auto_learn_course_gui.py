import tkinter as tk
from tkinter import ttk, messagebox
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import time
import threading
import logging
import configparser
import functools

def retry(max_attempts=3, delay=1):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(delay)
        return wrapper
    return decorator

class VideoPlayerApp:
    def __init__(self, master):
        self.master = master
        master.title("Video Player Application")
        master.geometry("400x350")

        self.setup_logging()
        self.load_config()
        self.create_widgets()
        self.driver = None

    def setup_logging(self):
        logging.basicConfig(filename='video_player.log', level=logging.INFO, 
                            format='%(asctime)s - %(levelname)s - %(message)s')

    def load_config(self):
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        self.debug_port = self.config.get('Browser', 'debug_port', fallback='9998')

    def create_widgets(self):
        ttk.Label(self.master, text="Starting Video Index:").grid(row=0, column=0, padx=5, pady=5)
        self.video_index_entry = ttk.Entry(self.master)
        self.video_index_entry.grid(row=0, column=1, padx=5, pady=5)
        self.video_index_entry.insert(0, self.config.get('Playback', 'start_index', fallback='0'))

        ttk.Label(self.master, text="Max Play Time (seconds):").grid(row=1, column=0, padx=5, pady=5)
        self.max_play_time_entry = ttk.Entry(self.master)
        self.max_play_time_entry.grid(row=1, column=1, padx=5, pady=5)
        self.max_play_time_entry.insert(0, self.config.get('Playback', 'max_play_time', fallback='2400'))

        ttk.Label(self.master, text="Popup Check Interval (seconds):").grid(row=2, column=0, padx=5, pady=5)
        self.popup_check_interval_entry = ttk.Entry(self.master)
        self.popup_check_interval_entry.grid(row=2, column=1, padx=5, pady=5)
        self.popup_check_interval_entry.insert(0, self.config.get('Playback', 'popup_check_interval', fallback='100'))

        self.start_button = ttk.Button(self.master, text="Start", command=self.start_playback)
        self.start_button.grid(row=3, column=0, columnspan=2, pady=10)

        self.status_label = ttk.Label(self.master, text="Status: Not started")
        self.status_label.grid(row=4, column=0, columnspan=2, pady=5)

        self.log_text = tk.Text(self.master, height=10, width=50)
        self.log_text.grid(row=5, column=0, columnspan=2, padx=5, pady=5)
        self.log_text.config(state=tk.DISABLED)

    def start_playback(self):
        try:
            video_index = int(self.video_index_entry.get())
            max_play_time = int(self.max_play_time_entry.get())
            popup_check_interval = int(self.popup_check_interval_entry.get())
        except ValueError:
            self.show_error("Input Error", "Please enter valid numbers for all fields.")
            return

        self.start_button.config(state="disabled")
        self.update_status("Initializing...")
        threading.Thread(target=self.run_playback, args=(video_index, max_play_time, popup_check_interval), daemon=True).start()

    def run_playback(self, video_index, max_play_time, popup_check_interval):
        try:
            self.initialize_driver()
            self.execute_initial_scripts()
            self.play_video_playlist(video_index, max_play_time, popup_check_interval)
        except Exception as e:
            self.handle_error(e)
        finally:
            if self.driver:
                self.driver.quit()
            self.start_button.config(state="normal")

    @retry(max_attempts=3, delay=2)
    def initialize_driver(self):
        options = webdriver.ChromeOptions()
        options.add_experimental_option("debuggerAddress", f"localhost:{self.debug_port}")
        options.add_argument("--disable-javascript")
        self.driver = webdriver.Chrome(options=options)
        self.driver.implicitly_wait(60)
        self.update_status("Driver initialized")

    def execute_initial_scripts(self):
        script = """
            document.oncontextmenu = null;
            document.onkeydown = null;
            document.onkeypress = null;
            document.onkeyup = null;
            window.addEventListener('keydown', function(event) {
                if (event.key === 'F12' || (event.key === 'I' && event.ctrlKey && event.shiftKey)) {
                    event.stopImmediatePropagation();
                }
            }, true);
            console.log = function(message) {
                var console = document.createElement('div');
                console.style.cssText = 'background:yellow;padding:10px;margin:10px;z-index:9999;position:absolute;';
                console.innerHTML = message;
                document.body.appendChild(console);
            };
            var video = document.querySelector('video');
            if (video) {
                video.pause = function() { console.log('视频暂停被拦截'); };
                video.play();
            } else {
                console.log('未找到视频元素');
            }
        """
        self.driver.execute_script(script)
        self.update_status("Initial scripts executed")

    def play_video_playlist(self, current_video_index, max_play_time, popup_check_interval):
        video_elements = self.driver.find_elements(By.XPATH, "//div[@class='el-step__title is-wait']")
        
        while True:
            try:
                self.play_single_video(video_elements, current_video_index, max_play_time, popup_check_interval)
                current_video_index = self.switch_to_next_video(video_elements, current_video_index)
                self.update_status(f"Switching to video {current_video_index}")
            except VideoPlayerError as e:
                self.update_status(f"Error: {str(e)}")
                break

    def play_single_video(self, video_elements, current_video_index, max_play_time, popup_check_interval):
        video_elements[current_video_index].click()
        time.sleep(3)
        self.pause_and_play()
        
        duration = self.get_video_duration()
        if duration:
            video_length = self.time_to_seconds(duration)
            current_max_play_time = min(video_length + 300, max_play_time)
        else:
            current_max_play_time = max_play_time
        
        start_time = time.time()
        last_popup_check = start_time

        while time.time() - start_time < current_max_play_time:
            if time.time() - last_popup_check >= popup_check_interval:
                self.handle_popup()
                last_popup_check = time.time()

            self.pause_and_play()
            time.sleep(10)

    def switch_to_next_video(self, video_elements, current_index):
        next_index = (current_index + 1) % len(video_elements)
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                video_elements[next_index].click()
                return next_index
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise VideoPlayerError(f"Failed to switch to next video: {str(e)}")
            time.sleep(1)

    @retry(max_attempts=3, delay=2)
    def pause_and_play(self):
        self.driver.execute_script("""
            var video = document.querySelector('video');
            if (video && video.paused) {
                video.play();
                console.log("Video resumed playing");
            }
        """)

    @retry(max_attempts=30, delay=2)
    def get_video_duration(self):
        try:
            duration_element = self.driver.find_element(By.XPATH, "//div[@class='vjs-duration vjs-time-control vjs-control']//span[@class='vjs-duration-display']")
            duration_text = duration_element.text
            if duration_text and duration_text != "0:00":
                self.update_status(f"Current video duration: {duration_text}")
                self.pause_and_play()
                return duration_text
        except Exception as e:
            self.update_status(f"Attempt to get video duration failed: {e}")
        
        return None

    def handle_popup(self):
        try:
            confirm_button = self.driver.find_element(By.XPATH, "//div[@class='el-dialog__footer']//button[@class='el-button el-button--primary']")
            confirm_button.click()
            self.update_status("Popup confirmed")
        except NoSuchElementException:
            self.update_status("Popup not found")
        except TimeoutException:
            self.update_status("Popup handling timed out")

    @staticmethod
    def time_to_seconds(time_str):
        parts = time_str.split(':')
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            raise ValueError("Invalid time format")

    def update_status(self, message):
        self.status_label.config(text=f"Status: {message}")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        logging.info(message)

    def show_error(self, title, message):
        messagebox.showerror(title, message)
        self.update_status(f"Error: {message}")

    def handle_error(self, e):
        if isinstance(e, NoSuchElementException):
            self.show_error("Error", "无法找到视频元素。请确保您在正确的页面上。")
        elif isinstance(e, TimeoutException):
            self.show_error("Error", "操作超时。请检查您的网络连接。")
        else:
            self.show_error("Error", f"发生未知错误: {str(e)}")

class VideoPlayerError(Exception):
    pass

if __name__ == "__main__":
    root = tk.Tk()
    app = VideoPlayerApp(root)
    root.mainloop()
