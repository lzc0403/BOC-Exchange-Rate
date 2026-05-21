#!/usr/bin/env python3
"""
基础功能测试脚本
"""

import sys
import os
sys.path.append('.')

# 测试导入是否成功
try:
    from boc_scraper_v6.1 import (
        make_session, get_captcha, submit_page1,
        parse_table, parse_pageform, fetch_one_day
    )
    print("✓ 所有模块导入成功")
except Exception as e:
    print(f"✗ 导入失败: {e}")
    sys.exit(1)

# 测试环境变量读取
from dotenv import load_dotenv
load_dotenv()

required_env = ['SMTP_SERVER', 'SENDER_EMAIL', 'SENDER_PASSWORD', 'RECIPIENT_EMAIL']
missing_env = [var for var in required_env if not os.getenv(var)]

if missing_env:
    print(f"⚠ 缺少环境变量: {', '.join(missing_env)}")
    print("请使用.env文件配置邮件信息")
else:
    print("✓ 环境变量配置完整")

print("\n测试完成！")