import threading
import websocket
import time
from src.Utils.Log import get_logger


logger = get_logger(name=__name__, log_file='./Log/ws_receiver.log')

class Receiver(threading.Thread):
    def __init__(self, url, input_queue, max_retries=5):
        super().__init__()
        self.url = url
        self.input_queue = input_queue
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
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                self.ws.run_forever()
            except Exception as e:
                logger.error(f"Receiver 连接错误：{e}")
                print(f"Receiver 连接错误：{e}")
            finally:
                # 等待连接完全关闭
                self.closed_event.wait()
                if not self.is_active:
                    break  # 如果已经停止，不再重连
                self.retry_count += 1
                logger.info(f"Receiver 将在 {self.retry_delay} 秒后重试（{self.retry_count}/{self.max_retries}）")
                # print(f"Receiver 将在 {self.retry_delay} 秒后重试（{self.retry_count}/{self.max_retries}）")
                time.sleep(self.retry_delay)
                self.retry_delay *= 2  # 指数退避
        logger.info(f"Receiver 达到最大重试次数，停止重连")


    def on_open(self, ws):
        logger.info(f"Receiver 连接成功")
        self.retry_count = 0  # 重置重连计数
        self.retry_delay = 5  # 重置重连延迟

    def on_message(self, ws, message):
        logger.info(f"Receiver 收到消息：{message}")
        self.input_queue.put(message)

    def on_error(self, ws, error):
        logger.error(f"Receiver 链接错误：{error}")
        print(f"Receiver 错误：{error}")

    def on_close(self, ws, close_status_code, close_msg):
        logger.info(f"Receiver 连接关闭：{close_status_code} {close_msg}")
        print("Receiver 连接已关闭")
        self.closed_event.set()  # 设置事件，表示连接已关闭

    def stop(self):
        self.is_active = False
        if self.ws:
            self.ws.close()
        self.closed_event.set()  # 确保停止等待
