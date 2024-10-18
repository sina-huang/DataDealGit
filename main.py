# WebSocketProcessControl.py

import json
import time
import queue
import threading
import redis
from settings import REDIS, GPT_API_KEY, URL, GPT_DESC,GPT01_mini
from src.AnalysisCore.dataDeduplication import DataDeduplication
from src.AnalysisCore.standardNameSetting import StandardNameSetting
from src.AnalysisCore.oddsCalculation import OddsCalculation
from src.WS.WS_Receiver import Receiver
from src.WS.WS_Sender import Sender
from src.WS.WS_Betting import Betting


from src.Utils.Log import get_logger


logger = get_logger(name=__name__, log_file='./Log/main.log')



class WebSocketProcessControl:
    def __init__(self, receive_url, sender_url, ws_alert_url, GPT_DESC, GPT_API_KEY,GPT_MODEL):
        self.url_receive_Str = receive_url
        self.url_sender_Str = sender_url
        self.ws_alert_url = ws_alert_url
        self.input_queue = queue.Queue()
        self.output_queue = queue.Queue()
        self.betting_queue = queue.Queue()
        self.r_Obj = redis.Redis(host=REDIS["host"], port=REDIS["port"], db=0, decode_responses=True)
        self.num_dedup_data_Int = 0
        self.num_new_data_Int = 0
        self.num_error_data_Int = 0
        self.num_gpt_ask_count_Int = 0
        self.GPT_StandardName_List = []
        self.GPT_DESC = GPT_DESC
        self.GPT_API_KEY = GPT_API_KEY
        self.num_Process_Int = 0

        # todo 注册1-- DataDeduplication 实例
        self.dedup = DataDeduplication(self.r_Obj)

        # todo 注册2-- StandardNameSetting 实例
        self.standard_name_setter = StandardNameSetting(
            redis_client=self.r_Obj,
            standard_name_list=self.GPT_StandardName_List,
            gpt_desc=self.GPT_DESC,
            openrouter_api_key=self.GPT_API_KEY,
            model=GPT_MODEL
        )

        # todo 注册3-- OddsCalculation 实例
        self.odds_calculator = OddsCalculation(
            redis_client=self.r_Obj,
            betting_queue=self.betting_queue
        )

        # todo Receiver--开启线程（ws接收者）
        self.receiver_obj = Receiver(url=self.url_receive_Str, input_queue=self.input_queue)
        self.receiver_obj.start()
        logger.warning("主进程中---启动接收者线程！")

        # todo Sender--开启线程（ws发送者）
        self.sender_obj = Sender(url=self.url_sender_Str, output_queue=self.output_queue)
        self.sender_obj.start()
        logger.warning("主进程中---启动发送者线程！")

        # todo Betting--开启线程（ws下单者）
        self.ws_sender = Betting(self.ws_alert_url, self.betting_queue)
        self.ws_sender.start()
        logger.warning("主进程中---启动下单者线程！")


        # todo Processor--开启线程（process处理者），程序正真开始执行
        self.processor_thread = threading.Thread(target=self.process_data, daemon=True)
        self.processor_thread.start()

    def process_data(self):
        def message_str_to_dict(message_str):
            try:
                message_dict = json.loads(message_str)
                if 'message' in message_dict:
                    data_str = message_dict['message']
                    if isinstance(data_str, str):
                        data_dict = json.loads(data_str)
                    elif isinstance(data_str, dict):
                        data_dict = data_str
                    else:
                        print("message 字段格式不正确")
                        self.num_error_data_Int += 1
                        return None
                else:
                    print("缺少 message 字段")
                    self.num_error_data_Int += 1
                    return None
                return {"message": data_dict}
            except json.JSONDecodeError as e:
                print("JSON 解析错误：", e)
                self.num_error_data_Int += 1
                return None



        while True:
            if self.num_Process_Int ==0:
                logger.warning("主进程中---启动处理者线程，开启Input_Queue监听程序！")
            # todo --01--从input_queue队列中提取数据，并解析
            try:
                message_str = self.input_queue.get(timeout=1)
            except queue.Empty:
                continue  # 队列为空，等待新的数据
            spider_data_dict = message_str_to_dict(message_str)
            if spider_data_dict is None:
                self.input_queue.task_done()
                continue

            # todo --02-- 去重 返回：新数据返回原始数据，重复、错误数据返None
            spider_data_dict = self.dedup.run(spider_data_dict["message"])  # 修改这里
            self.num_error_data_Int = DataDeduplication.num_error_data_Int
            self.num_dedup_data_Int = DataDeduplication.num_dedup_data_Int
            self.num_new_data_Int = DataDeduplication.num_new_data_Int
            if self.num_dedup_data_Int % 100 == 0:
                logger.info("主进程中---去重数据量：{}".format(self.num_dedup_data_Int))
            if not spider_data_dict:
                continue

            # todo --03-- 标准名称设置
            spider_data_with_standard_dict = self.standard_name_setter.run(spider_data_dict)
            if "standardName" not in spider_data_dict:
                continue

            # todo --04-- 赔率计算
            Summary_dict, odds_dict = self.odds_calculator.run(spider_data_with_standard_dict)

            # todo --05-- 将处理完的数据放入output_queue 和 betting_queue 队列
            put_data_dict = {
                "message": spider_data_dict,
                "total_data": Summary_dict,
                "max_odds": odds_dict,
                "dupdata_num": self.num_dedup_data_Int,
                "newdata_num": self.num_new_data_Int,
                "error_num": self.num_error_data_Int,
                "gptask": self.num_gpt_ask_count_Int,
                "input_queue": self.input_queue.qsize(),
                "processed_queue": self.output_queue.qsize(),
            }
            self.output_queue.put(put_data_dict)

            # todo --06-- 将处理完的数据放入 betting_queue 队列
            self.betting_queue.put(odds_dict[spider_data_with_standard_dict['standardName']])

            # todo --07-- 计数
            self.num_Process_Int += 1
            self.num_gpt_ask_count_Int = StandardNameSetting.gpt_ask_count
            self.input_queue.task_done()
        else:
            self.num_error_data_Int += 1






    def stop(self):
        # self.receiver_obj.stop()
        # self.sender_obj.stop()
        # self.ws_sender_thread.stop()
        # self.ws_sender_thread.join()
        pass

if __name__ == "__main__":
    controller = WebSocketProcessControl(
        receive_url=URL["receiverURL"],
        sender_url=URL["senderURL"],
        GPT_DESC=GPT_DESC,
        GPT_API_KEY=GPT_API_KEY,
        GPT_MODEL=GPT01_mini,
        ws_alert_url=URL["alertURL"],

    )

    try:
        while True:
            time.sleep(1)  # 保持主线程活动
    except KeyboardInterrupt:
        controller.stop()
        print("程序结束")
