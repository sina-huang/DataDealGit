# dataDeduplication.py

import json
import hashlib
import logging
import sys
# todo 创建一个日志器
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# todo 使用 FileHandler，每次运行时覆盖旧的日志内容
handler = logging.FileHandler('./LOG/01-DataDeduplication.log', mode='w', encoding='utf-8')
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)

# todo 创建一个控制台处理器，确保控制台可以正确显示 Unicode 字符
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

# todo 将处理器添加到日志器
logger.addHandler(handler)
logger.addHandler(console_handler)

class DataDeduplication:
    num_dedup_data_Int = 0
    num_new_data_Int = 0
    num_error_data_Int = 0
    def __init__(self, redis_client):
        self.redis = redis_client

    def run(self, message_dict):
        """
        执行数据去重的主流程。
        :param message_dict: 已解析的消息字典
        :return: 'new data'，'duplicate data' 或 'invalid data'
        """
        try:
            # 检查必需的字段
            required_fields = ['Platform', 'gameName', 'leagueName', 'outcomes']
            if not all(field in message_dict for field in required_fields):
                logger.error(f"判断为错误数据，缺少必需字段: {message_dict}")
                DataDeduplication.num_error_data_Int += 1
                return None

            # 计算数据的哈希值
            message_string = json.dumps(message_dict, sort_keys=True)
            message_sha256 = hashlib.sha256(message_string.encode('utf-8')).hexdigest()

            # 设置 Redis 键名，区分不同的比赛
            list_key = f"list:{message_dict['Platform']}:{message_dict['gameName']}"

            # 获取列表中最新的数据项（列表的最左边的第一个元素）
            latest_item_hash = self.redis.lindex(list_key, 0)

            # 检查是否为重复数据
            if latest_item_hash and latest_item_hash == message_sha256:
                DataDeduplication.num_dedup_data_Int += 1
                if DataDeduplication.num_dedup_data_Int % 100 == 0:
                    logger.info(f"判定为重复数据{DataDeduplication.num_dedup_data_Int}")
                return None
            else:
                # 添加到列表中，并保持列表长度为最多 999 个元素
                logger.warning(f"去重环节判断为新数据: 来自{message_dict['Platform']}，比赛名为{message_dict['gameName']}，联赛名为{message_dict['leagueName']}，胜平负为{message_dict['outcomes']}")
                self.redis.lpush(list_key, message_sha256)
                self.redis.ltrim(list_key, 0, 999)  # 保持列表长度为 999
                DataDeduplication.num_new_data_Int += 1
                return message_dict

        except Exception as e:
            logger.error(f"判断为错误数据，数据去重过程中发生错误: {e}")
            DataDeduplication.num_error_data_Int += 1
            return None
