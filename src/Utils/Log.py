# Log.py

import logging
import sys
"""
Logger: 日志记录器，可以设置日志级别，过滤器，处理器等
Handler: 日志处理器,将logger创建的日志分发到不同的目标 ，这里可以单独设置日志级别
Formatter: 日志格式化器，定义日志的输出格式
Level: 日志级别，定义了日志的输出级别，DEBUG < INFO < WARNING < ERROR < CRITICAL
"""

def get_logger(name, log_file, level=logging.INFO, console_level=logging.WARNING):
    """
    获取日志器

    :param name: 日志器名称，通常为 __name__
    :param log_file: 日志文件路径
    :param level: 文件日志记录级别，默认 INFO
    :param console_level: 控制台日志记录级别，默认 WARNING
    :return: 配置好的日志器
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 如果 logger 已经有处理器，避免重复添加
    if not logger.handlers:
        # 创建文件处理器，覆盖旧的日志内容
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s]  %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # 创建控制台处理器（可选）
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_formatter = logging.Formatter(
            ' [%(levelname)s] [%(name)s] %(message)s',

        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        # 防止日志传播到父日志器，避免重复
        logger.propagate = False

    return logger
