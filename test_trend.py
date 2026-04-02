"""test_trend.py — Yeni mimarinin testi"""
from scrapers.trend_engine import TrendEngine

class FakeDB:
    is_active = False
    db = None

engine = TrendEngine(FakeDB())

print("═" * 60)
print("ADIM 1: Dış kaynaklardan entity toplama...")
jikan = engine._get_jikan_entities()
print(f"  Jikan anime: {len(jikan)} entity")
for a in jikan[:3]:
    print(f"    [{a['source']}] {a['name']} (w={a['weight']:.2f})")

rss = engine._get_rss_entities()
print(f"  RSS kaynakları: {len(rss)} entity")
# Kaynağa göre grupla
from collections import Counter
src_counts = Counter(e['source'] for e in rss)
for src, cnt in src_counts.most_common():
    print(f"    {src}: {cnt} entity")

print("\nADIM 2: Roblox talep doğrulama (ilk 3 entity test)...")
sample = (jikan + rss)[:3]
for e in sample:
    count = engine._check_roblox_demand(e['name'])
    print(f"  {e['name'][:30]}: {count} Roblox ürünü")

print("\nADIM 3: Full run (bu ~2 dk sürebilir)...")
results = engine.get_suggestions_sync()
print(f"\n✅ Toplam öneri: {len(results)}")
print("═" * 60)
for i, r in enumerate(results, 1):
    rb = r['favorites']
    rb_str = f"{rb} ürün" if rb < 1000 else f"{rb/1000:.1f}K ürün"
    print(f"{i:2}. [{r['label']}] {r['kw']}")
    print(f"     Roblox: {rb_str} | {r.get('extra','')}")
print("═" * 60)
