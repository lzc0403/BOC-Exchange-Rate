// utils/api.js
const BASE_URL = 'https://lzc0403.github.io/BOC-Exchange-Rate/';
const CSV_FILES = {
  usd: 'boc_usd_cny.csv',
  hkd: 'boc_hkd_cny.csv'
};
const CURRENCY_LABELS = {
  usd: { name: '美元', pair: '美元兑人民币', flag: '🇺🇸' },
  hkd: { name: '港币', pair: '港币兑人民币', flag: '🇭🇰' }
};
const SUBSCRIBE_API = 'https://boc-subscription-api.lg111481.workers.dev';

function loadAllData(currency) {
  currency = currency || 'usd';
  const csvFile = CSV_FILES[currency] || CSV_FILES.usd;
  return new Promise((resolve, reject) => {
    wx.request({
      url: BASE_URL + csvFile,
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

module.exports = { loadAllData, subscribeEmail, CURRENCY_LABELS, CSV_FILES };