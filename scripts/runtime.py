"""Local Smartlect middleware operations; credentials never leave run/."""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "run/runtime.env"
PROCESS_FILE = ROOT / "run/processes.json"
PROCESS_LOCK = ROOT / "run/processes.lock"
DATABASES = ("admin", "user", "product", "stock", "cart", "order", "pay", "coupon")
APPS = ("assistant", "user", "product", "stock", "order", "pay", "cart", "coupon", "admin", "gateway", "web-user", "web-admin")
PORTS = {"MYSQL": 13306, "REDIS": 16379, "ROCKETMQ_NAMESRV": 9876, "ROCKETMQ_GRPC": 8081, "NACOS": 18848, "ES": 9200, "QDRANT": 6333, "CANAL": 11111, "XXLJOB": 18090, "LITELLM": 14000,
         "GATEWAY": 18080, "GROWTH": 18000, "DASHBOARD": 18501,
         "ADMIN": 18101, "USER": 18105, "PRODUCT": 18106, "STOCK": 18108,
         "CART": 18102, "ORDER": 18104, "PAY": 18103, "COUPON": 18107, "WEB_USER": 18180, "WEB_ADMIN": 18181}


def run(*args, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True,
                          capture_output=capture).stdout


def parse_env(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line and not line.startswith("#"))


def model_env(path=None):
    path = path or ROOT / "run/model.env"
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o777 != 0o600:
        raise RuntimeError("run/model.env must be a regular file with mode 600")
    allowed = {"SMARTLECT_" + field for field in (
        "MODEL_API_KEY", "MODEL_BASE_URL", "MODEL_ID", "EMBEDDING_API_KEY", "EMBEDDING_BASE_URL",
        "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS", "EMBEDDING_PROVIDER", "RERANK_API_KEY",
        "RERANK_BASE_URL", "RERANK_MODEL", "RERANK_API_FORMAT",
        "JUDGE_API_KEY", "JUDGE_BASE_URL", "JUDGE_MODEL")}
    values = parse_env(path)
    if set(values) - allowed:
        raise RuntimeError("run/model.env contains non-model fields; values suppressed")
    return values


def service_env(service, env):
    """Assistant processes must receive model.env; app_launch used to merge it locally
    and then throw the copy away, so live mode started with no keys."""
    if service == "assistant":
        return {**env, **model_env()}
    return dict(env)


def free_ports(start, offsets=(0,), occupied=None, host="127.0.0.1"):
    occupied = occupied or set()
    for port in range(start, 64000):
        sockets = []
        try:
            if any(port + offset in occupied for offset in offsets):
                continue
            for offset in offsets:
                sock = socket.socket()
                sockets.append(sock)
                sock.bind((host, port + offset))
            return port
        except OSError:
            continue
        finally:
            for sock in sockets:
                sock.close()
    raise RuntimeError(f"No free port above {start}")


def local_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 1))
        return sock.getsockname()[0]


def bootstrap():
    if ENV_FILE.exists():
        env = parse_env(ENV_FILE)
        web_port = env.get('SMARTLECT_WEB_USER_PORT') or str(free_ports(PORTS['WEB_USER'], occupied={
            int(v) for k, v in env.items() if k.endswith('_PORT')}))
        admin_port = env.get('SMARTLECT_WEB_ADMIN_PORT') or str(free_ports(PORTS['WEB_ADMIN'], occupied={
            int(v) for k, v in env.items() if k.endswith('_PORT')} | {int(web_port)}))
        candidate = {
            "SMARTLECT_DEMO_ENABLED": "true", "SMARTLECT_DEMO_PASSWORD": secrets.token_hex(24),
            "SMARTLECT_VISITOR_SECRET": secrets.token_hex(32),
            "SMARTLECT_ATTRIBUTION_SECRET": secrets.token_hex(32),
            "SMARTLECT_ALLOWED_ORIGINS": "http://127.0.0.1:" + env["SMARTLECT_GATEWAY_PORT"],
            "SMARTLECT_WEB_USER_PORT": web_port,
            "SMARTLECT_WEB_ADMIN_PORT": admin_port,
            "SMARTLECT_GROWTH_MYSQL_SSL": "0",
        }
        additions = {key: value for key, value in candidate.items() if key not in env}
        if additions:
            with ENV_FILE.open("a") as target:
                target.write("\n" + "\n".join(f"{key}={value}" for key, value in additions.items()) + "\n")
            print("Added missing Smartlect demo configuration; existing credentials and ports are unchanged.")
        else:
            print("Keeping existing Smartlect credentials and ports: run/runtime.env")
        origins = env.get('SMARTLECT_ALLOWED_ORIGINS', 'http://127.0.0.1:' + env['SMARTLECT_GATEWAY_PORT']).split(',')
        required_origins = ['http://127.0.0.1:' + port for port in (web_port, admin_port)]
        missing = [origin for origin in required_origins if origin not in origins]
        if missing:
            with ENV_FILE.open('a') as target:
                target.write('\nSMARTLECT_ALLOWED_ORIGINS=' + ','.join([*origins, *missing]) + '\n')
        return
    ENV_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if run("git", "check-ignore", "run/runtime.env", capture=True).strip() != "run/runtime.env":
        raise RuntimeError("run/runtime.env must be ignored by Git")
    env = {
        "SMARTLECT_MYSQL_HOST": "127.0.0.1", "SMARTLECT_MYSQL_USER": "smartlect_app",
        "SMARTLECT_FLYWAY_USER": "smartlect_flyway",
        "SMARTLECT_REDIS_HOST": "127.0.0.1", "SMARTLECT_REDIS_USERNAME": "",
        "SMARTLECT_REDIS_DB": "0", "SMARTLECT_ROCKETMQ_ENDPOINTS": "127.0.0.1:8081",
        "SMARTLECT_NACOS_USERNAME": "nacos", "SMARTLECT_NACOS_NAMESPACE": "",
        "SMARTLECT_NACOS_GROUP": "SMARTLECT_GROUP",
        "SMARTLECT_ES_URL": "http://127.0.0.1:9200",
        "SMARTLECT_QDRANT_URL": "http://127.0.0.1:6333",
        "SMARTLECT_GROWTH_MYSQL_USER": "smartlect_growth",
        "SMARTLECT_GROWTH_MYSQL_DATABASE": "smartlect_growth",
        "SMARTLECT_GROWTH_MYSQL_SSL": "0",
        "SMARTLECT_MODEL_MODE": "mock", "SMARTLECT_PAYMENT_MODE": "mock", "SMARTLECT_DEMO_ENABLED": "true",
    }
    password_keys = ["MYSQL_ROOT_PASSWORD", "MYSQL_PASSWORD", "FLYWAY_PASSWORD",
                     "REDIS_PASSWORD", "NACOS_PASSWORD",
                     "NACOS_MYSQL_PASSWORD", "NACOS_IDENTITY",
                     "INTERNAL_TOKEN", "INTERNAL_OPS_TOKEN",
                     "GROWTH_MYSQL_PASSWORD", "CANAL_MYSQL_PASSWORD",
                     "XXLJOB_MYSQL_PASSWORD", "XXLJOB_TOKEN",
                     "LITELLM_MASTER_KEY",
                     "ADMIN_PASSWORD", "DEMO_PASSWORD", "VISITOR_SECRET", "ATTRIBUTION_SECRET"]
    for key in password_keys:
        env[f"SMARTLECT_{key}"] = secrets.token_hex(24)
    env["SMARTLECT_NACOS_AUTH_TOKEN"] = base64.b64encode(secrets.token_bytes(48)).decode()
    occupied = set()
    for name, default in PORTS.items():
        offsets = (0, 1000) if name == "NACOS" else (0,)
        host = "127.0.0.1"
        port = free_ports(default, offsets, occupied, host)
        env[f"SMARTLECT_{name}_PORT"] = str(port)
        occupied.update(port + offset for offset in offsets)
    env["SMARTLECT_NACOS_GRPC_PORT"] = str(int(env["SMARTLECT_NACOS_PORT"]) + 1000)
    env["SMARTLECT_NACOS_ADDR"] = "127.0.0.1:" + env["SMARTLECT_NACOS_PORT"]
    env["SMARTLECT_GROWTH_BASE_URL"] = "http://127.0.0.1:" + env["SMARTLECT_GROWTH_PORT"]
    env["SMARTLECT_ALLOWED_ORIGINS"] = ','.join('http://127.0.0.1:' + env[k] for k in ('SMARTLECT_GATEWAY_PORT', 'SMARTLECT_WEB_USER_PORT', 'SMARTLECT_WEB_ADMIN_PORT'))
    with ENV_FILE.open("x") as target:
        os.chmod(ENV_FILE, 0o600)
        target.write("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
    print("Created independent credentials and available ports in run/runtime.env (mode 600).")


def cluster_node_env():
    """集群编排的节点拓扑（deploy/cluster/nodes.env），注入给 docker compose 用。

    单机形态没有这个文件，返回空——compose 命令与从前逐字一致。
    """
    path = ROOT / "deploy/cluster/nodes.env"
    if not path.exists():
        return {}
    return {key: value for key, value in parse_env(path).items() if not key.startswith("CLUSTER_SSH")}


def compose(*args, capture=False, cluster=False):
    files = ["-f", str(ROOT / "deploy/compose.yaml")]
    override = ROOT / "deploy/cluster/compose.node1.yaml"
    if cluster and override.exists():
        # 集群期叠加内网绑定；该文件把单机 rocketmq/nacos 挂到 single-only profile，
        # 所以集群形态必须走这条路径，否则重启时会去拉单机容器、与集群成员抢端口。
        files += ["-f", str(override)]
    return subprocess.run(("docker", "compose", "--project-name", "smartlect", "--env-file",
                           str(ENV_FILE), *files, *args),
                          cwd=ROOT, check=True, text=True,
                          capture_output=capture, env={**os.environ, **cluster_node_env()}).stdout


def verify_project():
    ids = run("docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=smartlect", capture=True).split()
    if ids:
        for container in json.loads(run("docker", "inspect", *ids, capture=True)):
            labels = container["Config"]["Labels"]
            # 允许同一 checkout 的叠加文件（集群期 compose.cluster.yaml），仍拒绝外来 checkout
            files = (labels.get("com.docker.compose.project.config_files") or "").split(",")
            if str(ROOT / "deploy/compose.yaml") not in files:
                raise RuntimeError("Existing smartlect container belongs to another checkout; refusing to modify it")


def cluster_form(env):
    # SMARTLECT_CLUSTER_FORM=cluster：RabbitMQ/Nacos 由 /opt/cluster 下的多机编排提供，
    # 本机 compose 只保留 mysql/redis（见 deploy/cluster/）。
    return env.get("SMARTLECT_CLUSTER_FORM") == "cluster"


def app_bind_address(env):
    """应用监听的地址。默认回环——单机形态的行为一字不变。

    分机部署时设为 0.0.0.0：服务要能被跨机的网关/对端访问，同时本机的
    assistant（SMARTLECT_JAVA_BASE_URL=http://127.0.0.1）与健康检查仍走回环，
    不必为了跨机访问去改本机寻址。
    """
    return env.get("SMARTLECT_APP_BIND_ADDRESS") or "127.0.0.1"


def app_register_ip(env):
    """注册到 Nacos 的 IP。默认回环；分机部署时必须是本机内网 IP，
    否则别的节点拿到 127.0.0.1 会打到自己身上。"""
    return env.get("SMARTLECT_APP_REGISTER_IP") or "127.0.0.1"


def app_services(env):
    """本机要跑的服务子集。默认全部——单机形态仍是十二进程。

    分机部署时用 SMARTLECT_APP_SERVICES 指定本机承载的服务（逗号分隔），
    这样同一份 runtime.env 与同一套 JAR 可以在三台机器上分别拉起不同的副本。
    """
    raw = env.get("SMARTLECT_APP_SERVICES")
    if not raw:
        return APPS
    wanted = tuple(name.strip() for name in raw.split(",") if name.strip())
    unknown = [name for name in wanted if name not in APPS]
    if unknown:
        raise RuntimeError(f"SMARTLECT_APP_SERVICES contains unknown services: {', '.join(unknown)}")
    if not wanted:
        raise RuntimeError("SMARTLECT_APP_SERVICES is empty; unset it to run all services")
    return wanted


def wait_cluster(env, timeout=300, interval=5):
    """轮询等待集群中间件可达（开机单元的 ExecStartPre 用）。

    为什么需要它：重启后 Docker 容器（rabbit-c*/nacos-c*/redis-sentinel）的就绪
    晚于 systemd 单元启动，而 app 单元是 Type=oneshot——首次检查失败就永久放弃，
    结果是"容器都活了、应用副本一个没起"（2026-10-05 扩容重启实测如此）。
    这里把"等"变成显式步骤，让开机自愈真正闭环。
    """
    deadline = time.monotonic() + timeout
    if not cluster_form(env):
        # 单机形态没有集群中间件要等；本机容器由 smartlect-infra 的前置依赖保证。
        # 这条分支是回退安全的关键：否则 revert 回单机后开机单元会在此空等超时。
        print("Single-node form: no cluster middleware to wait for.")
        return
    attempt = 0
    while True:
        attempt += 1
        try:
            cluster_endpoint_check(env)
            print(f"Cluster middleware is ready (attempt {attempt}).")
            return
        except (RuntimeError, OSError, urllib.error.URLError) as error:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Cluster middleware still unreachable after {timeout}s: {error}") from error
            print(f"waiting for cluster middleware (attempt {attempt}): {error}", flush=True)
            time.sleep(interval)


def java_service_count(services):
    """进 Nacos 注册表的服务数：assistant 与两个前端不注册。"""
    return len(set(services) - {"assistant", "web-user", "web-admin"})


def health_host(env):
    """健康探针用的主机：绑 0.0.0.0 时走回环（更省），绑具体地址时就用那个地址。"""
    bind = app_bind_address(env)
    return "127.0.0.1" if bind in ("0.0.0.0", "::") else bind


def amqp_port_open(endpoint, timeout=3):
    host, _, port = endpoint.rpartition(":")
    with socket.socket() as probe:
        probe.settimeout(timeout)
        return probe.connect_ex((host, int(port))) == 0


def nacos_addr(env):
    # Nacos 客户端支持逗号分隔多地址；本脚本的单请求取首个成员即可
    return env["SMARTLECT_NACOS_ADDR"].split(",")[0]


def nacos_request(env, path, data):
    req = urllib.request.Request("http://" + nacos_addr(env) + path,
                                 data=urllib.parse.urlencode(data).encode())
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def infra_up(env):
    verify_project()
    clustered = cluster_form(env)
    # 必须与 infra_check 的期望集合一致，否则全新环境 bootstrap 后
    # canal / xxl-job-admin 从未被拉起，infra-check 必然失败。
    services = ["mysql", "redis", "rocketmq-namesrv", "rocketmq-broker", "rocketmq-proxy",
                "nacos", "elasticsearch", "qdrant", "canal", "xxl-job-admin"]
    if clustered:
        # 集群期 rocketmq/nacos 由 deploy/cluster 下的多机编排提供，本机 compose 里
        # 这些服务挂在 single-only profile，显式点名会报 service not enabled by profile。
        services = [name for name in services
                    if name not in ("rocketmq-namesrv", "rocketmq-broker", "rocketmq-proxy", "nacos")]
    compose("up", "-d", "--wait", "--wait-timeout", "240", *services, cluster=clustered)
    try:
        nacos_request(env, "/nacos/v1/auth/users/admin", {"password": env["SMARTLECT_NACOS_PASSWORD"]})
    except urllib.error.HTTPError as error:
        if error.code not in (400, 409):
            raise
    result = nacos_request(env, "/nacos/v1/auth/login",
                           {"username": env["SMARTLECT_NACOS_USERNAME"], "password": env["SMARTLECT_NACOS_PASSWORD"]})
    if not result.get("accessToken"):
        raise RuntimeError("Smartlect Nacos login failed")
    print("Smartlect middleware is healthy; commerce/assistant application readiness is a separate gate.")


def infra_check(env):
    verify_project()
    states = compose("ps", "--all", "--format", "{{.Service}} {{.Health}} {{.State}}", capture=True)
    # 逐字段比对：endswith("healthy running") 会把 "unhealthy running" 一起放行，
    # 等于门禁失效（xxl-job-admin 曾经因此长期 unhealthy 却无人发现）。
    healthy = set()
    for line in states.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "healthy" and parts[2] == "running":
            healthy.add(parts[0])
    if cluster_form(env):
        if not {"mysql", "redis"} <= healthy:
            raise RuntimeError("Middleware health check incomplete; run infra-up first")
        # RocketMQ 集群：任一 proxy gRPC 端点可连即通过（节点级故障由演练覆盖）
        endpoints = [ep for ep in (env.get("SMARTLECT_ROCKETMQ_ENDPOINTS") or "").split(",") if ep]
        if not endpoints or not any(amqp_port_open(ep) for ep in endpoints):
            raise RuntimeError("No RocketMQ cluster endpoint reachable")
    elif not {"mysql", "redis", "rocketmq-proxy", "nacos", "elasticsearch", "qdrant", "canal", "xxl-job-admin"} <= healthy:
        raise RuntimeError("Middleware health check incomplete; run infra-up first")
    token = nacos_request(env, "/nacos/v1/auth/login", {
        "username": env["SMARTLECT_NACOS_USERNAME"], "password": env["SMARTLECT_NACOS_PASSWORD"]})["accessToken"]
    sql = ("SELECT GRANTEE,TABLE_SCHEMA,PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES "
           "UNION SELECT GRANTEE,'*',PRIVILEGE_TYPE FROM information_schema.USER_PRIVILEGES "
           "WHERE PRIVILEGE_TYPE <> 'USAGE';")
    rows = compose("exec", "-T", "mysql", "sh", "-ec",
                   'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -N -uroot -e "$1"', "infra-check", sql, capture=True)
    privileges = [row.split("\t") for row in rows.splitlines()]
    for user, expected in (("smartlect_growth", {"smartlect_growth"}),
                           ("smartlect_app", {"smartlect_" + domain for domain in DATABASES}),
                           ("smartlect_flyway", {"smartlect_" + domain for domain in DATABASES})):
        grants = [row for row in privileges if row[0] == f"'{user}'@'%'"]
        if {row[1] for row in grants} != expected:
            raise RuntimeError(f"Unexpected schemas granted to {user}")
        if user == "smartlect_app":
            if {row[2] for row in grants} != {"SELECT", "INSERT", "UPDATE", "DELETE"}:
                raise RuntimeError("Unexpected commercial application privileges")
    print("Infrastructure checks passed: authenticated Nacos, isolated assistant(Flyway)/app grants.")


def cluster_endpoint_check(env):
    """应用副本节点（不承载中间件）的前置检查：只验证到集群中间件的连通性。

    与 infra_check 的区别是它不碰本机 compose——副本节点上没有 mysql/redis 容器，
    照搬 compose 健康检查必然失败。检查项都是"连得上就算过"，可用性由中间件集群自身保证。
    """
    endpoints = [("MySQL", env["SMARTLECT_MYSQL_HOST"], int(env["SMARTLECT_MYSQL_PORT"]))]
    for name, key in (("Redis sentinel", "SPRING_DATA_REDIS_SENTINEL_NODES"),
                      ("RocketMQ proxy", "SMARTLECT_ROCKETMQ_ENDPOINTS")):
        for endpoint in [ep for ep in (env.get(key) or "").split(",") if ep]:
            endpoints.append((name, *endpoint.rsplit(":", 1)))
    unreachable = []
    for name, host, port in endpoints:
        try:
            with socket.create_connection((host, int(port)), timeout=5):
                pass
        except OSError as error:
            unreachable.append(f"{name} {host}:{port} ({error})")
    if unreachable:
        raise RuntimeError("Cluster middleware unreachable: " + "; ".join(unreachable))
    nacos_request(env, "/nacos/v1/auth/login", {
        "username": env["SMARTLECT_NACOS_USERNAME"], "password": env["SMARTLECT_NACOS_PASSWORD"]})
    print(f"Cluster endpoint checks passed: {len(endpoints)} middleware endpoints reachable, Nacos authenticated.")


def process_identity(pid):
    proc = Path("/proc") / str(pid)
    for _ in range(100):
        try:
            fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] == "Z":
                return None
            cmdline = (proc / "cmdline").read_bytes().rstrip(b"\0")
            executable, cwd = os.readlink(proc / "exe"), os.readlink(proc / "cwd")
            after = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            if after[0] == "Z":
                return None
            if cmdline and fields[19] == after[19] and executable == os.readlink(proc / "exe"):
                return {"pid": pid, "start_ticks": fields[19], "exe": executable,
                        "cwd": cwd, "cmdline": cmdline.decode().split("\0")}
        except (FileNotFoundError, ProcessLookupError):
            if not proc.exists():
                return None
        time.sleep(0.01)
    raise RuntimeError(f"PID {pid} has no stable readable identity; refusing to signal it")


def owned_process(record):
    identity = process_identity(record["pid"])
    if identity is None:
        return False
    if any(identity[key] != record[key] for key in identity) or identity["cwd"] != str(ROOT):
        # 身份不匹配 = 该 PID 已被系统复用为他人进程：视为非本方进程。
        # 绝不信号（安全性不变），但也不 raise——陈旧台账记录曾两次把整批 up/down
        # 卡死成停机（2026-09-16/19）；返回 False 让调用方跳过并随批次覆盖自愈。
        return False
    return True


@contextlib.contextmanager
def ledger_lock():
    """up/down 整批互斥：台账是无锁的读-改-写，并发批次会互相覆盖登记
    （2026-09-19 线上部署事故根因）。读者不加锁——save 的 tmp+replace 保证原子可见。"""
    if PROCESS_LOCK.is_symlink():
        raise RuntimeError(f"Process ledger lock is a symlink; refusing: {PROCESS_LOCK}")
    PROCESS_LOCK.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(PROCESS_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def load_processes():
    return json.loads(PROCESS_FILE.read_text()) if PROCESS_FILE.exists() else {}


def save_processes(records):
    # tmp 名带 pid：即使锁被绕过也不会两个写者互踩同一临时文件
    temporary = PROCESS_FILE.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(records, indent=2) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(PROCESS_FILE)


def signal_process(record, signum):
    if not hasattr(os, "pidfd_open"):
        try:
            if owned_process(record):
                os.kill(record["pid"], signum)
        except ProcessLookupError:
            pass
        return
    try:
        pidfd = os.pidfd_open(record["pid"])
    except ProcessLookupError:
        return
    try:
        if owned_process(record):
            signal.pidfd_send_signal(pidfd, signum)
    except ProcessLookupError:
        pass
    finally:
        os.close(pidfd)


def stop_process(record):
    if not owned_process(record):
        return
    signal_process(record, signal.SIGTERM)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if not owned_process(record):
            return
        time.sleep(0.2)
    if owned_process(record):
        signal_process(record, signal.SIGKILL)


def apps_down():
    with ledger_lock():
        records = load_processes()
        for service in reversed(APPS):
            if service in records:
                stop_process(records[service])
                del records[service]
                save_processes(records)
                print(f"Stopped Smartlect {service}.", flush=True)


def app_health(service, record):
    if not owned_process(record):
        return False
    path = '/admin/' if service == 'web-admin' else '/' if service == 'web-user' else "/health" if service == "assistant" else "/actuator/health"
    # health_host 由 start_app 写入台账；缺省回环，兼容旧台账
    host = record.get("health_host") or "127.0.0.1"
    try:
        with urllib.request.urlopen(f"http://{host}:{record['port']}{path}", timeout=2) as response:
            if service in {'web-user', 'web-admin'}:
                return response.status == 200 and b'Smartlect' in response.read(8192)
            health = json.load(response)
        return health.get("status") in ("UP", "ok")
    except (OSError, ValueError, KeyError):
        return False


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_fingerprint(directory):
    files = sorted(path for path in directory.rglob("*") if path.is_file()
                   and "__pycache__" not in path.parts and path.suffix != ".pyc")
    if not files:
        raise RuntimeError(f"Installed Python package contains no source files: {directory}")
    manifest = "\n".join(f"{path.relative_to(directory)}:{file_sha256(path)}" for path in files)
    return hashlib.sha256(manifest.encode()).hexdigest(), max(path.stat().st_mtime_ns for path in files)


def immutable_jar(source, directory):
    # ponytail: retain old hashes; prune only inactive snapshots if disk usage matters.
    before = source.stat()
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=directory, suffix=".tmp")
    os.close(descriptor)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        after = source.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise RuntimeError(f"JAR changed while copying: {source}; wait for build completion")
        try:
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() or not any(name.startswith("BOOT-INF/classes/") for name in archive.namelist()):
                    raise RuntimeError(f"Incomplete executable JAR: {source}; wait for build completion")
        except zipfile.BadZipFile as error:
            raise RuntimeError(f"Invalid JAR: {source}; wait for build completion") from error
        digest = file_sha256(temporary)
        target = directory / f"{digest}.jar"
        if target.exists():
            if file_sha256(target) != digest:
                raise RuntimeError(f"Immutable runtime JAR checksum changed: {target}")
        else:
            temporary.chmod(0o444)
            os.link(temporary, target)
        return target, digest, after.st_mtime_ns
    finally:
        temporary.unlink(missing_ok=True)


def java_launch_args(service, env):
    """Java 服务的 JAR 与命令行参数（start_app 与 smoke 共用一份，冒烟才真的等价）。"""
    module = ROOT / "backend" / f"smartlect-{service}"
    target = module / ("target" if service in ("admin", "gateway") else "app/target")
    artifacts = list(target.glob(f"smartlect-{service}-*.jar"))
    if len(artifacts) != 1:
        raise RuntimeError(f"Expected one executable JAR for {service}; run build first")
    artifact = artifacts[0]
    runtime_jar, source_sha, stamp = immutable_jar(artifact, ROOT / "run/apps" / service)
    executable = Path(shutil.which("java") or "/missing-java")
    # JVM 规格 env 化：默认值即 4c16g 共享机的保守配置；升配后按新规格调大。
    # 服务级键（SMARTLECT_JAVA_PROCESSORS_GATEWAY 等）优先于全局键，用于给
    # 网关/热点服务单独提预算；默认行为与纯全局键时代完全一致。
    def jvm(key, default):
        return env.get(f"{key}_{service.upper().replace('-', '_')}", env.get(key, default))
    command = [str(executable),
               "-Xms" + jvm("SMARTLECT_JAVA_XMS", "64m"),
               "-Xmx" + jvm("SMARTLECT_JAVA_XMX", "256m"),
               "-XX:MaxMetaspaceSize=192m", "-XX:MaxDirectMemorySize=64m",
               "-XX:ActiveProcessorCount=" + jvm("SMARTLECT_JAVA_PROCESSORS", "2"),
               f"-Dcsp.sentinel.log.dir={ROOT}/run/logs/sentinel/{service}",
               f"-DJM.LOG.PATH={ROOT}/run/logs/{service}",
               f"-DJM.SNAPSHOT.PATH={ROOT}/run/cache/{service}",
               "-jar", str(runtime_jar),
               f"--server.address={app_bind_address(env)}",
               f"--spring.cloud.nacos.discovery.ip={app_register_ip(env)}"]
    # OTel javaagent 只能经命令行注入（JAVA_TOOL_OPTIONS 已剥离）；agent 文件
    # 不存在时（本地无追踪）完全不影响原命令。约束 #7：改本函数后
    # check_independence + 进程身份核验必须仍过。
    agent = env.get("SMARTLECT_OTEL_AGENT") or str(ROOT / "run" / "opentelemetry-javaagent.jar")
    if not Path(agent).is_file():
        agent = "/opt/otel/opentelemetry-javaagent.jar"
    if Path(agent).is_file():
        # SMARTLECT_OTEL_EXPORTER 同时供 assistant(Python, 需含 /v1/traces 全路径)；
        # Java agent 只要基址（自动追加 /v1/traces、/v1/logs），必须剥掉后缀。
        endpoint = env.get("SMARTLECT_OTEL_EXPORTER", "http://127.0.0.1:4318").rstrip("/")
        if endpoint.endswith("/v1/traces"):
            endpoint = endpoint[: -len("/v1/traces")]
        command[1:1] = [f"-javaagent:{agent}",
                        f"-Dotel.service.name=smartlect-{service}",
                        f"-Dotel.exporter.otlp.endpoint={endpoint}",
                        "-Dotel.exporter.otlp.protocol=http/protobuf"]
    return executable, command, source_sha, stamp, runtime_jar


def launch_env_for(service, env):
    launch_env = {**os.environ, **service_env(service, env)}
    for variable in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "PYTHONPATH"):
        launch_env.pop(variable, None)
    # 上传目录默认本机 run/uploads；分机部署时由 env 指向共享挂载（NFS/对象存储），
    # 否则同一张图片在 A 副本写入、B 副本读不到。
    launch_env["SMARTLECT_PROJECT_FOLDER"] = (env.get("SMARTLECT_PROJECT_FOLDER")
                                              or str(ROOT / "run/uploads") + "/")
    launch_env['LANGSMITH_TRACING'] = 'false'
    launch_env['LANGCHAIN_TRACING_V2'] = 'false'
    if service in {'web-user', 'web-admin'}:
        launch_env = {k: v for k, v in os.environ.items() if k in {'PATH', 'LANG', 'LC_ALL', 'TZ'}}
    return launch_env


def smoke_apps(env, timeout=180):
    """启动前冒烟：同一份 JAR、同一份 env，只多一个 --spring.main.web-application-type=none。

    装配期错误（缺构造器、Bean 冲突、Flyway 连不上库）会让上下文刷新失败并打出
    "APPLICATION FAILED TO START"，而不必等全部应用停掉再发现——2026-09-16 就是因为
    没有这一步把整站停在了 502 上。非 web 应用不会自己退出（Nacos/连接池有非守护线程），
    所以用例以启动日志为准：看到 "Started ... in ... seconds" 即通过，随后主动回收进程。
    """
    failures = []
    for service in app_services(env):
        if service in {"assistant", "web-user", "web-admin"}:
            continue
        executable, command, _, _, _ = app_launch(service, env)
        if not executable.exists():
            failures.append((service, f"missing java: {executable}"))
            continue
        # gateway 是 WebFlux 应用：非 web 模式下 NettyConfiguration 拿不到 ServerProperties，
        # 只能按 reactive 起来并绑随机端口；同时关掉服务注册，避免冒烟进程进 Nacos 名单。
        if service == "gateway":
            smoke = [*command, "--spring.main.web-application-type=reactive", "--server.port=0",
                     "--spring.cloud.nacos.discovery.enabled=false"]
        else:
            smoke = [*command, "--spring.main.web-application-type=none"]
        smoke += ["--spring.main.banner-mode=off", "--logging.level.root=INFO"]
        started = time.monotonic()
        process = subprocess.Popen(smoke, cwd=ROOT, env=launch_env_for(service, env),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, start_new_session=True)
        lines = []
        outcome = None
        try:
            deadline = started + timeout
            while time.monotonic() < deadline:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue
                lines.append(line.rstrip())
                if "Started " in line and " in " in line and "seconds" in line:
                    outcome = "ok"
                    break
                if "APPLICATION FAILED TO START" in line:
                    outcome = "failed"
                    break
            if outcome is None:
                outcome = "failed" if process.poll() not in (None, 0) else "timeout"
        finally:
            for reader in (process.stdout, process.stderr):
                if reader is not None:
                    reader.close()
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
        elapsed = time.monotonic() - started
        if outcome == "ok":
            print(f"smoke: {service} ok ({elapsed:.0f}s)")
            continue
        detail = "\n".join(lines[-8:]) or "（无输出）"
        failures.append((service, f"{outcome} after {elapsed:.0f}s\n{detail}"))
        print(f"smoke: {service} FAILED ({outcome}, {elapsed:.0f}s)")
    if failures:
        for service, detail in failures:
            print(f"smoke failure [{service}]:\n{detail}", file=sys.stderr)
        raise RuntimeError(f"启动冒烟失败：{', '.join(service for service, _ in failures)}")


def app_launch(service, env):
    """解析某服务的可执行文件、命令行与产物指纹（不启动任何东西）。

    start_app 与部署前的 check-apps / smoke 共用同一份解析：2026-09-17 因为
    start_app 里少绑定一个产物路径，重启直接失败导致整站不可用——把"能不能拼出
    启动计划"变成可独立验证的一步，才能在下线重启前发现。
    """
    if service == "assistant":
        executable = ROOT / "assistant/.venv/bin/python"
        command = [str(executable), "-I", "-m", "smartlect.app"]
        artifact = Path(run(str(executable), "-I", "-c",
                            "import importlib.util; print(next(iter(importlib.util.find_spec('smartlect').submodule_search_locations)))",
                            capture=True).strip())
        source_sha, stamp = package_fingerprint(artifact)
    elif service in {'web-user', 'web-admin'}:
        frontend = ROOT / 'web' / service.removeprefix('web-')
        config = frontend / ('vite.config.ts' if service == 'web-user' else 'vite.config.js')
        artifact = frontend / 'dist'
        source_sha, stamp = package_fingerprint(artifact)
        source_sha = hashlib.sha256((source_sha + file_sha256(config)
                                    + file_sha256(frontend / 'package-lock.json')).encode()).hexdigest()
        executable = Path(shutil.which('node') or '/missing-node')
        command = [str(executable), str(frontend / 'node_modules/vite/bin/vite.js'), 'preview',
                   str(frontend), '--config', str(config)]
    else:
        executable, command, source_sha, stamp, artifact = java_launch_args(service, env)
    if not executable.exists():
        raise RuntimeError(f"Missing runtime executable for {service}; run build first")
    if not Path(artifact).exists():
        raise RuntimeError(f"Missing runtime artifact for {service}: {artifact}; run build first")
    return executable, command, source_sha, stamp, artifact


def check_apps(env):
    """部署前自检：为每个服务拼一遍启动计划，确认可执行文件与产物都在。"""
    for service in app_services(env):
        executable, command, _, _, artifact = app_launch(service, env)
        print(f"check: {service} ok ({Path(artifact).name})")


def start_app(service, env, records):
    executable, command, source_sha, stamp, artifact = app_launch(service, env)
    env_stamp = hashlib.sha256(json.dumps(service_env(service, env), sort_keys=True).encode()).hexdigest()
    if service in records and owned_process(records[service]):
        if (records[service].get("source_sha256") == source_sha and records[service].get("env_stamp") == env_stamp
                and records[service]["cmdline"] == command):
            return
        stop_process(records[service])
    # env 前缀沿用历史 growth 命名（线上 .env/数据库不随服务改名），这里显式映射。
    port_env = {"assistant": "SMARTLECT_GROWTH_PORT"}.get(service, f"SMARTLECT_{service.upper().replace('-', '_')}_PORT")
    port = int(env[port_env])
    if port is not None:
        # 预检端口占用：按实际绑定地址探测（绑 0.0.0.0 时通配探测，能同时挡住
        # 别的进程占着某个具体地址的情况）
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((app_bind_address(env), port))
    launch_env = launch_env_for(service, env)
    if service in {'web-user', 'web-admin'}:
        launch_env['SMARTLECT_' + service.upper().replace('-', '_') + '_PORT'] = str(port)
        launch_env['SMARTLECT_GATEWAY_URL'] = 'http://127.0.0.1:' + env['SMARTLECT_GATEWAY_PORT']
    logs = ROOT / "run/logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / f"smartlect-{service}.log").open("a") as output:
        output.write(f"\nSmartlect {service} startup at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        output.flush()
        process = subprocess.Popen(command, cwd=ROOT, env=launch_env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    identity = process_identity(process.pid)
    if identity is None:
        raise RuntimeError(f"{service} exited during launch; inspect run/logs/smartlect-{service}.log")
    if identity["cmdline"] != command or identity["exe"] != str(executable.resolve()) or identity["cwd"] != str(ROOT):
        raise RuntimeError(f"{service} PID {process.pid} does not match the exact launched command")
    records[service] = {**identity, "port": port, "health_host": health_host(env),
                        "artifact_stamp": stamp, "source_sha256": source_sha,
                        "source_artifact": str(artifact), "env_stamp": env_stamp}
    save_processes(records)
    print(f"Started Smartlect {service}: PID {process.pid}, port {port}.", flush=True)


def wait_apps(services, records):
    pending = set(services)
    deadline = time.monotonic() + 240
    while pending and time.monotonic() < deadline:
        for service in tuple(pending):
            if not owned_process(records[service]):
                raise RuntimeError(f"{service} exited; inspect run/logs/smartlect-{service}.log")
            if app_health(service, records[service]):
                pending.remove(service)
                print(f"Smartlect {service} health passed.", flush=True)
        if pending:
            time.sleep(1)
    if pending:
        raise RuntimeError(f"Health timeout: {', '.join(sorted(pending))}; inspect run/logs/")


def install_catalog(env):
    import importlib.util
    spec = importlib.util.spec_from_file_location("install_catalog", ROOT / "scripts/install_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.apply_catalog(env)


def apps_up(env):
    local = set(app_services(env))
    # 主节点（跑全部服务）沿用完整 infra 门禁；副本节点只验到集群中间件的连通性
    if local == set(APPS):
        infra_check(env)
    else:
        cluster_endpoint_check(env)
    with ledger_lock():
        records = load_processes()
        for services in (APPS[1:8], ('assistant',), ('admin', 'gateway'), ('web-user', 'web-admin')):
            for service in services:
                if service not in local:
                    continue
                start_app(service, env, records)
                # Warm one JVM at a time on the shared WSL host.
                wait_apps((service,), records)
                if service == "stock":
                    install_catalog(env)
        apps_check(env)
        java_count = len([name for name in local if name not in {"assistant", "web-user", "web-admin"}])
        print(f"Smartlect application startup smoke passed: {java_count} Java services, AI API and UI health.")


def apps_check(env):
    records = load_processes()
    local = app_services(env)
    if any(service not in records for service in local):
        raise RuntimeError("Some application processes are not registered; run up first")
    wait_apps(local, records)
    token = nacos_request(env, "/nacos/v1/auth/login", {
        "username": env["SMARTLECT_NACOS_USERNAME"], "password": env["SMARTLECT_NACOS_PASSWORD"]})["accessToken"]
    # 只有 Java 服务进 Nacos 注册表；注册 IP 是分机部署的关键断言（回环 IP 别的节点打不通）
    register_ip = app_register_ip(env)
    pending = set(local) - {"assistant", "web-user", "web-admin"}
    deadline = time.monotonic() + 30
    while pending and time.monotonic() < deadline:
        for service in tuple(pending):
            query = urllib.parse.urlencode({"accessToken": token, "serviceName": f"smartlect-{service}",
                                           "groupName": env["SMARTLECT_NACOS_GROUP"], "healthyOnly": "true"})
            with urllib.request.urlopen("http://" + nacos_addr(env) +
                                        "/nacos/v1/ns/instance/list?" + query, timeout=5) as response:
                hosts = json.load(response)["hosts"]
            if any(host["healthy"] and host["ip"] == register_ip
                   and host["port"] == records[service]["port"] for host in hosts):
                pending.remove(service)
        if pending:
            time.sleep(1)
    if pending:
        raise RuntimeError(f"Missing application discovery registrations: {', '.join(sorted(pending))}")
    java_local = java_service_count(local)
    print(f"Application checks passed: {len(local)} owned healthy processes, "
          f"{java_local} Nacos registrations at {register_ip}.")


def apps_status(services=None):
    records = load_processes()
    for service in services or APPS:
        record = records.get(service)
        state = "stopped" if record is None or not owned_process(record) else (
            "healthy" if app_health(service, record) else "starting/unhealthy")
        print(f"smartlect-{service}: {state}" + (f" (PID {record['pid']}, port {record['port']})" if record else ""))


def self_test():
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        busy = blocker.getsockname()[1]
        assert free_ports(busy) != busy
    # 分机部署开关的契约：不设任何开关时，必须与单机形态逐字一致（回环 + 全部服务）。
    # 这条断言是"改造不改变单机行为"的可执行证据，改动这些默认值会先在这里失败。
    assert app_services({}) == APPS
    assert app_bind_address({}) == "127.0.0.1"
    assert app_register_ip({}) == "127.0.0.1"
    assert health_host({}) == "127.0.0.1"
    assert app_services({"SMARTLECT_APP_SERVICES": "product, order"}) == ("product", "order")
    assert app_bind_address({"SMARTLECT_APP_BIND_ADDRESS": "0.0.0.0"}) == "0.0.0.0"
    assert health_host({"SMARTLECT_APP_BIND_ADDRESS": "0.0.0.0"}) == "127.0.0.1"
    assert health_host({"SMARTLECT_APP_BIND_ADDRESS": "172.19.34.202"}) == "172.19.34.202"
    # 注册数汇总必须能直接吃 app_services 的返回值（元组）——写成集合运算曾把
    # 启动门禁在最后一行打崩，进程其实全都起来了
    assert java_service_count(app_services({})) == 9
    assert java_service_count(("gateway", "product", "web-user", "assistant")) == 2
    # 绑定地址必须真的落到 java 命令行上（分机部署靠它跨机可达）
    java_command = java_launch_args("product", {"SMARTLECT_APP_BIND_ADDRESS": "0.0.0.0",
                                                "SMARTLECT_APP_REGISTER_IP": "172.19.34.202"})[1]
    assert "--server.address=0.0.0.0" in java_command
    assert "--spring.cloud.nacos.discovery.ip=172.19.34.202" in java_command
    for bad in ({"SMARTLECT_APP_SERVICES": "product,nope"}, {"SMARTLECT_APP_SERVICES": ","}):
        try:
            app_services(bad)
            raise AssertionError(f"Invalid SMARTLECT_APP_SERVICES accepted: {bad}")
        except RuntimeError:
            pass
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "runtime.env"
        path.write_text("# local\nSMARTLECT_TOKEN=abc==\nSMARTLECT_EMPTY=\n")
        assert parse_env(path) == {"SMARTLECT_TOKEN": "abc==", "SMARTLECT_EMPTY": ""}
        provider = Path(temp) / "model.env"
        provider.write_text("SMARTLECT_MODEL_API_KEY=literal-$(false)\nSMARTLECT_MODEL_ID=qwen3.7-plus\n")
        provider.chmod(0o600)
        assert model_env(provider)["SMARTLECT_MODEL_API_KEY"] == "literal-$(false)"
        saved_model_env = model_env
        try:
            globals()["model_env"] = lambda path=None: {"SMARTLECT_MODEL_API_KEY": "injected-from-model-env"}
            injected = launch_env_for("assistant", {"SMARTLECT_MODEL_MODE": "live"})
            java = launch_env_for("user", {"SMARTLECT_MODEL_MODE": "live"})
        finally:
            globals()["model_env"] = saved_model_env
        assert injected["SMARTLECT_MODEL_API_KEY"] == "injected-from-model-env"
        assert java.get("SMARTLECT_MODEL_API_KEY") != "injected-from-model-env"
        provider.write_text("SMARTLECT_INTERNAL_TOKEN=forbidden\n")
        try:
            model_env(provider)
            raise AssertionError("Model config overwrote business credentials")
        except RuntimeError:
            pass
        from unittest.mock import patch
        path.chmod(0o600)
        with patch.dict(globals(), ENV_FILE=path), patch.object(sys, 'argv', ['runtime.py', 'model-mode', 'mock']):
            main()
        assert parse_env(path)['SMARTLECT_MODEL_MODE'] == 'mock'
        assert parse_env(path)['SMARTLECT_TOKEN'] == 'abc==' and path.stat().st_mode & 0o777 == 0o600
        with patch.dict(globals(), ENV_FILE=path), patch.object(sys, 'argv', ['runtime.py', 'model-mode', 'unsafe']):
            try:
                main()
                raise AssertionError('Invalid mode accepted')
            except RuntimeError:
                pass
        provider.write_text("SMARTLECT_MODEL_ID=qwen3.7-plus\n")
        provider.chmod(0o644)
        try:
            model_env(provider)
            raise AssertionError("World-readable credentials accepted")
        except RuntimeError:
            pass
        jar = Path(temp) / "source.jar"
        with zipfile.ZipFile(jar, "w") as archive:
            archive.writestr("BOOT-INF/classes/test.class", b"original")
        snapshot, digest, _ = immutable_jar(jar, Path(temp) / "runtime")
        assert immutable_jar(jar, snapshot.parent)[0] == snapshot
        with zipfile.ZipFile(jar, "w") as archive:
            archive.writestr("BOOT-INF/classes/test.class", b"rebuilt")
        replacement, _, _ = immutable_jar(jar, snapshot.parent)
        assert replacement != snapshot and file_sha256(snapshot) == digest
        assert snapshot.stat().st_mode & 0o222 == 0
        jar.write_bytes(b"unfinished build")
        try:
            immutable_jar(jar, snapshot.parent)
            raise AssertionError("Invalid JAR accepted")
        except RuntimeError:
            assert file_sha256(snapshot) == digest
        package = Path(temp) / "package"
        (package / "ads").mkdir(parents=True)
        (package / "app.py").write_text("pass\n")
        settings = package / "ads/config.py"
        settings.write_text("VALUE = 1\n")
        package_sha, _ = package_fingerprint(package)
        timestamp = settings.stat().st_mtime_ns
        settings.write_text("VALUE = 2\n")
        os.utime(settings, ns=(timestamp, timestamp))
        assert package_fingerprint(package)[0] != package_sha
        sql = package / "migration.sql"
        sql.write_text("SELECT 1;\n")
        with_sql, _ = package_fingerprint(package)
        sql.write_text("SELECT 2;\n")
        assert package_fingerprint(package)[0] != with_sql
    # 只继承 PATH：自测环境不透传外部 SMARTLECT_* 变量，否则脚本里缺密钥
    # （历史上漏过 xxljob）会被开发机 shell 掩盖成"通过"。
    test_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                **{f"SMARTLECT_{key}": "a" * 48 for key in
                   ("MYSQL_PASSWORD", "FLYWAY_PASSWORD", "NACOS_MYSQL_PASSWORD",
                    "GROWTH_MYSQL_PASSWORD", "CANAL_MYSQL_PASSWORD",
                    "XXLJOB_MYSQL_PASSWORD")}}
    script = 'docker_process_sql() { cat; }; source "$1"'
    args = ["bash", "-ec", script, "self-test", str(ROOT / "deploy/mysql-init.sh")]
    sql = subprocess.run(args, env=test_env, check=True, text=True, capture_output=True).stdout
    assert sql.count("CREATE DATABASE smartlect_") == 11
    # 每个库的属主用户都必须在同一脚本里被创建（GRANT 不给隐式建用户）
    for identity in ("app", "flyway", "nacos", "growth", "canal", "xxljob"):
        assert f"CREATE USER 'smartlect_{identity}'@'%'" in sql
    grants = [line for line in sql.splitlines() if "TO 'smartlect_growth'" in line]
    assert grants == ["GRANT ALL ON smartlect_growth.* TO 'smartlect_growth'@'%';"]
    test_env["SMARTLECT_MYSQL_PASSWORD"] = "invalid'password"
    assert subprocess.run(args, env=test_env, text=True, capture_output=True).returncode != 0
    child_command = [sys.executable, "-c", "import time; time.sleep(30)"]
    child = subprocess.Popen(child_command, cwd=ROOT)
    try:
        from unittest.mock import patch
        original_read = Path.read_bytes
        empty_reads = []

        def cold_cmdline(path):
            if path == Path(f"/proc/{child.pid}/cmdline") and not empty_reads:
                empty_reads.append(True)
                return b""
            return original_read(path)

        with patch.object(Path, "read_bytes", cold_cmdline):
            identity = process_identity(child.pid)
        assert empty_reads and identity["cmdline"] == child_command
        assert owned_process(identity)
        # 篡改身份（PID 复用他人进程的模拟）：不得信号（子进程必须存活），也不得抛错卡死批次
        signal_process({**identity, "start_ticks": "wrong"}, signal.SIGTERM)
        assert child.poll() is None, "Tampered PID identity was signaled"
        assert not owned_process({**identity, "start_ticks": "wrong"})
        stop_process(identity)
        assert child.wait(timeout=2) == -signal.SIGTERM
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=2)
    # 台账锁互斥：持锁期间他人 LOCK_NB 抢锁必败，释放后可得；锁文件权限 0600
    lock_probe = ("import fcntl, sys\n"
                  "fd = open(sys.argv[1], 'a+')\n"
                  "try:\n"
                  "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                  "except BlockingIOError:\n"
                  "    sys.exit(3)\n")
    with ledger_lock():
        assert subprocess.run([sys.executable, "-c", lock_probe, str(PROCESS_LOCK)]).returncode == 3, \
            "ledger lock is not exclusive"
    assert subprocess.run([sys.executable, "-c", lock_probe, str(PROCESS_LOCK)]).returncode == 0, \
        "ledger lock was not released"
    assert PROCESS_LOCK.stat().st_mode & 0o777 == 0o600
    print("Runtime checks passed: immutable JARs, full Python package hashes, ports, env, grants, credentials, process signaling, ledger lock.")
    calls = []
    with patch.dict(globals(), infra_check=lambda env: None, compose=lambda *a, **kw: None,
                    load_processes=lambda: {}, apps_check=lambda env: None,
                    install_catalog=lambda env: calls.append(('catalog',)),
                    start_app=lambda name, env, records: calls.append(('start', name)),
                    wait_apps=lambda names, records: calls.append(('healthy', tuple(names)))):
        apps_up({})
    assert calls[:2] == [('start', 'user'), ('healthy', ('user',))]
    assert ('start', 'assistant') in calls and calls.index(('start', 'assistant')) > calls.index(('healthy', ('stock',)))
    assert ('catalog',) in calls and calls.index(('catalog',)) > calls.index(('healthy', ('stock',)))
    print('Assistant starts after Java services have declared their queues.')


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "bootstrap":
        bootstrap()
        return
    if command == "self-test":
        self_test()
        return
    if not ENV_FILE.exists():
        raise RuntimeError("Run ./scripts/dev.sh bootstrap first")
    env = parse_env(ENV_FILE)
    if command == "config":
        compose("config", "--quiet")
        print(json.dumps({k: v for k, v in env.items() if k.endswith("_PORT")}, indent=2))
    elif command == "model-mode":
        mode = sys.argv[2] if len(sys.argv) == 3 else ''
        if mode not in {'live', 'mock', 'rule-fallback'}:
            raise RuntimeError('Usage: ./scripts/dev.sh model-mode {live|mock|rule-fallback}')
        if ENV_FILE.is_symlink() or ENV_FILE.stat().st_mode & 0o777 != 0o600:
            raise RuntimeError('run/runtime.env must be a regular mode-600 file')
        if mode == 'live' and not model_env().get('SMARTLECT_MODEL_API_KEY'):
            raise RuntimeError('Configure SMARTLECT_MODEL_API_KEY in run/model.env first')
        env['SMARTLECT_MODEL_MODE'] = mode
        temporary = ENV_FILE.with_suffix('.env.tmp')
        with temporary.open('x') as target:
            os.chmod(temporary, 0o600)
            target.write('\n'.join(f'{key}={value}' for key, value in env.items()) + '\n')
        temporary.replace(ENV_FILE)
        print(f'Model mode saved: {mode}. Run ./scripts/dev.sh up to apply it.')
    elif command == "status":
        # 副本节点只有应用运行时（没有 deploy/ 与中间件容器），跳过 compose 那一段
        if (ROOT / "deploy/compose.yaml").exists():
            verify_project()
            compose("ps", "--all")
        apps_status(app_services(env))
    elif command == "infra-up":
        infra_up(env)
    elif command == "infra-check":
        infra_check(env)
    elif command == "catalog":
        install_catalog(env)
    elif command == "up":
        apps_up(env)
    elif command == "apps-check":
        apps_check(env)
    elif command == "smoke":
        smoke_apps(env)
    elif command == "wait-cluster":
        timeout = int(sys.argv[sys.argv.index("--timeout") + 1]) if "--timeout" in sys.argv else 300
        wait_cluster(env, timeout=timeout)
    elif command == "check-apps":
        check_apps(env)
    elif command == "apps-down":
        apps_down()
    elif command == "down":
        verify_project()
        apps_down()
        compose("down", "--timeout", "30")
    else:
        raise RuntimeError(f"Unknown runtime command: {command}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError, urllib.error.URLError) as error:
        print(f"Smartlect runtime failed: {error}", file=sys.stderr)
        sys.exit(1)
