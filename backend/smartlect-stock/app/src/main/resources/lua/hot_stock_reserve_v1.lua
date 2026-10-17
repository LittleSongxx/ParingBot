-- 热点库存预占：KEYS[1]=预留标记，KEYS[2..]=各桶；ARGV[1]=数量，ARGV[2]=TTL 秒。
-- 同一订单对同一 SKU 只预留一次；桶总量不足时不修改任何桶。
local reservation = KEYS[1]
local amount = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local existing = redis.call('get', reservation)
if existing then
    return tonumber(existing)
end
local total = 0
for i = 2, #KEYS do
    total = total + tonumber(redis.call('get', KEYS[i]) or '0')
end
if total < amount then
    return -1
end
local remaining = amount
for i = 2, #KEYS do
    if remaining <= 0 then
        break
    end
    local available = tonumber(redis.call('get', KEYS[i]) or '0')
    if available > 0 then
        local take = math.min(available, remaining)
        redis.call('decrby', KEYS[i], take)
        remaining = remaining - take
    end
end
redis.call('set', reservation, amount, 'EX', ttl)
return amount
