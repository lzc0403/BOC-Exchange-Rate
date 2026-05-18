#!/usr/bin/env python3
"""
中国银行美元现汇买入价获取工具
数据源: https://srh.bankofchina.com/search/whpj/search_cn.jsp
"""

import os
import asyncio
import base64
import datetime
import pandas as pd
import ddddocr
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

CSV_FILE = "data.csv"
URL = "https://srh.bankofchina.com/search/whpj/search_cn.jsp"


async def fetch_boc_rate(date_str, max_attempts=20):
    """
    使用 Playwright 抓取指定日期的美元现汇买入价
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        ocr = ddddocr.DdddOcr(show_ad=False)

        for attempt in range(max_attempts):
            try:
                await page.goto(URL)
                await page.wait_for_load_state('networkidle')
                await page.wait_for_selector('#captcha_img')
                await page.wait_for_timeout(500)

                captcha_src = await page.get_attribute('#captcha_img', 'src')
                if not captcha_src or 'base64,' not in captcha_src:
                    continue

                base64_str = captcha_src.split('base64,')[1]
                img_bytes = base64.b64decode(base64_str)
                code = ocr.classification(img_bytes)
                print(f"[-] 第 {attempt+1} 次验证码: [{code}]")

                await page.fill('input[name="searchDate"]', date_str)
                await page.select_option('select[name="pjname"]', '美元')
                await page.fill('input[name="captcha"]', code)
                await page.click('input[type="button"][value="查询"]')
                await page.wait_for_load_state('networkidle')
                await page.wait_for_timeout(1000)

                content = await page.content()

                if '验证码过期' in content or '验证码错误' in content:
                    print(f" [-] 验证码错误，重试...")
                    continue

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

            except Exception as e:
                print(f"[-] 异常: {e}")

        await browser.close()
        return None


def save_to_csv(data):
    """保存数据到CSV，自动去重"""
    if data is None:
        return

    new_row = pd.DataFrame([{'date': data['date'], 'rate': data['rate']}])

    if os.path.exists(CSV_FILE):
        existing_df = pd.read_csv(CSV_FILE)
        existing_df['date'] = existing_df['date'].astype(str)
        new_row['date'] = new_row['date'].astype(str)

        if data['date'] in existing_df['date'].values:
            print(f"[!] {data['date']} 已存在，跳过")
            return

        combined = pd.concat([existing_df, new_row], ignore_index=True)
        combined = combined.sort_values('date')
        combined.to_csv(CSV_FILE, index=False)
        print(f"[+] 已保存，共 {len(combined)} 条")
    else:
        new_row.to_csv(CSV_FILE, index=False)
        print(f"[+] 已保存，共 {len(new_row)} 条")


async def run_daily():
    """每日运行"""
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    print(f"获取 {today} 中行美元现汇买入价...")
    result = await fetch_boc_rate(today)
    if result:
        print(f"日期: {result['date']}")
        print(f"现汇买入价: {result['rate']:.4f} (牌价: {result['rate_raw']})")
        print(f"发布时间: {result['pub_time']}")
        save_to_csv(result)
    else:
        print("获取失败")


async def run_historical(start_date, end_date):
    """批量获取历史数据"""
    from datetime import timedelta

    start = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.datetime.strptime(end_date, "%Y-%m-%d")

    print(f"获取历史数据: {start_date} ~ {end_date}")

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
            skipped += 1
            current += timedelta(days=1)
            continue

        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        print(f"[获取] {date_str} ...")
        result = await fetch_boc_rate(date_str, max_attempts=10)
        if result:
            save_to_csv(result)
            total += 1
            existing_dates.add(date_str)

        current += timedelta(days=1)

    print(f"\n完成! 新增 {total} 条，跳过 {skipped} 条")


def main():
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "daily":
            asyncio.run(run_daily())
        elif cmd == "test":
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            result = asyncio.run(fetch_boc_rate(today, max_attempts=5))
            if result:
                print(f"测试成功!")
                print(f"  日期: {result['date']}")
                print(f"  现汇买入价: {result['rate']:.4f}")
                print(f"  牌价: {result['rate_raw']}")
                print(f"  时间: {result['pub_time']}")
            else:
                print("测试失败")
        elif cmd == "historical":
            if len(sys.argv) > 3:
                start = sys.argv[2]
                end = sys.argv[3]
            else:
                end = datetime.datetime.now().strftime("%Y-%m-%d")
                start = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
            asyncio.run(run_historical(start, end))
        else:
            print("用法: python main.py [daily|test|historical]")
    else:
        print("中国银行美元现汇买入价获取工具")
        print("=" * 40)
        print("数据源: srh.bankofchina.com")
        print("\n命令:")
        print("  python main.py daily                    # 获取今日数据")
        print("  python main.py test                     # 测试")
        print("  python main.py historical 2025-05-15 2026-05-15  # 历史数据")


if __name__ == "__main__":
    main()
