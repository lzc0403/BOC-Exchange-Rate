// pages/index/index.js
const app = getApp();

Page({
  data: {
    latestRate: '--',
    buyRate: '--', sellRate: '--', midRate: '--',
    lastUpdate: '加载中...',
    totalDays: '--', dataRange: '--',
    buyTrend: '', buyTrendClass: '',
    sellTrend: '', sellTrendClass: '',
    midTrend: '', midTrendClass: '',
    activeDays: 30,
    empty: false,
  },

  onShow() {
    this.loadData();
  },

  loadData() {
    const allData = app.globalData.allData;
    if (!allData || allData.length === 0) {
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
    }, () => setTimeout(() => this.drawChart(), 200));
  },

  onFilter(e) {
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
      data = allData.filter(d => d.date >= cutoff.toISOString().split('T')[0]);
    }

    if (data.length < 2) {
      this.setData({ empty: true });
      return;
    }
    this.setData({ empty: false });

    const query = wx.createSelectorQuery();
    query.select('#lineCanvas').fields({ node: true, size: true }).exec((res) => {
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
    const sys = wx.getSystemInfoSync();
    const isPhone = sys.windowWidth < 400;
    const pad = { top: 30, right: isPhone ? 20 : 30, bottom: 45, left: isPhone ? 50 : 60 };
    const chartW = w - pad.left - pad.right;
    const chartH = h - pad.top - pad.bottom;

    let min = Infinity, max = -Infinity;
    data.forEach(d => { [d.midRate, d.buyRate, d.sellRate].forEach(v => { if (v < min) min = v; if (v > max) max = v; }); });
    const range = max - min || 1;
    const yMin = min - range * 0.1;
    const yMax = max + range * 0.1;

    const toX = i => pad.left + (i / (data.length - 1)) * chartW;
    const toY = v => pad.top + chartH - ((v - yMin) / (yMax - yMin)) * chartH;

    ctx.clearRect(0, 0, w, h);

    // Grid
    ctx.strokeStyle = 'rgba(0,0,0,0.04)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (chartH / 4) * i;
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
    }

    // Y labels
    ctx.fillStyle = '#9A9A9A';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'right';
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (chartH / 4) * i;
      ctx.fillText((yMax - ((yMax - yMin) / 4) * i).toFixed(2), pad.left - 6, y + 4);
    }

    // X labels — adaptive
    ctx.textAlign = 'center';
    ctx.font = isPhone ? '10px sans-serif' : '11px sans-serif';
    // Smart label count: limit based on width AND data density
    const maxLabels = Math.min(
      Math.max(2, Math.floor(chartW / (isPhone ? 50 : 60))),
      Math.ceil(data.length / 2)
    );
    const xStep = Math.max(1, Math.floor(data.length / maxLabels));
    for (let i = 0; i < data.length; i += xStep) {
      let label = data[i].date;
      if (isPhone) label = label.replace(/^0(\d)-/, '$1-').replace(/-0(\d)/, '-$1');
      ctx.fillText(label, toX(i), h - pad.bottom + 18);
    }
    // Always show last date label
    let lastLabel = data[data.length - 1].date;
    if (isPhone) lastLabel = lastLabel.replace(/^0(\d)-/, '$1-').replace(/-0(\d)/, '-$1');
    ctx.fillText(lastLabel, w - pad.right, h - pad.bottom + 18);

    // Fill area
    const midData = data.map(d => d.midRate);
    ctx.beginPath();
    ctx.moveTo(toX(0), toY(midData[0]));
    ctx.lineTo(toX(0), pad.top + chartH);
    for (let i = 1; i < midData.length; i++) ctx.lineTo(toX(i), toY(midData[i]));
    ctx.lineTo(toX(midData.length - 1), pad.top + chartH);
    ctx.closePath();
    ctx.fillStyle = 'rgba(196, 149, 106, 0.08)';
    ctx.fill();

    // Lines
    const drawLine = (ds, color, w2, dashed) => {
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = w2;
      if (dashed) ctx.setLineDash([6, 4]);
      ds.forEach((v, i) => { const x = toX(i), y = toY(v); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); });
      ctx.stroke();
      ctx.setLineDash([]);
    };
    drawLine(midData, '#C4956A', 2.5, false);
    drawLine(data.map(d => d.buyRate), '#27AE60', 1.5, true);
    drawLine(data.map(d => d.sellRate), '#E74C3C', 1.5, true);
  }
});