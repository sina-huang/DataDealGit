import threading
import websocket
import time
import json
import queue
from src.Utils.Log import get_logger


logger = get_logger(name=__name__, log_file='./Log/ws_receiver.log')

class Betting(threading.Thread):
    def __init__(self, url, ws_queue):
        super().__init__()
        self.url = url
        self.ws_queue = ws_queue
        self.ws = None
        self.running = True
        self.connected = False

    def run(self):
        while self.running:
            self.connected = False
            try:
                self.ws = websocket.WebSocketApp(
                    self.url,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                self.ws.run_forever()
            except Exception as e:
                logger.error(f"连接到 {self.url} 时发生错误：{e}")
            time.sleep(5)  # 等待一段时间后重连

    def on_open(self, ws):
        self.connected = True
        logger.info("Betting下单者--连接已打开")
        # print("Betting下单者--连接已打开")

    def on_message(self, ws, message):
        # print("WSSender 收到消息：", message)
        # logger.info(f"Betting下单者 收到消息：{message}")
        pass

    def on_error(self, ws, error):

        logger.error(f"Betting下单者 发生错误：{error}")

    def on_close(self, ws, close_status_code, close_msg):
        self.connected = False
        logger.info("Betting下单者--连接已关闭")

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

    def send_messages(self):
        while self.running:
            if self.connected and self.ws:
                try:
                    message = self.ws_queue.get(timeout=1)
                    if isinstance(message, dict):
                        message = json.dumps(message, ensure_ascii=False)
                    self.ws.send(message)
                    logger.info(f"Betting下单者 发送消息：{message}")
                    self.ws_queue.task_done()
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"发送消息时发生错误：{e}")
            else:
                time.sleep(1)  # 如果未连接，等待一段时间

    def start(self):
        super().start()
        threading.Thread(target=self.send_messages, daemon=True).start()
