// app.js
const { loadAllData } = require('./utils/api');

App({
  globalData: {
    currency: 'usd',
    allData: [],
    latestRate: null,
    lastUpdate: '',
  },
  onLaunch() {
    this.loadExchangeData();
  },
  loadExchangeData() {
    const that = this;
    loadAllData(this.globalData.currency).then(data => {
      that.globalData.allData = data;
      that.globalData.latestRate = data[data.length - 1];
      that.globalData.lastUpdate = data[data.length - 1].date;
    }).catch(err => {
      console.error('数据加载失败', err);
    });
  }
});