# -*- coding: utf-8 -*-
"""针对性回归测试：同名酒店分店三层 bug 修复验证（无需网络/LLM）"""
import sys
sys.path.insert(0, "backend")

from app.agents.trip_planner_helpers import (
    _dedupe_candidates,
    _fallback_hotel_food,
    _unify_plan_hotel,
)
from app.models.schemas import (
    DayPlan, Hotel, HotelCandidate, RestaurantCandidate, TripPlan, HotelFoodResult,
)

passed, failed = 0, 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


print("== 测试 1：_dedupe_candidates 同名同址合并 / 同名不同址保留并加后缀 ==")
cands = [
    HotelCandidate(name="如家酒店(前门店)", address="东城区前门大街1号", longitude=116.397, latitude=39.899),
    HotelCandidate(name="如家酒店(前门店)", address="东城区前门大街1号", longitude=116.397, latitude=39.899),  # 完全重复
    HotelCandidate(name="如家酒店", address="东城区灯市口大街22号", longitude=116.411, latitude=39.920),      # 同名(归一化后)不同址
    HotelCandidate(name="汉庭酒店", address="西城区平安里南巷", longitude=116.360, latitude=39.933),
]
out = _dedupe_candidates(cands)
check("完全重复项被合并(4->3)", len(out) == 3)
check("第一家同名不同址保持原名(含分店括号)", out[0].name == "如家酒店(前门店)")
check("第二家同名不同址名称带分店后缀", "(灯市口大街" in out[1].name and out[1].name != out[0].name)
check("两家的坐标各自独立未串号", out[0].longitude == 116.397 and out[1].longitude == 116.411)
check("不同名酒店不受影响", out[2].name == "汉庭酒店" and out[2].longitude == 116.360)

print("== 测试 1b：坐标均缺失的同名候选视为同一家 ==")
cands2 = [
    HotelCandidate(name="如家酒店", longitude=None, latitude=None),
    HotelCandidate(name="如家酒店", longitude=None, latitude=None),
]
check("坐标缺失同名只保留一个", len(_dedupe_candidates(cands2)) == 1)

print("== 测试 1c：三家同名不同址都保留且名称互异 ==")
cands3 = [
    HotelCandidate(name="汉庭酒店", address="AAAAAAAAAA东直门", longitude=116.43, latitude=39.94),
    HotelCandidate(name="汉庭酒店", address="BBBBBBBBBB西直门", longitude=116.35, latitude=39.94),
    HotelCandidate(name="汉庭酒店", address="CCCCCCCCCC朝阳门", longitude=116.44, latitude=39.92),
]
out3 = _dedupe_candidates(cands3)
names = [c.name for c in out3]
check("三家全保留", len(out3) == 3)
check("名称两两互异", len(set(names)) == 3)

print("== 测试 2：_fallback_hotel_food 同名不同址不再被错误合并 ==")
hotel_pois = [
    {"name": "如家酒店(前门店)", "address": "前门大街1号", "location": "116.397,39.899", "id": "B001"},
    {"name": "如家酒店(王府井店)", "address": "灯市口大街22号", "location": "116.411,39.920", "id": "B002"},
    {"name": "如家酒店(前门店)", "address": "前门大街1号", "location": "116.397,39.899", "id": "B001"},  # 跨轮重复
]
fb = _fallback_hotel_food(hotel_pois, [])
check("同名不同址两家都保留", len(fb.hotels) == 2)
check("跨轮完全重复被去重", fb.hotels[0].poi_id == "B001" and fb.hotels[1].poi_id == "B002")
check("坐标各归各", fb.hotels[0].longitude == 116.397 and fb.hotels[1].longitude == 116.411)

print("== 测试 3：_unify_plan_hotel 强制全程固定候选首选 ==")
days = []
for i in range(3):
    d = DayPlan(date=f"2026-09-0{i+1}", day_index=i)
    # 模拟 LLM 逐日乱分配：第0天分店A、第1天同名分店B、第2天无酒店
    if i == 0:
        d.hotel = Hotel(name="如家酒店", address="前门大街1号")
    elif i == 1:
        d.hotel = Hotel(name="如家酒店", address="灯市口大街22号")
    days.append(d)
plan = TripPlan(city="北京", start_date="2026-09-01", end_date="2026-09-03", days=days)

pool = HotelFoodResult(hotels=[
    HotelCandidate(name="汉庭酒店", address="平安里南巷", longitude=116.360, latitude=39.933,
                   poi_id="B003", price_per_night=350, rating=4.5),
    HotelCandidate(name="如家酒店", address="灯市口大街22号", longitude=116.411, latitude=39.920),
])
_unify_plan_hotel(plan, pool)
check("三天全部变成候选池首选", all(d.hotel is not None and d.hotel.name == "汉庭酒店" for d in plan.days))
check("三天的地址/坐标完全一致", len({(d.hotel.address, str(d.hotel.location)) for d in plan.days}) == 1)
check("价格来自候选首选", all(d.hotel.estimated_cost == 350 for d in plan.days))
check("每天的hotel是深拷贝(互不共享引用)", plan.days[0].hotel is not plan.days[1].hotel)

print("== 测试 3b：候选池为空时不动原酒店（不伪造） ==")
# 独立构造，不复用已被测试3统一过的 days 对象
d_fresh = DayPlan(date="2026-09-01", day_index=0)
d_fresh.hotel = Hotel(name="如家酒店", address="前门大街1号")
plan2 = TripPlan(city="北京", start_date="2026-09-01", end_date="2026-09-02", days=[d_fresh])
_unify_plan_hotel(plan2, HotelFoodResult())
check("空池时保持原样", plan2.days[0].hotel is not None and plan2.days[0].hotel.name == "如家酒店")

print("== 测试 4：餐厅候选同样受益（同名不同址保留） ==")
r_cands = [
    RestaurantCandidate(name="老北京炸酱面", address="前门大街10号", longitude=116.398, latitude=39.899),
    RestaurantCandidate(name="老北京炸酱面", address="王府井大街5号", longitude=116.410, latitude=39.909),
]
out_r = _dedupe_candidates(r_cands)
check("同名餐厅不同址两家保留且名称可区分", len(out_r) == 2 and out_r[0].name != out_r[1].name)

print()
print(f"结果: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
