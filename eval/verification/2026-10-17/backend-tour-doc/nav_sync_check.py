#!/usr/bin/env python3
"""导航一致性校验：19 章逐节跳转，左侧章节高亮与右侧页内目录是否跟随。

无头虚拟时间下浏览器不会为程序化 scrollIntoView 派发 scroll 事件，
所以探针在滚动后手动 dispatchEvent(new Event('scroll'))——真实浏览器的滚动一定会派发。

用法：python3 nav_sync_check.py <doc.html> [轮数]
"""
import re
import subprocess
import sys
import tempfile
import pathlib

CHROME = pathlib.Path.home() / ".cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
PROBE = r'''
<pre id="RESULT" style="white-space:pre-wrap;font:12px monospace"></pre>
<script>
var out=[],tg=[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19],i=0;
window.__errs=[];window.onerror=function(m){window.__errs.push(String(m))};
document.documentElement.style.scrollBehavior='auto';
function step(){
  if(i>=tg.length){ out.push('JS_ERRORS='+JSON.stringify(window.__errs));
    document.getElementById('RESULT').textContent='===RESULT===\n'+out.join('\n')+'\n===END==='; return; }
  var n=tg[i], sec=document.getElementById('c'+n);
  sec.scrollIntoView({behavior:'instant',block:'start'});
  window.dispatchEvent(new Event('scroll'));
  setTimeout(function(){
    var nav=(document.querySelector('.nav-item.on')||{}).textContent||'(none)';
    var ok=nav.trim().indexOf(String(n)+' ·')===0;
    out.push((ok?'OK  ':'FAIL')+' c'+n+' 左='+nav.slice(0,18)
      +' 右='+document.getElementById('toc').textContent.replace(/\s+/g,' ').trim().slice(0,34));
    i++; step();
  },140);
}
window.addEventListener('load',function(){setTimeout(step,300)});
</script>'''

def main():
    doc = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    tmp = pathlib.Path(tempfile.mkdtemp()) / "nav.html"
    tmp.write_text(doc.replace("</body>", PROBE + "</body>"), encoding="utf-8")
    bad = 0
    for r in range(1, rounds + 1):
        dom = subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox",
                              "--hide-scrollbars", "--window-size=1440,1200",
                              "--virtual-time-budget=20000", "--dump-dom", tmp.as_uri()],
                             capture_output=True, text=True).stdout
        m = re.search(r"===RESULT===(.*?)===END===", dom, re.S)
        body = (m.group(1).strip() if m else "!! 探针未产出结果")
        fails = body.count("FAIL")
        bad += fails
        print(f"== 第 {r} 轮：FAIL {fails} ==")
        print(body)
        print()
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
