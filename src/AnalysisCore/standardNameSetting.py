# standardNameSetting.py

import json
import requests
import redis
import logging
import sys

# 修改标准输出的编码为 UTF-8
sys.stdout.reconfigure(encoding='utf-8')  # 重新配置控制台输出为 UTF-8
# todo 创建一个日志器
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# todo 使用 FileHandler，每次运行时覆盖旧的日志内容
handler = logging.FileHandler('./LOG/02-StandardNameSetting.log', mode='w', encoding='utf-8')
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

# todo 创建一个控制台处理器，确保控制台可以正确显示 Unicode 字符
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.WARNING)
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

# todo 将处理器添加到日志器
logger.addHandler(handler)
logger.addHandler(console_handler)

class StandardNameSetting:
    gpt_ask_count = 0  # 类变量，所有实例共享
    check_count = 0  # 类变量，所有实例共享

    def __init__(self, redis_client, standard_name_list, gpt_desc, openrouter_api_key, model="openai/gpt-4-turbo"):
        self.redis = redis_client
        self.standard_name_list = standard_name_list
        self.gpt_desc = gpt_desc
        self.api_key = openrouter_api_key
        self.model = model

    def run(self, data):
        """
        执行标准名称设置的主流程。
        :param data: 待处理的数据字典，爬虫字典
        :return: 处理后的数据字典，添加了标准名称 或 None
        """

        logger.info(f'{"-" * 10} 第 {StandardNameSetting.check_count} 次判断数据 {"-" * 50}')
        game_name_str = data['teams']['hometeam'] + " -- " + data['teams']['awayteam']
        game_name_add_league = f"{game_name_str} -- {data['leagueName'].strip()}"
        hash_key = f"hash:{game_name_str}"  # todo 更新 hash_key

        # todo --0-- 初始化
        if not self.standard_name_list:
            logger.info(f"标准名称列表为空，需要初始化。{data}")
            self.add_new_standard_name(data, game_name_add_league, hash_key)
            StandardNameSetting.check_count += 1  # todo 增加类变量
            logger.info(f'第 {StandardNameSetting.check_count} 次判断数据完成。')
            return data

        # todo --01-- 检查 Redis 中是否已挂载标准名称
        standard_name = self.get_standard_name_from_redis(hash_key)
        if standard_name:
            data["standardName"] = standard_name
            StandardNameSetting.check_count += 1  # todo 增加类变量
            logger.info(f'第 {StandardNameSetting.check_count} 次判断数据完成。')
            return data
        logger.info("Redis匹配失败,说明是新的比赛名称，需要请求 GPT。")
        StandardNameSetting.gpt_ask_count += 1
        logger.info(f"-------第 {StandardNameSetting.gpt_ask_count} 次GPT请求开始：")
        # todo --02-- 不在 Redis 中，说明是新比赛，需要调用 GPT
        gpt_response_content_dict = self.request_gpt(data, game_name_add_league)

        # todo --03-- 检查 GPT 匹配结果
        if gpt_response_content_dict:
            logger.warning(f"GPT 响应内容为：{gpt_response_content_dict.get('matchResult', '')}")
            self.process_gpt_response(data, hash_key, gpt_response_content_dict, game_name_add_league)
        else:
            logger.warning("请求GPT，但响应内容有问题，请查看！可能会消耗不必要的流量。")
            data["standardName"] = data['gameName']
        logger.info(f'第 {StandardNameSetting.gpt_ask_count} 次请求 GPT 完成。')
        return data

    def get_standard_name_from_redis(self, hash_key):
        """
        从 Redis 中获取标准名称。
        :param hash_key: Redis 中的键
        :return: 标准名称或 None
        """
        try:
            standard_name = self.redis.get(hash_key)
            if standard_name:
                logger.info("Redis匹配成功！！")
                logger.info(f"从 Redis 获取标准名称：{hash_key}，值为：{standard_name}")
                if isinstance(standard_name, bytes):
                    return standard_name.decode('utf-8')  # 如果是 bytes，解码为字符串
                return standard_name  # 如果已经是 str 类型，直接返回
            return None
        except Exception as e:
            logger.exception(f"从 Redis 获取标准名称时发生错误：{str(e)}")
            return None

    def add_new_standard_name(self, data, game_name_add_league, hash_key):
        """
        将新的比赛名称添加到标准名称列表和 Redis 中。
        """
        # todo 插入新的标准名称，并保持列表长度不超过 100
        self.standard_name_list.insert(0, game_name_add_league)
        self.standard_name_list = self.standard_name_list[:100]
        self.redis.set(hash_key, data['gameName'])
        self.redis.expire(hash_key, 3600 * 4)
        data["standardName"] = data['gameName']
        # todo 记录日志
        self.log_standard_name(data,game_name_add_league )


    def request_gpt(self, data, game_name_add_league):
        """
        向 GPT 发送匹配请求。
        :param data: 待处理的数据字典
        :param game_name_add_league: 完整的比赛名称（比赛名 + 联赛名）
        :return: GPT 响应的内容字典或 None
        """
        platform_data = {
            "Platform": data['Platform'],
            "gameName": data['gameName'],
            "leagueName": data['leagueName'],
            "gameNameAddLeague": game_name_add_league
        }
        # todo 构造 GPT 描述
        desc = self.gpt_desc.format(
            standard_list=json.dumps(self.standard_name_list, ensure_ascii=False),
            platform_data=json.dumps(platform_data, ensure_ascii=False)
        )
        self.log_request(platform_data)  # todo 记录GPT请求数据

        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": desc}],
                },
                timeout=10  # todo 设置请求超时时间，避免长时间等待
            )
            if response.status_code == 200:
                # todo 特别说明：这里因为是间接访问GPT，所以需要先判断返回结果
                # todo 这里拿到的是我自己要求GPT的返回格式
                return self.parse_gpt_response(response)
            else:
                logger.error(f"GPT 请求失败，状态码：{response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            logger.exception(f"GPT 请求发生异常：{str(e)}")
            return None

    def parse_gpt_response(self, response):
        """
        解析 GPT 的响应内容。
        :param response: GPT 的原始响应对象
        :return: 解析后的内容字典或 None
        """
        try:
            response_json = response.json()
            choices = response_json.get('choices', [])
            if not choices:
                logger.error("GPT 响应中没有 choices 字段")
                return None
            message = choices[0].get('message', {})
            content = message.get('content', '').strip()
            if content:
                content = content.replace('```json', '').replace('```', '').strip()
                content_dict = json.loads(content)
                if 'matchResult' in content_dict:
                    # logger.info(f"GPT 响应内容：{content_dict}")
                    return content_dict
                else:
                    logger.error(f"GPT 响应内容缺少 matchResult 字段{content_dict}")
                    return None
            else:
                logger.error(f"GPT 响应内容为空{response.text}")
                return None
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"解析 GPT 响应时发生错误：{str(e)}")
            logger.error(f"GPT 响应内容：{response.text}")
            return None

    def process_gpt_response(self, data, hash_key, gpt_response_content_dict, game_name_add_league):
        """
        处理 GPT 的响应内容，更新数据和 Redis。
        :param data: 待处理的数据字典
        :param hash_key: Redis 中的键
        :param gpt_response_content_dict: GPT 响应内容字典
        :param game_name_add_league: 完整的比赛名称（比赛名 + 联赛名）
        """
        match_result = gpt_response_content_dict.get("matchResult", "")
        if 'success' in match_result.lower():
            # todo GPT 匹配成功，说明是老比赛，更新 Redis
            logger.info(f"GPT 匹配成功,说明是老比赛，但平台{data['Platform']}中的名称不一样")
            standard_name = gpt_response_content_dict.get("successData", {}).get("matchName", "")
            self.redis.set(hash_key, standard_name)
            self.redis.expire(hash_key, 3600 * 4)
            logger.info("添加一条数据到redis中")
            logger.info(f"标准比赛名：{standard_name}")
            logger.info(f"平台比赛名：{data['gameName']}")
            logger.info("由于是老比赛，无需添加到standard_name_list中")
            data["standardName"] = standard_name
        else:
            # todo GPT 匹配失败，视为新比赛
            self.add_new_standard_name(data, game_name_add_league, hash_key)

    def log_request(self, platform_data):
        # todo 记录请求的相关信息
        logger.info(f"目前标准数据列表中一共有：{len(self.standard_name_list)}条数据")
        logger.info(f"GPT请求发送数据中的标准数据：{self.standard_name_list}")
        logger.info(f"GPT请求发送数据中的需核对数据：{platform_data}")


    def log_gpt_response(self, gpt_response_content_dict):
        # todo 记录GPT的响应内容
        logger.info(f"GPT 响应内容：{gpt_response_content_dict}")


    def log_standard_name(self, data ,game_name_add_league):
        # todo 记录标准名称和平台名称
        logger.info("添加一条数据到redis，内容如下：")
        logger.info(f"标准比赛名：{data['gameName']}")
        logger.info(f"平台比赛名：{data['gameName']}")
        logger.info("添加一条数据到standard_name_list标准列表中，内容如下：")
        logger.info(f"所添加的名称为：{game_name_add_league}")