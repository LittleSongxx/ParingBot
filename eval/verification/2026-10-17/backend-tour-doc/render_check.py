#!/usr/bin/env python3
"""后端全景讲解 HTML 的渲染量化校验（可复跑）。

把待检文档复制一份并在 </body> 前注入探针脚本，用无头 Chromium 跑完后解析结果。
检查项：图内文字越界 viewBox / 文字互相压字 / 文字溢出所属方框 / 窄窗口下图内字号 < 9px /
        SVG 比例异常 / figure 内逃逸文本 / 放大层与主题切换 / JS 报错。

用法：python3 render_check.py <doc.html> [视口宽度...]
"""
import re, subprocess, sys, tempfile, pathlib

CHROME = pathlib.Path.home()/".cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
PROBE = r'''
<pre id="RESULT" style="white-space:pre-wrap;font:12px monospace"></pre>
<script>
window.__errs=[];window.onerror=function(m){__errs.push(String(m))};
setTimeout(function(){
  var out=[];function r(n){return Math.round(n*10)/10}
  var svgs=[].slice.call(document.querySelectorAll('svg.sv'));
  out.push('SVG_COUNT='+svgs.length);
  svgs.forEach(function(svg){
    var vb=svg.viewBox.baseVal, rect=svg.getBoundingClientRect(), scale=rect.width/vb.width;
    var fig=svg.closest('.fig'), title=fig?fig.getAttribute('data-title'):'?';
    var boxes=[], rects=[].slice.call(svg.querySelectorAll('rect'));
    [].slice.call(svg.querySelectorAll('text')).forEach(function(t){
      var b; try{b=t.getBBox()}catch(e){out.push('  BBOX_ERR '+title);return}
      var eff=parseFloat(getComputedStyle(t).fontSize)*scale;
      boxes.push({t:t,b:b});
      if(b.x<-0.5||b.y<-0.5||b.x+b.width>vb.width+0.5||b.y+b.height>vb.height+0.5)
        out.push('  OOB ['+title+'] "'+t.textContent.slice(0,30)+'"');
      if(eff<9) out.push('  SMALLFONT ['+title+'] eff='+r(eff));
      var host=null;
      rects.forEach(function(rc){var rx=rc.x.baseVal.value,ry=rc.y.baseVal.value,rw=rc.width.baseVal.value,rh=rc.height.baseVal.value;
        var cx=b.x+b.width/2, cy=b.y+b.height/2;
        if(cx>rx&&cx<rx+rw&&cy>ry&&cy<ry+rh&&(!host||rw*rh<host.w*host.h)) host={x:rx,y:ry,w:rw,h:rh};});
      if(host && (host.x+host.w)-(b.x+b.width) < -2)
        out.push('  BLEED ['+title+'] 超框 '+r((b.x+b.width)-(host.x+host.w))+'px :: '+t.textContent.slice(0,36));
    });
    for(var i=0;i<boxes.length;i++)for(var j=i+1;j<boxes.length;j++){
      var A=boxes[i].b,B=boxes[j].b;
      var ox=Math.min(A.x+A.width,B.x+B.width)-Math.max(A.x,B.x), oy=Math.min(A.y+A.height,B.y+B.height)-Math.max(A.y,B.y);
      if(ox>1.5&&oy>1.5){var inter=ox*oy,minA=Math.min(A.width*A.height,B.width*B.height);
        if(inter/minA>0.18) out.push('  OVERLAP ['+title+'] "'+boxes[i].t.textContent.slice(0,16)+'" × "'+boxes[j].t.textContent.slice(0,16)+'"');}
    }
    if(Math.abs(rect.height-rect.width*vb.height/vb.width)>2) out.push('  ASPECT ['+title+']');
  });
  document.querySelectorAll('.fig').forEach(function(f,i){
    var stray=[].slice.call(f.childNodes).filter(function(n){
      return (n.nodeType===3&&n.textContent.trim())||(n.nodeType===1&&n.tagName.toLowerCase()!=='figcaption'
        &&n.tagName.toLowerCase()!=='svg'&&!n.classList.contains('zoom-hint'));});
    if(stray.length) out.push('  STRAY_TEXT in figure#'+i);
  });
  document.querySelector('.fig').click();
  out.push('ZOOM_OPEN='+(!document.getElementById('zoom').hidden));
  document.getElementById('zclose').click();
  out.push('ZOOM_CLOSED='+document.getElementById('zoom').hidden);
  document.getElementById('themebtn').click();
  out.push('THEME_TOGGLE='+document.documentElement.getAttribute('data-theme'));
  out.push('NAV='+document.querySelectorAll('.nav-item').length+' SECTIONS='+document.querySelectorAll('main section').length);
  out.push('JS_ERRORS='+JSON.stringify(window.__errs));
  document.getElementById('RESULT').textContent='===RESULT===\n'+out.join('\n')+'\n===END===';
},900);
</script>'''

def main():
    doc = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
    widths = [int(w) for w in sys.argv[2:]] or [1460, 1180, 1000]
    tmp = pathlib.Path(tempfile.mkdtemp())/'probe.html'
    tmp.write_text(doc.replace('</body>', PROBE+'</body>'), encoding='utf-8')
    bad_total = 0
    for w in widths:
        dom = subprocess.run([str(CHROME),'--headless=new','--disable-gpu','--no-sandbox',
                              '--hide-scrollbars',f'--window-size={w},1000','--virtual-time-budget=6000',
                              '--dump-dom', tmp.as_uri()], capture_output=True, text=True).stdout
        m = re.search(r'===RESULT===(.*?)===END===', dom, re.S)
        body = m.group(1).strip() if m else '!! 探针未产出结果'
        bad = [l for l in body.split('\n') if l.strip().startswith(('OOB','OVERLAP','BLEED','SMALLFONT','ASPECT','STRAY'))]
        bad_total += len(bad)
        print(f'--- 视口 {w}px：问题 {len(bad)} ---')
        print(body)
        print()
    print('== 合计问题数:', bad_total)
    sys.exit(1 if bad_total else 0)

if __name__ == '__main__':
    main()
