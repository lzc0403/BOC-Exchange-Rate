#!/usr/bin/env python3
"""
中国银行美元现汇买入价获取工具
数据源: https://www.boc.cn/sourcedb/whpj/ (当前牌价, 无需验证码)
       https://srh.bankofchina.com/search/whpj/search_cn.jsp (历史查询, 需验证码)
"""

import os
import datetime
import requests
from bs4 import BeautifulSoup
import pandas as pd

CSV_FILE = "data.csv"


def fetch_current_rate():
    """
    获取当前美元现汇买入价
    数据源: https://www.boc.cn/sourcedb/whpj/ (无需验证码)
    """
    try:
        s = requests.Session()
        s.trust_env = False
        r = s.get('https://www.boc.cn/sourcedb/whpj/', timeout=15)
        r.encoding = 'utf-8'

        soup = BeautifulSoup(r.text, 'html.parser')
        for table in soup.find_all('table'):
            for row in table.find_all('tr'):
                tds = row.find_all('td')
                if tds and '美元' in tds[0].text:
                    cells = [c.text.strip() for c in tds]
                    rate_raw = cells[1]
                    pub_datetime = cells[6]
                    date_str = pub_datetime.split(' ')[0].replace('/', '-')
                    return {
                        'date': date_str,
                        'rate': float(rate_raw) / 100,
                        'rate_raw': rate_raw,
                        'pub_time': cells[7]
                    }
        print("未找到美元数据")
        return None
    except Exception as e:
        print(f"获取失败: {e}")
        return None


def fetch_historical_rate(date_str):
    """
    获取指定日期的美元现汇买入价
    数据源: srh.bankofchina.com (需验证码, 半自动 - 需用户手动输入)
    """
    import asyncio
    import base64
    from playwright.async_api import async_playwright

    URL = "https://srh.bankofchina.com/search/whpj/search_cn.jsp"

    async def _fetch():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            await page.goto(URL)
            await page.wait_for_load_state('networkidle')
            await page.wait_for_selector('#captcha_img')
            await page.wait_for_timeout(1000)

            # 自动填写日期和货币
            await page.fill('input[name="searchDate"]', date_str)
            await page.select_option('select[name="pjname"]', '美元')

            # 提示用户手动输入验证码
            print(f"\n{'='*50}")
            print(f"请在浏览器中输入验证码，然后点击【查询】按钮")
            print(f"查询日期: {date_str}")
            print(f"{'='*50}\n")

            # 等待用户操作（检测页面跳转或表格出现）
            try:
                await page.wait_for_selector(
                    'table[align="center"] tr:has(td:has-text("美元"))',
                    timeout=120000  # 2分钟超时
                )
            except:
                await browser.close()
                return None

            # 解析结果
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            table = soup.find('table', attrs={'align': 'center'})
            if table:
                for row in table.find_all('tr'):
                    tds = row.find_all('td')
                    if tds and '美元' in tds[0].text:
                        cells = [c.text.strip() for c in tds]
                        rate_raw = cells[1]
                        if rate_raw:
                            await browser.close()
                            return {
                                'date': date_str,
                                'rate': float(rate_raw) / 100,
                                'rate_raw': rate_raw,
                                'pub_time': cells[7]
                            }

            await browser.close()
            return None

    return asyncio.run(_fetch())


def save_to_csv(data):
    """保存数据到CSV，自动去重"""
    if data is None:
        return False

    new_row = pd.DataFrame([{'date': data['date'], 'rate': data['rate']}])

    if os.path.exists(CSV_FILE):
        existing_df = pd.read_csv(CSV_FILE)
        existing_df['date'] = existing_df['date'].astype(str)
        new_row['date'] = new_row['date'].astype(str)

        if data['date'] in existing_df['date'].values:
            print(f"[!] {data['date']} 已存在，跳过")
            return False

        combined = pd.concat([existing_df, new_row], ignore_index=True)
        combined = combined.sort_values('date')
        combined.to_csv(CSV_FILE, index=False)
        print(f"[+] 已保存，共 {len(combined)} 条")
        return True
    else:
        new_row.to_csv(CSV_FILE, index=False)
        print(f"[+] 已保存，共 {len(new_row)} 条")
        return True


def run_daily():
    """每日运行 (自动, 无需验证码)"""
    print("正在获取中国银行美元现汇买入价...")
    data = fetch_current_rate()
    if data:
        print(f"日期: {data['date']}")
        print(f"现汇买入价: {data['rate']:.4f} (牌价: {data['rate_raw']})")
        print(f"发布时间: {data['pub_time']}")
        save_to_csv(data)
    else:
        print("获取失败")


def run_historical(start_date, end_date):
    """批量获取历史数据 (半自动, 需手动输入验证码)"""
    from datetime import timedelta

    start = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.datetime.strptime(end_date, "%Y-%m-%d")

    print(f"获取历史数据: {start_date} ~ {end_date}")
    print("注意: 每条数据需要手动输入验证码\n")

    existing_dates = set()
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        existing_dates = set(df['date'].astype(str).values)

    current = start
    total = 0
    skipped = 0

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")

        if date_str in existing_dates:
            print(f"[跳过] {date_str} 已存在")
            skipped += 1
            current += timedelta(days=1)
            continue

        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        print(f"\n[获取] {date_str}")
        result = fetch_historical_rate(date_str)
        if result:
            save_to_csv(result)
            total += 1
            existing_dates.add(date_str)
            print(f"  现汇买入价: {result['rate']:.4f}")
        else:
            print(f"  获取失败或已取消")

        current += timedelta(days=1)

    print(f"\n完成! 新增 {total} 条，跳过 {skipped} 条")


def main():
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "daily":
            run_daily()
        elif cmd == "current":
            data = fetch_current_rate()
            if data:
                print(f"中行美元现汇买入价: {data['rate']:.4f}")
                print(f"日期: {data['date']} {data['pub_time']}")
        elif cmd == "test":
            data = fetch_current_rate()
            if data:
                print(f"测试成功!")
                print(f"  日期: {data['date']}")
                print(f"  现汇买入价: {data['rate']:.4f}")
                print(f"  牌价: {data['rate_raw']}")
                print(f"  时间: {data['pub_time']}")
            else:
                print("测试失败")
        elif cmd == "historical":
            if len(sys.argv) > 3:
                run_historical(sys.argv[2], sys.argv[3])
            else:
                print("用法: python main.py historical 2025-05-15 2026-05-15")
        else:
            print("用法:")
            print("  python main.py daily      # 自动获取今日数据")
            print("  python main.py current    # 显示当前汇率")
            print("  python main.py test       # 测试")
            print("  python main.py historical 2025-05-15 2026-05-15  # 历史数据(半自动)")
    else:
        print("中国银行美元现汇买入价获取工具")
        print("=" * 40)
        print("数据源: www.boc.cn (中行官网)")
        print()
        print("命令:")
        print("  python main.py daily      # 自动获取今日数据 (无需验证码)")
        print("  python main.py current    # 显示当前汇率")
        print("  python main.py test       # 测试")
        print("  python main.py historical 2025-05-15 2026-05-15  # 历史数据 (需手动输入验证码)")


if __name__ == "__main__":
    main()
