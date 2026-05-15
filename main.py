#!/usr/bin/env python3
"""
中国银行美元现汇买入价获取工具
数据源:
  - 每日数据: https://www.boc.cn/sourcedb/whpj/ (中行官网，无需验证码)
  - 历史数据: https://api.frankfurter.app (欧洲央行，通过GitHub Actions获取)
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
    数据源: https://www.boc.cn/sourcedb/whpj/
    返回: {'date': '2026-05-15', 'rate': 6.7998, 'rate_raw': '679.98', 'pub_time': '17:24:59'}
    """
    try:
        s = requests.Session()
        s.trust_env = False
        r = s.get('https://www.boc.cn/sourcedb/whpj/', timeout=15)
        r.encoding = 'utf-8'

        soup = BeautifulSoup(r.text, 'html.parser')
        tables = soup.find_all('table')

        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                tds = row.find_all('td')
                if tds and '美元' in tds[0].text:
                    cells = [c.text.strip() for c in tds]
                    rate_raw = cells[1]  # 679.98
                    rate = float(rate_raw) / 100  # 6.7998
                    pub_datetime = cells[6]  # "2026/05/15 17:24:59"
                    date_str = pub_datetime.split(' ')[0].replace('/', '-')
                    pub_time = cells[7]  # "17:24:59"

                    return {
                        'date': date_str,
                        'rate': rate,
                        'rate_raw': rate_raw,
                        'pub_time': pub_time
                    }

        print("未找到美元数据")
        return None

    except Exception as e:
        print(f"获取失败: {e}")
        return None


def fetch_historical_data(start_date, end_date):
    """
    获取历史汇率数据
    数据源: https://api.frankfurter.app (欧洲央行)
    """
    try:
        url = f"https://api.frankfurter.app/{start_date}..{end_date}?from=USD&to=CNY"
        s = requests.Session()
        s.trust_env = False
        r = s.get(url, timeout=60)
        data = r.json()

        if 'rates' not in data:
            print(f"API返回错误: {data}")
            return None

        records = []
        for date_str, rate_data in data['rates'].items():
            records.append({
                'date': date_str,
                'rate': rate_data['CNY']
            })

        df = pd.DataFrame(records)
        df = df.sort_values('date').reset_index(drop=True)
        print(f"获取 {len(df)} 条历史记录")
        return df

    except Exception as e:
        print(f"获取历史数据失败: {e}")
        return None


def save_to_csv(data):
    """保存数据到CSV，自动去重"""
    if data is None:
        print("没有数据可保存")
        return

    new_row = pd.DataFrame([{
        'date': data['date'],
        'rate': data['rate']
    }])

    if os.path.exists(CSV_FILE):
        existing_df = pd.read_csv(CSV_FILE)
        existing_df['date'] = existing_df['date'].astype(str)
        new_row['date'] = new_row['date'].astype(str)

        # 去重
        if data['date'] in existing_df['date'].values:
            print(f"[!] 今天 ({data['date']}) 的数据已存在，跳过写入")
            return

        combined = pd.concat([existing_df, new_row], ignore_index=True)
        combined = combined.sort_values('date')
        combined.to_csv(CSV_FILE, index=False)
        print(f"[+] 数据已更新，共 {len(combined)} 条记录")
    else:
        new_row.to_csv(CSV_FILE, index=False)
        print(f"[+] 数据已保存，共 {len(new_row)} 条记录")


def run_daily():
    """每日运行"""
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
    """获取历史数据"""
    print(f"获取历史数据: {start_date} ~ {end_date}")
    df = fetch_historical_data(start_date, end_date)
    if df is not None and not df.empty:
        filename = f"historical_data_{start_date}_to_{end_date}.csv"
        df.to_csv(filename, index=False)
        print(f"历史数据已保存: {filename}")
    else:
        print("获取历史数据失败")


def main():
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "daily":
            run_daily()
        elif cmd == "current":
            data = fetch_current_rate()
            if data:
                print(f"中国银行美元现汇买入价: {data['rate']:.4f}")
                print(f"日期: {data['date']} {data['pub_time']}")
        elif cmd == "test":
            data = fetch_current_rate()
            if data:
                print(f"测试成功!")
                print(f"  日期: {data['date']}")
                print(f"  现汇买入价: {data['rate']:.4f}")
                print(f"  牌价原始值: {data['rate_raw']}")
                print(f"  发布时间: {data['pub_time']}")
            else:
                print("测试失败")
        elif cmd == "historical":
            if len(sys.argv) > 3:
                start = sys.argv[2]
                end = sys.argv[3]
            else:
                end = datetime.datetime.now().strftime("%Y-%m-%d")
                start = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
            run_historical(start, end)
        else:
            print("用法:")
            print("  python main.py daily      # 获取今日汇率")
            print("  python main.py current    # 显示当前汇率")
            print("  python main.py test       # 测试")
            print("  python main.py historical [start] [end]  # 历史数据")
    else:
        print("中国银行美元现汇买入价获取工具")
        print("=" * 40)
        print("数据源: https://www.boc.cn/sourcedb/whpj/")
        print("\n用法:")
        print("  python main.py daily      # 获取今日汇率")
        print("  python main.py current    # 显示当前汇率")
        print("  python main.py test       # 测试")
        print("  python main.py historical 2025-05-15 2026-05-15  # 历史数据")


if __name__ == "__main__":
    main()
