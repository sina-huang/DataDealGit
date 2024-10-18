import threading
import websocket
import time
import queue
from settings import SLEEP_TIME
import logging
import sys
import json
from src.Utils.Log import get_logger

logger = get_logger(name=__name__, log_file='./Log/ws_sender.log')

class Sender(threading.Thread):
    def __init__(self, url, output_queue, max_retries=5):
        super().__init__()
        self.url = url
        self.output_queue = output_queue
        self.ws = None
        self.is_active = True
        self.daemon = True
        self.max_retries = max_retries
        self.retry_count = 0
        self.retry_delay = 5
        self.closed_event = threading.Event()  # 用于等待连接关闭

    def run(self):
        while self.is_active and self.retry_count < self.max_retries:
            self.closed_event.clear()  # 清除事件标志
            try:
                self.ws = websocket.WebSocketApp(
                    self.url,
                    on_open=self.on_open,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                self.ws.run_forever()
            except Exception as e:
                logger.error(f"Sender 连接失败：{e}")
            finally:
                # 等待连接完全关闭
                self.closed_event.wait()
                if not self.is_active:
                    break  # 如果已经停止，不再重连
                self.retry_count += 1
                logger.warning(f"Sender 连接失败，正在进行第 {self.retry_count} 次重连")
                time.sleep(self.retry_delay)
                self.retry_delay *= 2  # 指数退避
        logger.error(f"Sender 连接失败，已达到最大重连次数 {self.max_retries}")

    def on_open(self, ws):
        logger.info("Sender 连接已打开")
        self.retry_count = 0  # 重置重连计数
        self.retry_delay = 5  # 重置重连延迟

        def send_messages():
            while self.is_active:
                try:
                    message = self.output_queue.get(timeout=1)
                    if isinstance(message, dict):
                        message = json.dumps(message, ensure_ascii=False)
                    ws.send(message)
                    logger.info(f"Sender 发送消息：{message}")
                    self.output_queue.task_done()
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Sender 发送消息失败：{e}")
                    time.sleep(1)

        self.sender_thread = threading.Thread(target=send_messages)
        self.sender_thread.daemon = True
        self.sender_thread.start()

    def on_error(self, ws, error):
        logger.error(f"Sender 错误：{error}")

    def on_close(self, ws, close_status_code, close_msg):
        logger.error(f"Sender 连接关闭：{close_status_code} {close_msg}")
        self.closed_event.set()  # 设置事件，表示连接已关闭

    def stop(self):
        self.is_active = False
        if self.ws:
            self.ws.close()
        self.closed_event.set()  # 确保停止等待
        if hasattr(self, 'sender_thread'):
            self.sender_thread.join()
