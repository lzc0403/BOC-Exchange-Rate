// pages/about/about.js
const app = getApp();
const api = require('../../utils/api');

Page({
  data: {
    email: '',
    subMsg: '',
    subMsgClass: '',
    dataRange: '--',
    totalDays: '--',
    lastUpdate: '--'
  },

  onShow() {
    const allData = app.globalData.allData;
    if (allData && allData.length > 0) {
      this.setData({
        dataRange: `${allData[0].date} ~ ${allData[allData.length-1].date}`,
        totalDays: allData.length,
        lastUpdate: allData[allData.length-1].date
      });
    }
  },

  onEmailInput(e) {
    this.setData({ email: e.detail.value });
  },

  onSubscribe() {
    const email = this.data.email.trim();
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      this.setData({ subMsg: '请输入有效的邮箱地址', subMsgClass: 'error' });
      return;
    }

    wx.showLoading({ title: '订阅中...' });
    api.subscribeEmail(email).then(res => {
      wx.hideLoading();
      if (res.success) {
        this.setData({
          subMsg: '✅ 订阅成功！每日汇率将推送到您的邮箱',
          subMsgClass: 'success',
          email: ''
        });
      } else {
        this.setData({ subMsg: res.error || '订阅失败', subMsgClass: 'error' });
      }
    }).catch(() => {
      wx.hideLoading();
      this.setData({ subMsg: '网络错误，请稍后重试', subMsgClass: 'error' });
    });
  },

  onOpenSite() {
    wx.setClipboardData({
      data: 'https://lzc0403.github.io/BOC-Exchange-Rate/',
      success: () => {
        wx.showToast({ title: '链接已复制，请在浏览器中打开', icon: 'none' });
      }
    });
  }
});