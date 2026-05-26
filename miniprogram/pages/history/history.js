// pages/history/history.js
const app = getApp();

Page({
  data: {
    list: [],
    showDateRange: false,
    startDateVal: '',
    endDateVal: ''
  },

  onShow() {
    this.loadHistory();
  },

  loadHistory(customStart, customEnd) {
    const allData = app.globalData.allData;
    if (!allData || allData.length === 0) {
      setTimeout(() => this.loadHistory(), 500);
      return;
    }

    let data = [...allData];

    if (customStart && customEnd) {
      data = data.filter(d => d.date >= customStart && d.date <= customEnd);
    } else {
      // Default: last 30 days
      data = data.slice(-30);
    }

    // Reverse to show newest first
    data = data.reverse();

    this.setData({
      list: data.map(d => ({
        date: d.date,
        buyRate: d.buyRate.toFixed(2),
        cashBuyRate: d.cashBuyRate.toFixed(2),
        sellRate: d.sellRate.toFixed(2),
        cashSellRate: d.cashSellRate.toFixed(2),
        midRate: d.midRate.toFixed(2)
      }))
    });
  },

  onToggleDateRange() {
    this.setData({ showDateRange: !this.data.showDateRange });
  },

  onStartDateChange(e) {
    this.setData({ startDateVal: e.detail.value });
  },

  onEndDateChange(e) {
    this.setData({ endDateVal: e.detail.value });
  },

  onDateQuery() {
    const s = this.data.startDateVal;
    const e = this.data.endDateVal;
    if (!s || !e) {
      wx.showToast({ title: '请选择起止日期', icon: 'none' });
      return;
    }
    if (s > e) {
      wx.showToast({ title: '开始日期不能晚于结束日期', icon: 'none' });
      return;
    }
    this.loadHistory(s, e);
    wx.showToast({ title: `查询 ${s} ~ ${e}`, icon: 'none' });
  },

  onDownload() {
    wx.setClipboardData({
      data: 'https://lzc0403.github.io/BOC-Exchange-Rate/',
      success: () => wx.showToast({ title: '网站链接已复制到剪贴板', icon: 'none' })
    });
  }
});