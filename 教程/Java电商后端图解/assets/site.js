/* Smartlect 图解 · 导航 / 目录 / 主题切换 */
(function () {
  'use strict';
  var REV = '0e94e7c';
  var NAV = [
    { g: '开始', items: [
      { f: 'index.html', t: '首页 · 贯穿案例' },
      { f: 'pages/01-start.html', t: '项目速览' } ] },
    { g: '全景', items: [
      { f: 'pages/02-architecture.html', t: '总体架构' } ] },
    { g: '接入层', items: [
      { f: 'pages/03-gateway.html', t: '网关与认证' } ] },
    { g: '商品域', items: [
      { f: 'pages/04-product.html', t: '商品与搜索' },
      { f: 'pages/05-cart.html', t: '购物车' } ] },
    { g: '交易域', items: [
      { f: 'pages/06-stock.html', t: '库存扣减' },
      { f: 'pages/07-order.html', t: '下单五阶段' },
      { f: 'pages/08-pay.html', t: '支付与 Outbox' },
      { f: 'pages/09-lifecycle.html', t: '订单状态机' } ] },
    { g: '营销与售后', items: [
      { f: 'pages/10-coupon-rush.html', t: '优惠券秒杀' },
      { f: 'pages/11-refund.html', t: '退款 Saga' } ] },
    { g: '收尾', items: [
      { f: 'pages/12-consistency.html', t: '一致性总纲' },
      { f: 'pages/13-deploy.html', t: '部署拓扑' } ] }
  ];
  var base = document.body.dataset.base || './';

  /* 当前页在导航中的位置 */
  var flat = [];
  NAV.forEach(function (grp) { grp.items.forEach(function (it) { flat.push(it); }); });
  var here = location.pathname.split('/').pop() || 'index.html';
  var idx = -1;
  flat.forEach(function (it, i) { if (it.f.split('/').pop() === here || it.f === here) idx = i; });
  if (idx < 0) idx = 0;

  /* ── 左侧导航 ── */
  var sb = document.getElementById('sidebar');
  if (sb) {
    var openSaved = {};
    try { openSaved = JSON.parse(localStorage.getItem('sl-nav-open') || '{}'); } catch (e) {}
    NAV.forEach(function (grp, gi) {
      var gEl = document.createElement('div');
      gEl.className = 'nav-group';
      var containsHere = grp.items.some(function (it) { return it.f.split('/').pop() === here; });
      var isOpen = (openSaved[grp.g] !== undefined) ? openSaved[grp.g] : containsHere;
      if (isOpen) gEl.classList.add('open');
      var btn = document.createElement('button');
      btn.className = 'nav-gt';
      btn.innerHTML = '<span class="arr">▶</span>' + grp.g;
      btn.addEventListener('click', function () {
        gEl.classList.toggle('open');
        openSaved[grp.g] = gEl.classList.contains('open');
        localStorage.setItem('sl-nav-open', JSON.stringify(openSaved));
      });
      var list = document.createElement('div');
      list.className = 'nav-items';
      grp.items.forEach(function (it) {
        var a = document.createElement('a');
        a.href = base + it.f;
        a.textContent = it.t;
        if (it.f.split('/').pop() === here) a.classList.add('on');
        list.appendChild(a);
      });
      gEl.appendChild(btn); gEl.appendChild(list);
      sb.appendChild(gEl);
    });
  }

  /* ── 移动端菜单 ── */
  var burger = document.getElementById('burger');
  if (burger) {
    var mask = document.createElement('div'); mask.id = 'mask';
    document.body.appendChild(mask);
    burger.addEventListener('click', function () { document.body.classList.toggle('nav-open'); });
    mask.addEventListener('click', function () { document.body.classList.remove('nav-open'); });
  }

  /* ── 主题切换 ── */
  var themeBtn = document.getElementById('themeBtn');
  function applyTheme(t) {
    document.documentElement.dataset.theme = t;
    if (themeBtn) themeBtn.textContent = t === 'dark' ? '☀️' : '🌙';
    localStorage.setItem('sl-theme', t);
  }
  var saved = localStorage.getItem('sl-theme');
  applyTheme(saved || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  if (themeBtn) themeBtn.addEventListener('click', function () {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });

  /* ── 右侧本页目录 + 滚动高亮 ── */
  var tocList = document.getElementById('toc-list');
  var content = document.querySelector('.content');
  if (tocList && content) {
    var heads = Array.prototype.slice.call(content.querySelectorAll('h2, h3'));
    var ul = document.createElement('ul'), curUl = null, sub = null;
    heads.forEach(function (h, i) {
      h.id = h.id || ('sec-' + i);
      var li = document.createElement('li');
      var a = document.createElement('a');
      a.href = '#' + h.id;
      a.textContent = h.textContent;
      a.className = h.tagName === 'H3' ? 'lv3' : 'lv2';
      li.appendChild(a);
      if (h.tagName === 'H2') { ul.appendChild(li); curUl = li; sub = null; }
      else {
        if (!sub || !curUl) { sub = document.createElement('ul'); (curUl || ul).appendChild(sub); }
        sub.appendChild(li);
      }
    });
    tocList.appendChild(ul);
    var links = Array.prototype.slice.call(tocList.querySelectorAll('a'));
    if ('IntersectionObserver' in window && heads.length) {
      var obs = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) {
            links.forEach(function (l) { l.classList.remove('on'); });
            var active = links.filter(function (l) { return l.getAttribute('href') === '#' + en.target.id; })[0];
            if (active) active.classList.add('on');
          }
        });
      }, { rootMargin: '-80px 0px -70% 0px' });
      heads.forEach(function (h) { obs.observe(h); });
    }
  }

  /* ── 上下页 ── */
  var pager = document.getElementById('pager');
  if (pager && flat.length > 1 && idx > 0) {
    var prev = flat[idx - 1], next = flat[idx + 1];
    function paged(it, cls, dir) {
      var a = document.createElement('a');
      a.href = base + it.f; a.className = cls;
      a.innerHTML = '<div class="dir">' + dir + '</div><div class="pt">' + it.t + '</div>';
      return a;
    }
    if (prev) pager.appendChild(paged(prev, 'prev', '← 上一页'));
    if (next) pager.appendChild(paged(next, 'next', '下一页 →'));
  }

  /* ── 阅读进度条 ── */
  var bar = document.createElement('div'); bar.id = 'progress';
  document.body.appendChild(bar);
  addEventListener('scroll', function () {
    var h = document.documentElement;
    var max = h.scrollHeight - h.clientHeight;
    bar.style.width = (max > 0 ? (h.scrollTop / max) * 100 : 0) + '%';
  }, { passive: true });

  /* ── 证据锚点：class="ev" 自动链接到 GitHub 对应行 ── */
  Array.prototype.forEach.call(document.querySelectorAll('a.ev[data-p]'), function (a) {
    var p = a.dataset.p, line = a.dataset.l;
    var url = 'https://github.com/LittleSongxx/Smartlect/blob/' + REV + '/' + p + (line ? '#L' + line : '');
    a.href = url; a.target = '_blank'; a.rel = 'noopener';
    a.title = p + (line ? ':' + line : '');
  });
})();
