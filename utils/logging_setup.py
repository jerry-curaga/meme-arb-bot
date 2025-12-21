"""
Logging configuration for the trading bot
"""
import logging


def setup_file_loggers():
    """Setup separate file loggers for orders, trades, and bot activity"""
    import datetime

    # Orders logger
    orders_logger = logging.getLogger('orders')
    orders_handler = logging.FileHandler('orders.log', mode='a')
    orders_formatter = logging.Formatter('%(asctime)s | %(message)s')
    orders_handler.setFormatter(orders_formatter)
    orders_logger.addHandler(orders_handler)
    orders_logger.setLevel(logging.INFO)
    orders_logger.propagate = False

    # Trades logger
    trades_logger = logging.getLogger('trades')
    trades_handler = logging.FileHandler('trades.log', mode='a')
    trades_formatter = logging.Formatter('%(asctime)s | %(message)s')
    trades_handler.setFormatter(trades_formatter)
    trades_logger.addHandler(trades_handler)
    trades_logger.setLevel(logging.INFO)
    trades_logger.propagate = False

    # Activity logger (main log with all actions)
    bot_logger = logging.getLogger('bot_activity')
    bot_handler = logging.FileHandler('activity.log', mode='a')
    bot_formatter = logging.Formatter('%(asctime)s | %(message)s')
    bot_handler.setFormatter(bot_formatter)
    bot_logger.addHandler(bot_handler)
    bot_logger.setLevel(logging.INFO)
    bot_logger.propagate = False

    return orders_logger, trades_logger, bot_logger


# Initialize loggers
orders_logger, trades_logger, bot_logger = setup_file_loggers()
