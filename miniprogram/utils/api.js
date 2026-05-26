// utils/api.js
const CSV_URL = 'https://lzc0403.github.io/BOC-Exchange-Rate/boc_usd_cny.csv';
const SUBSCRIBE_API = 'https://boc-subscription-api.lg111481.workers.dev';

function loadAllData() {
  return new Promise((resolve, reject) => {
    wx.request({
      url: CSV_URL,
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
        resolve(data);
      },
      fail: reject
    });
  });
}

function subscribeEmail(email) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: SUBSCRIBE_API + '/subscribe',
      method: 'POST',
      header: { 'content-type': 'application/json' },
      data: { email },
      success: res => resolve(res.data),
      fail: reject
    });
  });
}

module.exports = { loadAllData, subscribeEmail };