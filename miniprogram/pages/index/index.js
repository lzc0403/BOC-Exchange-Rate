// pages/index/index.js
const app = getApp();

Page({
  data: {
    latestRate: '--',
    buyRate: '--',
    sellRate: '--',
    midRate: '--',
    lastUpdate: '加载中...',
    totalDays: '--',
    dataRange: '--',
    buyTrend: '',
    buyTrendClass: '',
    sellTrend: '',
    sellTrendClass: '',
    midTrend: '',
    midTrendClass: '',
  },

  onShow() {
    this.loadData();
  },

  loadData() {
    const allData = app.globalData.allData;
    if (!allData || allData.length === 0) {
      // 首次加载，等待数据
      const timer = setInterval(() => {
        if (app.globalData.allData.length > 0) {
          clearInterval(timer);
          this.renderData(app.globalData.allData);
        }
      }, 500);
      return;
    }
    this.renderData(allData);
  },

  renderData(allData) {
    const latest = allData[allData.length - 1];
    const prev = allData.length > 1 ? allData[allData.length - 2] : null;

    const fmt = v => (v || v === 0) ? v.toFixed(2) : '--';
    const trend = (v, p) => {
      if (!p || !v) return { text: '', cls: '' };
      const diff = v - p;
      if (diff > 0) return { text: `↑ ${diff.toFixed(2)}`, cls: 'trend-up' };
      if (diff < 0) return { text: `↓ ${Math.abs(diff).toFixed(2)}`, cls: 'trend-down' };
      return { text: '— 0.00', cls: 'trend-flat' };
    };

    this.setData({
      latestRate: latest.midRate.toFixed(2),
      buyRate: fmt(latest.buyRate),
      sellRate: fmt(latest.sellRate),
      midRate: fmt(latest.midRate),
      lastUpdate: latest.date,
      totalDays: allData.length,
      dataRange: `${allData[0].date} ~ ${latest.date}`,
      buyTrend: trend(latest.buyRate, prev ? prev.buyRate : null).text,
      buyTrendClass: trend(latest.buyRate, prev ? prev.buyRate : null).cls,
      sellTrend: trend(latest.sellRate, prev ? prev.sellRate : null).text,
      sellTrendClass: trend(latest.sellRate, prev ? prev.sellRate : null).cls,
      midTrend: trend(latest.midRate, prev ? prev.midRate : null).text,
      midTrendClass: trend(latest.midRate, prev ? prev.midRate : null).cls,
    });
  }
});