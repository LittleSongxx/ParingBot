#!/usr/bin/env bash
# 部署后生产核对（越权写探测只挑"即使守卫失效也无副作用"的参数；结束时按失败项给退出码）：
#   ① 逐服务版本指纹：不带 cookie 打各服务接口——2026-10-16 起的异常映射把"未登录"
#      规范成 HTTP 401 + code 901；仍返回 500 说明该服务跑的是旧产物（部署没生效）。
#   ② 展厅矩阵：越权面必须 403（守卫拒绝清单），允许面必须 200（读默认允许）。
#      每条路径连打 8 次以暴露"三节点 LB 下副本版本不一致"。
#   ③ 健康面：无 cookie/缺参/演示账号登录的行为基线。
#
# 用法：bash scripts/probes/post_deploy_check.sh [base_url，默认 https://smartlect.cn]
# 输出：stdout（重定向到 eval/verification/<date>/ 作为证据文件）；失败项 >0 时退出码 1。
set -uo pipefail

BASE="${1:-https://smartlect.cn}"
JAR="$(mktemp)"
OUT="$(mktemp)"
trap 'rm -f "$JAR" "$OUT"' EXIT
FAILS=0

post() { # post <path> <data>
  curl -s -m 25 -o "$OUT" -w "HTTP %{http_code} " -X POST "$BASE/$1" -d "$2"
  head -c 110 "$OUT"; echo
}

echo "=== 部署后核对：$BASE @ $(TZ=Asia/Shanghai date '+%F %T %Z') ==="
echo
echo "--- ① 逐服务版本指纹（期望 HTTP 401 + code 901；500 即旧产物）---"
# stock 服务只有 /stock/health（无需登录，200 无指纹）且无管理端接口；gateway 的 JAR
# 不含 common 类（异常映射/守卫都在 common）——两者的产物一致性由部署阶段的门禁覆盖。
for ep in "admin-api/user/loadUser:pageNo=1" \
          "admin-api/order/loadOrder:pageNo=1" \
          "admin-api/productInfo/loadProduct:pageNo=1" \
          "api/productCart/loadProductCart:pageNo=1" \
          "api/payTrade/loadMyTrades:pageNo=1" \
          "admin-api/discountCoupon/loadDiscountCoupon:pageNo=1" \
          "admin-api/home/getTodayData:"; do
  printf "  %-46s " "${ep%%:*}"
  result=$(post "${ep%%:*}" "${ep#*:}")
  echo "$result"
  if ! echo "$result" | grep -q "HTTP 401" || ! echo "$result" | grep -q '"code":901'; then
    echo "    ✗ 期望 HTTP 401 + code 901（500/200 说明该服务是旧产物）"
    FAILS=$((FAILS + 1))
  fi
done

echo
echo "--- ② 展厅矩阵（gallery 会话；越权 → 403，允许 → 200）---"
echo "    ★ 每条路径连打 8 次：三节点集群下同一路径会 LB 到不同服务实例，"
echo "      \"期望码与其它码交替\"即存在未更新的副本节点（node2/node3 需 sync-app-node.sh）。"
echo "      未登录请求被网关前置拦截，测不到后端版本——本节必须带有效会话。"
# 写探测参数须"即使守卫失效也无副作用"：不存在的 id / 不存在的用户，绝不指向真实账号；
# 此前用演示买家 8800000002 与批量工具入口做探针，守卫失效时会真的改数据（2026-10-17 审计）。
LOGIN_BODY=$(curl -s -m 25 -c "$JAR" -X POST "$BASE/admin-api/account/login" \
  --data-urlencode "account=gallery" --data-urlencode "password=Visit-Smartlect-2026")
if ! echo "$LOGIN_BODY" | grep -q '"code":200'; then
  echo "  登录失败，核对中止：$LOGIN_BODY"
  exit 2
fi
for ep in "admin-api/user/loadUser:pageNo=1:403" \
          "admin-api/user/changeStatus:userId=0&status=1:403" \
          "admin-api/order/delivery:orderId=0&company=x&trackingNumber=x:403" \
          "admin-api/sysCategory/delCategory:categoryId=0:403" \
          "admin-api/discountCoupon/updateDiscountCouponStatus:couponId=0&status=0:403" \
          "admin-api/productInfo/updateSkuStock:productId=0&propertyValueId=0&stock=1:403" \
          "admin-api/userAddress/deleteUserAddressByAddressId:addressId=0:403" \
          "admin-api/discountCoupon/loadDiscountCoupon:pageNo=1&pageSize=1:200" \
          "admin-api/home/getTodayData::200" \
          "admin-api/order/loadOrder:pageNo=1&pageSize=1:200" \
          "admin-api/productInfo/loadProduct:pageNo=1&pageSize=1:200"; do
  path="${ep%%:*}"; rest="${ep#*:}"; data="${rest%%:*}"; want="${rest##*:}"
  printf "  %-46s " "${path#admin-api/}"
  codes=""
  for _ in 1 2 3 4 5 6 7 8; do
    got=$(curl -s -m 25 -b "$JAR" -X POST "$BASE/$path" -d "$data" \
          | python3 -c "import json,sys;print(json.load(sys.stdin).get('code'))" 2>/dev/null || echo '?')
    codes="$codes $got"
  done
  unique=$(echo "$codes" | tr ' ' '\n' | sort -u | grep -v '^$' | tr '\n' ',' | sed 's/,$//')
  if echo "$unique" | grep -q "901"; then
    echo "✗ 会话失效（出现 901）——本次统计不可用，请重跑"
    FAILS=$((FAILS + 1))
  elif [ "$unique" = "$want" ]; then
    echo "✓ 8/8 code=$want"
  elif echo "$unique" | grep -q ","; then
    echo "★ 不一致（期望 $want）：$unique —— 疑有副本节点未更新，跑 sync-app-node.sh"
    FAILS=$((FAILS + 1))
  else
    echo "✗ 实测 code=$unique（期望 $want）"
    FAILS=$((FAILS + 1))
  fi
done

echo
echo "--- ③ 健康面基线 ---"
printf "  %-46s " "无 cookie（期望 401/901）"
curl -s -m 25 -o "$OUT" -w "HTTP %{http_code} " -X POST "$BASE/admin-api/home/getTodayData" -d ""
head -c 70 "$OUT"; echo
printf "  %-46s " "用户端登录缺参（期望 600 参数错误）"
curl -s -m 25 -o "$OUT" -w "HTTP %{http_code} " -X POST "$BASE/api/account/login" -d "password=x"
head -c 90 "$OUT"; echo
printf "  %-46s " "shopper 登录（期望 200）"
curl -s -m 25 -X POST "$BASE/api/account/login" \
  --data-urlencode "email=shopper@smartlect.demo" --data-urlencode "password=Visit-Smartlect-2026" | head -c 90; echo
printf "  %-46s " "visitor 登录（期望 200）"
curl -s -m 25 -X POST "$BASE/api/account/login" \
  --data-urlencode "email=visitor@smartlect.demo" --data-urlencode "password=Visit-Smartlect-2026" | head -c 90; echo
echo
if [ "$FAILS" -eq 0 ]; then
  echo "=== 核对结束：全部通过 ==="
else
  echo "=== 核对结束：失败项 $FAILS（见上方 ✗/★）==="
  exit 1
fi
