-- 释放热点库存预占：KEYS[1]=预留标记，KEYS[2]=回补桶；返回释放数量（0=无预占）。
-- 全部回补到第一个桶，保证总量守恒；桶的分布不要求均匀。
local reservation = KEYS[1]
local amount = redis.call('get', reservation)
if not amount then
    return 0
end
redis.call('incrby', KEYS[2], tonumber(amount))
redis.call('del', reservation)
return tonumber(amount)
