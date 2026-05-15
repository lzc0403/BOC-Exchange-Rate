#!/usr/bin/env python3
"""
中国银行美元现汇买入价 - 每日自动获取
数据源: https://www.boc.cn/sourcedb/whpj/
"""

import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import os
import sys


class BOCExchangeRateFetcher:
    """中国银行外汇牌价获取器"""

    def __init__(self):
        self.data_file = "data.csv"
        self.url = "https://www.boc.cn/sourcedb/whpj/"

    def fetch_current_rate(self):
        """
        获取当前美元现汇买入价
        返回: {'date': '2026/05/15', 'time': '17:24:59', 'rate': 679.98} 或 None
        """
        try:
            s = requests.Session()
            s.trust_env = False
            r = s.get(self.url, timeout=15)
            r.encoding = 'utf-8'

            soup = BeautifulSoup(r.text, 'html.parser')
            tables = soup.find_all('table')

            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    tds = row.find_all('td')
                    if tds and '美元' in tds[0].text:
                        cells = [c.text.strip() for c in tds]
                        rate = float(cells[1]) / 100  # 679.98 -> 6.7998
                        pub_datetime = cells[6]  # "2026/05/15 17:24:59"
                        date_str = pub_datetime.split(' ')[0].replace('/', '-')
                        time_str = cells[7]  # "17:24:59"

                        return {
                            'date': date_str,
                            'time': time_str,
                            'rate': rate,
                            'rate_raw': cells[1]
                        }

            print("未找到美元数据")
            return None

        except Exception as e:
            print(f"获取失败: {e}")
            return None

    def save_to_csv(self, data):
        """保存数据到CSV文件"""
        if data is None:
            print("没有数据可保存")
            return

        new_row = pd.DataFrame([{
            'date': data['date'],
            'rate': data['rate']
        }])

        if os.path.exists(self.data_file):
            existing_df = pd.read_csv(self.data_file)
            existing_df['date'] = existing_df['date'].astype(str)
            new_row['date'] = new_row['date'].astype(str)

            combined = pd.concat([existing_df, new_row], ignore_index=True)
            combined = combined.drop_duplicates(subset=['date'], keep='last')
            combined = combined.sort_values('date')
            combined.to_csv(self.data_file, index=False)
            print(f"数据已更新，共 {len(combined)} 条记录")
        else:
            new_row.to_csv(self.data_file, index=False)
            print(f"数据已保存，共 {len(new_row)} 条记录")

    def run_daily(self):
        """每日运行"""
        print("正在获取中国银行美元现汇买入价...")

        data = self.fetch_current_rate()
        if data:
            print(f"日期: {data['date']}")
            print(f"时间: {data['time']}")
            print(f"现汇买入价: {data['rate']:.4f} (牌价: {data['rate_raw']})")
            self.save_to_csv(data)
        else:
            print("获取失败")


def main():
    fetcher = BOCExchangeRateFetcher()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "daily":
            fetcher.run_daily()

        elif command == "current":
            data = fetcher.fetch_current_rate()
            if data:
                print(f"中国银行美元现汇买入价")
                print(f"日期: {data['date']} {data['time']}")
                print(f"汇率: {data['rate']:.4f}")

        elif command == "test":
            data = fetcher.fetch_current_rate()
            if data:
                print(f"测试成功!")
                print(f"  日期: {data['date']}")
                print(f"  时间: {data['time']}")
                print(f"  现汇买入价: {data['rate']:.4f}")
                print(f"  牌价原始值: {data['rate_raw']}")

        else:
            print("用法:")
            print("  python main.py daily    # 获取今日汇率并保存")
            print("  python main.py current  # 显示当前汇率")
            print("  python main.py test     # 测试抓取")
    else:
        print("中国银行美元现汇买入价获取工具")
        print("=" * 40)
        print("数据源: https://www.boc.cn/sourcedb/whpj/")
        print("\n用法:")
        print("  python main.py daily    # 获取今日汇率并保存")
        print("  python main.py current  # 显示当前汇率")
        print("  python main.py test     # 测试抓取")


if __name__ == "__main__":
    main()
