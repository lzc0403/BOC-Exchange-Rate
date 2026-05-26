// app.js
App({
  globalData: {
    allData: [],
    latestRate: null,
    lastUpdate: '',
  },
  onLaunch() {
    // 加载数据
    this.loadExchangeData();
  },
  loadExchangeData() {
    const that = this;
    wx.request({
      url: 'https://lzc0403.github.io/BOC-Exchange-Rate/boc_usd_cny.csv',
      success(res) {
        const text = res.data;
        const lines = text.trim().split('\n');
        const data = lines.slice(1).map(line => {
          const v = line.split(',');
          return {
            name: v[0],
            buyRate: parseFloat(v[1]),
            cashBuyRate: parseFloat(v[2]),
            sellRate: parseFloat(v[3]),
            cashSellRate: parseFloat(v[4]),
            midRate: parseFloat(v[5]),
            publishTime: v[6],
            date: v[7]
          };
        }).filter(d => d.date && !isNaN(d.midRate));
        data.sort((a, b) => a.date.localeCompare(b.date));
        that.globalData.allData = data;
        that.globalData.latestRate = data[data.length - 1];
        that.globalData.lastUpdate = data[data.length - 1].date;
      },
      fail(err) {
        console.error('数据加载失败', err);
      }
    });
  }
});