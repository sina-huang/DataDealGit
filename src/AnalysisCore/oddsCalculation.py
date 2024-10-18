# oddsCalculation.py

from datetime import datetime
import json
import logging
import sys
from expiringdict import ExpiringDict

# 修改标准输出的编码为 UTF-8
sys.stdout.reconfigure(encoding='utf-8')  # 重新配置控制台输出为 UTF-8
# todo 创建一个日志器
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# todo 使用 FileHandler，每次运行时覆盖旧的日志内容
handler = logging.FileHandler('./LOG/03-OddsCalculation.log', mode='w', encoding='utf-8')
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

# todo 创建一个控制台处理器，确保控制台可以正确显示 Unicode 字符
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.WARNING)
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

# todo 将处理器添加到日志器
logger.addHandler(handler)
logger.addHandler(console_handler)


class OddsCalculation:
    num_calculation_Int = 0
    def __init__(self, redis_client=None, betting_queue=None):
        self.all_platforms_odds_dict = ExpiringDict(max_len=5000, max_age_seconds=4 * 3600)
        self.max_odds_dict = ExpiringDict(max_len=5000, max_age_seconds=4 * 3600)
        self.redis_client = redis_client
        self.time_differences = {}
        self.current_states = {}
        self.ws_data = {}  # 用于存储当前倒数之和小于1的比赛数据
        self.betting_queue = betting_queue

    def run(self, spider_data_dict):
        """
            all_platforms_odds_dict 的结构：
            {
                '标准比赛名1': {
                    '平台1': {
                        'home_odds': 1.8,
                        'draw_odds': 3.2,
                        'away_odds': 4.5,
                        'original_game_name': '原始比赛名1',
                        'all_info': { ... }  # 完整的数据字典
                    },
                    '平台2': {
                        'home_odds': 1.9,
                        'draw_odds': 3.1,
                        'away_odds': 4.4,
                        'original_game_name': '原始比赛名1',
                        'all_info': { ... }
                    },
                    # 更多平台的数据...
                },
                '标准比赛名2': {
                    '平台1': {
                        'home_odds': 2.0,
                        'draw_odds': 3.0,
                        'away_odds': 4.0,
                        'original_game_name': '原始比赛名2',
                        'all_info': { ... }
                    },
                    # 更多平台的数据...
                },
                # 更多标准比赛名的数据...
            }

        """

        """
        max_odds_dict 的结构：
            {
                '标准比赛名1': {
                    'home_max_odds': {
                        'odds': 1.9,
                        'from': '平台2',
                        'original_game_name': '原始比赛名1'
                    },
                    'draw_max_odds': {
                        'odds': 3.2,
                        'from': '平台1',
                        'original_game_name': '原始比赛名1'
                    },
                    'away_max_odds': {
                        'odds': 4.5,
                        'from': '平台1',
                        'original_game_name': '原始比赛名1'
                    }
                },
                '标准比赛名2': {
                    'home_max_odds': {
                        'odds': 2.0,
                        'from': '平台1',
                        'original_game_name': '原始比赛名2'
                    },
                    'draw_max_odds': {
                        'odds': 3.0,
                        'from': '平台1',
                        'original_game_name': '原始比赛名2'
                    },
                    'away_max_odds': {
                        'odds': 4.0,
                        'from': '平台1',
                        'original_game_name': '原始比赛名2'
                    }
                },
            }
        """
        logger.info(f'{"-" * 10} 第 {OddsCalculation.num_calculation_Int} 计算赔率 {"-" * 50}')
        # todo --01-- 数据清洗（将赔率转换为 float 浮点类型，并且异常情况下，将赔率统一设为 0）
        home_odds, draw_odds, away_odds = self.check_outcomes(spider_data_dict["outcomes"])

        # todo --02-- 更新 赔率汇总表,由于接收的数据是一条来自某个平台的某场比赛，所以只需要更新进去即可
        self.update_platform_odds(spider_data_dict,home_odds,draw_odds,away_odds)

        # todo --03-- 根据最新的汇总表，更新 最大赔率表
        self.update_max_odds(spider_data_dict['standardName'])

        # # todo --04-- 将最新的汇总表推送到output_queue队列中，以便后续可以ws发送出去
        # self.output_queue.put(self.all_platforms_odds_dict)

        # todo --05-- 计算（利用前面构造的两个字典） 求倒数之和
        max_odds_int = self.calculate_inverse_sum(spider_data_dict['standardName'])

        # todo --06-- 如果 倒数之和小于 1时，需要注册一下，等大于1时，再计算持续时间
        if max_odds_int < 1:
            current_time = datetime.now()
            # 小于1时，登记。
            self.current_states[spider_data_dict['standardName']] = {
                'start_time': current_time,
                'start_value': max_odds_int
            }
        else:
            # 大于1时，判断是否已经登记过，如果登记过，则计算持续时间，如果没登记过，直接pass。
            self.calculate_time(spider_data_dict['standardName'], max_odds_int)

        # todo --07-- 计算次数+1
        OddsCalculation.num_calculation_Int += 1
        return self.all_platforms_odds_dict, self.max_odds_dict

    def check_outcomes(self, outcomes):
        if len(outcomes) == 3:
            try:
                home_odds = float(list(outcomes[0].values())[0])
                draw_odds = float(list(outcomes[1].values())[0])
                away_odds = float(list(outcomes[2].values())[0])
                logger.info("--01--:数据清洗，赔率转换为 float 浮点类型")
            except (IndexError, ValueError, TypeError) as e:
                logger.error(f"--01--:数据清洗，{outcomes}，提取赔率时发生错误：{e},将所有赔率设为0")
                home_odds, draw_odds, away_odds = 0, 0, 0
        else:
            home_odds, draw_odds, away_odds = 0, 0, 0
            logger.error(f"--01--:数据清洗，{outcomes},赔率格式不正确，长度为 {len(outcomes)}，将所有赔率设为0")
        return home_odds, draw_odds, away_odds

    def update_platform_odds(self,  spider_data_dict,home_odds, draw_odds, away_odds):
        standard_name = spider_data_dict['standardName']
        platform = spider_data_dict['Platform']
        original_game_name = spider_data_dict.get('gameName', '未知比赛名')

        if standard_name not in self.all_platforms_odds_dict:
            logger.info(f"--02--汇总表更新--情况1--新建一个键值对，添加第一层健，{standard_name}")
            self.all_platforms_odds_dict[standard_name] = {}

        self.all_platforms_odds_dict[standard_name][platform] = {
            'home_odds': home_odds,
            'draw_odds': draw_odds,
            'away_odds': away_odds,
            'original_game_name': original_game_name,
            'spider_data_dict': spider_data_dict  # 包含完整信息
        }
        logger.info(f"--02--汇总表更新--情况2--已存在该比赛名，数据更新成功！！：标准比赛名{standard_name}下，平台{platform}的数据已更新")

    def update_max_odds(self, standard_name):
        if standard_name not in self.all_platforms_odds_dict:
            logger.info(f"计算最大赔率时，数据中没有找到对应的键： '{standard_name}'")
            return

        match_odds = self.all_platforms_odds_dict[standard_name]


            # 继续执行，更新 self.max_odds_dict

        max_home_odds = {'odds': 0, 'from': None, 'original_game_name': None}
        max_draw_odds = {'odds': 0, 'from': None, 'original_game_name': None}
        max_away_odds = {'odds': 0, 'from': None, 'original_game_name': None}

        for platform, game_info_dict in match_odds.items():
            if game_info_dict['home_odds'] >= max_home_odds['odds']:
                max_home_odds = {
                    'odds': game_info_dict['home_odds'],
                    'from': platform,
                    'original_game_name': game_info_dict['original_game_name']
                }
            if game_info_dict['draw_odds'] >= max_draw_odds['odds']:
                max_draw_odds = {
                    'odds': game_info_dict['draw_odds'],
                    'from': platform,
                    'original_game_name': game_info_dict['original_game_name']
                }
            if game_info_dict['away_odds'] >= max_away_odds['odds']:
                max_away_odds = {
                    'odds': game_info_dict['away_odds'],
                    'from': platform,
                    'original_game_name': game_info_dict['original_game_name']
                }

        self.max_odds_dict[standard_name] = {
            'home_max_odds': max_home_odds,
            'draw_max_odds': max_draw_odds,
            'away_max_odds': max_away_odds
        }
        logger.info(f"--03--赔率表更新完毕，更新项为：{self.max_odds_dict[standard_name]}")

    def calculate_inverse_sum(self,standard_name):
        max_home_odds = self.max_odds_dict[standard_name]['home_max_odds']['odds'] if self.max_odds_dict[standard_name]['home_max_odds']['odds'] > 0 else float('inf')
        max_draw_odds = self.max_odds_dict[standard_name]['draw_max_odds']['odds'] if self.max_odds_dict[standard_name]['draw_max_odds']['odds'] > 0 else float('inf')
        max_away_odds = self.max_odds_dict[standard_name]['away_max_odds']['odds'] if self.max_odds_dict[standard_name]['away_max_odds']['odds'] > 0 else float('inf')
        inverse_sum = 1 / max_home_odds + 1 / max_draw_odds + 1 / max_away_odds
        logger.info(f"--04--计算赔率倒数和值，当前比赛 [{standard_name}] 的倒数之和为：{inverse_sum:.4f},具体数据如下")
        logger.info(f"主场最大赔率：{self.max_odds_dict[standard_name]['home_max_odds']['odds']},来自：{self.max_odds_dict[standard_name]['home_max_odds']['from']} 平台")
        logger.info(f"平局最大赔率：{self.max_odds_dict[standard_name]['draw_max_odds']['odds']}，来自：{self.max_odds_dict[standard_name]['draw_max_odds']['from']} 平台")
        logger.info(f"客场最大赔率：{self.max_odds_dict[standard_name]['away_max_odds']['odds']}，来自：{self.max_odds_dict[standard_name]['away_max_odds']['from']} 平台")
        return inverse_sum

    def calculate_time(self, standard_name, inverse_sum):
        # todo 只有曾经小于1，之后又大于1才会执行。
        if standard_name in self.current_states:
            current_time = datetime.now()
            start_data = self.current_states.pop(standard_name)
            start_time = start_data['start_time']
            start_value = start_data['start_value']
            duration = (current_time - start_time).total_seconds()
            if standard_name not in self.time_differences:
                self.time_differences[standard_name] = []
            self.time_differences[standard_name].append({
                'start_time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                'end_time': current_time.strftime('%Y-%m-%d %H:%M:%S'),
                'duration': duration,
                'start_value': start_value,
                'end_value': inverse_sum
            })
            logger.warning(f"倒数恢复到大于1，持续时间：{duration} 秒，当时出现机会时值为：{inverse_sum}")


    def calculate_duration_below_one(self, standard_name, inverse_sum):
        current_time = datetime.now()

        if inverse_sum < 1 and inverse_sum != 0:
            if standard_name not in self.current_states:
                self.current_states[standard_name] = {
                    'start_time': current_time,
                    'start_value': inverse_sum
                }
        else:
            if standard_name in self.current_states:
                start_data = self.current_states.pop(standard_name)
                start_time = start_data['start_time']
                start_value = start_data['start_value']
                duration = (current_time - start_time).total_seconds()

                # 更新需要发送的数据，添加 overtime 和 持续时间，并写入 Redis
                self.update_ws_data(standard_name, inverse_sum, current_time, overtime=current_time, duration=duration)
                self.store_data_in_redis(standard_name, current_time, duration)

                # 从内存中清除相应的数据
                if standard_name in self.ws_data:
                    del self.ws_data[standard_name]

                if standard_name not in self.time_differences:
                    self.time_differences[standard_name] = []
                self.time_differences[standard_name].append({
                    'start_time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'end_time': current_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'duration': duration,
                    'start_value': start_value,
                    'end_value': inverse_sum
                })
                print(f"[{standard_name}] 倒数之和恢复到大于等于 1，结束时间：{current_time}, 持续时间：{duration} 秒")
            else:
                # 如果 standard_name 不在 self.current_states 中，什么也不做
                pass

    def update_ws_data(self, standard_name, inverse_sum, current_time, overtime=None, duration=None):
        if standard_name not in self.ws_data:
            self.ws_data[standard_name] = {}

        # 更新 'home_max_odds'，确保包含 'gameName'。
        self.ws_data[standard_name].update({
            'home_max_odds': self.max_odds_dict[standard_name]['home_max_odds'],
            'draw_max_odds': self.max_odds_dict[standard_name]['draw_max_odds'],
            'away_max_odds': self.max_odds_dict[standard_name]['away_max_odds'],
            'inverse_sum': inverse_sum
        })

        # 添加对 self.current_states 的检查
        if standard_name in self.current_states:
            self.ws_data[standard_name]['starttime'] = self.current_states[standard_name]['start_time'].strftime(
                '%Y-%m-%d %H:%M:%S')
        else:
            # 处理不存在的情况，可以设置为 None 或 current_time，视情况而定
            self.ws_data[standard_name]['starttime'] = current_time.strftime('%Y-%m-%d %H:%M:%S')
            print(f"警告：{standard_name} 不在 current_states 中，starttime 使用 current_time")

        if overtime and duration:
            self.ws_data[standard_name]['overtime'] = overtime.strftime('%Y-%m-%d %H:%M:%S')
            self.ws_data[standard_name]['持续时间'] = duration

    def send_ws_message(self):
        if self.betting_queue:
            try:
                data_to_send = json.dumps(self.ws_data, ensure_ascii=False)
                self.betting_queue.put(data_to_send)
                print(f"已发送 WebSocket 消息：{data_to_send}")
            except Exception as e:
                print(f"发送 WebSocket 消息时发生错误：{e}")
        else:
            print(f"需要发送的 WebSocket 消息：{self.ws_data}")

    def store_data_in_redis(self, standard_name, current_time, duration):
        if self.redis_client:
            try:
                key = "odds_data"  # 统一存储在一个 zset 中
                score = current_time.timestamp()
                data = {standard_name: self.ws_data[standard_name]}
                self.redis_client.zadd(key, {json.dumps(data, ensure_ascii=False): score})
                print(f"数据已写入 Redis zset，键：{key}")
            except Exception as e:
                print(f"写入 Redis 时发生错误：{e}")
        else:
            print("Redis 客户端未初始化，无法写入数据")
