#!/usr/bin/env python3
"""
数据可视化：生成汇率走势图
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import os

def load_data(csv_file):
    """加载CSV数据"""
    if not os.path.exists(csv_file):
        print(f"文件不存在: {csv_file}")
        return None
    
    df = pd.read_csv(csv_file)
    df['date'] = pd.to_datetime(df['date'])
    return df

def plot_exchange_rate(df, output_file="exchange_rate_chart.png"):
    """生成汇率走势图"""
    if df is None or df.empty:
        print("没有数据可绘制")
        return
    
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 创建图形
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # 绘制折线图
    ax.plot(df['date'], df['rate'], 'b-', linewidth=1.5, label='USD/CNY 汇率')
    
    # 添加数据点
    ax.scatter(df['date'], df['rate'], color='red', s=20, alpha=0.6)
    
    # 设置标题和标签
    ax.set_title('美元兑人民币汇率走势', fontsize=16, fontweight='bold')
    ax.set_xlabel('日期', fontsize=12)
    ax.set_ylabel('汇率 (人民币/美元)', fontsize=12)
    
    # 设置x轴日期格式
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    plt.xticks(rotation=45)
    
    # 添加网格
    ax.grid(True, alpha=0.3)
    
    # 添加图例
    ax.legend(loc='upper right')
    
    # 添加数据范围说明
    date_range = f"数据范围: {df['date'].min().strftime('%Y-%m-%d')} 至 {df['date'].max().strftime('%Y-%m-%d')}"
    ax.text(0.02, 0.98, date_range, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # 保存图片
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"图表已保存: {output_file}")
    
    # 显示图表
    plt.show()

def generate_summary(df):
    """生成数据摘要"""
    if df is None or df.empty:
        return
    
    print("\n" + "=" * 50)
    print("数据摘要")
    print("=" * 50)
    
    print(f"数据条数: {len(df)}")
    print(f"日期范围: {df['date'].min().strftime('%Y-%m-%d')} 至 {df['date'].max().strftime('%Y-%m-%d')}")
    print(f"最高汇率: {df['rate'].max():.4f}")
    print(f"最低汇率: {df['rate'].min():.4f}")
    print(f"平均汇率: {df['rate'].mean():.4f}")
    print(f"汇率波动: {df['rate'].std():.4f}")
    
    # 计算涨跌幅
    if len(df) > 1:
        first_rate = df.iloc[0]['rate']
        last_rate = df.iloc[-1]['rate']
        change_pct = ((last_rate - first_rate) / first_rate) * 100
        print(f"期间涨跌幅: {change_pct:+.2f}%")

def main():
    """主函数"""
    # 默认数据文件
    data_file = "data.csv"
    
    # 检查命令行参数
    import sys
    if len(sys.argv) > 1:
        data_file = sys.argv[1]
    
    # 加载数据
    df = load_data(data_file)
    
    if df is not None:
        # 生成摘要
        generate_summary(df)
        
        # 生成图表
        output_file = data_file.replace('.csv', '_chart.png')
        plot_exchange_rate(df, output_file)
    else:
        print("请先运行 main.py 获取数据")

if __name__ == "__main__":
    main()