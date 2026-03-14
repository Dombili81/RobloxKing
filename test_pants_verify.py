import requests

# Test the pants verification step
linked_id = "15670295717"
headers = {"User-Agent": "Mozilla/5.0"}
url = "https://economy.roblox.com/v1/assets/details"

print(f"Testing {url} with ID: {linked_id}")
r = requests.get(url, params={"assetIds": linked_id}, headers=headers, timeout=10)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    print(r.json())
else:
    print(r.text)
