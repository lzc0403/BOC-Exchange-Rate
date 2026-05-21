#!/usr/bin/env python3
"""
GitHub部署自动化脚本
一键创建仓库、推送代码、配置Secrets
"""
import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, description=""):
    """执行命令并显示结果"""
    print(f"\n{'='*60}")
    print(f"📍 {description}")
    print(f"   命令: {cmd}")
    print(f"{'='*60}")
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    
    if result.returncode != 0:
        print(f"❌ 命令执行失败 (退出码: {result.returncode})")
        return False
    
    print("✅ 命令执行成功")
    return True

def main():
    """主部署流程"""
    print("\n🚀 开始GitHub自动化部署")
    print(f"   工作目录: {os.getcwd()}")
    print(f"   Python版本: {sys.version}")
    
    # 1. 检查GitHub CLI
    print("\n🔍 步骤1: 检查GitHub CLI")
    if not run_command("gh --version", "检查GitHub CLI版本"):
        print("❌ 未找到GitHub CLI，请先安装: https://cli.github.com/")
        return False
    
    # 2. 检查认证状态
    print("\n🔐 步骤2: 检查GitHub认证")
    if not run_command("gh auth status", "检查GitHub认证状态"):
        print("❌ GitHub认证失败，请运行: gh auth login")
        return False
    
    # 3. 获取用户名
    print("\n👤 步骤3: 获取GitHub用户名")
    result = subprocess.run("gh api user --jq '.login'", shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print("❌ 无法获取GitHub用户名，使用默认: lzc0403")
        username = "lzc0403"
    else:
        username = result.stdout.strip()
    print(f"✅ GitHub用户名: {username}")
    
    # 4. 创建仓库
    print("\n📦 步骤4: 创建GitHub仓库")
    repo_name = "boc-scraper"
    repo_full = f"{username}/{repo_name}"
    print(f"   完整仓库名: {repo_full}")
    
    # 检查仓库是否已存在
    check_result = subprocess.run(
        f"gh repo view {repo_full}", 
        shell=True, capture_output=True, text=True
    )
    
    if check_result.returncode == 0:
        print(f"⚠️ 仓库 {repo_full} 已存在，跳过创建")
    else:
        if not run_command(
            f"gh repo create {repo_full} --public --source=. --remote=origin --push",
            "创建GitHub仓库并推送代码"
        ):
            print("❌ 创建仓库失败，请检查Token权限")
            return False
    
    # 5. 配置GitHub Secrets
    print("\n🔑 步骤5: 配置GitHub Secrets")
    
    secrets = {
        "SMTP_SERVER": "smtp.qq.com",
        "SENDER_EMAIL": "21618822@qq.com",
        "SENDER_PASSWORD": "pgzznzltqyfebhic",
        "RECIPIENT_EMAIL": "21618822@qq.com"
    }
    
    for key, value in secrets.items():
        if not run_command(
            f'gh secret set {key} --repo {repo_full} --body "{value}"',
            f"配置Secret: {key}"
        ):
            print(f"⚠️ 配置Secret {key} 失败")
    
    # 6. 验证部署
    print("\n✅ 部署完成！")
    print(f"\n📍 仓库地址: https://github.com/{repo_full}")
    print(f"📍 Actions页面: https://github.com/{repo_full}/actions")
    
    print("\n🎯 下一步操作:")
    print("1. 访问Actions页面，点击'Run workflow'进行手动测试")
    print("2. 等待运行完成，检查是否收到测试邮件")
    print("3. 确认邮件内容和CSV附件正确")
    print("4. 等待第二天10:30自动运行")
    
    print("\n📞 如有问题，请提供:")
    print("- GitHub Actions运行日志截图")
    print("- 错误信息详细内容")
    print("- 运行时间和现象描述")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
