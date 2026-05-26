// pages/history/history.js
const app = getApp();

Page({
  data: {
    list: []
  },

  onShow() {
    this.loadHistory();
  },

  loadHistory() {
    const allData = app.globalData.allData;
    if (!allData || allData.length === 0) {
      setTimeout(() => this.loadHistory(), 500);
      return;
    }
    const recent = [...allData].reverse().slice(0, 30);
    this.setData({
      list: recent.map(d => ({
        date: d.date,
        buyRate: d.buyRate.toFixed(2),
        cashBuyRate: d.cashBuyRate.toFixed(2),
        sellRate: d.sellRate.toFixed(2),
        cashSellRate: d.cashSellRate.toFixed(2),
        midRate: d.midRate.toFixed(2)
      }))
    });
  },

  onDownload() {
    wx.setClipboardData({
      data: 'https://lzc0403.github.io/BOC-Exchange-Rate/',
      success: () => wx.showToast({ title: '网站链接已复制到剪贴板', icon: 'none' })
    });
  }
});