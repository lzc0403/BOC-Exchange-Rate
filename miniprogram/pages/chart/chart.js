// pages/chart/chart.js
const app = getApp();
const { CURRENCY_LABELS } = require('../../utils/api');

Page({
  data: {
    currency: 'usd',
    currencyLabel: '美元兑人民币',
    currencies: [
      { key: 'usd', label: '🇺🇸 美元' },
      { key: 'hkd', label: '🇭🇰 港币' }
    ],
    activeDays: 90,
    empty: false,
    isPhone: false,
  },

  onLoad() {
    const sys = wx.getSystemInfoSync();
    this.setData({ isPhone: sys.windowWidth < 400 });
  },

  onShow() {
    this.setData({ currency: app.globalData.currency || 'usd' });
    setTimeout(() => this.drawChart(), 300);
  },

  onCurrencyTap(e) {
    const currency = e.currentTarget.dataset.key;
    if (currency === this.data.currency) return;
    this.setData({ currency, currencyLabel: CURRENCY_LABELS[currency].pair });
    app.globalData.currency = currency;
    app.globalData.allData = [];
    app.loadExchangeData();
    setTimeout(() => this.drawChart(), 500);
  },

  onTimeFilter(e) {
    const days = parseInt(e.currentTarget.dataset.days);
    this.setData({ activeDays: days }, () => this.drawChart());
  },

  drawChart() {
    const allData = app.globalData.allData;
    if (!allData || allData.length === 0) return;

    const days = this.data.activeDays;
    let data = allData;
    if (days > 0) {
      const cutoff = new Date();
      cutoff.setDate(cutoff.getDate() - days);
      const cutoffStr = cutoff.toISOString().split('T')[0];
      data = allData.filter(d => d.date >= cutoffStr);
    }

    if (data.length < 2) {
      this.setData({ empty: true });
      return;
    }
    this.setData({ empty: false });

    const query = wx.createSelectorQuery();
    query.select('#lineCanvas')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res || !res[0]) return;
        const canvas = res[0].node;
        const ctx = canvas.getContext('2d');
        const dpr = wx.getSystemInfoSync().pixelRatio;
        const width = res[0].width;
        const height = res[0].height;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        ctx.scale(dpr, dpr);

        this._renderChart(ctx, data, width, height);
      });
  },

  _renderChart(ctx, data, w, h) {
    const isPhone = this.data.isPhone;
    const pad = { top: 30, right: isPhone ? 20 : 30, bottom: 45, left: isPhone ? 50 : 60 };
    const chartW = w - pad.left - pad.right;
    const chartH = h - pad.top - pad.bottom;

    // Find min/max
    let min = Infinity, max = -Infinity;
    data.forEach(d => {
      [d.midRate, d.buyRate, d.sellRate].forEach(v => {
        if (v < min) min = v;
        if (v > max) max = v;
      });
    });
    const range = max - min || 1;
    const padRange = range * 0.1;
    const yMin = min - padRange;
    const yMax = max + padRange;

    const toX = i => pad.left + (i / (data.length - 1)) * chartW;
    const toY = v => pad.top + chartH - ((v - yMin) / (yMax - yMin)) * chartH;

    // Clear
    ctx.clearRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = 'rgba(0,0,0,0.04)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (chartH / 4) * i;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
    }

    // Y-axis labels
    ctx.fillStyle = '#9A9A9A';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'right';
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (chartH / 4) * i;
      const val = yMax - ((yMax - yMin) / 4) * i;
      ctx.fillText(val.toFixed(2), pad.left - 6, y + 4);
    }

    // X-axis labels — adaptive to screen width
    ctx.textAlign = 'center';
    ctx.font = isPhone ? '10px sans-serif' : '11px sans-serif';
    // Calculate max labels that can fit without overlapping
    // Each label ~35px on phone, ~40px on desktop
    const labelSpace = isPhone ? 40 : 50;
    const maxLabels = Math.max(2, Math.floor(chartW / labelSpace));
    const xStep = Math.max(1, Math.floor(data.length / maxLabels));
    
    for (let i = 0; i < data.length; i += xStep) {
      const x = toX(i);
      // Shorter format on phone: "5-26" instead of "05-26"
      let label = data[i].date;
      if (isPhone) {
        label = label.replace(/^0(\d)-/, '$1-').replace(/-0(\d)/, '-$1');
      } else {
        label = label.slice(5);
      }
      ctx.fillText(label, x, h - pad.bottom + 18);
    }

    // Draw line
    const drawLine = (dataset, color, width, dashed) => {
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      if (dashed) ctx.setLineDash([6, 4]);
      else ctx.setLineDash([]);

      for (let i = 0; i < dataset.length; i++) {
        const x = toX(i);
        const y = toY(dataset[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    };

    // Fill area under midRate
    const midData = data.map(d => d.midRate);
    ctx.beginPath();
    ctx.moveTo(toX(0), toY(midData[0]));
    ctx.lineTo(toX(0), pad.top + chartH);
    for (let i = 1; i < midData.length; i++) {
      ctx.lineTo(toX(i), toY(midData[i]));
    }
    ctx.lineTo(toX(midData.length - 1), pad.top + chartH);
    ctx.closePath();
    ctx.fillStyle = 'rgba(196, 149, 106, 0.08)';
    ctx.fill();

    // Draw three lines
    drawLine(midData, '#C4956A', 2.5, false);
    drawLine(data.map(d => d.buyRate), '#27AE60', 1.5, true);
    drawLine(data.map(d => d.sellRate), '#E74C3C', 1.5, true);
  }
});