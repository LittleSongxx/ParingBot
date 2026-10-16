"""消融实验切臂工具：切换 SMARTLECT_DISPATCH_ENABLED 并重启 assistant。

用法：
  python3 scripts/ablation_arm.py status
  python3 scripts/ablation_arm.py arm A   # Supervisor-Workers：task_dispatch 可见
  python3 scripts/ablation_arm.py arm B   # 单 Agent 对照：task_dispatch 结构性不可见

事实基础（2026-10-06 核验）：生效系统提示词是 DB 模板（热更新覆盖代码常量），
其正文不含任何派发措辞——派发指引唯一载体是 task_dispatch 的工具 description，
随 schema 在 B 臂一并移除。因此两臂系统提示词逐字节相同，唯一架构差异
即工具可见性；臂别经 audit.dispatch_enabled 与 -nd 标签双重落库。
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / 'run' / 'runtime.env'
FLAG = 'SMARTLECT_DISPATCH_ENABLED'


def read_flag() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith(FLAG + '='):
            return line.split('=', 1)[1].strip()
    return '(未设置, 默认 true → A 臂)'


def load_runtime_env() -> None:
    for line in ENV_FILE.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())


def prompt_dispatch_wording() -> int:
    load_runtime_env()
    from smartlect.prompts import PromptStore
    active = PromptStore().active('shopping', 'system_prompt', 'system') or {}
    body = active.get('body') or ''
    return sum(body.count(word) for word in ('task_dispatch', '派发', '子智能体', '并行'))


def set_flag(value: str) -> None:
    lines = ENV_FILE.read_text().splitlines()
    out, replaced = [], False
    for line in lines:
        if line.startswith(FLAG + '='):
            out.append(f'{FLAG}={value}')
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f'{FLAG}={value}')
    ENV_FILE.write_text('\n'.join(out) + '\n')


def restart_assistant() -> None:
    for pid in subprocess.run(['pgrep', '-f', 'smartlect.app'], capture_output=True,
                              text=True).stdout.split():
        subprocess.run(['kill', pid], check=False)
    subprocess.run([str(ROOT / 'scripts' / 'dev.sh'), 'up'], capture_output=True, text=True)
    port = next((line.split('=', 1)[1] for line in ENV_FILE.read_text().splitlines()
                 if line.startswith('SMARTLECT_ASSISTANT_PORT=')), '18001')
    for _ in range(30):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port.strip()}/health', timeout=2) as resp:
                if resp.status == 200:
                    print('assistant 已重启并通过健康检查')
                    return
        except Exception:
            time.sleep(4)
    raise SystemExit('assistant 重启后健康检查超时')


def status() -> None:
    wording = prompt_dispatch_wording()
    print(f'进程开关 {FLAG} = {read_flag()}')
    print(f'DB 系统提示词派生措辞计数 = {wording}（应为 0，保证两臂提示词同文）')


def switch(arm: str) -> None:
    if prompt_dispatch_wording() != 0:
        raise SystemExit('DB 模板出现派发措辞，两臂提示词不再同文——先人工核验再继续')
    set_flag('true' if arm == 'A' else 'false')
    restart_assistant()
    print(f'已切到 {arm} 臂：{FLAG}={read_flag()}')


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'status':
        status()
    elif len(sys.argv) >= 3 and sys.argv[1] == 'arm' and sys.argv[2] in {'A', 'B'}:
        switch(sys.argv[2])
    else:
        print(__doc__)
