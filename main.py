#!/usr/bin/env python3
"""
美元兑人民币汇率数据获取工具
支持历史数据获取和每日自动运行

数据来源：
1. 主数据源：Frankfurter.app (欧洲央行汇率数据，免费无需API Key)
2. 备用数据源：ExchangeRate-API (免费)

说明：
- 数据基于欧洲央行(ECB)每日参考汇率
- 与银行现汇买入价有0.1%-0.3%的点差（银行利润）
- 与在岸人民币(CNY)有微小差异
"""

import pandas as pd
import requests
from datetime import datetime, timedelta
import os
import sys
import warnings

# 忽略SSL警告
warnings.filterwarnings('ignore', message='Unverified HTTPS request')


class ExchangeRateFetcher:
    """汇率数据获取器"""
    
    def __init__(self):
        self.data_file = "data.csv"
        self.frankfurter_base = "https://api.frankfurter.app"
        self.exchangerate_base = "https://api.exchangerate-api.com/v4/latest/USD"
        
    def get_historical_data(self, start_date=None, end_date=None):
        """
        获取历史汇率数据
        数据源：Frankfurter.app (欧洲央行)
        
        返回: DataFrame with columns [date, rate]
        """
        print("正在获取历史汇率数据...")
        
        # 默认获取最近一年
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        
        try:
            # 使用 frankfurter.app API
            url = f"{self.frankfurter_base}/{start_date}..{end_date}?from=USD&to=CNY"
            r = requests.get(url, timeout=30, verify=False)
            data = r.json()
            
            if 'rates' not in data:
                print(f"API返回错误: {data}")
                return None
            
            # 转换为DataFrame
            records = []
            for date_str, rate_data in data['rates'].items():
                records.append({
                    'date': date_str,
                    'rate': rate_data['CNY']
                })
            
            df = pd.DataFrame(records)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            
            print(f"成功获取 {len(df)} 条记录")
            print(f"日期范围: {df['date'].min().strftime('%Y-%m-%d')} 至 {df['date'].max().strftime('%Y-%m-%d')}")
            
            return df
            
        except Exception as e:
            print(f"获取数据失败: {e}")
            return None
    
    def get_current_rate(self):
        """
        获取当前实时汇率
        数据源：ExchangeRate-API (免费)
        """
        try:
            r = requests.get(self.exchangerate_base, timeout=10, verify=False)
            data = r.json()
            return {
                'base': data['base'],
                'date': data['date'],
                'rate': data['rates']['CNY']
            }
        except Exception as e:
            print(f"获取实时汇率失败: {e}")
            return None
    
    def save_to_csv(self, df, filename=None):
        """保存数据到CSV文件"""
        if df is None or df.empty:
            print("没有数据可保存")
            return
        
        if filename is None:
            filename = self.data_file
        
        # 如果是追加模式且文件已存在
        if os.path.exists(filename) and filename == self.data_file:
            existing_df = pd.read_csv(filename)
            
            # 确保两个DataFrame的date列都是字符串类型
            existing_df['date'] = existing_df['date'].astype(str)
            df['date'] = df['date'].astype(str)
            
            # 合并数据，去重
            combined_df = pd.concat([existing_df, df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(subset=['date'], keep='last')
            combined_df = combined_df.sort_values('date')
            combined_df.to_csv(filename, index=False)
            print(f"数据已追加到 {filename}，共 {len(combined_df)} 条记录")
        else:
            df.to_csv(filename, index=False)
            print(f"数据已保存到 {filename}，共 {len(df)} 条记录")
    
    def run_daily(self):
        """每日运行：获取今天的汇率"""
        print(f"获取今日汇率数据...")
        
        # 获取当前实时汇率
        current = self.get_current_rate()
        if current:
            print(f"当前 USD/CNY 汇率: {current['rate']}")
            print(f"数据日期: {current['date']}")
            
            # 保存今日数据
            today_df = pd.DataFrame([{
                'date': current['date'],
                'rate': current['rate']
            }])
            self.save_to_csv(today_df)
        else:
            print("未能获取今日汇率")


def main():
    """主函数"""
    fetcher = ExchangeRateFetcher()
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "daily":
            # 每日运行模式
            fetcher.run_daily()
            
        elif command == "historical":
            # 历史数据获取模式
            if len(sys.argv) > 3:
                start_date = sys.argv[2]
                end_date = sys.argv[3]
            else:
                # 默认获取最近一年数据
                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            
            df = fetcher.get_historical_data(start_date, end_date)
            if df is not None and not df.empty:
                filename = f"historical_data_{start_date}_to_{end_date}.csv"
                fetcher.save_to_csv(df, filename)
                
        elif command == "test":
            # 测试模式：获取最近一周数据
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            df = fetcher.get_historical_data(start_date, end_date)
            if df is not None and not df.empty:
                fetcher.save_to_csv(df, "test_data.csv")
                print("\n数据预览:")
                print(df)
                
        elif command == "current":
            # 获取当前汇率
            current = fetcher.get_current_rate()
            if current:
                print(f"USD/CNY 当前汇率: {current['rate']}")
                print(f"数据日期: {current['date']}")
                
        else:
            print("用法:")
            print("  python main.py daily          # 获取今日汇率")
            print("  python main.py current        # 显示当前实时汇率")
            print("  python main.py historical     # 获取历史一年数据")
            print("  python main.py historical 2025-05-15 2026-05-15  # 指定日期范围")
            print("  python main.py test           # 测试模式（最近一周）")
    else:
        # 默认显示帮助
        print("美元兑人民币汇率数据获取工具")
        print("=" * 40)
        print("\n用法:")
        print("  python main.py daily          # 获取今日汇率")
        print("  python main.py current        # 显示当前实时汇率")
        print("  python main.py historical     # 获取历史一年数据")
        print("  python main.py test           # 测试模式（最近一周）")
        print("\n数据来源:")
        print("  - Frankfurter.app (欧洲央行每日参考汇率)")
        print("  - ExchangeRate-API (实时汇率)")


if __name__ == "__main__":
    main()