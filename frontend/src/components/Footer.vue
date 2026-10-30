<template>
  <footer class="footer-wrap">
    <div class="footer-inner">
      <div class="footer-brand">
        <img src="@/assets/imgs/logo-bot.svg" alt="ParingBot" />
        <div class="footer-brand-text">
          <b>ParingBot</b>
          <span>智能合租匹配平台</span>
        </div>
      </div>
      <div class="footer-meta">
        <span>站内租客档案、头像与动态均为虚构，仅用于功能演示</span>
        <span class="footer-sep"></span>
        <span>CopyRight 2026© ParingBot</span>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.footer-wrap {
  margin-top: 30px;
  border-top: 1px solid var(--pb-line);
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(10px);
}

.footer-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 20px;
  padding: 18px 20px;
}

.footer-brand { display: flex; align-items: center; gap: 9px; }
.footer-brand img { width: 26px; height: 26px; border-radius: 8px; }
.footer-brand-text { display: flex; flex-direction: column; line-height: 1.25; }
.footer-brand-text b { font-size: 13px; color: var(--pb-text); }
.footer-brand-text span { font-size: 11px; color: var(--pb-muted); }

.footer-meta { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--pb-faint); }
.footer-sep { width: 1px; height: 12px; background: var(--pb-line-strong); }
</style>
