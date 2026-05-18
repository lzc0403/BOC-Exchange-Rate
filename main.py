#!/usr/bin/env python3
"""
中国银行美元现汇买入价获取工具
数据源: https://www.boc.cn/sourcedb/whpj/ (当前牌价, 无需验证码)
       https://srh.bankofchina.com/search/whpj/search_cn.jsp (历史查询, 需验证码)
"""

import os
import sys
import datetime
import requests
from bs4 import BeautifulSoup
import pandas as pd

CSV_FILE = "data.csv"


def p(msg):
    """带 flush 的 print，确保在 IDE 中也能立即显示"""
    print(msg, flush=True)


def fetch_current_rate():
    """获取当前美元现汇买入价 (无需验证码)"""
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
        p("未找到美元数据")
        return None
    except Exception as e:
        p(f"获取失败: {e}")
        return None


def fetch_historical_rate(date_str):
    """
    获取指定日期的美元现汇买入价 (半自动, 需手动输入验证码)
    """
    import asyncio
    from playwright.async_api import async_playwright

    URL = "https://srh.bankofchina.com/search/whpj/search_cn.jsp"

    async def _fetch():
        p("正在启动浏览器...")
        async with async_playwright() as pwr:
            browser = await pwr.chromium.launch(headless=False)
            page = await browser.new_page()

            p("正在打开中行页面...")
            await page.goto(URL)
            await page.wait_for_load_state('networkidle')
            await page.wait_for_selector('#captcha_img')
            await page.wait_for_timeout(1000)

            # 自动填写日期和货币
            await page.fill('input[name="searchDate"]', date_str)
            await page.select_option('select[name="pjname"]', '美元')

            p(f"\n{'='*50}")
            p(f"  浏览器已打开，请完成以下操作：")
            p(f"  1. 输入验证码图片中的文字")
            p(f"  2. 点击【查询】按钮")
            p(f"  查询日期: {date_str}")
            p(f"  超时时间: 5分钟")
            p(f"{'='*50}\n")

            # 循环检测页面变化（每3秒检查一次，共5分钟）
            for i in range(100):
                await asyncio.sleep(3)

                try:
                    content = await page.content()
                    soup = BeautifulSoup(content, 'html.parser')

                    # 检查是否出现数据表格
                    table = soup.find('table', attrs={'align': 'center'})
                    if table:
                        for row in table.find_all('tr'):
                            tds = row.find_all('td')
                            if tds and '美元' in tds[0].text:
                                cells = [c.text.strip() for c in tds]
                                rate_raw = cells[1]
                                if rate_raw:
                                    p(f"[+] 成功获取数据!")
                                    await browser.close()
                                    return {
                                        'date': date_str,
                                        'rate': float(rate_raw) / 100,
                                        'rate_raw': rate_raw,
                                        'pub_time': cells[7]
                                    }

                    # 检查是否验证码错误
                    if '验证码错误' in content or '验证码过期' in content:
                        p("[!] 验证码错误，请重新输入")

                    # 检查是否是非交易日
                    if '没有找到' in content or '无记录' in content:
                        p(f"[!] {date_str} 可能是非交易日，无数据")
                        await browser.close()
                        return None

                except Exception:
                    pass

                # 每30秒提示一次
                if i > 0 and i % 10 == 0:
                    p(f"  等待中... ({i * 3}秒)")

            p("[!] 超时（5分钟），请重试")
            await browser.close()
            return None

    try:
        return asyncio.run(_fetch())
    except Exception as e:
        p(f"[!] 错误: {e}")
        return None


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
            p(f"[!] {data['date']} 已存在，跳过")
            return False

        combined = pd.concat([existing_df, new_row], ignore_index=True)
        combined = combined.sort_values('date')
        combined.to_csv(CSV_FILE, index=False)
        p(f"[+] 已保存，共 {len(combined)} 条")
        return True
    else:
        new_row.to_csv(CSV_FILE, index=False)
        p(f"[+] 已保存，共 {len(new_row)} 条")
        return True


def run_daily():
    """每日运行 (自动, 无需验证码)"""
    p("正在获取中国银行美元现汇买入价...")
    data = fetch_current_rate()
    if data:
        p(f"日期: {data['date']}")
        p(f"现汇买入价: {data['rate']:.4f} (牌价: {data['rate_raw']})")
        p(f"发布时间: {data['pub_time']}")
        save_to_csv(data)
    else:
        p("获取失败")


def run_historical(start_date, end_date):
    """批量获取历史数据 (半自动)"""
    from datetime import timedelta

    start = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.datetime.strptime(end_date, "%Y-%m-%d")

    p(f"获取历史数据: {start_date} ~ {end_date}")
    p("注意: 每条数据需要手动输入验证码\n")

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
            p(f"[跳过] {date_str} 已存在")
            skipped += 1
            current += timedelta(days=1)
            continue

        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        p(f"\n[获取] {date_str}")
        result = fetch_historical_rate(date_str)
        if result:
            save_to_csv(result)
            total += 1
            existing_dates.add(date_str)
            p(f"  现汇买入价: {result['rate']:.4f}")
        else:
            p(f"  获取失败或已取消")
            # 询问是否继续
            try:
                ans = input("\n继续获取下一天？(y/n): ").strip().lower()
                if ans != 'y':
                    p("已停止")
                    break
            except EOFError:
                break

        current += timedelta(days=1)

    p(f"\n完成! 新增 {total} 条，跳过 {skipped} 条")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "daily":
            run_daily()
        elif cmd == "current":
            data = fetch_current_rate()
            if data:
                p(f"中行美元现汇买入价: {data['rate']:.4f}")
                p(f"日期: {data['date']} {data['pub_time']}")
        elif cmd == "test":
            data = fetch_current_rate()
            if data:
                p(f"测试成功!")
                p(f"  日期: {data['date']}")
                p(f"  现汇买入价: {data['rate']:.4f}")
                p(f"  牌价: {data['rate_raw']}")
                p(f"  时间: {data['pub_time']}")
            else:
                p("测试失败")
        elif cmd == "historical":
            if len(sys.argv) > 3:
                run_historical(sys.argv[2], sys.argv[3])
            else:
                p("用法: python main.py historical 2025-05-15 2026-05-15")
        else:
            p("用法:")
            p("  python main.py daily      # 自动获取今日数据")
            p("  python main.py current    # 显示当前汇率")
            p("  python main.py test       # 测试")
            p("  python main.py historical 2025-05-15 2026-05-15  # 历史数据(半自动)")
    else:
        p("中国银行美元现汇买入价获取工具")
        p("=" * 40)
        p("数据源: www.boc.cn (中行官网)")
        p()
        p("命令:")
        p("  python main.py daily      # 自动获取今日数据 (无需验证码)")
        p("  python main.py current    # 显示当前汇率")
        p("  python main.py test       # 测试")
        p("  python main.py historical 2025-05-15 2026-05-15  # 历史数据 (需手动输入验证码)")


if __name__ == "__main__":
    main()
