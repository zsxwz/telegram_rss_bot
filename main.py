# rss_to_telegram_bot.py
import feedparser
import telegram
import json
import os
import time
import schedule
import logging
from telegram.error import TelegramError
# 修正 ParseMode 的导入路径
from telegram import ParseMode

# --- 配置 ---
# 从 Telegram BotFather 获取你的 Bot Token
BOT_TOKEN = "1971623038:AAFqe8A93nWCWavvMGXJ4yTmLNxQ7oGcnIY"
# 你想要推送到的频道的 ID (例如: '@your_channel_name' 或 '-1001234567890')
CHANNEL_ID = "@zsxwz"
# 你要监控的 RSS 源 URL 列表
RSS_FEED_URLS = [
    "https://bbs.zsxwz.com/index-0.htm?rss=1",
    "https://zsxwz.com/feed/",
    # 在这里添加更多 RSS 源 URL
]
# 检查 RSS 源更新的频率（分钟）
CHECK_INTERVAL_MINUTES = 1
# 用于存储已发送文章 ID 的文件路径
STATE_FILE = "sent_items.json"
# --- 配置结束 ---

# 设置日志记录
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 全局变量存储已发送项
sent_items_global = set()

def load_sent_items():
    """从文件加载已发送项的 ID 集合"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                items_list = json.load(f)
                return set(items_list)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"无法加载状态文件 {STATE_FILE}: {e}")
            return set()
    return set()

def save_sent_items(sent_items):
    """将已发送项的 ID 集合保存到文件"""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(list(sent_items), f, indent=4)
    except IOError as e:
        logger.error(f"无法保存状态文件 {STATE_FILE}: {e}")

def send_telegram_message(bot, text):
    """发送消息到指定的 Telegram 频道"""
    try:
        # 使用修正后导入的 ParseMode
        bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            parse_mode=ParseMode.HTML, # 使用 HTML 格式化消息
            disable_web_page_preview=False # 可以选择是否禁用链接预览
        )
        logger.info(f"成功发送消息到频道 {CHANNEL_ID}")
        return True
    except TelegramError as e:
        logger.error(f"发送消息到频道 {CHANNEL_ID} 时出错: {e}")
        # 可以根据错误类型决定是否重试或采取其他操作
        # 例如，如果是因为速率限制，可以等待一段时间
        if "Too Many Requests" in str(e):
            logger.warning("触发速率限制，暂停 5 秒...")
            time.sleep(5)
            # 可以选择在这里重试一次，或者让下次检查时再处理
            # return send_telegram_message(bot, text) # 小心无限递归
        return False
    except Exception as e:
        logger.error(f"发送消息时发生未知错误: {e}")
        return False

def process_single_feed(feed_url, bot, sent_items):
    """处理单个 RSS 源"""
    logger.info(f"开始检查 RSS 源: {feed_url}")
    items_sent_this_run = 0
    try:
        # 增加 User-Agent 可能会提高某些源的抓取成功率
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
        feed = feedparser.parse(feed_url, agent=headers.get('User-Agent'))
    except Exception as e:
        logger.error(f"获取或解析 RSS 源 {feed_url} 时出错: {e}")
        return 0 # 返回发送成功的条目数

    if feed.bozo:
        # feed.bozo_exception 可能包含更详细的错误信息
        bozo_msg = feed.bozo_exception if hasattr(feed, 'bozo_exception') else '未知格式问题'
        logger.warning(f"RSS 源 {feed_url} 可能格式不正确: {bozo_msg}")
        # 即使格式可能不正确，有时也能解析出部分内容，所以我们继续尝试

    if not feed.entries:
        # 检查 HTTP 状态码，如果可用
        status = feed.get('status')
        if status and (status < 200 or status >= 300):
             logger.warning(f"获取 RSS 源 {feed_url} 时返回 HTTP 状态码: {status}")
        else:
             logger.info(f"RSS 源 {feed_url} 为空或无法解析条目。")
        return 0

    # 从旧到新处理条目
    for entry in reversed(feed.entries):
        # 优先使用 guid，如果不可用或没有，则使用 link 作为唯一标识
        item_id = entry.get('id', entry.get('link'))

        if not item_id:
            logger.warning(f"源 {feed_url} 中的条目缺少 'id' 和 'link'，无法确定唯一性: {entry.get('title', '无标题')}")
            continue # 跳过没有唯一标识的条目

        if item_id not in sent_items:
            logger.info(f"发现新条目 (源: {feed_url}): {entry.title} ({item_id})")
            # 构建消息内容 (可以根据需要自定义格式)
            # 使用 html.escape 防止标题中的特殊字符破坏HTML格式
            import html
            escaped_title = html.escape(entry.title)
            message = f"<b>{escaped_title}</b>\n\n{entry.link}"
            # 可以选择性地添加来源信息
            # feed_title = feed.feed.get('title', feed_url) # 获取 RSS 源的标题
            # escaped_feed_title = html.escape(feed_title)
            # message = f"<b>{escaped_title}</b>\n<i>来源: {escaped_feed_title}</i>\n\n{entry.link}"

            if send_telegram_message(bot, message):
                sent_items.add(item_id)
                # 注意：这里直接修改了传入的 sent_items 集合
                save_sent_items(sent_items) # 每次成功发送后保存状态
                items_sent_this_run += 1
                time.sleep(1) # 在连续发送多条消息之间稍作停顿，避免触发 Telegram 的速率限制
            else:
                logger.error(f"未能发送条目 (源: {feed_url}): {entry.title}。将在下次检查时重试。")
                # 如果发送失败，则不将其添加到 sent_items，以便下次重试

    if items_sent_this_run > 0:
         logger.info(f"处理完成源 {feed_url}，发送了 {items_sent_this_run} 个新条目。")
    # else: # 不需要为没有新条目的源打印日志，check_all_feeds 会总结
    #      logger.info(f"源 {feed_url} 没有发现新条目。")

    return items_sent_this_run # 返回本次处理发送成功的条目数

def check_all_feeds():
    """检查所有配置的 RSS 源并发送新内容"""
    global sent_items_global
    logger.info("开始新一轮 RSS 源检查...")

    # 在检查开始时重新加载一次状态，以防文件在运行时被外部修改
    # sent_items_global = load_sent_items() # 可选：如果担心外部修改可以取消注释

    try:
        bot = telegram.Bot(token=BOT_TOKEN)
    except Exception as e:
        logger.error(f"初始化 Telegram Bot 时出错: {e}")
        return # 如果无法初始化 Bot，则无法继续

    total_new_items = 0

    for feed_url in RSS_FEED_URLS:
        try:
            # 将全局的 sent_items_global 传入，process_single_feed 会直接修改它
            sent_count = process_single_feed(feed_url, bot, sent_items_global)
            total_new_items += sent_count
            # 在处理不同 feed 之间也稍作停顿，特别是如果上一个 feed 发送了消息
            if sent_count > 0:
                time.sleep(2) # 稍微增加停顿时间
        except Exception as e:
            # 捕获处理单个 feed 时的意外错误
            logger.error(f"处理 RSS 源 {feed_url} 时发生未捕获的异常: {e}", exc_info=True) # exc_info=True 会记录堆栈跟踪
            # 即使一个源出错，也继续处理下一个

    if total_new_items > 0:
        logger.info(f"所有 RSS 源检查完毕，本轮共发送 {total_new_items} 个新条目。")
    else:
        logger.info("所有 RSS 源检查完毕，没有发现新条目。")


if __name__ == "__main__":
    # --- 输入检查 ---
    if BOT_TOKEN == "YOUR_BOT_TOKEN" or CHANNEL_ID == "YOUR_CHANNEL_ID":
        logger.error("请在脚本中设置 BOT_TOKEN 和 CHANNEL_ID！")
        exit(1)
    # 检查 RSS_FEED_URLS 是否为列表以及是否为空或包含示例 URL
    if not isinstance(RSS_FEED_URLS, list) or not RSS_FEED_URLS or \
       any(url.startswith("YOUR_RSS_FEED_URL") for url in RSS_FEED_URLS):
         logger.error("请在脚本的 RSS_FEED_URLS 列表中设置至少一个有效的 RSS 源 URL！")
         exit(1)
    if not isinstance(CHECK_INTERVAL_MINUTES, int) or CHECK_INTERVAL_MINUTES <= 0:
         logger.error("CHECK_INTERVAL_MINUTES 必须是一个正整数！")
         exit(1)

    logger.info("机器人启动...")

    # 加载已发送项
    sent_items_global = load_sent_items()
    logger.info(f"已加载 {len(sent_items_global)} 个已发送项的 ID。")

    # 立即执行一次检查
    logger.info("执行首次 RSS 源检查...")
    check_all_feeds()

    # 设置定时任务
    logger.info(f"设置定时任务：每 {CHECK_INTERVAL_MINUTES} 分钟检查一次所有 RSS 源。")
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_all_feeds)

    # 运行调度器
    logger.info("调度器开始运行，等待定时任务...")
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到退出信号，正在关闭...")
            break
        except Exception as e:
            logger.error(f"调度器主循环发生错误: {e}", exc_info=True)
            # 发生未知错误时，可以稍微等待一下再继续，防止快速连续失败
            time.sleep(60)

    logger.info("机器人已停止。")